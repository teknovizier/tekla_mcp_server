"""
Properties tools for Tekla model operations.
"""

from collections import Counter
from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    ElementProperties,
    ReportProperty,
    UDASetMode,
)
from tekla_mcp_server.tekla.loader import BooleanPart, Operation
from tekla_mcp_server.tekla.model_object import (
    TeklaAssembly,
    TeklaModelObject,
    TeklaPart,
    wrap_model_object,
    wrap_model_objects,
)
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.utils import log_function_call, serialize_to_json


@log_function_call
def tool_set_elements_udas(selected_objects: Any, udas: dict[str, Any], mode: UDASetMode) -> dict[str, Any]:
    """
    Applies UDAs to a collection of Tekla model objects.

    Args:
        selected_objects: Enumerator of selected objects
        udas: Dictionary of user-defined attributes to set
        mode: UDASetMode (ADD, OVERWRITE, or REMOVE)
    """
    processed_elements = 0
    updated_attributes = 0
    skipped_attributes = 0
    for selected_object in wrap_model_objects(selected_objects):
        for key, value in udas.items():
            try:
                _ = selected_object.get_user_property(key, type(value))
                uda_exists = True
            except AttributeError:
                uda_exists = False

            if mode == UDASetMode.KEEP and uda_exists:
                skipped_attributes += 1
                continue
            else:
                if selected_object.set_user_property(key, value):
                    updated_attributes += 1
        processed_elements += 1
    logger.info("Updated %s UDAs in %s element, skipped %s", updated_attributes, processed_elements, skipped_attributes)
    return {
        "status": "success" if updated_attributes else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "skipped_attributes": skipped_attributes,
        "updated_attributes": updated_attributes,
    }


@log_function_call
def tool_get_elements_udas(selected_objects: Any) -> dict[str, Any]:
    """
    Retrieves GUID, position, and all UDAs for a collection of model objects.

    Args:
        selected_objects: Enumerator of selected objects
    """
    processed_elements = 0
    assemblies: list[dict] = []
    parts: list[dict] = []

    def extract_metadata(selected_object: TeklaModelObject) -> dict[str, Any]:
        return {"guid": selected_object.guid, "position": selected_object.position, "udas": selected_object.get_all_user_properties()}

    for selected_object in wrap_model_objects(selected_objects):
        metadata = extract_metadata(selected_object)
        if isinstance(selected_object, TeklaAssembly):
            assemblies.append(metadata)
        elif isinstance(selected_object, TeklaPart):
            parts.append(metadata)
        processed_elements += 1
    logger.info("Retrieved UDAs for %s elements", processed_elements)
    return {
        "status": "success" if assemblies or parts else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "assemblies": assemblies,
        "parts": parts,
    }


@log_function_call
def tool_get_elements_properties(selected_objects: Any, custom_props_definitions: list[str]) -> dict[str, Any]:
    """
    Extracts and serializes key element properties from a collection of model objects.

    Args:
        selected_objects: Enumerator of selected objects
        custom_props_definitions: List of custom property names to extract
    """
    from collections import defaultdict

    resolution_errors: list[dict[str, Any]] = []
    if custom_props_definitions:
        resolution = TemplateAttributeParser.resolve_attributes(custom_props_definitions)
        resolution_errors = resolution.get("errors", [])
        custom_props_definitions = resolution["resolved"]

    processed_elements = 0
    assemblies: list[ElementProperties] = []
    parts: list[ElementProperties] = []
    custom_props_errors: dict[str, dict[str, str]] = defaultdict(dict)

    parsed_custom_props: list[ReportProperty] = []
    failed_custom_prop_definitions = []
    for error_entry in resolution_errors:
        failed_custom_prop_definitions.append(error_entry["query"])
    if custom_props_definitions:
        for attr_name in custom_props_definitions:
            try:
                parsed_prop = TemplateAttributeParser.get_attribute(attr_name)
                parsed_custom_props.append(parsed_prop)
            except KeyError:
                failed_custom_prop_definitions.append(attr_name)
                logger.warning("Attribute not found: '%s'", attr_name)

    def get_single_element_properties(selected_object: TeklaModelObject) -> ElementProperties:
        try:
            weight, _ = selected_object.weight
        except AttributeError:
            weight = None

        custom_properties = []
        for custom_property in parsed_custom_props:
            try:
                custom_property_copy = custom_property.model_copy(deep=False)
                custom_property_copy.value = selected_object.get_report_property(custom_property_copy.name)
                custom_properties.append(custom_property_copy)
            except Exception as e:
                custom_props_errors[selected_object.guid][custom_property.name] = str(e)
                logger.warning(
                    "Error extracting custom property '%s' for the object %s: %s",
                    custom_property.name,
                    selected_object.guid,
                    e,
                )

        return ElementProperties(
            position=selected_object.position,
            guid=selected_object.guid,
            name=selected_object.name,
            profile=selected_object.profile,
            material=selected_object.material,
            finish=selected_object.finish,
            tekla_class=selected_object.tekla_class,
            weight=weight,
            custom_properties=custom_properties,
        )

    for selected_object in wrap_model_objects(selected_objects):
        metadata = get_single_element_properties(selected_object).model_copy(deep=True)
        if isinstance(selected_object, TeklaAssembly):
            assemblies.append(metadata)
        elif isinstance(selected_object, TeklaPart):
            parts.append(metadata)
        processed_elements += 1

    serialized_assemblies = serialize_to_json([a.model_dump() for a in assemblies])
    serialized_parts = serialize_to_json([a.model_dump() for a in parts])

    logger.info("Retrieved properties for %s elements", processed_elements)
    status = "success" if assemblies or parts else "error"
    if resolution_errors:
        status = "partial"
    return {
        "status": status,
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "assemblies_list": serialized_assemblies,
        "parts_list": serialized_parts,
        "invalid_custom_property_definitions": failed_custom_prop_definitions,
        "custom_property_extraction_errors": custom_props_errors,
        "resolution_errors": resolution_errors,
    }


@log_function_call
def tool_get_elements_cut_parts(selected_objects: Any) -> dict[str, Any]:
    """
    Extracts cut parts from selected elements and groups them by profile.

    Args:
        selected_objects: Enumerator of selected objects
    """
    processed_elements = 0
    cut_parts_by_profile: Counter[str] = Counter()

    for selected_object in selected_objects:
        boolean_part_enum = selected_object.GetBooleans()
        while boolean_part_enum.MoveNext():
            boolean_part = boolean_part_enum.Current
            if isinstance(boolean_part, BooleanPart):
                operative_part = boolean_part.OperativePart
                if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT:
                    profile = operative_part.Profile.ProfileString
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
def tool_compare_elements(selected_objects: Any, ignore_numbering: bool = False, tolerance: float = 0.01) -> dict[str, Any]:
    """
    Compares two selected Tekla parts or assemblies and returns the differences.

    Args:
        selected_objects: ModelObjectEnumerator with at least two parts selected
        ignore_numbering: If False, returns error when numbering is not up-to-date (default False)
        tolerance: Tolerance for comparing floating-point numbers (default 0.01)
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
