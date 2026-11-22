"""
Operations tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

import math
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Annotated, Literal
from pydantic import Field

import numpy as np
from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult

from tekla_mcp_server.config import get_tolerance, get_advanced_option_directories, get_report_preview_max_chars, get_report_preview_timeout
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import AttachmentPair
from tekla_mcp_server.geometry import EPSILON, FloatArray, OrientedBox, aabb, aabb_gap, axis_overlap, box_gap, box_sample_points, orientation, relation, search_extents, sides
from tekla_mcp_server.utils import mcp_handler, build_report_filename, normalize_guid, resolve_model_relative_dir
from tekla_mcp_server.tekla.clash_check import TeklaClashCheckHandler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import (
    BoundingBox,
    wrap_model_objects,
    wrap_model_object,
    TeklaAssembly,
    TeklaBooleanPart,
    TeklaModelObject,
    TeklaPart,
    TeklaReinforcement,
    SolidGeometryMixin,
    ZERO_GUID,
    REINFORCEMENT_CLASSES,
    EMBEDDED_DETAILS_CLASSES,
)
from tekla_mcp_server.tekla.loader import Assembly, Operation, Part, Reinforcement
from tekla_mcp_server.tekla.utils import (
    iterate_boolean_parts,
    get_candidates_in_bounding_box,
    get_objects_in_bounding_box,
    get_all_materials,
    get_all_rebar_items,
    get_oriented_box,
    get_parts_in_extent,
    global_work_plane,
    require_selection_filter,
    ensure_macro_installed,
    wait_for_macro,
)


operations_provider = LocalProvider()


@dataclass
class CheckResult:
    """Result of a model object validity or orphan check."""

    guid: str
    name: str | None
    position: str | None
    tekla_class: int | None
    issues: list[str] = field(default_factory=list)


def _enumerator_ids(enumerator: Any) -> set[int]:
    """
    Return the IDs of the objects of a model object enumerator without loading them.

    Args:
        enumerator: `ModelObjectEnumerator`, or None

    Returns:
        Object IDs
    """
    ids: set[int] = set()
    if enumerator is None:
        return ids
    enumerator.SelectInstances = False
    while enumerator.MoveNext():
        ids.add(enumerator.Current.Identifier.ID)
    return ids


def _get_attached_part_ids(element: TeklaAssembly) -> tuple[set[int], set[str]]:
    """
    Return IDs of the parts in element's subassemblies at any depth, and GUIDs of its attached embeds.

    These parts belong to the element, so the spatial search can leave them out without
    loading them or asking each one for its assembly.

    Args:
        element: Host assembly

    Returns:
        Tuple of (part IDs, GUIDs of direct subassemblies that are embedded details)
    """
    part_ids: set[int] = set()
    embed_guids: set[str] = set()
    stack = [(sub, True) for sub in element.model_object.GetSubAssemblies()]
    while stack:
        sub, direct = stack.pop()
        main = sub.GetMainPart()
        if main is not None:
            part_ids.add(main.Identifier.ID)
            try:
                if direct and int(main.Class) in EMBEDDED_DETAILS_CLASSES:
                    embed_guids.add(sub.Identifier.GUID.ToString())
            except (TypeError, ValueError):
                logger.debug("Subassembly %s has a non-numeric main part class", sub.Identifier.ID)
        part_ids.update(sec.Identifier.ID for sec in sub.GetSecondaries())
        stack.extend((nested, False) for nested in sub.GetSubAssemblies())
    return part_ids, embed_guids


def _get_reinforcement_ids(element: TeklaAssembly) -> set[int]:
    """
    Return IDs of all reinforcement attached to element, across main part and all secondaries.

    IDs need no loading of the rebars, which is slow for large groups and meshes.

    Args:
        element: Assembly to inspect

    Returns:
        Reinforcement IDs
    """
    ids: set[int] = set()

    try:
        ids |= _enumerator_ids(element.main_part.model_object.GetReinforcements())
    except Exception:
        logger.debug("Failed to read reinforcement of the main part of %s", element.guid)

    try:
        secondaries = element.model_object.GetSecondaries()
    except Exception:
        secondaries = None

    if secondaries is not None:
        for sec in secondaries:
            try:
                ids |= _enumerator_ids(sec.GetReinforcements())
            except Exception:
                continue

    return ids


def _is_inside_any_part(points: FloatArray, parts: list[SolidGeometryMixin], solid_cache: dict[int, dict[str, Any]], raw: bool) -> bool:
    """
    Check whether any sample point of an object lies within the solid of any part in the list.

    Objects without sample points are skipped to avoid false-positive orphans.
    `solid_cache` maps object ID to its solids and is shared across all candidates,
    so each part's solids are built once instead of once per candidate.

    Args:
        points: Sample points of the tested object
        parts: Container parts
        solid_cache: Shared solids by object ID
        raw: Test against RAW solids, without cuts

    Returns:
        True if any part contains a point, False otherwise or for an empty list
    """
    return any(part.contains_any_point(points, raw, solid_cache.setdefault(part.id, {})) for part in parts)


def _embed_sample_points(embed: TeklaAssembly, work_plane_handler: Any) -> FloatArray:
    """
    Return sample points along every part of an embed, its subassemblies included.

    The main part alone is not enough: a plate flush with the face is outside the
    concrete while only its anchors, often in subassemblies, are cast in.

    Args:
        embed: Embedded-detail assembly
        work_plane_handler: Handler from `global_work_plane`

    Returns:
        Points in global coordinates, shape (n, 3)
    """
    boxes = [get_oriented_box(part, work_plane_handler) for part in embed.get_all_parts()]
    chunks = [box_sample_points(box) for box in boxes if box is not None]
    return np.concatenate(chunks) if chunks else np.empty((0, 3))


def _check_element_bounding_box_embeds(
    element: TeklaAssembly,
    target_assembly_guids: set[str],
    tolerance: float,
    work_plane_handler: Any,
) -> tuple[list[CheckResult], set[str]]:
    """
    Find embedded details inside element that are not attached to it.

    Uses bounding box to find candidates, then checks parent assembly and containment.
    Attached embeds are counted without a geometry test, most embeds in an element are attached.
    Containment is tested against the RAW solids of the element's parts: embeds cut their
    own holes and recesses into the concrete, so the NORMAL solid never contains them.

    Args:
        element: Host assembly
        target_assembly_guids: Assemblies counted as attached
        tolerance: Bounding box tolerance
        work_plane_handler: Handler from `global_work_plane`

    Returns:
        Tuple of (orphaned embeds, evaluated GUIDs) with deduplicated GUIDs
    """
    # Pre-compute assembly parts once (not per-candidate) for containment checks
    assembly_parts = element.get_top_level_parts()
    if not assembly_parts:
        return [], set()

    # The element's own parts and the parts of its attached embeds are never orphans,
    # leave them out without loading them. Attached embeds still count as evaluated
    attached_part_ids, evaluated_guids = _get_attached_part_ids(element)
    candidates = get_objects_in_bounding_box(element, tolerance, (Part, Assembly), {part.id for part in assembly_parts} | attached_part_ids)

    orphaned: list[CheckResult] = []
    seen_assembly_ids: set[int] = set()
    part_solids: dict[int, dict[str, Any]] = {}

    for candidate in candidates:
        # Candidates may be parts belonging to a multi-part embed, promote to assembly
        # so we evaluate and report at assembly level rather than per-part
        if isinstance(candidate, TeklaAssembly):
            assembly_obj = candidate.model_object
        elif isinstance(candidate, TeklaPart):
            assembly_obj = candidate.model_object.GetAssembly()
        else:
            continue
        if not assembly_obj:
            continue

        # A multi-part embed yields multiple candidates that resolve to the same assembly, process each
        # assembly once. The ID is read before wrapping so repeated parts cost one call
        assembly_id = assembly_obj.Identifier.ID
        if assembly_id in seen_assembly_ids:
            continue
        seen_assembly_ids.add(assembly_id)

        wrapped_assembly = candidate if isinstance(candidate, TeklaAssembly) else wrap_model_object(assembly_obj)
        if not isinstance(wrapped_assembly, TeklaAssembly):
            continue

        try:
            candidate_main = wrapped_assembly.main_part
        except ValueError:
            continue

        # Only embedded-detail classes are relevant, other nearby objects are ignored
        if not wrapped_assembly.is_embedded_detail(candidate_main):
            continue

        # An embed is orphaned when its parent assembly isn't one of the assemblies we're
        # checking against - i.e. it's physically inside the element but not attached to it.
        # Checked before the geometry, which attached embeds do not need
        parent = assembly_obj.GetAssembly()
        parent_guid = parent.Identifier.GUID.ToString() if parent else None
        if parent_guid in target_assembly_guids:
            evaluated_guids.add(wrapped_assembly.guid)
            continue

        # Skip embeds that are in the bounding box but outside the element's actual solid
        if not _is_inside_any_part(_embed_sample_points(wrapped_assembly, work_plane_handler), assembly_parts, part_solids, raw=True):
            continue

        evaluated_guids.add(wrapped_assembly.guid)
        orphaned.append(
            CheckResult(
                guid=wrapped_assembly.guid,
                name=candidate_main.name,
                position=candidate_main.position,
                tekla_class=candidate_main.tekla_class,
            )
        )
    logger.debug("Found %d orphaned embeds for element %s", len(orphaned), element.guid)
    return orphaned, evaluated_guids


def _check_element_bounding_box_rebars(
    element: TeklaAssembly,
    element_reinforcement_ids: set[int],
    tolerance: float,
) -> tuple[list[CheckResult], set[int]]:
    """
    Find rebars inside element that are not in element_reinforcement_ids.

    Uses bounding box to find candidates, then checks containment and attachment status.
    Rebars attached to the element are counted but never loaded.
    Containment samples points along every bar leg and tests them against the NORMAL
    solids of the element's parts, so bars in openings or hollow cores do not count.

    Args:
        element: Host assembly
        element_reinforcement_ids: IDs of rebars attached to the element
        tolerance: Bounding box tolerance

    Returns:
        Tuple of (orphaned rebars, evaluated rebar IDs)
    """
    # Pre-compute assembly parts once (not per-candidate) for containment checks
    assembly_parts = element.get_top_level_parts()
    if not assembly_parts:
        return [], set()

    # Rebar is correctly attached to this element - not orphaned, skipped without loading
    evaluated_ids: set[int] = set()
    candidates = get_objects_in_bounding_box(element, tolerance, (Reinforcement,), element_reinforcement_ids, evaluated_ids)
    if not candidates:
        return [], evaluated_ids

    orphaned: list[CheckResult] = []
    part_solids: dict[int, dict[str, Any]] = {}

    for candidate in candidates:
        if not isinstance(candidate, TeklaReinforcement):
            continue

        # Only reinforcement classes are relevant, other nearby objects are ignored
        reinforcement_class = candidate.tekla_class
        if reinforcement_class not in REINFORCEMENT_CLASSES:
            continue

        candidate_guid = candidate.guid
        try:
            points = candidate.get_sample_points()
        except Exception:
            # Without bar geometry the bar cannot be ruled out, report it rather than hide an orphan
            logger.warning("Bar geometry of rebar %s unavailable, treating it as inside", candidate_guid)
            points = None

        # Skip rebars that are in the bounding box but outside the element's actual solid
        if points is not None and not _is_inside_any_part(points, assembly_parts, part_solids, raw=False):
            continue

        evaluated_ids.add(candidate.id)

        # Starter bars: rebar belongs to a neighboring element and
        # legitimately reaches into this one. Recognised by the bar still lying
        # inside the solid of its actual father part.
        # We check only the father part, not the entire father assembly, because we
        # are verifying specific ownership.
        # Neighbouring bars often share a father, so its solids go in the same per-part cache
        father = candidate.father
        if points is not None and isinstance(father, SolidGeometryMixin) and father.guid != ZERO_GUID and _is_inside_any_part(points, [father], part_solids, raw=False):
            continue

        orphaned.append(
            CheckResult(
                guid=candidate.guid,
                name=candidate.name,
                position=candidate.position,
                tekla_class=reinforcement_class,
            )
        )
    logger.debug("Found %d orphaned rebars for element %s", len(orphaned), element.guid)
    return orphaned, evaluated_ids


def _solid_box(obj: Any) -> BoundingBox | None:
    """
    Box of the solid `has_spatial_overlap` uses, or None if there is no solid.

    Args:
        obj: Wrapped model object

    Returns:
        Solid box or None
    """
    try:
        return BoundingBox.from_solid(obj.get_solid())
    except Exception:
        return None


def _overlapping_cutters(target_box: BoundingBox | None, cutters: list[Any], cutter_boxes: list[BoundingBox | None]) -> list[Any]:
    """
    Keep the cutters whose box touches the target's, in their original order.

    Zero tolerance gives the same test as `has_spatial_overlap`. An unknown box on
    either side keeps the cutter, so `add_cut` makes the call as before.

    Args:
        target_box: Target box from `_solid_box`
        cutters: Wrapped cutter parts
        cutter_boxes: Boxes aligned with `cutters`

    Returns:
        Cutters that may overlap the target
    """
    if target_box is None:
        return list(cutters)
    return [cutter for cutter, box in zip(cutters, cutter_boxes, strict=True) if box is None or target_box.overlaps(box, 0.0)]


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def cut_elements_with_cutters(
    cutter_class: Annotated[int | None, Field(description="Tekla class of the parts to use as cutters")] = None,
    cutter_guids: Annotated[list[str], Field(description="GUIDs of the parts to use as cutters (e.g. from `get_elements_properties`)")] = [],
    delete_cutting_parts: Annotated[
        bool,
        Field(description="Remove cutting parts after cuts are applied. A cutter given as a cut part GUID is an existing cut of another part and is never removed"),
    ] = False,
) -> ToolResult:
    """
    Performs boolean cuts on selected model objects.

    Provide exactly one of:
    - `cutter_class`: use all parts with the specified Tekla class as cutters
    - `cutter_guids`: use specific parts as cutters (useful in multi-step workflows)
    """
    if cutter_class is None and not cutter_guids:
        raise ValueError("Provide exactly one of 'cutter_class' or 'cutter_guids'")
    if cutter_class is not None and cutter_guids:
        raise ValueError("Provide exactly one of 'cutter_class' or 'cutter_guids'")

    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    missing_guids: list[str] = []
    unsupported_guids: list[str] = []
    # Operative parts of existing cuts. Deleting one removes that cut from its own part
    cut_part_cutter_ids: set[int] = set()
    if cutter_class is not None:
        cutters = list(wrap_model_objects(model.get_objects_by_class(cutter_class)))
        label = f"class {cutter_class}"
    else:
        raw_cutters, found_guids, missing_guids = model.resolve_guids(cutter_guids)
        cutters = []
        for guid, raw_cutter in zip(found_guids, raw_cutters, strict=True):
            cutter = wrap_model_object(raw_cutter)
            # The GUID of a cut part (e.g. `cutting_part_guid` from `get_elements_cut_parts`) resolves
            # to its BooleanPart, the part that shapes the cut is the operative part
            from_cut_part = isinstance(cutter, TeklaBooleanPart)
            if from_cut_part:
                cutter = cutter.operative_part
            # Only a part can be set as the operative part of a boolean cut
            if isinstance(cutter, TeklaPart):
                cutters.append(cutter)
                if from_cut_part:
                    cut_part_cutter_ids.add(cutter.id)
            else:
                unsupported_guids.append(guid)
        if not cutters:
            raise ValueError(f"None of the cutter GUIDs is a part in the model (missing: {missing_guids}, not a part: {unsupported_guids})")
        label = f"{len(cutters)} cutter GUIDs"

    processed_count = 0
    performed_cuts = 0
    # Read each cutter's AABB once
    cutter_boxes = [_solid_box(cutter) for cutter in cutters]
    cutter_ids = {cutter.id for cutter in cutters}
    used_cutter_ids: set[int] = set()
    skipped_cutter_guids: list[str] = []
    logger.debug("Processing %d selected objects with %d cutters (%s)", selected_objects.GetSize(), len(cutters), label)
    if cutters:
        for selected_object in wrap_model_objects(selected_objects):
            # Only parts can be cut, skip cut parts, bolts and other selected objects
            if not isinstance(selected_object, TeklaPart):
                continue
            # A selected part that is also a cutter is never cut, otherwise cutters would cut
            # themselves and each other, and `delete_cutting_parts` could delete the target
            if selected_object.id in cutter_ids:
                skipped_cutter_guids.append(selected_object.guid)
                continue
            element_had_cut = False
            target_box = _solid_box(selected_object)
            for cutter in _overlapping_cutters(target_box, cutters, cutter_boxes):
                # Never delete the cutter here: the same cutter may need to cut
                # several selected targets. Deleting mid-loop would leave later
                # targets with an invalid (deleted) cutter handle, silently
                # skipping their cuts. Deletion is deferred until all cuts run.
                if selected_object.add_cut(cutter, False):
                    performed_cuts += 1
                    element_had_cut = True
                    used_cutter_ids.add(cutter.id)
            if element_had_cut:
                processed_count += 1

    # Delete cutters once, after every target has been processed, so a cutter
    # shared by multiple targets is removed only when it is no longer needed.
    deleted_cutters = 0
    kept_cut_part_guids: list[str] = []
    if delete_cutting_parts and used_cutter_ids:
        for cutter in cutters:
            if cutter.id not in used_cutter_ids:
                continue
            if cutter.id in cut_part_cutter_ids:
                kept_cut_part_guids.append(cutter.guid)
            elif cutter.delete():
                deleted_cutters += 1

    commit_success: bool | None = None
    if performed_cuts:
        commit_success = model.commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after performing %d cuts", performed_cuts)
            status = "error"
        else:
            logger.info("Performed %s cuts on %s elements", performed_cuts, processed_count)
            status = "partial" if missing_guids or unsupported_guids else "success"
    else:
        logger.warning("cut_elements_with_cutters: No cuts performed (%s)", label)
        status = "warning"

    result: dict = {
        "status": status,
        "selected_count": selected_objects.GetSize(),
        "processed_count": processed_count,
        "performed_cuts_count": performed_cuts,
    }
    if cutter_guids:
        result["missing_guids"] = missing_guids
        result["unsupported_guids"] = unsupported_guids
    if skipped_cutter_guids:
        result["skipped_cutter_guids"] = skipped_cutter_guids
    if delete_cutting_parts:
        result["deleted_cutters_count"] = deleted_cutters
    if kept_cut_part_guids:
        result["kept_cut_part_guids"] = kept_cut_part_guids
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def convert_cut_parts_to_real_parts() -> ToolResult:
    """
    Finds boolean parts and inserts them as real model objects.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    processed_count = 0
    converted_booleans_count = 0
    for selected_object in wrap_model_objects(selected_objects):
        if not isinstance(selected_object, TeklaPart):
            logger.debug("convert_cut_parts_to_real_parts: skipping non-part object: %s", selected_object.element_type)
            continue
        for boolean_part in iterate_boolean_parts(selected_object.model_object):
            if boolean_part.OperativePart.Insert():
                converted_booleans_count += 1
        processed_count += 1
    commit_success: bool | None = None
    if converted_booleans_count > 0:
        commit_success = model.commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after converting %d boolean parts", converted_booleans_count)
            status = "error"
        else:
            logger.info("Inserted %s boolean parts as real parts", converted_booleans_count)
            status = "success"
    else:
        logger.warning("convert_cut_parts_to_real_parts failed: No boolean parts converted")
        status = "warning"

    result: dict = {
        "status": status,
        "selected_count": selected_objects.GetSize(),
        "processed_count": processed_count,
        "converted_booleans_count": converted_booleans_count,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def run_macro(macro_name: Annotated[str, Field(description="Name of the macro file to run (e.g. 'MyMacro.cs')")]) -> ToolResult:
    """
    Runs a Tekla macro with the specified name.

    ## AVAILABLE MACROS
    Use the `tekla://macros` resource to get a list of available macros.
    """

    if Operation.IsMacroRunning():
        raise RuntimeError("Tekla is busy running another macro")

    result = Operation.RunMacro(macro_name)

    if not result:
        logger.error("run_macro failed: Macro '%s' returned false", macro_name)
    else:
        logger.info("Ran macro '%s'", macro_name)

    return ToolResult(
        structured_content={
            "status": "success" if result else "error",
            "macro_name": macro_name,
        }
    )


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_model_objects_from_drawings() -> ToolResult:
    """
    Select the model objects corresponding to the currently selected drawings.
    """
    # Runs the bundled macro, which triggers Tekla's native "Select objects in the model
    # for selected drawings" command. The macro approach was chosen because it is fast,
    # needs no reimplementation of logic Tekla already provides natively, and it works

    SELECT_MODEL_OBJECTS_MACRO = "TeklaMCPSelectModelObjectsFromDrawings.cs"
    ensure_macro_installed(SELECT_MODEL_OBJECTS_MACRO, category="modeling")

    macro_result = run_macro(macro_name=SELECT_MODEL_OBJECTS_MACRO)
    if macro_result.structured_content.get("status") != "success":
        raise RuntimeError("Select-in-model macro failed. Ensure Document Manager has drawings selected.")
    # RunMacro only starts the macro, report success once the selection has actually been made
    wait_for_macro(SELECT_MODEL_OBJECTS_MACRO)

    return ToolResult(structured_content={"status": "success"})


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def check_for_orphans(
    mode: Annotated[Literal["subassemblies", "rebars"], Field(description="Check mode: 'subassemblies' (embedded detail assemblies) or 'rebars' (reinforcement)")],
) -> ToolResult:
    """
    Find subassemblies or rebars inside selected elements that are not attached.

    Read-only. Returns pairs of `{object_guid, target_guid}`. Pipe into `attach_assemblies`
    or `attach_rebars` to fix.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()
    tolerance = get_tolerance("default", 20.0)

    orphaned: list[dict] = []
    orphaned_guids: set[str] = set()
    skipped_elements: list[str] = []
    # Embed GUIDs or rebar IDs, one kind per run
    evaluated_guids: set[str | int] = set()
    checked_assembly_guids: set[str] = set()

    for obj in wrap_model_objects(selected_objects):
        if not isinstance(obj, (TeklaPart, TeklaAssembly)):
            skipped_elements.append(obj.guid)
            logger.debug("Skipping non-part/assembly object: %s", obj.guid)
            continue

        # The top-level assembly is where this orphan would attach
        parent_assembly = obj.get_top_level_assembly()
        if parent_assembly is None:
            skipped_elements.append(obj.guid)
            logger.debug("No top-level assembly for %s, skipping", obj.guid)
            continue

        # Selected parts of the same assembly would repeat the whole spatial check
        if parent_assembly.guid in checked_assembly_guids:
            continue
        checked_assembly_guids.add(parent_assembly.guid)

        # Sample points and solids must share one coordinate system
        ev_keys: set[str] | set[int]
        with global_work_plane(model) as work_plane_handler:
            if mode == "subassemblies":
                orphans, ev_keys = _check_element_bounding_box_embeds(parent_assembly, {parent_assembly.guid}, tolerance, work_plane_handler)
            else:  # "rebars"
                orphans, ev_keys = _check_element_bounding_box_rebars(parent_assembly, _get_reinforcement_ids(parent_assembly), tolerance)

        evaluated_guids |= ev_keys

        # Skip duplicates: same orphan may overlap multiple selected elements
        for item in orphans:
            if item.guid in orphaned_guids or item.guid == parent_assembly.guid:
                continue
            orphaned_guids.add(item.guid)
            entry = asdict(item)
            entry.pop("issues", None)
            entry["object_guid"] = entry.pop("guid")
            entry["target_guid"] = parent_assembly.guid
            orphaned.append(entry)

    if not evaluated_guids:
        logger.warning("No %s candidates evaluated: selection may lack geometry or contain none (elements: %d)", mode, selected_objects.GetSize())

    logger.info("check_for_orphans(%s): elements=%d, evaluated=%d, orphaned=%d", mode, selected_objects.GetSize(), len(evaluated_guids), len(orphaned))

    result_content: dict = {
        "status": "warning" if orphaned else "success",
        "mode": mode,
        "selected_count": selected_objects.GetSize(),
        "evaluated_count": len(evaluated_guids),
        "orphaned_count": len(orphaned),
        "orphaned": orphaned,
    }
    if skipped_elements:
        result_content["skipped_elements"] = skipped_elements
        result_content["skipped_count"] = len(skipped_elements)

    return ToolResult(structured_content=result_content)


def _resolve_pair(model: TeklaModel, object_guid: str, target_guid: str) -> tuple[TeklaModelObject, TeklaModelObject, None] | tuple[None, None, str]:
    """
    Look up both GUIDs.

    Args:
        model: Tekla model
        object_guid: Object GUID
        target_guid: Target GUID

    Returns:
        (obj, target, None) on success, or (None, None, reason)
    """
    raw_orphan = model.get_object_by_guid(object_guid)
    if raw_orphan is None:
        return None, None, "object_not_found"
    raw_target = model.get_object_by_guid(target_guid)
    if raw_target is None:
        return None, None, "target_not_found"
    orphan = wrap_model_object(raw_orphan)
    if orphan is None:
        return None, None, "unsupported_object_type"
    target = wrap_model_object(raw_target)
    if target is None:
        return None, None, "unsupported_target_type"
    return orphan, target, None


def _is_valid_assembly_pair(obj, target) -> bool:
    """
    Object and target must both be assemblies.

    Args:
        obj: Wrapped object
        target: Wrapped target

    Returns:
        True if the pair is valid
    """
    return isinstance(obj, TeklaAssembly) and isinstance(target, TeklaAssembly)


def _is_valid_rebar_pair(obj, target) -> bool:
    """
    Object must be reinforcement and the target an assembly.

    Args:
        obj: Wrapped object
        target: Wrapped target

    Returns:
        True if the pair is valid
    """
    return isinstance(obj, TeklaReinforcement) and isinstance(target, TeklaAssembly)


def _attach_assembly(obj: TeklaAssembly, target: TeklaAssembly) -> str | None:
    """
    Add object assembly into target assembly.

    If `Add` succeeds but `modify()` fails later, we log a warning but still return
    None - the change is already in the transaction and will be committed.

    Args:
        obj: Assembly to add
        target: Target assembly

    Returns:
        None on success, or a reason string if adding the assembly failed
    """
    try:
        added = target.model_object.Add(obj.model_object)
    except Exception:
        logger.exception("Add() raised attaching %s to %s", obj.guid, target.guid)
        return "add_failed"
    if not added:
        return "add_failed"
    for label, modify in (("object", obj.modify), ("target", target.modify)):
        try:
            if not modify():
                logger.warning("%s.modify() returned False after attaching %s; committing anyway", label, obj.guid)
        except Exception:
            logger.exception("%s.modify() raised after attaching %s; committing anyway", label, obj.guid)
    return None


def _attach_rebar(obj: TeklaReinforcement, target: TeklaAssembly) -> str | None:
    """
    Set rebar father to target's main part.

    If the father is set but `modify()` fails later, we log a warning but still
    return None - the change is already in the transaction.

    Args:
        obj: Rebar to re-parent
        target: Target assembly

    Returns:
        None on success, or a reason string if there is no main part or setting the father fails
    """
    try:
        main_part = target.main_part
    except ValueError:
        return "no_main_part"
    try:
        obj.father = main_part
    except Exception:
        logger.exception("Setting father raised for %s", obj.guid)
        return "attach_error"
    for label, modify in (("main_part", main_part.modify), ("object", obj.modify)):
        try:
            if not modify():
                logger.warning("%s.modify() returned False after re-parenting %s; committing anyway", label, obj.guid)
        except Exception:
            logger.exception("%s.modify() raised after re-parenting %s; committing anyway", label, obj.guid)
    return None


def _batch_attach(mode: str, pairs: list[AttachmentPair], attach_fn, valid_fn) -> ToolResult:
    """
    Attach each pair in one batch commit. Skip bad pairs and report.

    GUIDs are normalized and repeated pairs are attached once. An object paired with
    several targets is not attached at all. Items in `skipped` failed before changing the model. Only `attach_fn` returning a reason means the
    model was never modified for that pair.

    Args:
        mode: Attachment mode label
        pairs: Object and target GUID pairs
        attach_fn: Attaches one pair
        valid_fn: Validates one pair

    Returns:
        Batch attach tool result

    Raises:
        ValueError: If `pairs` is empty.
    """
    if not pairs:
        raise ValueError("No pairs given")

    model = TeklaModel()
    staged: list[str] = []
    skipped: list[dict] = []
    missing_guids: list[str] = []

    # Spelling variants of one GUID resolve to the same object, so compare normalized pairs
    unique_pairs = dict.fromkeys((normalize_guid(pair.object_guid), normalize_guid(pair.target_guid)) for pair in pairs)
    # An object has one parent, so pairing it with several targets is ambiguous. Attaching
    # each pair in turn would let the last one win and report the object as attached twice
    targets_by_object: dict[str, list[str]] = {}
    for object_guid, target_guid in unique_pairs:
        targets_by_object.setdefault(object_guid, []).append(target_guid)
    for object_guid, targets in targets_by_object.items():
        if len(targets) > 1:
            skipped.append({"object_guid": object_guid, "reason": "conflicting_targets", "target_guids": targets})
    for object_guid, target_guid in unique_pairs:
        if len(targets_by_object[object_guid]) > 1:
            continue
        # Same GUID means the object would attach to itself - always invalid
        if object_guid == target_guid:
            skipped.append({"object_guid": object_guid, "reason": "self_attach"})
            continue

        obj, target, fail_reason = _resolve_pair(model, object_guid, target_guid)
        if fail_reason is not None:
            skipped.append({"object_guid": object_guid, "reason": fail_reason})
            if fail_reason in ("object_not_found", "target_not_found"):
                missing_guid = object_guid if fail_reason == "object_not_found" else target_guid
                if missing_guid not in missing_guids:
                    missing_guids.append(missing_guid)
            continue

        if not valid_fn(obj, target):
            skipped.append({"object_guid": object_guid, "reason": "wrong_type"})
            continue

        try:
            fail_reason = attach_fn(obj, target)
        except Exception:
            logger.exception("Unexpected error attaching %s to %s", object_guid, target_guid)
            fail_reason = "attach_error"

        if fail_reason is None:
            staged.append(object_guid)
        else:
            skipped.append({"object_guid": object_guid, "reason": fail_reason})

    # Only report as attached if the commit succeeds
    attached: list[str] = []
    commit_success: bool | None = None
    if staged:
        commit_success = model.commit_changes()
        if commit_success:
            attached = staged
        else:
            logger.error("commit_changes() failed; %d staged %s not persisted", len(staged), mode)
            skipped.extend({"object_guid": guid, "reason": "commit_failed"} for guid in staged)

    if commit_success is False:
        status = "error"
    elif attached and skipped:
        status = "partial"
    elif skipped:
        status = "error"
    else:
        status = "success"

    logger.info("attach_%s: attached=%d, skipped=%d, missing GUIDs=%s, commit=%s", mode, len(attached), len(skipped), missing_guids, commit_success)

    result_content: dict = {
        "status": status,
        "mode": mode,
        "attached_count": len(attached),
        "attached": attached,
        "skipped": skipped,
        "missing_guids": missing_guids,
    }
    if commit_success is not None:
        result_content["commit_success"] = commit_success

    return ToolResult(structured_content=result_content)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def attach_assemblies(
    pairs: Annotated[list[AttachmentPair], Field(description="Object and target assembly pairs to attach", min_length=1)],
) -> ToolResult:
    """
    Attach assemblies to target assemblies.

    Each pair adds the assembly into the target assembly.
    """
    return _batch_attach("subassemblies", pairs, _attach_assembly, _is_valid_assembly_pair)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def attach_rebars(
    pairs: Annotated[list[AttachmentPair], Field(description="Rebar and target assembly pairs to attach", min_length=1)],
) -> ToolResult:
    """
    Attach reinforcement bars to target assemblies.

    Each pair sets the rebar's father to the target assembly's main part.
    """
    return _batch_attach("rebars", pairs, _attach_rebar, _is_valid_rebar_pair)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def check_for_invalid_objects() -> ToolResult:
    """
    Find invalid objects in selected objects and their bounding boxes.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    tolerance = get_tolerance("default", 20.0)

    # All valid material names and reinforcement grades from Tekla catalogs.
    # An empty set means the catalog could not be read (disconnected) rather than
    # "no valid materials" - guard the validity checks below so a transient catalog
    # failure does not flag every element's material/grade as invalid.
    valid_materials = {item["name"] for item in get_all_materials()}
    valid_grades = {item["grade"] for item in get_all_rebar_items()}

    invalid_parts: list[CheckResult] = []
    invalid_reinforcements: list[CheckResult] = []
    invalid_assemblies: list[CheckResult] = []
    processed_guids: set[str] = set()
    checked_assembly_guids: set[str] = set()
    total_evaluated = 0

    for model_obj in wrap_model_objects(selected_objects):
        if not isinstance(model_obj, (TeklaPart, TeklaAssembly)):
            logger.debug(f"Skipping non-part/assembly object: {type(model_obj).__name__}")
            continue

        # Get top-level assembly for the selected object
        parent_assembly = model_obj.get_top_level_assembly()
        if parent_assembly is None:
            logger.debug("No assembly found for %s, checking object directly", model_obj.guid)
            objects_to_check = [model_obj]
        elif parent_assembly.guid in checked_assembly_guids:
            # Children and the bounding box search were already gathered for this assembly
            continue
        else:
            checked_assembly_guids.add(parent_assembly.guid)
            # Start with all structural children that belong to the assembly
            children = list(wrap_model_objects(parent_assembly.get_all_children()))

            # Also include nearby objects from the bounding box search
            bbox_candidates = get_candidates_in_bounding_box(
                parent_assembly,
                tolerance,
            )

            objects_to_check = children + bbox_candidates

            logger.debug(
                ("Processing assembly %s: %d children, %d bounding box candidates, %d total objects"),
                parent_assembly.guid,
                len(children),
                len(bbox_candidates),
                len(objects_to_check),
            )

        for obj in objects_to_check:
            guid = obj.guid
            if guid in processed_guids:
                continue
            processed_guids.add(guid)

            # Process parts
            if isinstance(obj, TeklaPart):
                total_evaluated += 1
                issues: list[str] = []

                # Missing profile
                profile = obj.profile
                if not profile:
                    issues.append("missing_profile")

                # Missing or invalid material
                material = obj.material
                if not material:
                    issues.append("missing_material")
                elif valid_materials and material not in valid_materials:
                    issues.append(f"invalid_material: '{material}'")

                # Invalid solid
                solid = obj.get_solid()
                if not solid or not solid.IsValid():
                    issues.append("invalid_solid")

                # Zero or negative volume
                try:
                    volume = float(obj.get_report_property("VOLUME"))
                    if volume <= EPSILON:
                        issues.append("zero_volume")
                except Exception as e:
                    logger.warning("Failed to read VOLUME for %s: %s", guid, e)
                    issues.append("volume_unreadable")

                if issues:
                    invalid_parts.append(
                        CheckResult(
                            guid=guid,
                            name=obj.name,
                            position=obj.position,
                            tekla_class=obj.tekla_class,
                            issues=issues,
                        )
                    )

            # Process assemblies
            elif isinstance(obj, TeklaAssembly):
                total_evaluated += 1
                assembly_issues: list[str] = []

                # Missing main part
                try:
                    main = obj.main_part
                except ValueError:
                    assembly_issues.append("no_main_part")
                    main = None

                if assembly_issues:
                    wrapped_main = wrap_model_object(main) if main else None
                    invalid_assemblies.append(
                        CheckResult(
                            guid=guid,
                            name=obj.name,
                            position=obj.position,
                            tekla_class=wrapped_main.tekla_class if wrapped_main else None,
                            issues=assembly_issues,
                        )
                    )

            # Process reinforcements
            elif isinstance(obj, TeklaReinforcement):
                total_evaluated += 1
                reinf_issues: list[str] = []

                # Invalid geometry
                if not obj.model_object.IsGeometryValid():
                    reinf_issues.append("invalid_geometry")

                # Invalid solid
                solid = obj.get_solid()
                if not solid or not solid.IsValid():
                    reinf_issues.append("invalid_solid")

                # Missing or invalid grade
                grade = obj.model_object.Grade
                if not grade:
                    reinf_issues.append("missing_grade")
                elif valid_grades and grade not in valid_grades:
                    reinf_issues.append(f"invalid_grade: '{grade}'")

                # Missing father (not attached to part/assembly)
                if obj.father is None:
                    reinf_issues.append("no_father")

                if reinf_issues:
                    invalid_reinforcements.append(
                        CheckResult(
                            guid=guid,
                            name=obj.name,
                            position=obj.position,
                            tekla_class=obj.tekla_class,
                            issues=reinf_issues,
                        )
                    )

    logger.info(
        "Evaluated %d objects, found %d invalid parts, %d invalid reinforcements, %d invalid assemblies",
        total_evaluated,
        len(invalid_parts),
        len(invalid_reinforcements),
        len(invalid_assemblies),
    )

    result_content = {
        "status": "success" if not invalid_parts and not invalid_reinforcements and not invalid_assemblies else "warning",
        "selected_count": selected_objects.GetSize(),
        "total_evaluated_count": total_evaluated,
        "invalid_parts_count": len(invalid_parts),
        "invalid_reinforcements_count": len(invalid_reinforcements),
        "invalid_assemblies_count": len(invalid_assemblies),
    }

    if invalid_parts:
        result_content["invalid_parts"] = [asdict(r) for r in invalid_parts]

    if invalid_reinforcements:
        result_content["invalid_reinforcements"] = [asdict(r) for r in invalid_reinforcements]

    if invalid_assemblies:
        result_content["invalid_assemblies"] = [asdict(r) for r in invalid_assemblies]

    return ToolResult(structured_content=result_content)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def clash_check(
    min_distance: Annotated[float, Field(description="Minimum clearance in mm for clashes involving reference models and pour objects.", ge=0.0)] = 0.0,
    between_parts: Annotated[bool, Field(description="Check clashes between Tekla parts")] = True,
    between_reference_models: Annotated[bool, Field(description="Check clashes between reference models")] = False,
    objects_inside_reference_models: Annotated[bool, Field(description="Check clashes between Tekla parts and objects inside reference models")] = False,
    filter_name: Annotated[str | None, Field(description="Name of a saved Tekla selection filter. Only objects matching the filter are then selected before the clash check runs")] = None,
) -> ToolResult:
    """
    Run clash check against the current selection.

    ## EXAMPLES
    # Check only objects matching a saved filter
    clash_check(filter_name="CONCRETE_PARTS")

    # Include the IFC reference model in the check
    clash_check(between_reference_models=True, objects_inside_reference_models=True)
    """

    model = TeklaModel()
    selected_objects = list(model.get_selected_objects())

    if filter_name:
        require_selection_filter(filter_name)

        to_select = []
        for raw_obj in selected_objects:
            wrapped = wrap_model_object(raw_obj)
            if isinstance(wrapped, TeklaAssembly):
                for child in wrapped.get_all_children(include_all=True):
                    if Operation.ObjectMatchesToFilter(child, filter_name):
                        to_select.append(child)
            else:
                if Operation.ObjectMatchesToFilter(raw_obj, filter_name):
                    to_select.append(raw_obj)

        if not to_select:
            raise ValueError(f"Filter '{filter_name}' matched 0 objects in current selection ({len(selected_objects)} selected)")

        TeklaModel.select_objects(to_select)
        logger.debug("filter_name=%r: pre-selected %d parts for clash check", filter_name, len(to_select))

    checked_count = model.get_selected_objects().GetSize()

    handler = TeklaClashCheckHandler()
    records = []
    try:
        records = handler.run(
            between_parts=between_parts,
            between_reference_models=between_reference_models,
            objects_inside_reference_models=objects_inside_reference_models,
            min_distance=min_distance,
        )
    finally:
        if filter_name:
            TeklaModel.select_objects(selected_objects)

    timed_out = handler.timed_out
    logger.info(
        "clash_check finished: selected=%d, checked=%d, clashes=%d, timed_out=%s (min_distance=%.1f filter_name=%r)",
        len(selected_objects),
        checked_count,
        len(records),
        timed_out,
        min_distance,
        filter_name,
    )

    result: dict[str, Any] = {
        "status": "warning" if records or timed_out else "success",
        "selected_count": len(selected_objects),
        "checked_objects_count": checked_count,
        "clashes_count": len(records),
        "clashes": [c.to_dict() for c in records],
    }
    if timed_out:
        result["timed_out"] = True
        result["message"] = f"Clash check timed out after {handler.timeout_seconds:.0f}s before Tekla signalled completion. Results may be incomplete - the reported clash count is not conclusive."
    return ToolResult(structured_content=result)


def _report_format(path: Path) -> tuple[str, bool]:
    """
    Return (format_label, is_readable_as_text) based on file extension.

    Args:
        path: Report file path

    Returns:
        Tuple of (format label, readable as text)
    """
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls", ".xlsm", ".xlsb"}:
        return "excel", False
    if suffix == ".pdf":
        return "pdf", False
    if suffix in {".html", ".htm"}:
        return "html", True
    if suffix == ".csv":
        return "csv", True
    if suffix == ".xsr":
        return "xsr", True
    return "text", True


# Caps for `find_nearby_elements`. They bound the work of one call, so each is checked
# before the step it protects
_NEARBY_MAX_GUIDS = 200  # GUIDs accepted, before they are resolved
_NEARBY_MAX_SOURCES = 20  # sources after resolution
_NEARBY_MAX_OBJECTS = 5000  # objects one area search may return, before any is loaded
_NEARBY_MAX_LOADED = 5000  # parts loaded and filtered over the whole call
_NEARBY_MAX_CANDIDATES = 300  # parts near the sources, before top-level lookups and boxes
_NEARBY_MAX_NEIGHBOUR_ASSEMBLIES = 100  # neighbouring assemblies, before their parts are collected
_NEARBY_MAX_NEIGHBOUR_PARTS = 600  # parts of neighbouring assemblies, before their boxes are built
_NEARBY_MAX_PART_PAIRS = 10000  # exact box comparisons
_NEARBY_MAX_PIECES_PER_PART = 16  # search pieces one long rotated part is cut into
# Area searches per source, more fall back to one search. Twice the pieces of one part,
# so a long beam keeps its tight searches next to a few end plates
_NEARBY_MAX_SEARCH_EXTENTS = 2 * _NEARBY_MAX_PIECES_PER_PART
_NEARBY_MAX_TOLERANCE_MM = 50.0
_NEARBY_ANGLE_TOLERANCE_DEG = 1.0
# Box sides within this of each other leave the axis between them unclear, e.g. the thickness of a square
# column. Kept apart from `touch_tolerance_mm`, so a looser contact tolerance does not blur the orientation
_NEARBY_TIE_TOLERANCE_MM = 1.0


@dataclass
class _NearbyUnit:
    """
    One element `find_nearby_elements` measures: a part in part mode, a top-level assembly in assembly mode.

    Attributes:
        element: The part or top-level assembly
        parts: Its parts with their boxes
        main_box: Box whose axes describe the unit
    """

    element: TeklaPart | TeklaAssembly
    parts: list[tuple[TeklaPart, OrientedBox]]
    main_box: OrientedBox

    @property
    def key(self) -> str:
        return self.element.guid

    @property
    def boxes(self) -> list[OrientedBox]:
        """
        Return the boxes of the unit's parts.
        """
        return [box for _, box in self.parts]


def _try_read(getter: Callable[[], Any], errors: tuple[type[Exception], ...] = (KeyError, ValueError)) -> Any:
    """
    Read one identity field, returning None when Tekla has no value for it.

    Only the given errors mean "no value". A lost connection or a wrong attribute name
    still raises, so it is not reported as an empty field.

    Args:
        getter: Zero-argument reader
        errors: Exceptions that mean the value is missing

    Returns:
        The value, or None
    """
    try:
        return getter()
    except errors:
        return None


class _NearbyContext:
    """
    Per-call cache for `find_nearby_elements`.

    Boxes, identities, top-level assemblies and filter results are read from Tekla once
    each, and only for the parts that need them.
    """

    def __init__(self, handler: Any, filter_name: str | None) -> None:
        """
        Start an empty cache.

        Args:
            handler: Work plane handler from `global_work_plane`
            filter_name: Saved selection filter neighbours must match, None for all
        """
        self._handler = handler
        self._filter_name = filter_name
        self._boxes: dict[str, OrientedBox | None] = {}
        self._identities: dict[str, dict[str, Any]] = {}
        self._tops: dict[str, TeklaAssembly | None] = {}
        self._matches: dict[str, bool] = {}
        self._pairs = 0

    def box(self, part: TeklaPart) -> OrientedBox | None:
        """
        Return a part's box.

        Args:
            part: Part to measure

        Returns:
            The box, or None without a solid
        """
        if part.guid not in self._boxes:
            self._boxes[part.guid] = get_oriented_box(part, self._handler)
        return self._boxes[part.guid]

    def count_pair(self) -> None:
        """
        Count one exact box comparison.

        Raises:
            ValueError: If the call would compare more part pairs than the cap allows.
        """
        self._pairs += 1
        _check_cap(self._pairs, _NEARBY_MAX_PART_PAIRS, "part pairs to compare", "Use a smaller `radius_mm`, fewer sources, a `filter_name` or `include_embeds=False`.")

    def top(self, part: TeklaPart) -> TeklaAssembly | None:
        """
        Return a part's top-level assembly.

        Args:
            part: Part to look up

        Returns:
            The assembly, or None
        """
        if part.guid not in self._tops:
            self._tops[part.guid] = part.get_top_level_assembly()
        return self._tops[part.guid]

    def wanted(self, element: TeklaPart | TeklaAssembly) -> bool:
        """
        Check a neighbour against the optional selection filter.

        Tekla ignores part rules when it tests an assembly and assembly rules when it tests
        a part, so callers test parts in part mode and assemblies in assembly mode.

        Args:
            element: Neighbour part or top-level assembly

        Returns:
            True if it is measured
        """
        if self._filter_name is None:
            return True
        if element.guid not in self._matches:
            self._matches[element.guid] = bool(Operation.ObjectMatchesToFilter(element.model_object, self._filter_name))
        return self._matches[element.guid]

    def identity(self, element: TeklaPart | TeklaAssembly) -> dict[str, Any]:
        """
        Return the fields describing an element in the result.

        Args:
            element: Part or top-level assembly

        Returns:
            GUID, type, name, profile and assembly position
        """
        if element.guid in self._identities:
            return self._identities[element.guid]
        if isinstance(element, TeklaPart):
            identity = {
                "guid": element.guid,
                "type": element.element_type,
                "name": _try_read(lambda: element.name),
                "profile": _try_read(lambda: element.profile),
                # Tekla raises AttributeError when a report property has no value
                "assembly_position": _try_read(lambda: element.get_report_property("ASSEMBLY_POS"), (AttributeError, KeyError)),
            }
        else:
            main_part = _try_read(lambda: element.main_part)
            identity = {
                "guid": element.guid,
                "type": "Assembly",
                "name": _try_read(lambda: element.name),
                "assembly_position": _try_read(lambda: element.position, (AttributeError, KeyError)),
                "main_part_profile": main_part.profile if isinstance(main_part, TeklaPart) else None,
            }
        self._identities[element.guid] = identity
        return identity

    def part_unit(self, part: TeklaPart) -> _NearbyUnit | None:
        """
        Build the unit of a single part.

        Args:
            part: Part to measure

        Returns:
            The unit, or None without a solid
        """
        box = self.box(part)
        return None if box is None else _NearbyUnit(part, [(part, box)], box)

    def assembly_unit(self, assembly: TeklaAssembly, parts: list[TeklaPart]) -> _NearbyUnit | None:
        """
        Build the unit of a top-level assembly from the given parts.

        The main part's box gives the unit's axes. When the main part has no solid or is
        not among `parts` (an embed left out), the largest part's box is used instead.

        Args:
            assembly: Top-level assembly
            parts: Parts that make up the unit

        Returns:
            The unit, or None when no part has a solid
        """
        boxed = [(part, box) for part in parts if (box := self.box(part)) is not None]
        if not boxed:
            return None
        main_part = _try_read(lambda: assembly.main_part)
        main_guid = main_part.guid if isinstance(main_part, TeklaPart) else None
        main_box = next((box for part, box in boxed if part.guid == main_guid), None)
        if main_box is None:
            main_box = max((box for _, box in boxed), key=lambda box: math.prod(box.half))
        return _NearbyUnit(assembly, boxed, main_box)


def _resolve_nearby_sources(guids: list[str] | None, mode: str) -> tuple[list[TeklaPart | TeklaAssembly], list[dict[str, Any]]]:
    """
    Turn the given GUIDs, or the current selection, into deduplicated sources.

    Args:
        guids: Source GUIDs, None or empty for the current selection
        mode: 'part' or 'assembly'

    Returns:
        (sources, skipped inputs with a reason)

    Raises:
        ValueError: If nothing is selected, nothing is usable, or more than the source cap remain.
    """
    model = TeklaModel()
    skipped: list[dict[str, Any]] = []
    if guids:
        found, _, missing = model.resolve_guids(guids)
        skipped += [{"guid": guid, "type": None, "reason": "not_found"} for guid in missing]
        raw_objects = list(found)
    else:
        raw_objects = list(model.get_selected_objects())

    sources: dict[str, TeklaPart | TeklaAssembly] = {}
    for raw in raw_objects:
        wrapped = wrap_model_object(raw)
        entry = {"guid": normalize_guid(raw.Identifier.GUID.ToString()), "type": type(raw).__name__}
        if mode == "part":
            if isinstance(wrapped, TeklaPart):
                sources.setdefault(wrapped.guid, wrapped)
            else:
                skipped.append({**entry, "reason": "not_a_part"})
            continue
        top = wrapped.get_top_level_assembly() if wrapped is not None else None
        if isinstance(top, TeklaAssembly):
            sources.setdefault(top.guid, top)
        else:
            skipped.append({**entry, "reason": "no_assembly"})

    if not sources:
        summary = ", ".join(f"{count} {type_name} ({reason})" for (type_name, reason), count in Counter((s["type"], s["reason"]) for s in skipped).items())
        hint = " Use mode='assembly' for assemblies." if mode == "part" and any(s["type"] == "Assembly" for s in skipped) else ""
        raise ValueError(f"No usable source. Skipped: {summary}.{hint}")
    if len(sources) > _NEARBY_MAX_SOURCES:
        raise ValueError(f"{len(sources)} sources resolved, at most {_NEARBY_MAX_SOURCES} are allowed per call")
    return list(sources.values()), skipped


def _check_cap(count: int, cap: int, what: str, hint: str = "Use a smaller `radius_mm` or fewer sources.") -> None:
    """
    Raise when a step would handle more items than one call may.

    Args:
        count: Number of items found
        cap: Most items allowed
        what: Description of the counted items for the message
        hint: What the caller can change

    Raises:
        ValueError: If `count` exceeds `cap`.
    """
    if count > cap:
        raise ValueError(f"Search found {count} {what}, more than the {cap} one call may handle. {hint}")


def _nearby_row(ctx: _NearbyContext, source: _NearbyUnit, neighbour: _NearbyUnit, mode: str, radius: float, tolerance: float) -> tuple[float, float, str, dict[str, Any]] | None:
    """
    Measure one neighbour against one source, part to part.

    Args:
        ctx: Per-call cache
        source: Source unit, its main box gives the axes for `axis_overlap_mm`
        neighbour: Neighbour unit
        mode: 'part' or 'assembly'
        radius: Search radius in mm
        tolerance: Contact tolerance in mm

    Returns:
        (unrounded gap, penetration, neighbour key, row), or None when the neighbour is beyond the radius
    """
    best: tuple[float, float, TeklaPart, TeklaPart] | None = None
    parts_within_radius = 0
    source_extents = [(part, box, aabb([box])) for part, box in source.parts]
    for neighbour_part, neighbour_box in neighbour.parts:
        neighbour_extent = aabb([neighbour_box])
        nearest = math.inf
        for source_part, source_box, source_extent in source_extents:
            # The cheap extent distance skips pairs that cannot be within the radius
            if aabb_gap(source_extent, neighbour_extent) > radius:
                continue
            ctx.count_pair()
            gap, depth = box_gap(source_box, neighbour_box)
            nearest = min(nearest, gap)
            if best is None or (gap, -depth) < (best[0], -best[1]):
                best = (gap, depth, source_part, neighbour_part)
        if nearest <= radius:
            parts_within_radius += 1
    if best is None or best[0] > radius:
        return None

    gap, depth, closest_source, closest_neighbour = best
    row = dict(ctx.identity(neighbour.element))
    if mode == "part":
        source_top, neighbour_top = ctx.top(closest_source), ctx.top(closest_neighbour)
        row["same_assembly"] = source_top is not None and neighbour_top is not None and source_top.guid == neighbour_top.guid
    else:
        row["parts_within_radius"] = parts_within_radius
        row["closest_parts"] = {"source": closest_source.guid, "neighbour": closest_neighbour.guid}
    row.update(
        {
            "gap_mm": round(gap, 1),
            "penetration_mm": round(depth, 1),
            "relation": relation(gap, depth, tolerance),
            "sides": sides(source.boxes, neighbour.boxes, tolerance),
            "axis_overlap_mm": {name: round(value, 1) for name, value in axis_overlap(source.main_box, source.boxes, neighbour.boxes).items()},
            "orientation": orientation(source.main_box, neighbour.main_box, _NEARBY_TIE_TOLERANCE_MM, _NEARBY_ANGLE_TOLERANCE_DEG),
        }
    )
    return gap, depth, neighbour.key, row


def _search_around(unit: _NearbyUnit, radius: float, own: set[str], loaded: set[str]) -> list[TeklaPart]:
    """
    Find the parts within the radius of a unit's extent, without the unit's own parts.

    Each part box gets its own tight search extents, so a long rotated part does not
    search a whole bay. A unit needing more searches than the cap gets one search
    around its whole extent.

    Args:
        unit: Source unit
        radius: Search radius in mm
        own: GUIDs of the unit's own parts, embeds included
        loaded: GUIDs of parts loaded so far in the call, extended here

    Returns:
        Parts found, each once

    Raises:
        ValueError: If a search or the whole call loads more than the caps allow.
    """
    extents = [extent for box in unit.boxes for extent in search_extents(box, radius, _NEARBY_MAX_PIECES_PER_PART)]
    if len(extents) > _NEARBY_MAX_SEARCH_EXTENTS:
        extents = [aabb(unit.boxes, radius)]
    found: dict[str, TeklaPart] = {}
    for lo, hi in extents:
        for part in get_parts_in_extent(lo, hi, _NEARBY_MAX_OBJECTS):
            if part.guid not in own:
                found.setdefault(part.guid, part)
                loaded.add(part.guid)
        _check_cap(len(loaded), _NEARBY_MAX_LOADED, "parts to load")
    return list(found.values())


def _find_nearby(
    sources: list[TeklaPart | TeklaAssembly],
    mode: str,
    handler: Any,
    radius: float,
    limit: int,
    offset: int,
    tolerance: float,
    include_embeds: bool,
    skip_own_assembly: bool,
    filter_name: str | None,
    skipped: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Find the neighbouring parts or top-level assemblies of each source.

    Part mode is assembly mode with one-part units, so both share this path. They differ
    only in what a neighbour is (a part or the top-level assembly of a part) and in the
    extra row fields.

    Args:
        sources: Source parts (part mode) or top-level assemblies (assembly mode)
        mode: 'part' or 'assembly'
        handler: Work plane handler from `global_work_plane`
        radius: Search radius in mm
        limit: Neighbours returned per source
        offset: Neighbours skipped per source before the first one returned
        tolerance: Contact tolerance in mm
        include_embeds: Whether embed parts take part in assembly mode
        skip_own_assembly: Part mode only. Whether parts of the source's own top-level assembly are left out
        filter_name: Saved selection filter neighbours must match, None for all
        skipped: Skipped list, extended with sources that have no geometry

    Returns:
        One entry per measured source

    Raises:
        ValueError: If no source has geometry, or a step would exceed its cap.
    """
    ctx = _NearbyContext(handler, filter_name)

    # Source units, with the GUIDs of each source's own parts, embeds included
    measured: list[tuple[_NearbyUnit, set[str]]] = []
    for source in sources:
        if isinstance(source, TeklaPart):
            unit, own = ctx.part_unit(source), {source.guid}
            if skip_own_assembly and (own_top := ctx.top(source)) is not None:
                # The source's own cast-in items sit inside its box and would crowd out the real neighbours
                own |= {part.guid for part in own_top.get_all_parts(include_embeds=True)}
        else:
            all_parts = source.get_all_parts(include_embeds=True)
            unit = ctx.assembly_unit(source, all_parts if include_embeds else source.get_all_parts(include_embeds=False))
            own = {part.guid for part in all_parts}
        if unit is None:
            skipped.append({"guid": source.guid, "type": source.element_type, "reason": "no_geometry"})
        else:
            measured.append((unit, own))
    if not measured:
        raise ValueError("None of the sources has geometry")

    # Parts near each source. In part mode the filter runs here, before the cap. Assemblies
    # are only known after the top-level lookups the cap protects
    loaded: set[str] = set()
    found = {unit.key: [part for part in _search_around(unit, radius, own, loaded) if mode != "part" or ctx.wanted(part)] for unit, own in measured}
    _check_cap(len({part.guid for parts in found.values() for part in parts}), _NEARBY_MAX_CANDIDATES, "parts near the sources", "Use a smaller `radius_mm`, fewer sources or a `filter_name`.")

    # Neighbour units: each candidate part, or each top-level assembly a candidate belongs to
    neighbours: dict[str, _NearbyUnit] = {}
    neighbour_keys: dict[str, list[str]] = {}
    if mode == "part":
        for unit, _ in measured:
            for part in found[unit.key]:
                if part.guid not in neighbours and (part_unit := ctx.part_unit(part)) is not None:
                    neighbours[part.guid] = part_unit
            neighbour_keys[unit.key] = [part.guid for part in found[unit.key] if part.guid in neighbours]
    else:
        # A top-level lookup walks up the assembly tree and costs about 20 ms. Once one part's
        # assembly is known, its whole part list maps the other parts without a lookup
        seen: dict[str, TeklaAssembly] = {}
        # Parts of each seen assembly without embeds, loaded once and reused as the neighbour's parts
        members: dict[str, list[TeklaPart]] = {}
        owner: dict[str, str] = {}
        tops: dict[str, TeklaAssembly] = {}
        found_by_top: dict[str, list[TeklaPart]] = {}
        for unit, _ in measured:
            keys: dict[str, None] = {}
            for part in found[unit.key]:
                if part.guid not in owner:
                    top = ctx.top(part)
                    if top is None:
                        continue
                    if top.guid not in seen:
                        seen[top.guid] = top
                        _check_cap(len(seen), _NEARBY_MAX_NEIGHBOUR_ASSEMBLIES, "neighbouring assemblies", "Use a smaller `radius_mm` or fewer sources.")
                        # Without embeds, a precast unit can hold hundreds. An embed found nearby gets its own lookup
                        members[top.guid] = top.get_all_parts(include_embeds=False)
                        owner.update((member.guid, top.guid) for member in members[top.guid])
                    owner[part.guid] = top.guid
                top_guid = owner[part.guid]
                top = seen[top_guid]
                if top_guid == unit.key or not ctx.wanted(top):
                    continue
                tops.setdefault(top_guid, top)
                found_by_top.setdefault(top_guid, []).append(part)
                keys.setdefault(top_guid)
            neighbour_keys[unit.key] = list(keys)
        top_parts: dict[str, list[TeklaPart]] = {}
        for guid in tops:
            parts = list(members[guid])
            if include_embeds:
                # Only the neighbour's embeds that lie in the search area, a precast unit can hold hundreds
                base = {part.guid for part in parts}
                parts += [part for part in found_by_top[guid] if part.guid not in base]
            top_parts[guid] = parts
        _check_cap(sum(len(parts) for parts in top_parts.values()), _NEARBY_MAX_NEIGHBOUR_PARTS, "parts in neighbouring assemblies")
        for guid, top in tops.items():
            if (assembly_unit := ctx.assembly_unit(top, top_parts[guid])) is not None:
                neighbours[guid] = assembly_unit
        for unit, _ in measured:
            neighbour_keys[unit.key] = [key for key in neighbour_keys[unit.key] if key in neighbours]

    entries = []
    for unit, _ in measured:
        rows = [row for key in neighbour_keys[unit.key] if (row := _nearby_row(ctx, unit, neighbours[key], mode, radius, tolerance)) is not None]
        # Closest first, deeper penetration first among equal gaps, GUID breaks the rest.
        # The order is stable, so `offset` pages through the same list on every call
        rows.sort(key=lambda item: (item[0], -item[1], item[2]))
        has_more = offset + limit < len(rows)
        entries.append(
            {
                **ctx.identity(unit.element),
                "neighbours_found": len(rows),
                "offset": offset,
                "has_more": has_more,
                "next_offset": offset + limit if has_more else None,
                "neighbours": [row for *_, row in rows[offset : offset + limit]],
            }
        )
    return entries


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def find_nearby_elements(
    guids: Annotated[list[str] | None, Field(description="GUIDs to check. Empty means the current selection. Max 20 sources", max_length=_NEARBY_MAX_GUIDS)] = None,
    mode: Annotated[Literal["part", "assembly"], Field(description="'part': find parts near parts. 'assembly': find cast units near cast units")] = "part",
    radius_mm: Annotated[float, Field(description="How far to search, in mm", ge=0.0, le=5000.0)] = 100.0,
    limit: Annotated[int, Field(description="Max neighbours per element in one page, closest first", ge=1, le=50)] = 20,
    offset: Annotated[int, Field(description="Neighbours to skip per element, the `next_offset` of the previous page", ge=0)] = 0,
    touch_tolerance_mm: Annotated[float, Field(description="Distance in mm that still counts as touching", ge=0.0, le=_NEARBY_MAX_TOLERANCE_MM)] = 1.0,
    include_embeds: Annotated[bool, Field(description="Assembly mode only. Also measure embeds, the neighbours' embeds only within the radius")] = False,
    skip_own_assembly: Annotated[bool, Field(description="Part mode only. Leave out parts of the source's own cast unit, e.g. its cast-in items")] = True,
    filter_name: Annotated[str | None, Field(description="Saved Tekla selection filter. Only matching neighbours are measured. Part mode tests parts, assembly mode tests assemblies")] = None,
) -> ToolResult:
    """
    Find what is near the given parts or assemblies.

    Each part is treated as a box. Cuts, slots and holes are ignored. So the real gap
    can be bigger than `gap_mm`, never smaller, and nothing within the radius is missed.

    Per neighbour:
    - `gap_mm`: space between the boxes, 0 if they go into each other.
    - `penetration_mm`: how far one box must move to get clear of the other, 0 if apart. For an embed deep inside a wall it includes the way out.
    - `relation`: `near`, `touching` (within the tolerance) or `boxes_overlap`. `boxes_overlap` is not a clash, use `clash_check` for that.
    - `sides`: where the neighbour is, in global directions: above, below, +X, -X, +Y, -Y.
    - `axis_overlap_mm`: how much they overlap along the element's length, width and thickness, e.g. how far a slab bears on a wall.
    - `orientation`: for the `length` and the `thickness` axis, the angle between the two elements' axes and its label, `parallel`, `perpendicular` or `skew`. An axis is `null` when it is unclear, e.g. the thickness of a square column.

    In part mode, parts of the source's own cast unit are left out unless `skip_own_assembly`
    is false, then `same_assembly` marks them. In assembly mode, `closest_parts` names the
    two parts that are closest.

    Results come in pages of `limit` per element. When `has_more` is true, call again with
    `offset` set to `next_offset`. Each page repeats the search, the order stays the same.

    Use `filter_name` to skip what does not matter, e.g. a filter for walls only. In part
    mode it must be a part filter, in assembly mode an assembly filter (object type
    Assembly). Tekla lets every assembly pass a part-only filter. Available filters are in
    the `tekla://filters/selection` resource.
    """
    if filter_name:
        require_selection_filter(filter_name)
    sources, skipped = _resolve_nearby_sources(guids, mode)
    with global_work_plane(TeklaModel()) as handler:
        entries = _find_nearby(sources, mode, handler, radius_mm, limit, offset, touch_tolerance_mm, include_embeds, skip_own_assembly, filter_name or None, skipped)

    logger.info("find_nearby_elements(%s): sources=%d, skipped=%d, radius=%.1f", mode, len(entries), len(skipped), radius_mm)
    return ToolResult(
        structured_content={
            "status": "partial" if skipped else "success",
            "geometry_basis": "oriented_boxes",
            "mode": mode,
            "radius_mm": radius_mm,
            "touch_tolerance_mm": touch_tolerance_mm,
            "filter_name": filter_name,
            "limit": limit,
            "has_more": any(entry["has_more"] for entry in entries),
            "sources": entries,
            "skipped": skipped,
        }
    )


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def create_report(
    template_name: Annotated[str, Field(description="Report template name, e.g. 'Cast_Unit_List'")],
    output_filename: Annotated[str | None, Field(description="Output file name without extension. If omitted, the template name is used")] = None,
    output_folder: Annotated[str | None, Field(description="Output folder. When omitted, the default Tekla report output directory is used")] = None,
    title1: Annotated[str, Field(description="First title for the created report")] = "",
    title2: Annotated[str, Field(description="Second title for the created report")] = "",
    title3: Annotated[str, Field(description="Third title for the created report")] = "",
    return_full_content: Annotated[bool, Field(description="When True, return the complete report text instead of the preview for readable formats")] = False,
) -> ToolResult:
    """
    Create a Tekla report from the currently selected model objects.

    The report is generated using a Tekla report template.

    Use the `tekla://reports` resource to discover available report templates before calling this tool.
    """
    if not template_name.strip():
        raise ValueError("'template_name' is required")

    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    # The template directory is a Tekla environment setting. A missing one is a
    # configuration problem, not a bad request - surface it explicitly so the
    # caller does not retry with different arguments.
    if not get_advanced_option_directories("XS_TEMPLATE_DIRECTORY"):
        raise ValueError("XS_TEMPLATE_DIRECTORY is not set or does not point to an existing directory - check the Tekla environment configuration")

    user_provided_folder = bool(output_folder)

    if not output_folder:
        # No folder given: the report lands in XS_REPORT_OUTPUT_DIRECTORY, so that
        # directory must be configured and exist.
        report_dirs = get_advanced_option_directories("XS_REPORT_OUTPUT_DIRECTORY")
        if not report_dirs:
            raise ValueError("XS_REPORT_OUTPUT_DIRECTORY is not set or does not point to an existing directory - check the Tekla environment configuration")
        output_folder = report_dirs[0]
    else:
        # A relative folder is resolved against the model folder, the same meaning
        # relative paths carry for advanced-option directories.
        output_folder = resolve_model_relative_dir(output_folder, model.model_path)
        if not Path(output_folder).is_dir():
            raise ValueError(f"Output directory '{output_folder}' does not exist")

    file_name = build_report_filename(template_name, output_filename)
    output_file = str(Path(output_folder) / file_name)
    report_path = Path(output_file)

    # Remove any leftover report with this name so a stale file from an earlier run
    # cannot be mistaken for fresh output. If it cannot be deleted (e.g. locked),
    # fall back to requiring a newer modification time than the leftover.
    previous_mtime: float | None = None
    if report_path.exists():
        try:
            report_path.unlink()
        except OSError:
            previous_mtime = report_path.stat().st_mtime

    created = Operation.CreateReportFromSelected(template_name, output_file, title1, title2, title3)
    if not created:
        raise RuntimeError(f"Tekla failed to create report from template '{template_name}'. Verify the template exists in XS_TEMPLATE_DIRECTORY and the output path is writable.")

    # Wait for the report to appear AND finish writing. Tekla writes incrementally,
    # so require the size to be stable across two consecutive polls before reading -
    # otherwise the preview could capture a half-written file. `is_file()` also keeps
    # a directory with a colliding name from being treated as the report.
    timeout = get_report_preview_timeout()
    last_size = -1
    settled = False
    while timeout > 0:
        try:
            st = report_path.stat() if report_path.is_file() else None
        except OSError:
            st = None
        if st is not None and (previous_mtime is None or st.st_mtime > previous_mtime):
            if st.st_size == last_size:
                settled = True
                break
            last_size = st.st_size
        time.sleep(0.5)
        timeout -= 0.5

    logger.info("create_report: template=%s, elements=%d, output=%s", template_name, selected_objects.GetSize(), output_file)

    result: dict[str, Any] = {
        "template_name": template_name,
        "selected_count": selected_objects.GetSize(),
        "file_name": report_path.name,
    }

    if settled:
        try:
            size_bytes = report_path.stat().st_size
            fmt, text_readable = _report_format(report_path)
            result["format"] = fmt

            result["content_readable"] = text_readable
            result["size_bytes"] = size_bytes

            if return_full_content:
                if not text_readable:
                    result["status"] = "warning"
                    result["message"] = f"Report is in {fmt.upper()} format and cannot be returned as text. The file is available in the Tekla report output directory."
                else:
                    # Cap full-content reads to avoid loading pathologically large reports into memory.
                    preview_max = get_report_preview_max_chars()
                    full_content_max = preview_max * 10 if preview_max > 0 else 0
                    with report_path.open("r", encoding="utf-8", errors="replace") as f:
                        if full_content_max > 0:
                            chunk = f.read(full_content_max + 1)
                            result["content"] = chunk[:full_content_max]
                            result["content_truncated"] = len(chunk) > full_content_max
                        else:
                            result["content"] = f.read()
                            result["content_truncated"] = False
                    result["status"] = "success"
            else:
                preview_max = get_report_preview_max_chars()
                content_preview: str | None = None
                content_truncated = False
                if preview_max > 0 and text_readable:
                    # Read only preview_max + 1 chars: enough to fill the preview and to
                    # detect truncation, without loading a huge report fully into memory.
                    with report_path.open("r", encoding="utf-8", errors="replace") as f:
                        chunk = f.read(preview_max + 1)
                    content_preview = chunk[:preview_max]
                    content_truncated = len(chunk) > preview_max
                result["status"] = "success"
                if content_preview is not None:
                    result["content_preview"] = content_preview
                    result["content_truncated"] = content_truncated
        except OSError as e:
            # The file is on disk but not readable yet (locked by Tekla / sharing
            # violation on Windows, or not a regular file). Report a warning rather
            # than a hard error, since the report itself was created.
            logger.warning("create_report: report file not readable yet: %s", e)
            result["status"] = "warning"
            result["message"] = "Report was created but could not be read yet, it may still be in use. Try again shortly."
    else:
        result["status"] = "warning"
        result["message"] = "Report was submitted but the file did not appear on disk within the timeout period."

    # Always include the folder when the caller provided one, or on warnings - the
    # caller needs it to locate the file once it eventually lands on disk.
    if user_provided_folder or result["status"] == "warning":
        result["output_folder"] = output_folder

    return ToolResult(structured_content=result)
