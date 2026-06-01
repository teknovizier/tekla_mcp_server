"""
Operations tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

import time
from pathlib import Path
from typing import Any, Annotated, Literal
from pydantic import Field

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult

from tekla_mcp_server.config import get_config, get_tolerance, get_advanced_option_directories, get_report_preview_max_chars, get_report_preview_timeout
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import CheckResult, AttachmentPair
from tekla_mcp_server.utils import mcp_handler, build_report_filename, resolve_model_relative_dir
from tekla_mcp_server.tekla.clash_check import TeklaClashCheckHandler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects, wrap_model_object, TeklaAssembly, TeklaModelObject, TeklaPart, TeklaReinforcement, SolidGeometryMixin, ZERO_GUID
from tekla_mcp_server.tekla.loader import Operation
from tekla_mcp_server.tekla.utils import iterate_boolean_parts, get_candidates_in_bounding_box, get_all_materials, get_all_rebar_items, get_filters


operations_provider = LocalProvider()


def _get_tekla_classes(material_key: str) -> set[int]:
    """Get all tekla_classes for a material group from the config."""
    material = get_config().element_types.get(material_key, {})
    return {tekla_class for type_config in material.values() for tekla_class in type_config.get("tekla_classes", [])}


# Class IDs for filtering candidates in orphan-detection tools
EMBEDDED_DETAILS_CLASSES: set[int] = _get_tekla_classes("MATERIAL_EMBEDDED")
REINFORCEMENT_CLASSES: set[int] = _get_tekla_classes("MATERIAL_REINFORCEMENT")


def _get_reinforcement_guids(element: TeklaAssembly) -> set[str]:
    """Return GUIDs of all reinforcement attached to element, across main part and all secondaries."""
    guids: set[str] = set()

    try:
        reinfs = element.main_part.model_object.GetReinforcements()
    except Exception:
        reinfs = None

    if reinfs is not None:
        for rebar in wrap_model_objects(reinfs):
            if rebar:
                guids.add(rebar.guid)

    try:
        secondaries = element.model_object.GetSecondaries()
    except Exception:
        secondaries = None

    if secondaries is not None:
        for sec in secondaries:
            try:
                sec_reinfs = sec.GetReinforcements()
            except Exception:
                continue
            for rebar in wrap_model_objects(sec_reinfs):
                if rebar:
                    guids.add(rebar.guid)

    return guids


def _is_inside_any_assembly_part(candidate: SolidGeometryMixin, parts: list[TeklaPart]) -> bool:
    """
    Check whether candidate lies within the solid geometry of any part in the list.

    Returns True when any part's solid contains the candidate.
    Returns False when no part contained the candidate, or when the list is empty
    (degenerate/no-geometry elements are skipped to avoid false-positive orphans).

    Delegates to `is_inside` which handles the NORMAL → RAW fallback internally
    for TeklaPart containers and never propagates exceptions (conservative True).
    """
    for part in parts:
        if candidate.is_inside(part):
            return True
    return False


def _check_element_bounding_box_embeds(
    element: TeklaAssembly,
    target_assembly_guids: set[str],
    tolerance: float,
) -> tuple[list[CheckResult], set[str]]:
    """
    Find embedded details inside element that are not attached to it.

    Uses bounding box to find candidates, then checks containment and parent assembly.

    Returns (orphaned, evaluated_guids) with deduplicated GUIDs.
    """
    # Pre-compute assembly parts once (not per-candidate) for containment checks
    assembly_parts = element.get_top_level_parts()
    if not assembly_parts:
        return [], set()

    candidates = get_candidates_in_bounding_box(element, tolerance)

    orphaned: list[CheckResult] = []
    processed_guids: set[str] = set()

    for candidate in candidates:
        # Candidates may be parts belonging to a multi-part embed, promote to assembly
        # so we evaluate and report at assembly level rather than per-part
        assembly_obj = None
        wrapped_assembly = None

        if isinstance(candidate, TeklaAssembly):
            wrapped_assembly = candidate
            assembly_obj = candidate.model_object
        elif isinstance(candidate, TeklaPart):
            assembly_obj = candidate.model_object.GetAssembly()
            if assembly_obj:
                wrapped_assembly = wrap_model_object(assembly_obj)

        if not assembly_obj or not wrapped_assembly:
            continue

        # A multi-part embed yields multiple candidates that resolve to the same assembly, process each assembly once
        assembly_guid = wrapped_assembly.guid
        if assembly_guid in processed_guids:
            continue

        try:
            candidate_main = wrapped_assembly.main_part
        except ValueError:
            continue

        # Only embedded-detail classes are relevant, other nearby objects are ignored
        part_class = candidate_main.tekla_class
        if part_class not in EMBEDDED_DETAILS_CLASSES:
            continue

        # Skip embeds that are in the bounding box but outside the element's actual solid
        if not _is_inside_any_assembly_part(candidate_main, assembly_parts):
            continue

        processed_guids.add(assembly_guid)

        # An embed is orphaned when its parent assembly isn't one of the assemblies we're
        # checking against - i.e. it's physically inside the element but not attached to it
        parent = assembly_obj.GetAssembly()
        parent_guid = parent.Identifier.GUID.ToString() if parent else None

        if parent_guid not in target_assembly_guids:
            orphaned.append(
                CheckResult(
                    guid=assembly_guid,
                    name=candidate_main.name,
                    position=candidate_main.position,
                    tekla_class=part_class,
                )
            )
    logger.debug("Found %d orphaned embeds for element %s", len(orphaned), element.guid)
    return orphaned, processed_guids


def _check_element_bounding_box_rebars(
    element: TeklaAssembly,
    element_reinforcement_guids: set[str],
    tolerance: float,
) -> tuple[list[CheckResult], set[str]]:
    """
    Find rebars inside element that are not in element_reinforcement_guids.

    Uses bounding box to find candidates, then checks containment and attachment status.

    Returns (orphaned, evaluated_guids) with deduplicated GUIDs.
    """
    # Pre-compute assembly parts once (not per-candidate) for containment checks
    assembly_parts = element.get_top_level_parts()
    if not assembly_parts:
        return [], set()

    candidates = get_candidates_in_bounding_box(element, tolerance)
    if not candidates:
        return [], set()

    orphaned: list[CheckResult] = []
    evaluated_guids: set[str] = set()

    for candidate in candidates:
        if not isinstance(candidate, TeklaReinforcement):
            continue

        # Only reinforcement classes are relevant, other nearby objects are ignored
        reinforcement_class = candidate.tekla_class
        if reinforcement_class not in REINFORCEMENT_CLASSES:
            continue

        # Skip rebars that are in the bounding box but outside the element's actual solid
        if not _is_inside_any_assembly_part(candidate, assembly_parts):
            continue

        evaluated_guids.add(candidate.guid)

        # Rebar is correctly attached to this element - not orphaned
        if candidate.guid in element_reinforcement_guids:
            continue

        # Starter bars: rebar belongs to a neighboring element and
        # legitimately reaches into this one. Recognised by the bar still lying
        # inside the solid of its actual father part.
        # We check only the father part, not the entire father assembly, because we
        # are verifying specific ownership.
        father = candidate.father
        if father is not None and father.guid != ZERO_GUID and candidate.is_inside(father):
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
    return orphaned, evaluated_guids


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def cut_elements_with_cutters(
    cutter_class: Annotated[int | None, Field(description="Tekla class of the parts to use as cutters")] = None,
    cutter_guids: Annotated[list[str] | None, Field(description="GUIDs of the parts to use as cutters")] = None,
    delete_cutting_parts: Annotated[bool, Field(description="Remove cutting parts after cuts are applied")] = False,
) -> ToolResult:
    """
    Performs boolean cuts on selected model objects.

    Provide exactly one of:
    - `cutter_class`: use all parts with the specified Tekla class as cutters
    - `cutter_guids`: use specific parts as cutters (useful in multi-step workflows)
    """
    if cutter_class is None and cutter_guids is None:
        raise ValueError("Provide exactly one of 'cutter_class' or 'cutter_guids'")
    if cutter_class is not None and cutter_guids is not None:
        raise ValueError("Provide exactly one of 'cutter_class' or 'cutter_guids'")

    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    if cutter_class is not None:
        raw_cutters = model.get_objects_by_class(cutter_class)
        label = f"class {cutter_class}"
    else:
        assert cutter_guids is not None  # narrowed by the guards above
        raw_cutters = model.get_objects_by_guid(cutter_guids)
        label = f"{len(cutter_guids)} GUIDs"

    processed_count = 0
    performed_cuts = 0
    cutters = list(wrap_model_objects(raw_cutters))
    logger.debug("Processing %d selected objects with %d cutters (%s)", selected_objects.GetSize(), len(cutters), label)
    if cutters:
        for selected_object in wrap_model_objects(selected_objects):
            element_had_cut = False
            for cutter in cutters:
                if selected_object.add_cut(cutter, delete_cutting_parts):
                    performed_cuts += 1
                    element_had_cut = True
            if element_had_cut:
                processed_count += 1
    commit_success: bool | None = None
    if performed_cuts:
        commit_success = model.commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after performing %d cuts", performed_cuts)
            status = "error"
        else:
            logger.info("Performed %s cuts on %s elements", performed_cuts, processed_count)
            status = "success"
    else:
        logger.warning("cut_elements_with_cutters: No cuts performed (%s)", label)
        status = "warning"

    result: dict = {
        "status": status,
        "elements_count": selected_objects.GetSize(),
        "processed_count": processed_count,
        "performed_cuts_count": performed_cuts,
    }
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
            logger.debug("convert_cut_parts_to_real_parts: skipping non-part object: %s", selected_object.GetType())
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
        "elements_count": selected_objects.GetSize(),
        "processed_count": processed_count,
        "converted_booleans_count": converted_booleans_count,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def run_macro(macro_name: Annotated[str, Field(description="Name of the macro file to run (e.g., 'MyMacro.cs'")]) -> ToolResult:
    """
    Runs a Tekla macro with the specified name.

    ## AVAILABLE MACROS
    Use the `macro://list` resource to get a list of available macros.
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
def check_for_orphans(
    mode: Annotated[Literal["subassemblies", "rebars"], Field(description="Check mode: 'subassemblies' (embedded detail assemblies) or 'rebars' (reinforcement)")],
) -> ToolResult:
    """
    Find sub-assemblies or rebars inside selected elements that are not attached.

    Read-only. Returns pairs of `{object_guid, target_guid}`. Pipe into `attach_assemblies`
    or `attach_rebars` to fix.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()
    tolerance = get_tolerance()

    orphaned: list[dict] = []
    orphaned_guids: set[str] = set()
    skipped_elements: list[str] = []
    evaluated_guids: set[str] = set()

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

        if mode == "subassemblies":
            orphans, ev_guids = _check_element_bounding_box_embeds(parent_assembly, {parent_assembly.guid}, tolerance)
        else:  # "rebars"
            orphans, ev_guids = _check_element_bounding_box_rebars(parent_assembly, _get_reinforcement_guids(parent_assembly), tolerance)

        evaluated_guids |= ev_guids

        # Skip duplicates: same orphan may overlap multiple selected elements
        for item in orphans:
            if item.guid in orphaned_guids or item.guid == parent_assembly.guid:
                continue
            orphaned_guids.add(item.guid)
            entry = item.model_dump(mode="json")
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
        "elements_count": selected_objects.GetSize(),
        "evaluated_count": len(evaluated_guids),
        "orphaned_count": len(orphaned),
        "orphaned": orphaned,
    }
    if skipped_elements:
        result_content["skipped_elements"] = skipped_elements
        result_content["skipped_count"] = len(skipped_elements)

    return ToolResult(structured_content=result_content)


def _resolve_pair(model: TeklaModel, object_guid: str, target_guid: str) -> tuple[TeklaModelObject, TeklaModelObject, None] | tuple[None, None, str]:
    """Look up both GUIDs. Returns (obj, target, None) or (None, None, reason)."""
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
    """Object and target must both be assemblies."""
    return isinstance(obj, TeklaAssembly) and isinstance(target, TeklaAssembly)


def _is_valid_rebar_pair(obj, target) -> bool:
    """Object must be reinforcement and the target an assembly."""
    return isinstance(obj, TeklaReinforcement) and isinstance(target, TeklaAssembly)


def _attach_assembly(obj: TeklaAssembly, target: TeklaAssembly) -> str | None:
    """Add object assembly into target assembly.

    Returns None on success. Returns a reason string if adding the assembly failed.
    If `Add` succeeds but `modify()` fails later, we log a warning but still return
    None - the change is already in the transaction and will be committed.
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
    """Set rebar father to target's main part.

    Returns None on success. Returns a reason string if the target has no main part
    or if setting the father fails. If the father is set but `modify()` fails later,
    we log a warning but still return None - the change is already in the transaction.
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
    """Attach each pair in one batch commit. Skip bad pairs and report. Empty input returns success with nothing done.

    Items in `skipped` failed before changing the model. Only `attach_fn` returning a
    reason means the model was never modified for that pair.
    """
    model = TeklaModel()
    staged: list[str] = []
    skipped: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for pair in pairs:
        # Drop exact duplicate pairs so a GUID can't be double-counted in `attached`
        key = (pair.object_guid, pair.target_guid)
        if key in seen:
            skipped.append({"object_guid": pair.object_guid, "reason": "duplicate_pair"})
            continue
        seen.add(key)

        # Same GUID means the object would attach to itself - always invalid
        if pair.object_guid == pair.target_guid:
            skipped.append({"object_guid": pair.object_guid, "reason": "self_attach"})
            continue

        obj, target, fail_reason = _resolve_pair(model, pair.object_guid, pair.target_guid)
        if fail_reason is not None:
            skipped.append({"object_guid": pair.object_guid, "reason": fail_reason})
            continue

        if not valid_fn(obj, target):
            skipped.append({"object_guid": pair.object_guid, "reason": "wrong_type"})
            continue

        try:
            fail_reason = attach_fn(obj, target)
        except Exception:
            logger.exception("Unexpected error attaching %s to %s", pair.object_guid, pair.target_guid)
            fail_reason = "attach_error"

        if fail_reason is None:
            staged.append(pair.object_guid)
        else:
            skipped.append({"object_guid": pair.object_guid, "reason": fail_reason})

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
        status = "warning"
    elif skipped:
        status = "error"
    else:
        status = "success"

    logger.info("attach_%s: attached=%d, skipped=%d, commit=%s", mode, len(attached), len(skipped), commit_success)

    result_content: dict = {
        "status": status,
        "mode": mode,
        "attached_count": len(attached),
        "attached": attached,
        "skipped": skipped,
    }
    if commit_success is not None:
        result_content["commit_success"] = commit_success

    return ToolResult(structured_content=result_content)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def attach_assemblies(
    pairs: Annotated[list[AttachmentPair], Field(description="Object and target assembly pairs to attach")],
) -> ToolResult:
    """
    Attach assemblies to target assemblies.

    Each pair adds the assembly into the target assembly.
    """
    return _batch_attach("subassemblies", pairs, _attach_assembly, _is_valid_assembly_pair)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def attach_rebars(
    pairs: Annotated[list[AttachmentPair], Field(description="Rebar and target assembly pairs to attach")],
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

    tolerance = get_tolerance()

    # All valid material names and reinforcement grades from Tekla catalogs
    valid_materials = {item["name"] for item in get_all_materials()}
    valid_grades = {item["grade"] for item in get_all_rebar_items()}

    invalid_parts: list[CheckResult] = []
    invalid_reinforcements: list[CheckResult] = []
    invalid_assemblies: list[CheckResult] = []
    processed_guids: set[str] = set()
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
        else:
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
                elif material not in valid_materials:
                    issues.append(f"invalid_material: '{material}'")

                # Invalid solid
                solid = obj.get_solid()
                if not solid or not solid.IsValid():
                    issues.append("invalid_solid")

                # Zero or negative volume
                try:
                    volume = float(obj.get_report_property("VOLUME"))
                    epsilon = 0.0001
                    if volume <= epsilon:
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
                elif grade not in valid_grades:
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
        "elements_count": selected_objects.GetSize(),
        "total_evaluated_count": total_evaluated,
        "invalid_parts_count": len(invalid_parts),
        "invalid_reinforcements_count": len(invalid_reinforcements),
        "invalid_assemblies_count": len(invalid_assemblies),
    }

    if invalid_parts:
        result_content["invalid_parts"] = invalid_parts

    if invalid_reinforcements:
        result_content["invalid_reinforcements"] = invalid_reinforcements

    if invalid_assemblies:
        result_content["invalid_assemblies"] = invalid_assemblies

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
        available_filters = get_filters(".SObjGrp")
        if filter_name not in available_filters:
            raise ValueError(f"Filter '{filter_name}' not found. Available filters: {available_filters}")

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

    logger.info(
        "clash_check finished: selected=%d, checked=%d, clashes=%d (min_distance=%.1f filter_name=%r)",
        len(selected_objects),
        checked_count,
        len(records),
        min_distance,
        filter_name,
    )

    return ToolResult(
        structured_content={
            "status": "success" if not records else "warning",
            "elements_count": len(selected_objects),
            "checked_objects_count": checked_count,
            "clashes_count": len(records),
            "clashes": [c.to_dict() for c in records],
        }
    )


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def create_report(
    template_name: Annotated[str, Field(description="Report template name, e.g. 'Cast_Unit_List'")],
    output_filename: Annotated[str | None, Field(description="Output file name without extension. If omitted, the template name is used")] = None,
    output_folder: Annotated[str | None, Field(description="Output folder. When omitted, the default Tekla report output directory is used.")] = None,
    title1: Annotated[str, Field(description="First title for the created report")] = "",
    title2: Annotated[str, Field(description="Second title for the created report")] = "",
    title3: Annotated[str, Field(description="Third title for the created report")] = "",
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

    # The template directory is a Tekla environment setting; a missing one is a
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
        output_folder = resolve_model_relative_dir(output_folder, model.model.GetInfo().ModelPath or "")
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
        "elements_count": selected_objects.GetSize(),
        "file_name": report_path.name,
    }

    if settled:
        try:
            size_bytes = report_path.stat().st_size
            preview_max = get_report_preview_max_chars()
            content_preview: str | None = None
            content_truncated = False
            if preview_max > 0:
                # Read only preview_max + 1 chars: enough to fill the preview and to
                # detect truncation, without loading a huge report fully into memory.
                with report_path.open("r", encoding="utf-8", errors="replace") as f:
                    chunk = f.read(preview_max + 1)
                content_preview = chunk[:preview_max]
                content_truncated = len(chunk) > preview_max
        except OSError as e:
            # The file is on disk but not readable yet (locked by Tekla / sharing
            # violation on Windows, or not a regular file). Report a warning rather
            # than a hard error, since the report itself was created.
            logger.warning("create_report: report file not readable yet: %s", e)
            result["status"] = "warning"
            result["message"] = "Report was created but could not be read yet, it may still be in use. Try again shortly."
        else:
            result["status"] = "success"
            result["size_bytes"] = size_bytes
            if content_preview is not None:
                result["content_preview"] = content_preview
                result["content_truncated"] = content_truncated
    else:
        result["status"] = "warning"
        result["message"] = "Report was submitted but the file did not appear on disk within the timeout period."

    # Normally the default output directory is not exposed (only the file name is
    # returned). On a warning the caller needs the folder to locate the file once
    # it eventually lands, so include it regardless.
    if user_provided_folder or result["status"] == "warning":
        result["output_folder"] = output_folder

    return ToolResult(structured_content=result)
