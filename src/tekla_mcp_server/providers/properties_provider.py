"""
Properties tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from collections import Counter
from typing import Any, Annotated

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import TeklaAssembly, TeklaBeam, TeklaContourPlate, TeklaPart, wrap_model_object, wrap_model_objects
from tekla_mcp_server.tekla.loader import Part, BooleanPart, Operation
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.utils import iterate_boolean_parts

properties_provider = LocalProvider()


def _validate_exactly_two_selected(count: int) -> ToolResult | None:
    if count == 0:
        return ToolResult(structured_content={"status": "error", "message": "No elements selected. Please select two elements."})
    if count == 1:
        return ToolResult(structured_content={"status": "error", "message": "Only one element selected. Please select two elements."})
    if count > 2:
        return ToolResult(structured_content={"status": "error", "message": f"More than two elements selected. Expected 2, got {count}."})
    return None


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def set_elements_properties(
    name: Annotated[str | None, Field(description="Part name")] = None,
    profile: Annotated[str | None, Field(description="Profile string (e.g., '3000*200', 'HEA200')")] = None,
    material: Annotated[str | None, Field(description="Material string (e.g., 'C25/30', 'S355J2')")] = None,
    tekla_class: Annotated[int | None, Field(description="Tekla class (e.g., 1, 100 etc.)")] = None,
    finish: Annotated[str | None, Field(description="Finish type")] = None,
    part_prefix: Annotated[str | None, Field(description="Part numbering prefix")] = None,
    part_start_number: Annotated[int | None, Field(description="Part start number")] = None,
    assembly_prefix: Annotated[str | None, Field(description="Assembly numbering prefix")] = None,
    assembly_start_number: Annotated[int | None, Field(description="Assembly start number")] = None,
    phase: Annotated[int | None, Field(description="Phase number (1, 2, 3, etc.)")] = None,
    user_properties: Annotated[dict[str, Any] | None, Field(description="Dictionary of user-defined attribute names and values")] = None,
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
    processed_elements = 0
    modified_elements = 0

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
                    tekla_class=str(tekla_class),
                    finish=finish,
                    part_prefix=part_prefix,
                    part_start_number=part_start_number,
                    assembly_prefix=assembly_prefix,
                    assembly_start_number=assembly_start_number,
                    phase=phase,
                    user_properties=user_properties,
                )
            else:
                logger.warning("Unsupported object type: %s", type(selected_object).__name__)
                continue

            for key, value in changes.items():
                if key in total_changes:
                    total_changes[key] += value
            if any(v > 0 for v in changes.values()):
                modified_elements += 1
        except Exception:
            logger.exception("Failed to set properties on %s", selected_object.guid)
        processed_elements += 1

    if modified_elements > 0:
        TeklaModel().commit_changes()

    logger.info("Set properties on %s elements: %s", modified_elements, total_changes)
    return ToolResult(
        structured_content={
            "status": "success" if modified_elements > 0 else "warning",
            "selected_elements": selected_objects.GetSize(),
            "processed_elements": processed_elements,
            "modified_elements": modified_elements,
            "changes_applied": total_changes,
        }
    )


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_elements_properties(
    report_props_definitions: Annotated[list[str] | None, Field(description="List of user-friendly property names")] = None,
) -> ToolResult:
    """
    Retrieve key properties for selected Tekla elements (assemblies or parts).

    ### BEHAVIOR
    - Extract properties not in default columns; split multi-property phrases into separate items.
    - Example: ["gross weight", "assembly top and bottom level", "length"] → ["gross weight", "assembly top level", "assembly bottom level", "length"]

    ## OUTPUT
    - Return the result table in Markdown format EXACTLY as provided by the tool.
    - DO NOT reformat.
    - DO NOT modify spacing, columns, or headers.
    """
    selected_objects = TeklaModel().get_selected_objects()

    resolution_errors: list[dict[str, Any]] = []
    extraction_errors: list[dict[str, Any]] = []
    resolved_props: list[str] = []

    if report_props_definitions:
        resolution = TemplateAttributeParser.resolve_attributes(report_props_definitions)
        resolution_errors = resolution.get("errors", [])
        resolved_props = resolution.get("resolved", [])

    assemblies: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    processed_elements = 0

    for selected_object in wrap_model_objects(selected_objects):
        try:
            props = selected_object.get_properties(resolved_props if resolved_props else None)
        except Exception as e:
            extraction_errors.append({"guid": selected_object.guid, "error": str(e)})
            props = selected_object.get_properties(None)

        if isinstance(selected_object, TeklaAssembly):
            assemblies.append(props)
        elif isinstance(selected_object, TeklaPart):
            parts.append(props)
        processed_elements += 1

    logger.info("Retrieved properties for %s elements", processed_elements)
    status = "success" if assemblies or parts else "error"
    if resolution_errors or extraction_errors:
        status = "partial"

    def _flatten_props(props: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        result["GUID"] = props.get("guid", "")
        standard_fields = ["position", "name", "profile", "material", "finish", "tekla_class", "part_prefix", "part_start_number", "assembly_prefix", "assembly_start_number"]
        for field in standard_fields:
            if field in props:
                result[field.replace("_", " ").title()] = props[field]
        result["Phase"] = props.get("phase", "")
        return result

    def _flatten(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return []
        flat_items = []
        for i, item in enumerate(items):
            row = _flatten_props(item)
            if user_props := item.get("user_properties"):
                row.update(user_props)
            if report_props := item.get("report_properties"):
                for rp in report_props:
                    name = rp.get("name", "")
                    value = rp.get("value")
                    unit = rp.get("unit", "")
                    header = f"{name} ({unit})" if unit else name
                    if value is not None:
                        row[header] = round(value, 3) if isinstance(value, float) else value
                    else:
                        row[header] = "N/A"
            flat_items.append({"No": i + 1, **row})
        return flat_items

    content_json = {k: v for k, v in (("assemblies", _flatten(assemblies)), ("parts", _flatten(parts))) if v}

    return ToolResult(
        content=content_json,
        structured_content={
            "status": status,
            "selected_elements": selected_objects.GetSize(),
            "processed_elements": processed_elements,
            "assemblies": assemblies,
            "parts": parts,
            "resolution_errors": resolution_errors,
            "extraction_errors": extraction_errors,
        },
    )


@properties_provider.tool(tags={"catalog"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_elements_cut_parts() -> ToolResult:
    """
    Find all cut parts in the selected Tekla elements and return a summary grouped by profile.

    ## OUTPUT
    - Return the result table in Markdown format EXACTLY as provided by the tool.
    - DO NOT reformat.
    - DO NOT modify spacing, columns, or headers.
    """
    selected_objects = TeklaModel().get_selected_objects()

    processed_elements = 0
    cut_parts_by_profile: Counter[str] = Counter()

    for selected_object in selected_objects:
        if not isinstance(selected_object, Part):
            logger.warning("Skipping non-Part object: %s", selected_object.GetType())
            continue
        for boolean_part in iterate_boolean_parts(selected_object):
            if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT:
                profile = boolean_part.OperativePart.Profile.ProfileString
                cut_parts_by_profile[profile] += 1
        processed_elements += 1

    cut_parts_sorted_by_profile = sorted(cut_parts_by_profile.items(), key=lambda x: x[0])

    content_json = [{"No": i + 1, "Profile": profile, "Count": count} for i, (profile, count) in enumerate(cut_parts_sorted_by_profile)]

    total_cut_parts = sum(cut_parts_by_profile.values())
    logger.info("Found %s cut parts across %s profiles in %s elements", total_cut_parts, len(cut_parts_sorted_by_profile), processed_elements)
    return ToolResult(
        content=content_json,
        structured_content={
            "status": "success" if cut_parts_sorted_by_profile else "warning",
            "selected_elements": selected_objects.GetSize(),
            "processed_elements": processed_elements,
            "total_cut_parts": total_cut_parts,
            "cut_parts_list": cut_parts_sorted_by_profile,
        },
    )


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def compare_elements(
    ignore_numbering: Annotated[bool, Field(description="Skip numbering check")] = False,
) -> ToolResult:
    """
    Compares two selected Tekla parts or assemblies and returns a summary of changes.

    ## RULES
    - Only use information explicitly present in the diff. Do not infer or assume changes.
    - Ignore `id` and `guid` fields - they are ALWAYS different (not actual differences).
    - Ignore order of items in lists (cutparts, reinforcements, welds).
    """
    selected_objects = TeklaModel().get_selected_objects()

    validation_result = _validate_exactly_two_selected(selected_objects.GetSize())
    if validation_result:
        return validation_result

    parts = list(selected_objects)
    if not ignore_numbering:
        if not all(Operation.IsNumberingUpToDate(part) for part in parts):
            return ToolResult(structured_content={"status": "error", "message": "Numbering is not up-to-date for selected elements."})

    object_a = wrap_model_object(parts[0])
    object_b = wrap_model_object(parts[1])

    valid_types = (TeklaPart, TeklaAssembly)
    if not isinstance(object_a, valid_types) or not isinstance(object_b, valid_types):
        return ToolResult(structured_content={"status": "error", "message": "Both objects must be parts or assemblies"})

    snapshot_a = object_a.to_snapshot()
    snapshot_b = object_b.to_snapshot()

    snapshot_a_normalized = snapshot_a.normalize(0.01)
    snapshot_b_normalized = snapshot_b.normalize(0.01)

    diff_a = snapshot_a_normalized.to_diff_view()
    diff_b = snapshot_b_normalized.to_diff_view()

    IGNORED_KEYS = {"id", "guid"}

    def _canonical(value: Any) -> Any:
        if isinstance(value, dict):
            return tuple((k, _canonical(v)) for k, v in sorted(value.items()) if k.lower() not in IGNORED_KEYS)

        if isinstance(value, list):
            return tuple(_canonical(v) for v in value)  # <-- KEEP ORDER

        return value

    def _compute_diff(a: Any, b: Any) -> Any:
        canon_a, canon_b = _canonical(a), _canonical(b)
        if canon_a == canon_b:
            return None
        if isinstance(a, dict) and isinstance(b, dict):
            diff = {}
            for key in sorted(set(a) | set(b)):
                if key.lower() in IGNORED_KEYS:
                    continue
                d = _compute_diff(a.get(key), b.get(key))
                if d is not None:
                    diff[key] = d
            return diff or None
        return [a, b]

    def _strip_ignored(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _strip_ignored(v) for k, v in value.items() if k.lower() not in IGNORED_KEYS}
        if isinstance(value, list):
            return [_strip_ignored(v) for v in value]
        return value

    diff_a_clean = _strip_ignored(diff_a)
    diff_b_clean = _strip_ignored(diff_b)

    if _canonical(diff_a_clean) == _canonical(diff_b_clean):
        return ToolResult(structured_content={"status": "success", "identical": True, "message": "Elements are identical"})

    diff = _compute_diff(diff_a_clean, diff_b_clean)

    return ToolResult(
        content=diff,
        structured_content={
            "status": "success",
            "identical": False,
            "part_a_raw": snapshot_a_normalized.model_dump(),
            "part_b_raw": snapshot_b_normalized.model_dump(),
            "message": "Elements have differences",
        },
    )


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def clear_elements_udas(
    uda_names: Annotated[list[str] | None, Field(description="List of specific UDA names to clear")] = None,
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

            selected_object.model_object.Modify()

            if isinstance(selected_object, TeklaPart):
                modified_parts += 1
            elif isinstance(selected_object, TeklaAssembly):
                modified_assemblies += 1
        except Exception:
            logger.exception("Failed to clear UDAs on %s", selected_object.guid)

    if cleared_udas > 0:
        TeklaModel().commit_changes()

    logger.info("Cleared %s UDAs from %s parts and %s assemblies", cleared_udas, modified_parts, modified_assemblies)
    return ToolResult(
        structured_content={
            "status": "success" if cleared_udas > 0 else "warning",
            "cleared_udas": cleared_udas,
            "modified_parts": modified_parts,
            "modified_assemblies": modified_assemblies,
        }
    )


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

    return ToolResult(
        structured_content={
            "status": "success" if elements else "warning",
            "elements": elements,
        }
    )
