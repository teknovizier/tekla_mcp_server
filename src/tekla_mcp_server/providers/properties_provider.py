"""
Properties tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from collections import Counter
from typing import Any, Annotated

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field
from tabulate import tabulate

from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import log_mcp_tool_call
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import TeklaAssembly, TeklaPart, wrap_model_object, wrap_model_objects
from tekla_mcp_server.tekla.loader import Part, BooleanPart, Operation
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.utils import iterate_boolean_parts

properties_provider = LocalProvider()


def _validate_exactly_two_selected(count: int) -> None:
    if count == 0:
        raise ValueError("No elements selected. Please select two elements.")
    if count == 1:
        raise ValueError("Only one element selected. Please select two elements.")
    if count > 2:
        raise ValueError(f"More than two elements selected. Expected 2, got {count}.")


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@log_mcp_tool_call
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
) -> dict[str, Any]:
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
    return {
        "status": "success" if modified_elements > 0 else "warning",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "modified_elements": modified_elements,
        "changes_applied": total_changes,
    }


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@log_mcp_tool_call
def get_elements_properties(
    report_props_definitions: Annotated[list[str] | None, Field(description="List of user-friendly property names")] = None,
) -> ToolResult:
    """
    Retrieve key properties for selected Tekla elements (assemblies or parts).

    ### BEHAVIOR
    - Extract properties not in default columns; split multi-property phrases into separate items.
    - Example: ["gross weight", "assembly top and bottom level", "length"] → ["gross weight", "assembly top level", "assembly bottom level", "length"]

    ## OUTPUT
    - Return the result tables EXACTLY as provided by the tool.
    - DO NOT reformat, summarize, or explain.
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

    def _flatten_properties(props: dict[str, Any]) -> dict[str, Any]:
        """Flatten properties for table rendering."""
        result: dict[str, Any] = {}

        result["GUID"] = props.get("guid", "")

        standard_fields = ["position", "name", "profile", "material", "finish", "tekla_class", "part_prefix", "part_start_number", "assembly_prefix", "assembly_start_number"]
        for field in standard_fields:
            if field in props:
                result[field.replace("_", " ").title()] = props[field]

        result["Phase"] = props.get("phase", "")

        return result

    def _build_table(items: list[dict[str, Any]]) -> str:
        """Build markdown table from properties list."""
        if not items:
            return ""

        standard_keys = list(_flatten_properties(items[0]).keys())

        all_user_keys: set[str] = set()
        all_report_keys: set[str] = set()
        for item in items:
            if user_props := item.get("user_properties"):
                all_user_keys.update(user_props.keys())
            if report_props := item.get("report_properties"):
                for rp in report_props:
                    name = rp.get("name", "")
                    unit = rp.get("unit", "")
                    header = f"{name} ({unit})" if unit else name
                    all_report_keys.add(header)

        user_keys_sorted = [k.replace("_", " ").title() for k in sorted(all_user_keys)]
        report_keys_sorted = [k.replace("_", " ").title() for k in sorted(all_report_keys)]

        headers = ["No"] + standard_keys + user_keys_sorted + report_keys_sorted

        flat_items = []
        for item in items:
            flat = _flatten_properties(item)
            row = {**flat}

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

            flat_items.append(row)

        data = [[i + 1] + [row.get(h, "") for h in headers[1:]] for i, row in enumerate(flat_items)]
        return tabulate(data, headers=headers, tablefmt="github")

    content_parts: list[str] = []

    if assemblies:
        assembly_table = _build_table(assemblies)
        content_parts.append(f"## Assemblies\n{assembly_table}\n")

    if parts:
        parts_table = _build_table(parts)
        content_parts.append(f"## Parts\n{parts_table}\n")

    content = "\n\n".join(content_parts) if content_parts else "No elements found!"

    logger.info("Retrieved properties for %s elements", processed_elements)

    return ToolResult(
        content=content,
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
@log_mcp_tool_call
def get_elements_cut_parts() -> ToolResult:
    """
    Find all cut parts in the selected Tekla elements and return a summary grouped by profile.

    ## OUTPUT
    - Return the result table EXACTLY as provided by the tool.
    - DO NOT reformat, summarize, or explain.
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

    sorted_profiles = sorted(cut_parts_by_profile.items(), key=lambda x: x[0])
    table_data = [[i + 1, profile, count] for i, (profile, count) in enumerate(sorted_profiles)]
    cut_parts_table = tabulate(table_data, headers=["No", "Profile", "Count"], tablefmt="github")

    total_cut_parts = sum(cut_parts_by_profile.values())
    logger.info("Found %s cut parts across %s profiles in %s elements", total_cut_parts, len(sorted_profiles), processed_elements)
    return ToolResult(
        content=f"## Cut Parts\n{cut_parts_table}\n",
        structured_content={
            "status": "success" if sorted_profiles else "warning",
            "selected_elements": selected_objects.GetSize(),
            "processed_elements": processed_elements,
            "total_cut_parts": total_cut_parts,
            "cut_parts_list": sorted_profiles,
        },
    )


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@log_mcp_tool_call
def compare_elements(
    ignore_numbering: Annotated[bool, Field(description="Skip numbering check")] = False,
) -> dict[str, Any]:
    """
    Compares two selected Tekla parts or assemblies and returns a human-readable summary of changes.

    ## RESPONSE FIELDS
    - `identical`: Boolean - True if elements are identical, False otherwise
    - `differences`: Only present when `identical=False`. Machine-readable diff format
    - `differences_summary`: Only present when `identical=False`. Human-readable list of differences
    - `part_a_raw`: Full snapshot of Part A (with guid/id) - use only when you need identifiers
    - `part_b_raw`: Full snapshot of Part B (with guid/id) - use only when you need identifiers

    ## INSTRUCTIONS
    1. Check `identical` field first
    2. If `identical=False`, use `differences_summary` for human-readable report
    3. Use `differences` for programmatic analysis if needed
    4. Use `part_a_raw`/`part_b_raw` only when you need guid/id identifiers

    ## WHAT TO IGNORE
    - `id` and `guid` fields - they are ALWAYS different (not actual differences)
    - Order of items in lists (cutparts, reinforcements, welds) - pre-sorted for comparison

    ## OUTPUT
    A human-readable summary listing only the actual differences between the two selected parts or assemblies.
    """
    selected_objects = TeklaModel().get_selected_objects()

    _validate_exactly_two_selected(selected_objects.GetSize())

    parts = list(selected_objects)
    if not ignore_numbering:
        if not all(Operation.IsNumberingUpToDate(part) for part in parts):
            return {"status": "error", "message": "Numbering is not up-to-date for selected elements."}

    object_a = wrap_model_object(parts[0])
    object_b = wrap_model_object(parts[1])

    valid_types = (TeklaPart, TeklaAssembly)
    if not isinstance(object_a, valid_types) or not isinstance(object_b, valid_types):
        return {"status": "error", "message": "Both objects must be parts or assemblies"}

    snapshot_a = object_a.to_snapshot()
    snapshot_b = object_b.to_snapshot()

    snapshot_a_normalized = snapshot_a.normalize(0.01)
    snapshot_b_normalized = snapshot_b.normalize(0.01)

    diff_a = snapshot_a_normalized.to_diff_view()
    diff_b = snapshot_b_normalized.to_diff_view()

    def _canonical(value: Any) -> Any:
        if isinstance(value, dict):
            return tuple((k, _canonical(v)) for k, v in sorted(value.items()) if k.lower() not in ("id", "guid"))
        if isinstance(value, list):
            return tuple(sorted(_canonical(v) for v in value))
        return value

    def _compute_diff(a: Any, b: Any) -> Any:
        canon_a, canon_b = _canonical(a), _canonical(b)
        if canon_a == canon_b:
            return None
        if isinstance(a, dict) and isinstance(b, dict):
            diff = {}
            for key in set(a) | set(b):
                if key.lower() in ("id", "guid"):
                    continue
                d = _compute_diff(a.get(key), b.get(key))
                if d is not None:
                    diff[key] = d
            return diff or None
        return {"a": a, "b": b}

    if _canonical(diff_a) == _canonical(diff_b):
        return {"status": "success", "identical": True, "message": "Elements are identical"}

    diff = _compute_diff(diff_a, diff_b)

    def diff_to_summary(d: Any, path: str = "") -> list[str]:
        if d is None or not isinstance(d, dict):
            return []
        summary = []
        for key, value in d.items():
            current_path = f"{path}.{key}" if path else key
            if isinstance(value, dict) and "a" in value and "b" in value:
                summary.append(f"{current_path}: A={value['a']}, B={value['b']}")
            else:
                summary.extend(diff_to_summary(value, current_path))
        return summary

    diff_summary = diff_to_summary(diff)

    return {
        "status": "success",
        "identical": False,
        "differences": diff,
        "differences_summary": diff_summary,
        "part_a_raw": snapshot_a_normalized.model_dump(),
        "part_b_raw": snapshot_b_normalized.model_dump(),
        "message": "Elements have differences",
    }


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@log_mcp_tool_call
def clear_elements_udas(
    uda_names: Annotated[list[str] | None, Field(description="List of specific UDA names to clear")] = None,
) -> dict[str, Any]:
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
    return {
        "status": "success" if cleared_udas > 0 else "warning",
        "cleared_udas": cleared_udas,
        "modified_parts": modified_parts,
        "modified_assemblies": modified_assemblies,
    }
