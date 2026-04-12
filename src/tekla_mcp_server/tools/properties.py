"""
Properties tools for Tekla model operations.
"""

from collections import Counter
from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.loader import BooleanPart, Operation
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.wrappers.model_object import (
    TeklaAssembly,
    TeklaPart,
    wrap_model_object,
    wrap_model_objects,
)
from tekla_mcp_server.tekla.utils import iterate_boolean_parts
from tekla_mcp_server.utils import log_function_call, serialize_to_json


@log_function_call
def tool_set_elements_properties(
    selected_objects: Any,
    name: str | None = None,
    profile: str | None = None,
    material: str | None = None,
    tekla_class: str | None = None,
    finish: str | None = None,
    user_properties: dict[str, Any] | None = None,
    part_prefix: str | None = None,
    part_start_number: int | None = None,
    assembly_prefix: str | None = None,
    assembly_start_number: int | None = None,
    phase: int | None = None,
) -> dict[str, Any]:
    """
    Sets properties and UDAs on a collection of Tekla model objects.

    Args:
        selected_objects: Enumerator of selected objects
        name: Name to set
        profile: Profile to set
        material: Material to set
        tekla_class: Class to set
        finish: Finish to set
        user_properties: UDAs to set
        part_prefix: Part numbering prefix to set
        part_start_number: Part start number to set
        assembly_prefix: Assembly numbering prefix to set
        assembly_start_number: Assembly start number to set
        phase: Phase number to set

    Returns:
        dict with status, elements count, and total changes by property
    """
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

    logger.info(
        "Set properties on %s elements: %s",
        modified_elements,
        total_changes,
    )
    return {
        "status": "success" if modified_elements > 0 else "warning",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "modified_elements": modified_elements,
        "changes_applied": total_changes,
    }


@log_function_call
def tool_get_elements_properties(selected_objects: Any, report_props_definitions: list[str] | None = None) -> dict[str, Any]:
    """
    Extracts and serializes key element properties from a collection of model objects.

    Args:
        selected_objects: Enumerator of selected objects
        report_props_definitions: List of report property names to extract

    Returns:
        dict with status, parts list, assemblies list, and any errors
    """
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


@log_function_call
def tool_get_elements_cut_parts(selected_objects: Any) -> dict[str, Any]:
    """
    Extracts cut parts from selected elements and groups them by profile.

    Args:
        selected_objects: Enumerator of selected objects

    Returns:
        dict with status, elements count, and cut parts grouped by profile
    """
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


@log_function_call
def tool_clear_elements_udas(selected_objects: Any, uda_names: list[str] | None = None) -> dict[str, Any]:
    """
    Clears user-defined attributes (UDAs) from selected Tekla parts and assemblies.

    Args:
        selected_objects: Enumerator of selected objects
        uda_names: Optional list of UDA names to clear. If None, clears all UDAs.

    Returns:
        dict with status, cleared count, and modified elements
    """
    cleared_udas = 0
    modified_parts = 0
    modified_assemblies = 0

    for selected_object in wrap_model_objects(selected_objects):
        try:
            user_props = selected_object.get_all_user_properties()
            if not user_props:
                continue

            if uda_names is not None:
                target_keys = [k for k in uda_names if k in user_props]
            else:
                target_keys = list(user_props.keys())

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


@log_function_call
def tool_compare_elements(selected_objects: Any, ignore_numbering: bool = False, tolerance: float = 0.01) -> dict[str, Any]:
    """
    Compares two selected Tekla parts or assemblies and returns the differences.

    Args:
        selected_objects: ModelObjectEnumerator with at least two parts selected
        ignore_numbering: If False, returns error when numbering is not up-to-date (default False)
        tolerance: Tolerance for comparing floating-point numbers (default 0.01)

    Returns:
        dict with status, comparison results, and any differences found
    """
    from tekla_mcp_server.tools.selection import validate_exactly_two_selected

    validate_exactly_two_selected(selected_objects.GetSize())

    parts = list(selected_objects)
    if not ignore_numbering:
        if not all(Operation.IsNumberingUpToDate(part) for part in parts):
            return {
                "status": "error",
                "message": "Numbering is not up-to-date for selected elements. Please update numbering before comparing.",
            }

    object_a = wrap_model_object(parts[0])
    object_b = wrap_model_object(parts[1])

    valid_types = (TeklaPart, TeklaAssembly)
    if not isinstance(object_a, valid_types) or not isinstance(object_b, valid_types):
        return {
            "status": "error",
            "message": "Both objects must be parts or assemblies",
        }

    snapshot_a = object_a.to_snapshot()
    snapshot_b = object_b.to_snapshot()

    snapshot_a_normalized = snapshot_a.normalize(tolerance)
    snapshot_b_normalized = snapshot_b.normalize(tolerance)

    diff_a = snapshot_a_normalized.to_diff_view()
    diff_b = snapshot_b_normalized.to_diff_view()

    def _canonical(value: Any) -> Any:
        if isinstance(value, dict):
            return tuple((k, _canonical(v)) for k, v in sorted(value.items()) if k.lower() not in ("id", "guid"))
        if isinstance(value, list):
            return tuple(sorted(_canonical(v) for v in value))
        return value

    def _compute_diff(a: Any, b: Any) -> Any:
        canon_a = _canonical(a)
        canon_b = _canonical(b)

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
        return {
            "status": "success",
            "identical": True,
            "message": "Elements are identical",
        }

    diff = _compute_diff(diff_a, diff_b)

    def diff_to_summary(d: Any, path: str = "") -> list[str]:
        if d is None:
            return []
        if not isinstance(d, dict):
            return []

        summary = []
        for key, value in d.items():
            current_path = f"{path}.{key}" if path else key

            if isinstance(value, dict) and "a" in value and "b" in value:
                summary.append(f"{current_path}: A={value['a']}, B={value['b']}")
            else:
                child_summary = diff_to_summary(value, current_path)
                summary.extend(child_summary)

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
