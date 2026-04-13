"""
Properties tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from collections import Counter
from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import log_mcp_tool_call, serialize_to_json
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import TeklaAssembly, TeklaPart, wrap_model_object, wrap_model_objects
from tekla_mcp_server.tekla.loader import BooleanPart, Operation
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


@properties_provider.tool()
@log_mcp_tool_call
def set_elements_properties(
    name: str | None = None,
    profile: str | None = None,
    material: str | None = None,
    tekla_class: str | None = None,
    finish: str | None = None,
    part_prefix: str | None = None,
    part_start_number: int | None = None,
    assembly_prefix: str | None = None,
    assembly_start_number: int | None = None,
    phase: int | None = None,
    user_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Sets properties and user-defined attributes (UDAs) on selected Tekla elements (assemblies or parts).

    ## INPUT

    ### APPLICABLE PROPERTIES BY ELEMENT TYPE

    #### For PARTS (all properties apply):
    - `name` [Optional]: Part name
    - `profile` [Optional]: Profile string (e.g., "3000*200", "HEA200")
    - `material` [Optional]: Material string (e.g., "C25/30", "S355J2")
    - `tekla_class` [Optional]: Tekla class (e.g., "1", "100", etc.)
    - `finish` [Optional]: Finish type
    - `part_prefix` [Optional]: Part numbering prefix
    - `part_start_number` [Optional]: Part start number
    - `assembly_prefix` [Optional]: Assembly numbering prefix
    - `assembly_start_number` [Optional]: Assembly start number
    - `phase` [Optional]: Phase number (1, 2, 3, etc.)

    #### For ASSEMBLIES (only these properties apply):
    - `name` [Optional]: Assembly name
    - `assembly_prefix` [Optional]: Assembly numbering prefix
    - `assembly_start_number` [Optional]: Assembly start number
    - `phase` [Optional]: Phase number (1, 2, 3, etc.)

    Note: Assemblies do not have profile, material, finish, tekla_class, or part numbering.
    These properties will only affect parts, not assemblies.

    - `user_properties` [Optional]: Dictionary of user-defined attribute names and values

    ## OUTPUT
    - `status`: "success" if any changes were made, "warning" if no changes
    - `selected_elements`: Total number of selected elements
    - `processed_elements`: Elements that were processed
    - `modified_elements`: Elements that were actually modified
    - `changes_applied`: Breakdown of changes by property type
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


@properties_provider.tool()
@log_mcp_tool_call
def get_elements_properties(report_props_definitions: list[str] | None = None) -> dict[str, Any]:
    """
    Retrieve key properties for selected Tekla elements (assemblies or parts).

    ## INPUT
    - `report_props_definitions` [Optional]: List of user-friendly property names.

    ### BEHAVIOR
    - Extract properties not in default columns; split multi-property phrases into separate items.
    - Example: ["gross weight", "assembly top and bottom level", "length"] → ["gross weight", "assembly top level", "assembly bottom level", "length"]
    - Only resolved report properties appear in the table; unresolved ones are mentioned after the table.

    ## OUTPUT
    - Table format only; first row = headers, no JSON or extra text.
    - Leftmost "No" column with sequential row numbers starting from 1.

    - If the result contains ONLY assemblies → return ONE table with assembly columns.
    - If the result contains ONLY parts → return ONE table with part columns.
    - If the result contains BOTH assemblies AND parts → return TWO separate tables:
        1. First table: Assemblies only
        2. Second table: Parts only
    - Do NOT mix assemblies and parts in the same table.

    ### DEFAULT COLUMNS
    - Position, GUID

    - Assemblies:
        - Assembly Name, Assembly Prefix, Assembly Start Number, Phase
        - These columns apply ONLY to the assemblies table.

    - Parts:
        - Name, Profile, Material, Finish, Class, Part Prefix, Part Start Number, Assembly Prefix, Assembly Start Number, Phase
        - These columns apply ONLY to the parts table.

    ### USER PROPERTIES (UDAs)
    - UDAs MUST be included as columns in each table.
    - Each UDA appears as a separate column using its exact property name.
    - Apply UDAs independently for assemblies and parts.
    - If a UDA value is missing for an element, the cell should be empty.

    ### REPORT PROPERTIES
    - Include report properties as additional columns in the SAME table (per type).
    - Use backend-resolved names exactly; append units if provided.
    - Float values should be rounded to 3 decimals.
    - Missing values must be shown as "N/A".
    - Example: ASSEMBLY_TOP_LEVEL, ASSEMBLY_BOTTOM_LEVEL_UNFORMATTED, WEIGHT_GROSS (kg)

    ### GENERAL RULES
    - Each table must have a flat structure.
    - Each row represents one element.
    - Each column represents one property (default, UDA, or report).
    - Do NOT merge or share columns between assemblies and parts tables.

    ## RETURN KEYS
    - `status`: "success", "partial" (if some errors occurred), or "error"
    - `assemblies_list`: JSON array of assembly properties
    - `parts_list`: JSON array of part properties
    - `resolution_errors`: List of errors when resolving property names
    - `extraction_errors`: List of errors when extracting properties from elements
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

    serialized_assemblies = serialize_to_json(assemblies)
    serialized_parts = serialize_to_json(parts)

    logger.info("Retrieved properties for %s elements", processed_elements)
    status = "success" if assemblies or parts else "error"
    if resolution_errors or extraction_errors:
        status = "partial"

    return {
        "status": status,
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "assemblies_list": serialized_assemblies,
        "parts_list": serialized_parts,
        "resolution_errors": resolution_errors,
        "extraction_errors": extraction_errors,
    }


@properties_provider.tool()
@log_mcp_tool_call
def get_elements_cut_parts() -> dict[str, Any]:
    """
    Find all cut parts in the selected Tekla elements and return a summary grouped by profile.

    ## INPUT
    - No additional parameters required.

    ## OUTPUT
    - Table format only; first row = headers, no JSON or extra text.
    - Leftmost "No" column with sequential row numbers starting from 1.

    ### TABLE COLUMNS
    - Profile
    - Count

    ### SUMMARY
    - Show the total number of cut parts found across all profiles.
    - Show the total number of processed elements.
    """
    selected_objects = TeklaModel().get_selected_objects()

    processed_elements = 0
    cut_parts_by_profile: Counter[str] = Counter()

    for selected_object in selected_objects:
        for boolean_part in iterate_boolean_parts(selected_object):
            if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT:
                profile = boolean_part.OperativePart.Profile.ProfileString
                cut_parts_by_profile[profile] += 1
        processed_elements += 1

    sorted_profiles = sorted(cut_parts_by_profile.items(), key=lambda x: x[0])
    cut_parts_list = [{"profile": profile, "count": count} for profile, count in sorted_profiles]
    serialized_cut_parts = serialize_to_json(cut_parts_list)

    total_cut_parts = sum(cut_parts_by_profile.values())
    logger.info("Found %s cut parts across %s profiles in %s elements", total_cut_parts, len(sorted_profiles), processed_elements)
    return {
        "status": "success" if cut_parts_list else "warning",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "total_cut_parts": total_cut_parts,
        "cut_parts_list": serialized_cut_parts,
    }


@properties_provider.tool()
@log_mcp_tool_call
def compare_elements(ignore_numbering: bool = False) -> dict[str, Any]:
    """
    Compares two selected Tekla parts or assemblies and returns a human-readable summary of changes.

    ## INPUT
    - `ignore_numbering` [Optional]: If True, skips numbering check (default: False)

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


@properties_provider.tool()
@log_mcp_tool_call
def clear_elements_udas(uda_names: list[str] | None = None) -> dict[str, Any]:
    """
    Clears user-defined attributes (UDAs) from selected Tekla parts and assemblies.

    ## INPUT
    - `uda_names` [Optional]: List of specific UDA names to clear. If not provided, clears all UDAs.

    ## EXAMPLES
    # Clear all UDAs from selected elements
    clear_elements_udas()

    # Clear only specific UDAs
    clear_elements_udas(uda_names=["STATUS", "APPROVED_BY"])

    ## OUTPUT
    - `status`: "success" if UDAs were cleared, "warning" if no UDAs found
    - `cleared_udas`: Total number of UDAs cleared
    - `modified_parts`: Number of parts modified
    - `modified_assemblies`: Number of assemblies modified
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
