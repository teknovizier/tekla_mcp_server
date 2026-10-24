"""
Properties tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from collections import Counter
from collections.abc import Callable
from functools import cache
from typing import Any, Annotated, Literal

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.config import get_tolerance
from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import (
    BoundingBox,
    TeklaAssembly,
    TeklaBeam,
    TeklaBoltGroup,
    TeklaBooleanPart,
    TeklaContourPlate,
    TeklaModelObject,
    TeklaPart,
    TeklaReferenceModel,
    TeklaReferenceModelObject,
    TeklaReinforcement,
    wrap_model_object,
    wrap_model_objects,
)
from tekla_mcp_server.tekla.loader import BooleanPart, CutPlane, EdgeChamfer, Fitting, Operation
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.utils import expand_to_parts, iterate_boolean_parts

properties_provider = LocalProvider()


def _plane_to_dict(plane: Any) -> dict[str, dict[str, float]]:
    """Convert the `Plane` of a fitting or cut plane to its origin and axes, in the current work plane."""
    return {
        "origin": {"x": plane.Origin.X, "y": plane.Origin.Y, "z": plane.Origin.Z},
        "axis_x": {"x": plane.AxisX.X, "y": plane.AxisX.Y, "z": plane.AxisX.Z},
        "axis_y": {"x": plane.AxisY.X, "y": plane.AxisY.Y, "z": plane.AxisY.Z},
    }


def _compact_field_getters(obj: TeklaModelObject) -> dict[str, Callable[[], Any]]:
    """
    Map each `compact` mode field that applies to the object type to a function reading it.

    Args:
        obj: Wrapped model object

    Returns:
        dict of field name to a zero-argument getter. Fields missing from the dict do not apply to the type.
    """
    if isinstance(obj, TeklaPart):
        return {"name": lambda: obj.name, "position": lambda: obj.position, "profile": lambda: obj.profile, "material": lambda: obj.material}
    if isinstance(obj, TeklaAssembly):
        # An assembly has no profile or material of its own, so take them from the main part
        main_part = cache(lambda: obj.main_part)
        return {
            "name": lambda: obj.name,
            "position": lambda: obj.position,
            "profile": lambda: main_part().profile if isinstance(main_part(), TeklaPart) else None,
            "material": lambda: main_part().material if isinstance(main_part(), TeklaPart) else None,
        }
    if isinstance(obj, TeklaReinforcement):
        return {"name": lambda: obj.name, "position": lambda: obj.position, "material": lambda: obj.grade, "size": lambda: obj.size}
    if isinstance(obj, TeklaBooleanPart):
        # A cut part is identified by the part that shapes the cut
        operative = cache(lambda: obj.operative_part)
        return {
            "name": lambda: operative().name if isinstance(operative(), TeklaPart) else None,
            "profile": lambda: operative().profile if isinstance(operative(), TeklaPart) else None,
            "material": lambda: operative().material if isinstance(operative(), TeklaPart) else None,
        }
    if isinstance(obj, TeklaBoltGroup):
        return {"material": lambda: obj.bolt_standard, "size": lambda: obj.bolt_size}
    if isinstance(obj, TeklaReferenceModelObject):
        # IFC objects often lack these properties, so a missing one is None, not an error
        ifc_props = cache(lambda: obj.get_report_properties(["NAME", "PROFILE", "MATERIAL"]))
        return {
            "ifc_guid": lambda: obj.get_report_property("GUID"),
            "name": lambda: ifc_props()["NAME"],
            "profile": lambda: ifc_props()["PROFILE"],
            "material": lambda: ifc_props()["MATERIAL"],
        }
    if isinstance(obj, TeklaReferenceModel):
        return {"name": lambda: obj.title}
    return {}


def _compact_row(obj: TeklaModelObject) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Build the identifying fields of one element for the `compact` mode.

    Each field is read on its own, so a failing field is set to None and reported
    instead of dropping the whole row.

    Args:
        obj: Wrapped model object

    Returns:
        Tuple of (row with GUID, Tekla type, name, position, profile, material and size, errors for fields that failed).
        Fields that do not apply to the type are None.
    """
    row: dict[str, Any] = {"guid": obj.guid, "type": obj.element_type, "name": None, "position": None, "profile": None, "material": None, "size": None}
    errors: list[dict[str, Any]] = []
    for field, getter in _compact_field_getters(obj).items():
        try:
            row[field] = getter()
        except Exception as e:
            logger.warning("Failed to read `%s` of %s: %s", field, row["guid"], e)
            row[field] = None
            errors.append({"guid": row["guid"], "field": field, "error": str(e)})
    return row, errors


def _get_compact_properties(selected_objects: Any) -> dict[str, Any]:
    """
    Read the identifying fields of the selected objects for the `compact` mode.

    Args:
        selected_objects: Enumerator of the selected model objects

    Returns:
        dict with status, counts, element rows, field errors and the objects that could not be wrapped
    """
    elements: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    skipped_objects: list[dict[str, str]] = []
    for raw in selected_objects:
        obj = wrap_model_object(raw)
        if obj is None:
            skipped_objects.append({"guid": raw.Identifier.GUID.ToString(), "type": type(raw).__name__})
            continue
        row, row_errors = _compact_row(obj)
        elements.append(row)
        errors.extend(row_errors)

    logger.info("Retrieved compact properties for %d elements, %d field errors, %d skipped", len(elements), len(errors), len(skipped_objects))
    if not elements:
        status = "warning"
    elif errors:
        status = "partial"
    else:
        status = "success"
    return {
        "status": status,
        "selected_count": selected_objects.GetSize(),
        "processed_count": len(elements),
        "elements": elements,
        "errors": errors,
        "skipped_objects": skipped_objects,
    }


def _validate_at_least_two_selected(count: int) -> None:
    if count == 0:
        raise ValueError("No elements selected. Please select at least two elements.")
    if count == 1:
        raise ValueError("Only one element selected. Please select at least two elements.")


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def set_elements_properties(
    name: Annotated[str | None, Field(description="Part name")] = None,
    profile: Annotated[str | None, Field(description="Profile string (e.g. '3000*200', 'HEA200')")] = None,
    material: Annotated[str | None, Field(description="Material string (e.g. 'C25/30', 'S355J2')")] = None,
    tekla_class: Annotated[int | None, Field(description="Tekla class (e.g. 1, 100 etc.)")] = None,
    finish: Annotated[str | None, Field(description="Finish type")] = None,
    part_prefix: Annotated[str | None, Field(description="Part numbering prefix")] = None,
    part_start_number: Annotated[int | None, Field(description="Part start number")] = None,
    assembly_prefix: Annotated[str | None, Field(description="Assembly numbering prefix")] = None,
    assembly_start_number: Annotated[int | None, Field(description="Assembly start number")] = None,
    phase: Annotated[int | None, Field(description="Phase number (1, 2, 3, etc.)")] = None,
    user_properties: Annotated[dict[str, Any], Field(description="Dictionary of user-defined attribute names and values")] = {},
) -> ToolResult:
    """
    Sets properties and user-defined attributes (UDAs) on selected Tekla elements (assemblies or parts).

    Assemblies do not have `profile`, `material`, `finish`, `tekla_class`, `part_prefix`, `part_start_number`.
    These properties will only affect parts, not assemblies.
    """
    selected_objects = TeklaModel().get_selected_objects()

    total_changes: dict[str, int] = {
        "name": 0,
        "profile": 0,
        "material": 0,
        "tekla_class": 0,
        "finish": 0,
        "part_prefix": 0,
        "part_start_number": 0,
        "assembly_prefix": 0,
        "assembly_start_number": 0,
        "phase": 0,
        "udas": 0,
    }
    processed_count = 0
    modified_count = 0
    property_errors: list[dict] = []

    for selected_object in wrap_model_objects(selected_objects):
        try:
            if isinstance(selected_object, TeklaAssembly):
                changes = selected_object.set_properties(
                    name=name,
                    assembly_prefix=assembly_prefix,
                    assembly_start_number=assembly_start_number,
                    phase=phase,
                    user_properties=user_properties,
                )
            elif isinstance(selected_object, TeklaPart):
                changes = selected_object.set_properties(
                    name=name,
                    profile=profile,
                    material=material,
                    tekla_class=tekla_class,
                    finish=finish,
                    part_prefix=part_prefix,
                    part_start_number=part_start_number,
                    assembly_prefix=assembly_prefix,
                    assembly_start_number=assembly_start_number,
                    phase=phase,
                    user_properties=user_properties,
                )
            else:
                logger.error("set_elements_properties: Unsupported object type: %s", type(selected_object).__name__)
                continue

            elem_errors: list[dict] = changes.pop("errors", [])
            for key, value in changes.items():
                if key in total_changes:
                    total_changes[key] += value
            if any(v > 0 for v in changes.values()):
                modified_count += 1
            if elem_errors:
                logger.warning("Property errors on %s: %s", selected_object.guid, elem_errors)
                property_errors.append({"guid": selected_object.guid, "errors": elem_errors})
        except Exception:
            logger.exception("Failed to set properties on %s", selected_object.guid)
        processed_count += 1

    commit_success: bool | None = None
    if modified_count > 0:
        commit_success = TeklaModel().commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after modifying %s elements", modified_count)

    if commit_success is False:
        status = "error"
        message = "Changes were not persisted. Commit failed (possible constraint violation or locked objects)."
    elif modified_count > 0 and property_errors:
        status = "partial"
        message = f"Modified {modified_count} elements with some errors"
    elif modified_count > 0:
        status = "success"
        message = f"Successfully modified {modified_count} elements"
    else:
        status = "warning"
        message = "No elements were modified"

    logger.info("Set properties result: %s — %s", status, message)
    result: dict = {
        "status": status,
        "message": message,
        "selected_count": selected_objects.GetSize(),
        "processed_count": processed_count,
        "modified_count": modified_count,
        "changes_applied": total_changes,
        "property_errors": property_errors,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_elements_properties(
    report_props_definitions: Annotated[list[str], Field(description="Additional report property names")] = [],
    mode: Annotated[
        Literal["flat", "snapshot", "compact"],
        Field(description="Output detail: 'flat' = key properties table, 'snapshot' = full element state, 'compact' = GUID, type, name, position, profile, material and size only"),
    ] = "flat",
) -> ToolResult:
    """
    Retrieve properties for selected Tekla model objects - parts, assemblies, reinforcement or IFC reference objects.

    ## MODES (select via `mode`)

    ### `mode="flat"` (default)
    Returns key element properties with UDAs, grouped by type.
    Optionally request extra columns via `report_props_definitions`.
    - Extract properties not in default columns; split multi-property phrases into separate items.
    - Example: ["gross weight", "assembly top and bottom level", "length"] → ["gross weight", "assembly top level", "assembly bottom level", "length"]

    ### `mode="snapshot"`
    Returns full element snapshots for convention and QA checks, including basic element properties, UDAs, cutparts, welds and reinforcement.
    Directly selected reinforcement objects are returned in a dedicated `reinforcements` list.

    ### `mode="compact"`
    Returns one row per selected element in `elements` with its GUID, type, name, position, profile, material
    and size. Use it for large or mixed selections to tell the elements apart before requesting details.
    `type` is the Tekla Open API class name, not the structural role. Insulation or a wall layer modeled as a
    beam reports 'Beam', so use name and material to tell what an element is.
    Fields that do not apply to the type are null. Assemblies report the profile and material of their main part.
    Reinforcement reports its grade as material and its bar size as size. Bolt groups report their bolt standard
    as material and their diameter as size. Cut parts report the name, profile and material of the cutting part.
    IFC reference objects also report `ifc_guid`, while `guid` stays the Tekla GUID.
    A field that fails to read is null and listed in `errors`. Selected objects of unsupported types are listed
    in `skipped_objects`. The returned GUIDs feed straight into `select_elements_by_guid` and other
    GUID-consuming tools. `report_props_definitions` is ignored in this mode.
    """
    selected_objects = TeklaModel().get_selected_objects()

    if mode == "compact":
        structured_content = _get_compact_properties(selected_objects)
    elif mode == "snapshot":
        structured_content = _get_snapshot_properties(selected_objects)
    else:
        structured_content = _get_flat_properties(selected_objects, report_props_definitions)

    return ToolResult(structured_content=structured_content)


def _get_snapshot_properties(selected_objects: Any) -> dict[str, Any]:
    """
    Build full snapshots of the selected objects for the `snapshot` mode.

    Args:
        selected_objects: Enumerator of the selected model objects

    Returns:
        dict with status, counts, part, assembly and reinforcement snapshots and errors
    """
    processed_count = 0
    parts: list[dict[str, Any]] = []
    assemblies: list[dict[str, Any]] = []
    reinforcements: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for obj in wrap_model_objects(selected_objects):
        try:
            if isinstance(obj, TeklaPart):
                parts.append(obj.to_snapshot().model_dump())
                processed_count += 1
            elif isinstance(obj, TeklaAssembly):
                assemblies.append(obj.to_snapshot().model_dump())
                processed_count += 1
            elif isinstance(obj, TeklaReinforcement):
                reinforcements.append(obj.to_snapshot().model_dump())
                processed_count += 1
        except Exception as e:
            logger.exception("Failed to build snapshot for %s: %s", obj.guid, str(e))
            errors.append({"guid": obj.guid, "error": str(e)})

    total = len(parts) + len(assemblies) + len(reinforcements)
    logger.info("Snapshot mode: built snapshots for %d parts, %d assemblies, %d reinforcements", len(parts), len(assemblies), len(reinforcements))
    return {
        "status": "success" if total > 0 else "warning",
        "selected_count": selected_objects.GetSize(),
        "processed_count": processed_count,
        "parts": parts,
        "assemblies": assemblies,
        "reinforcements": reinforcements,
        "errors": errors,
    }


def _get_flat_properties(selected_objects: Any, report_props_definitions: list[str]) -> dict[str, Any]:
    """
    Read key properties of the selected objects for the `flat` mode.

    Args:
        selected_objects: Enumerator of the selected model objects
        report_props_definitions: Extra report property names requested by the caller

    Returns:
        dict with status, counts, properties grouped by object type and errors
    """
    processed_count = 0
    resolution_errors: list[dict[str, Any]] = []
    extraction_errors: list[dict[str, Any]] = []
    resolved_props: list[str] = []

    if report_props_definitions:
        resolution = TemplateAttributeParser.resolve_attributes(report_props_definitions)
        resolution_errors = resolution.get("errors", [])
        resolved_props = resolution.get("resolved", [])

        if resolved_props:
            logger.debug("Resolved %d property names: %s", len(resolved_props), resolved_props)
        if resolution_errors:
            logger.warning("Failed to resolve %d properties: %s", len(resolution_errors), [e.get("query") for e in resolution_errors])

    flat_assemblies: list[dict[str, Any]] = []
    flat_parts: list[dict[str, Any]] = []
    flat_reinforcements: list[dict[str, Any]] = []
    reference_objects: list[dict[str, Any]] = []

    for selected_object in wrap_model_objects(selected_objects):
        try:
            props = selected_object.get_properties(resolved_props if resolved_props else None)
        except Exception as e:
            extraction_errors.append({"guid": selected_object.guid, "error": str(e)})
            props = selected_object.get_properties(None)

        if isinstance(selected_object, TeklaReferenceModelObject):
            reference_objects.append(props)
            processed_count += 1
        elif isinstance(selected_object, TeklaAssembly):
            flat_assemblies.append(props)
            processed_count += 1
        elif isinstance(selected_object, TeklaPart):
            flat_parts.append(props)
            processed_count += 1
        elif isinstance(selected_object, TeklaReinforcement):
            flat_reinforcements.append(props)
            processed_count += 1

    logger.info("Retrieved properties for %s elements", processed_count)
    status = "success" if flat_assemblies or flat_parts or flat_reinforcements or reference_objects else "error"
    if resolution_errors or extraction_errors:
        status = "partial"
        if extraction_errors:
            logger.warning("Failed to extract properties for %d elements: %s", len(extraction_errors), [e.get("guid") for e in extraction_errors])

    return {
        "status": status,
        "selected_count": selected_objects.GetSize(),
        "processed_count": processed_count,
        "assemblies": flat_assemblies,
        "parts": flat_parts,
        "reinforcements": flat_reinforcements,
        "reference_objects": reference_objects,
        "resolution_errors": resolution_errors,
        "extraction_errors": extraction_errors,
    }


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_elements_cut_parts(
    include_embeds: Annotated[bool, Field(description="Also check embedded details inside selected assemblies. Directly selected parts are always checked")] = False,
) -> ToolResult:
    """
    Find all boolean cut parts, fittings, cut planes and edge chamfers in the selected Tekla elements, grouped by parent part.

    A selected assembly is expanded to all its parts, including those in subassemblies, so selecting
    a cast unit such as a sandwich wall checks every layer. Reinforcement is skipped and listed in `skipped_objects`.
    `processed_count` is the number of parts checked after this expansion.
    Each part reports its `name`, `position`, `profile` and `material` so layers can be told apart.

    One cutting part often cuts several parts, e.g. one window opening through all layers of a wall.
    `cutting_parts` lists each cutting part once with the GUIDs of all parts it cuts.
    To move or delete openings, act on `cutting_parts`, not on every cut entry, or a shared cutter is changed more than once.

    Coordinates of fitting and cut plane planes and of edge chamfer ends are in the current work plane.
    """
    selected_objects = TeklaModel().get_selected_objects()

    processed_count = 0
    parts_with_cuts: list[dict[str, Any]] = []
    cutting_parts: dict[str, dict[str, Any]] = {}
    total_cut_parts = 0
    total_fittings = 0
    total_cut_planes = 0
    total_edge_chamfers = 0

    parts, skipped_objects = expand_to_parts(list(wrap_model_objects(selected_objects)), include_embeds)
    for part in parts:
        cuts: list[dict[str, Any]] = []
        for boolean in iterate_boolean_parts(part.model_object, (BooleanPart, Fitting, CutPlane, EdgeChamfer)):
            if isinstance(boolean, BooleanPart):
                if boolean.Type != BooleanPart.BooleanTypeEnum.BOOLEAN_CUT:
                    continue
                cutting_part = wrap_model_object(boolean.OperativePart)
                if cutting_part is None:
                    logger.warning("get_elements_cut_parts: could not wrap OperativePart for boolean on %s, skipping", part.guid)
                    continue
                cutting_profile = cutting_part.profile if isinstance(cutting_part, TeklaPart) else "N/A"
                cuts.append(
                    {
                        "type": "BOOLEAN_CUT",
                        "guid": boolean.Identifier.GUID.ToString(),
                        "cutting_part_guid": cutting_part.guid,
                        "cutting_profile": cutting_profile,
                    }
                )
                cutter = cutting_parts.setdefault(cutting_part.guid, {"guid": cutting_part.guid, "profile": cutting_profile, "cut_part_guids": []})
                if part.guid not in cutter["cut_part_guids"]:
                    cutter["cut_part_guids"].append(part.guid)
                total_cut_parts += 1
            elif isinstance(boolean, Fitting):
                cuts.append({"type": "FITTING", "guid": boolean.Identifier.GUID.ToString(), "plane": _plane_to_dict(boolean.Plane)})
                total_fittings += 1
            elif isinstance(boolean, CutPlane):
                cuts.append({"type": "CUT_PLANE", "guid": boolean.Identifier.GUID.ToString(), "plane": _plane_to_dict(boolean.Plane)})
                total_cut_planes += 1
            elif isinstance(boolean, EdgeChamfer):
                chamfer = boolean.Chamfer
                cuts.append(
                    {
                        "type": "EDGE_CHAMFER",
                        "guid": boolean.Identifier.GUID.ToString(),
                        "first_end": {"x": boolean.FirstEnd.X, "y": boolean.FirstEnd.Y, "z": boolean.FirstEnd.Z},
                        "second_end": {"x": boolean.SecondEnd.X, "y": boolean.SecondEnd.Y, "z": boolean.SecondEnd.Z},
                        "chamfer": {"type": str(chamfer.Type), "x": chamfer.X, "y": chamfer.Y},
                    }
                )
                total_edge_chamfers += 1

        if cuts:
            parts_with_cuts.append(
                {
                    "part_guid": part.guid,
                    "name": part.name,
                    "position": part.position,
                    "profile": part.profile,
                    "material": part.material,
                    "cut_count": len(cuts),
                    "cuts": cuts,
                }
            )

        processed_count += 1

    logger.info(
        "Found %s cut parts (%s unique cutting parts), %s fittings, %s cut planes and %s edge chamfers in %s elements with cuts",
        total_cut_parts,
        len(cutting_parts),
        total_fittings,
        total_cut_planes,
        total_edge_chamfers,
        len(parts_with_cuts),
    )
    result: dict[str, Any] = {
        "status": "success" if parts_with_cuts else "warning",
        "selected_count": selected_objects.GetSize(),
        "processed_count": processed_count,
        "total_cut_parts_count": total_cut_parts,
        "total_fittings_count": total_fittings,
        "total_cut_planes_count": total_cut_planes,
        "total_edge_chamfers_count": total_edge_chamfers,
        "cutting_parts": list(cutting_parts.values()),
        "parts_with_cuts": parts_with_cuts,
        "skipped_objects": skipped_objects,
    }
    if not parts:
        result["message"] = "The selection contains no parts. Select parts or assemblies, reinforcement and cut parts are not checked."
    return ToolResult(structured_content=result)


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def compare_elements(
    ignore_numbering: Annotated[bool, Field(description="Skip numbering check")] = False,
) -> ToolResult:
    """
    Compares all selected Tekla elements with each other.
    Supports parts, assemblies, and reinforcement. Requires at least two elements to be selected.
    All selected elements must be of the same type.

    ## RULES
    - Only use information explicitly present in the diff. Do not infer or assume changes.
    - Each diff value is a list aligned by index with `elements`, so the first value belongs to the first element.
      `elements` follows Tekla's selection order, not necessarily the order the user picked.
      When reporting a difference, name the element by its `pos` mark and add the `guid` if marks repeat.
    - With `ignore_numbering`, `pos` marks may be outdated or empty. Identify elements by `guid` then.
    - `id` and `guid` fields are left out of the diff - they always differ and are not actual differences.
    - Ignore order of items in lists (cutparts, reinforcements, welds).
      When all elements have the same number of items, the items are compared in sorted order and keyed by position (`#1`, `#2`, ...).
      When the number differs, `count` gives each element's number of items and `not_in_all` only the items not every element has.
    - For reinforcement: `father_guid` is excluded from the diff - it is a relationship pointer,
      not a property of the rebar itself.
    """
    selected_objects = TeklaModel().get_selected_objects()

    tolerance = get_tolerance("comparison", default=0.01)

    _validate_at_least_two_selected(selected_objects.GetSize())

    raw_objects = list(selected_objects)
    logger.debug("Comparing %d elements", len(raw_objects))

    valid_types = (TeklaPart, TeklaAssembly, TeklaReinforcement)

    # Wrap early so we can validate types before doing any Tekla API calls.
    # Positive isinstance branch lets type checkers narrow obj to the union type.
    wrapped_objects: list[TeklaPart | TeklaAssembly | TeklaReinforcement] = []
    for raw in raw_objects:
        obj = wrap_model_object(raw)
        if isinstance(obj, valid_types):
            wrapped_objects.append(obj)
        else:
            raise TypeError(f"Element must be a part, assembly or reinforcement, got {type(obj).__name__ if obj is not None else 'None'}")

    # Enforce type homogeneity - mixing Part snapshots with Reinforcement snapshots
    # produces meaningless diffs (completely different diff-view schemas).
    def _comparison_category(obj: TeklaModelObject) -> str:
        if isinstance(obj, TeklaReinforcement):
            return "reinforcement"
        if isinstance(obj, TeklaAssembly):
            return "assembly"
        return "part"

    categories = {_comparison_category(o) for o in wrapped_objects}
    if len(categories) > 1:
        raise TypeError(f"Cannot compare mixed object types: {', '.join(sorted(categories))}. Select only parts, only assemblies, or only reinforcement.")

    if not ignore_numbering:
        if not all(Operation.IsNumberingUpToDate(o.model_object) for o in wrapped_objects):
            raise ValueError("Numbering is not up-to-date for selected elements.")

    IGNORED_KEYS = {"id", "guid"}

    def _canonical(value: Any) -> Any:
        if isinstance(value, dict):
            return tuple((k, _canonical(v)) for k, v in sorted(value.items()) if k.lower() not in IGNORED_KEYS)
        if isinstance(value, list):
            return tuple(_canonical(v) for v in value)
        return value

    def _strip_ignored(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _strip_ignored(v) for k, v in value.items() if k.lower() not in IGNORED_KEYS}
        if isinstance(value, list):
            return [_strip_ignored(v) for v in value]
        return value

    def _diff_values(values: list[Any]) -> Any:
        """
        Recursively compute a diff across N per-element values, stripping identical sub-values.

        Returns None when all values are identical.
        """
        if len({_canonical(v) for v in values}) == 1:
            return None  # all identical - strip entirely

        if all(isinstance(v, dict) for v in values):
            all_keys: set[str] = set()
            for v in values:
                all_keys.update(v.keys())
            result: dict[str, Any] = {}
            for key in sorted(all_keys):
                child = _diff_values([v.get(key) for v in values])
                if child is not None:
                    result[key] = child
            return result or None

        if all(isinstance(v, list) for v in values):
            lengths = {len(v) for v in values}
            if len(lengths) == 1:  # same length - recurse positionally
                n = next(iter(lengths))
                # Keyed by position, not a list: every list left in the diff is then a per-element
                # value list aligned with `elements`, and the differing item keeps its position
                positions = {f"#{i + 1}": _diff_values([v[i] for v in values]) for i in range(n)}
                return {pos: child for pos, child in positions.items() if child is not None} or None

            # Different lengths: items every element has are left out, so ten shared
            # cuts and one extra report only the extra one, not all eleven per element
            keys = [[_canonical(item) for item in v] for v in values]
            shared = Counter(keys[0])
            for element_keys in keys[1:]:
                shared &= Counter(element_keys)
            not_in_all = []
            for v, element_keys in zip(values, keys, strict=True):
                remaining = shared.copy()
                extra = []
                for item, key in zip(v, element_keys, strict=True):
                    if remaining[key] > 0:
                        remaining[key] -= 1
                    else:
                        extra.append(item)
                not_in_all.append(extra)
            return {"count": [len(v) for v in values], "not_in_all": not_in_all}

        return values  # primitives or mismatched shapes - show raw values per element

    def _compute_multi_diff(snap_views: list[dict]) -> dict[str, Any] | None:
        """Top-level diff: for each field that differs across any element, recurse into it."""
        all_keys: set[str] = set()
        for snap in snap_views:
            all_keys.update(snap.keys())
        diff: dict[str, Any] = {}
        for key in sorted(all_keys):
            d = _diff_values([snap.get(key) for snap in snap_views])
            if d is not None:
                diff[key] = d
        return diff if diff else None

    # Legend the diff value lists are aligned with. `pos` is not unique (identical
    # elements share a mark), so `guid` stays the identifier
    elements: list[dict[str, str]] = []
    snap_views: list[dict] = []

    for obj in wrapped_objects:
        snapshot = obj.to_snapshot().normalize(tolerance)
        elements.append({"guid": obj.guid, "pos": snapshot.pos})
        snap_views.append(_strip_ignored(snapshot.to_diff_view()))

    diff = _compute_multi_diff(snap_views)
    identical = diff is None

    logger.info("compare_elements: %d elements, identical=%s", len(elements), identical)

    # When identical: minimal confirmation, no diff key
    result: dict[str, Any] = {"status": "success", "identical": identical, "elements": elements}
    if diff is not None:
        result["diff"] = diff
    return ToolResult(structured_content=result)


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def clear_elements_udas(
    uda_names: Annotated[list[str], Field(description="List of specific UDA names to clear")] = [],
) -> ToolResult:
    """
    Clears user-defined attributes (UDAs) from selected Tekla parts and assemblies.

    If the list of specific UDA names is not provided, clears all UDAs.

    ## EXAMPLES
    # Clear all UDAs from selected elements
    clear_elements_udas()

    # Clear only specific UDAs
    clear_elements_udas(uda_names=["STATUS", "APPROVED_BY"])
    """
    selected_objects = TeklaModel().get_selected_objects()

    cleared_udas = 0
    modified_parts = 0
    modified_assemblies = 0

    for selected_object in wrap_model_objects(selected_objects):
        try:
            user_props = selected_object.get_all_user_properties()
            if not user_props:
                continue

            target_keys = [k for k in uda_names if k in user_props] if uda_names else list(user_props.keys())
            if not target_keys:
                continue

            for key in target_keys:
                value = user_props[key]
                if isinstance(value, str):
                    selected_object.set_user_property(key, "")
                elif isinstance(value, int):
                    selected_object.set_user_property(key, -2147483648)
                elif isinstance(value, float):
                    selected_object.set_user_property(key, float(-2147483648))
                cleared_udas += 1

            selected_object.modify()

            if isinstance(selected_object, TeklaPart):
                modified_parts += 1
            elif isinstance(selected_object, TeklaAssembly):
                modified_assemblies += 1
        except Exception:
            logger.exception("Failed to clear UDAs on %s", selected_object.guid)

    commit_success: bool | None = None
    if cleared_udas > 0:
        commit_success = TeklaModel().commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after clearing %d UDAs", cleared_udas)

    if commit_success is False:
        status = "error"
    elif cleared_udas > 0:
        status = "success"
    else:
        status = "warning"
    logger.info("Cleared %s UDAs from %s parts and %s assemblies", cleared_udas, modified_parts, modified_assemblies)
    result: dict = {
        "status": status,
        "selected_count": selected_objects.GetSize(),
        "cleared_udas_count": cleared_udas,
        "modified_parts_count": modified_parts,
        "modified_assemblies_count": modified_assemblies,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_elements_coordinates() -> ToolResult:
    """
    Get coordinates of selected Tekla elements.

    ## OUTPUT
    - Beams: start_point, end_point (x, y, z) and start_point_offset, end_point_offset (dx, dy, dz)
    - Slabs: contour_points list of {x, y, z}
    """
    selected_objects = TeklaModel().get_selected_objects()

    elements: list[dict[str, Any]] = []

    for obj in wrap_model_objects(selected_objects):
        if isinstance(obj, TeklaBeam):
            start_pt = obj.start_point
            end_pt = obj.end_point
            start_offset = obj.start_point_offset
            end_offset = obj.end_point_offset

            elements.append(
                {
                    "guid": obj.guid,
                    "type": "Beam",
                    "start_point": {"x": start_pt.X, "y": start_pt.Y, "z": start_pt.Z},
                    "end_point": {"x": end_pt.X, "y": end_pt.Y, "z": end_pt.Z},
                    "start_point_offset": {"dx": start_offset.Dx, "dy": start_offset.Dy, "dz": start_offset.Dz},
                    "end_point_offset": {"dx": end_offset.Dx, "dy": end_offset.Dy, "dz": end_offset.Dz},
                }
            )
        elif isinstance(obj, TeklaContourPlate):
            contour_pts = obj.contour_points
            elements.append(
                {
                    "guid": obj.guid,
                    "type": "Slab",
                    "contour_points": [{"x": pt.X, "y": pt.Y, "z": pt.Z} for pt in contour_pts],
                }
            )

    logger.info("Retrieved coordinates for %d of %d elements", len(elements), selected_objects.GetSize())
    return ToolResult(
        structured_content={
            "status": "success" if elements else "warning",
            "selected_count": selected_objects.GetSize(),
            "processed_count": len(elements),
            "elements": elements,
        }
    )


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_elements_bounding_boxes() -> ToolResult:
    """
    Get bounding boxes for all selected Tekla elements.

    ## OUTPUT
    Each element entry contains:
    - element_type: Tekla class name (Beam, ContourPlate, Assembly, etc.)
    - min/max: Corner coordinates {x, y, z} in model units (mm)
    - centroid: Center point {x, y, z}
    """
    selected_objects = TeklaModel().get_selected_objects()

    elements: list[dict[str, Any]] = []

    for obj in wrap_model_objects(selected_objects):
        bb = obj.bounding_box
        if bb is None:
            continue
        cx, cy, cz = bb.centroid
        elements.append(
            {
                "guid": obj.guid,
                "element_type": obj.element_type,
                "min": {"x": bb.min_x, "y": bb.min_y, "z": bb.min_z},
                "max": {"x": bb.max_x, "y": bb.max_y, "z": bb.max_z},
                "centroid": {"x": cx, "y": cy, "z": cz},
            }
        )

    selected_count = selected_objects.GetSize()
    processed_count = len(elements)
    if processed_count == 0:
        status = "warning"
    elif processed_count < selected_count:
        status = "partial"
    else:
        status = "success"

    logger.info("Retrieved bounding boxes for %d of %d elements", processed_count, selected_count)
    return ToolResult(
        structured_content={
            "status": status,
            "selected_count": selected_count,
            "processed_count": processed_count,
            "elements": elements,
        }
    )


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def copy_properties_from_ifc(
    user_properties: Annotated[dict[str, str], Field(description="Mapping of IFC property names to Tekla UDA names.")],
) -> ToolResult:
    """
    Copy user-defined properties from IFC reference objects to matching Tekla model elements.

    Use when both IFC references and Tekla parts are selected. The tool matches objects by geometry
    and transfers specified properties from IFC to Tekla elements UDAs.
    """
    selected_objects = TeklaModel().get_selected_objects()

    # Separate IFC references from Tekla parts
    ifc_sources: list[tuple[str, TeklaReferenceModelObject]] = []
    tekla_targets: list[tuple[str, TeklaModelObject]] = []
    skipped_objects: list[dict[str, Any]] = []

    for selected_object in wrap_model_objects(selected_objects):
        if selected_object is None:
            continue
        # Use GUID from report properties: native Tekla objects may not have valid GUID.
        # Isolate per-object failures so one object with an unreadable GUID does not
        # abort the whole tool.
        try:
            guid = str(selected_object.get_report_property("GUID"))
        except Exception as e:
            logger.warning("copy_properties_from_ifc: skipping object %s with unreadable GUID: %s", selected_object.id, e)
            skipped_objects.append({"id": selected_object.id, "error": str(e)})
            continue
        if isinstance(selected_object, TeklaReferenceModelObject):
            ifc_sources.append((guid, selected_object))
        elif isinstance(selected_object, TeklaBooleanPart):
            # A cut part's box can match an IFC opening object better than the real part
            continue
        else:
            tekla_targets.append((guid, selected_object))

    if not ifc_sources:
        raise ValueError("No IFC reference objects found in selection. Please select IFC references and Tekla parts together.")
    if not tekla_targets:
        raise ValueError("No Tekla parts found in selection. Please select IFC references and Tekla parts together.")

    # Collect bounding boxes for matching
    ifc_bboxes: dict[str, Any] = {}
    for guid, obj in ifc_sources:
        bbox = obj.bounding_box
        if bbox is not None:
            ifc_bboxes[guid] = bbox

    tekla_bboxes: dict[str, Any] = {}
    for guid, obj in tekla_targets:
        bbox = obj.bounding_box
        if bbox is not None:
            tekla_bboxes[guid] = bbox

    errors: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    matched_tekla_guids: set[str] = set()
    properties_copied = 0
    matches_made = 0

    # Read once
    match_tol, center_tol_factor = BoundingBox.matching_tolerances()

    # Match IFC to Tekla elements by bounding box and copy properties
    for i, (ifc_guid, ifc_object) in enumerate(ifc_sources):
        if ifc_guid not in ifc_bboxes:
            logger.debug("Skipping IFC %s: no bounding box", ifc_guid)
            continue

        logger.debug("Processing IFC source %d/%d: %s", i + 1, len(ifc_sources), ifc_guid)
        ifc_bbox = ifc_bboxes[ifc_guid]
        found_match = False

        for tekla_guid, tekla_object in tekla_targets:
            if tekla_guid in matched_tekla_guids:
                continue
            if tekla_guid not in tekla_bboxes:
                continue

            tekla_bbox = tekla_bboxes[tekla_guid]
            if ifc_bbox.matches(tekla_bbox, match_tol, center_tol_factor):
                for ifc_prop, uda_name in user_properties.items():
                    try:
                        value = ifc_object.get_report_property(ifc_prop)
                        if value is not None:
                            set_ok = tekla_object.set_user_property(uda_name, value)
                            if set_ok:
                                properties_copied += 1
                            else:
                                errors.append(
                                    {
                                        "ifc_object": ifc_guid,
                                        "tekla_object": tekla_guid,
                                        "ifc_property": ifc_prop,
                                        "uda": uda_name,
                                        "reason": "Failed to set property",
                                    }
                                )
                    except Exception as e:
                        errors.append(
                            {
                                "ifc_object": ifc_guid,
                                "tekla_object": tekla_guid,
                                "ifc_property": ifc_prop,
                                "uda": uda_name,
                                "reason": str(e),
                            }
                        )

                matched_tekla_guids.add(tekla_guid)
                matches_made += 1
                found_match = True
                logger.debug("Matched IFC %s -> Tekla %s", ifc_guid, tekla_guid)
                break

        if not found_match:
            unmatched.append({"ifc_object": ifc_guid, "reason": "No matching Tekla element found"})

    # Track unmatched Tekla elements
    for tekla_guid, _ in tekla_targets:
        if tekla_guid not in matched_tekla_guids:
            unmatched.append({"tekla_object": tekla_guid, "reason": "No matching IFC reference found"})

    if matches_made == 0:
        logger.error("copy_properties_from_ifc failed: No matches made between IFC and Tekla elements")
        status = "error"
    elif errors:
        status = "partial"
    elif unmatched:
        status = "partial"
    else:
        status = "success"

    logger.info("IFC copy complete: %d matches, %d properties copied, %d errors, %d unmatched", matches_made, properties_copied, len(errors), len(unmatched))
    return ToolResult(
        structured_content={
            "status": status,
            "ifc_sources": len(ifc_sources),
            "tekla_targets": len(tekla_targets),
            "matches_made": matches_made,
            "properties_copied": properties_copied,
            "errors": errors,
            "unmatched": unmatched,
            "skipped_objects": skipped_objects,
        }
    )
