"""
Selection tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Annotated, Any

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    ElementType,
    SelectionMode,
    StringFilterOption,
    NumericFilterOption,
)
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects
from tekla_mcp_server.tekla.filter_builder import add_filter, build_filter_group, to_filter_option
from tekla_mcp_server.tekla.loader import (
    ArrayList,
    BinaryFilterExpression,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    BinaryFilterOperatorType,
    NumericConstantFilterExpression,
    NumericOperatorType,
    ObjectFilterExpressions,
    PartFilterExpressions,
    TeklaStructuresDatabaseTypeEnum,
    TemplateFilterExpressions,
)
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser


# Define expression maps
STANDARD_STRING_EXPRESSION_MAP = {
    "name": PartFilterExpressions.Name(),
    "profile": PartFilterExpressions.Profile(),
    "material": PartFilterExpressions.Material(),
    "finish": PartFilterExpressions.Finish(),
    "phase": TemplateFilterExpressions.CustomString("ASSEMBLY.PHASE"),
    "part_prefix": PartFilterExpressions.Prefix(),
    "assembly_prefix": TemplateFilterExpressions.CustomString("ASSEMBLY_PREFIX"),
}

STANDARD_NUMERIC_EXPRESSION_MAP = {
    "part_start_number": PartFilterExpressions.StartNumber(),
    "assembly_start_number": TemplateFilterExpressions.CustomNumber("ASSEMBLY_START_NUMBER"),
}


selection_provider = LocalProvider()


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_filter(
    element_type: Annotated[str | None, Field(description="Named element type (e.g. 'Wall', 'Steel Beam')")] = None,
    tekla_classes: Annotated[int | list[int] | None, Field(description="Tekla class numbers")] = None,
    standard_string_filters: Annotated[dict[str, Any] | None, Field(description="Dict of standard string properties to filter options")] = None,
    standard_numeric_filters: Annotated[dict[str, Any] | None, Field(description="Dict of standard numeric properties to filter options")] = None,
    custom_string_filters: Annotated[dict[str, Any] | None, Field(description="Dict of custom attribute names to StringFilterOption")] = None,
    custom_numeric_filters: Annotated[dict[str, Any] | None, Field(description="Dict of custom property names to NumericFilterOption")] = None,
    combine_with: Annotated[str, Field(description="How to combine filter groups: 'AND' or 'OR'")] = "AND",
) -> ToolResult:
    """
    Selects elements in the Tekla model using standard properties, custom attributes and numeric ranges.

    ### EXAMPLES
    # NAME = "Wall" OR PHASE = "2"
    {
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Is Equal", "value": "Wall"}},
            "phase": {"conditions": {"match_type": "Is Equal", "value": "2"}}
        },
        "combine_with": "OR"
    }

    # element_type = Wall AND (name = "beam" OR profile = "200*600")
    {
        "element_type": "Wall",
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Is Equal", "value": "beam"}},
            "profile": {"conditions": {"match_type": "Is Equal", "value": "200*600"}}
        },
        "combine_with": "OR"
    }

    # Elements in class 1 (Wall) with name ending in "1601"
    {
        "tekla_classes": 1,
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Ends With", "value": "1601"}}
        }
    }

    # Elements in class 1 (Wall) with height > 2m
    {
        "tekla_classes": 1,
        "custom_numeric_filters": {
            "HEIGHT": {"conditions": {"match_type": "Greater Than", "value": 2000}}
        }
    }

    # Combined: prefix starts with SB AND part_start_number > 50
    {
        "standard_string_filters": {
            "part_prefix": {"conditions": {"match_type": "Starts With", "value": "SB"}}
        },
        "standard_numeric_filters": {
            "part_start_number": {"conditions": {"match_type": "Greater Than", "value": 50}}
        },
        "combine_with": "AND"
    }

    At least one filter must be provided.
    """
    # Validate combine_with and ensure at least one filter provided
    if combine_with not in {"AND", "OR"}:
        raise ValueError(f"Invalid combine_with '{combine_with}'. Must be 'AND' or 'OR'.")

    if not any((element_type, tekla_classes, standard_string_filters, standard_numeric_filters, custom_string_filters, custom_numeric_filters)):
        raise ValueError("At least one filter must be provided.")

    if element_type:
        try:
            element_type_enum = ElementType(element_type.strip())
        except Exception as e:
            raise ValueError(f"Invalid element_type: {e}") from e

    model = TeklaModel()

    # Base filter: always filter for parts only
    filter_collection = BinaryFilterExpressionCollection()
    filter_collection.Add(
        BinaryFilterExpressionItem(
            BinaryFilterExpression(
                ObjectFilterExpressions.Type(),
                NumericOperatorType.IS_EQUAL,
                NumericConstantFilterExpression(TeklaStructuresDatabaseTypeEnum.PART),
            )
        )
    )

    # Derive valid keys from expression maps
    _VALID_STRING_KEYS = frozenset(STANDARD_STRING_EXPRESSION_MAP.keys())
    _VALID_NUMERIC_KEYS = frozenset(STANDARD_NUMERIC_EXPRESSION_MAP.keys())

    # Validate input keys
    if standard_string_filters:
        for key in standard_string_filters:
            if key not in _VALID_STRING_KEYS:
                raise ValueError(f"Invalid standard_string_filters key '{key}'. Must be one of: {_VALID_STRING_KEYS}")

    if standard_numeric_filters:
        for key in standard_numeric_filters:
            if key not in _VALID_NUMERIC_KEYS:
                raise ValueError(f"Invalid standard_numeric_filters key '{key}'. Must be one of: {_VALID_NUMERIC_KEYS}")

    filter_groups: list[BinaryFilterExpressionCollection] = []

    # Resolve element_type to tekla class numbers
    if element_type:
        element_type_classes: list[int] = []
        for material_types in get_config().element_types.values():
            for type_name, config in material_types.items():
                logger.debug("Checking element type '%s' against '%s', classes=%s", element_type_enum.name, type_name, config.get("tekla_classes", []))
                if element_type_enum.name.replace(" ", "_").upper() in type_name.upper() or type_name.upper() in element_type_enum.name.upper():
                    element_type_classes.extend(config.get("tekla_classes", []))
        type_sub = BinaryFilterExpressionCollection()
        for cls in element_type_classes:
            add_filter(type_sub, PartFilterExpressions.Class(), cls, NumericOperatorType.IS_EQUAL, operator=BinaryFilterOperatorType.BOOLEAN_OR)
        filter_groups.append(type_sub)

    # Add explicit tekla_classes to filter
    if tekla_classes:
        if isinstance(tekla_classes, int):
            tekla_classes = [tekla_classes]
        type_sub = BinaryFilterExpressionCollection()
        for cls in tekla_classes:
            add_filter(type_sub, PartFilterExpressions.Class(), cls, NumericOperatorType.IS_EQUAL, operator=BinaryFilterOperatorType.BOOLEAN_OR)
        filter_groups.append(type_sub)

    # Add standard string filters (name, profile, material, finish, phase, part_prefix, assembly_prefix)
    if standard_string_filters:
        for key, filter_option in standard_string_filters.items():
            expression = STANDARD_STRING_EXPRESSION_MAP[key]
            filter_option = to_filter_option(filter_option, StringFilterOption)
            result = build_filter_group(expression, filter_option)
            if result is not None:
                filter_groups.append(result)

    # Add standard numeric filters (part_start_number, assembly_start_number)
    if standard_numeric_filters:
        for key, filter_option in standard_numeric_filters.items():
            expression = STANDARD_NUMERIC_EXPRESSION_MAP[key]
            filter_option = to_filter_option(filter_option, NumericFilterOption)
            result = build_filter_group(expression, filter_option, is_numeric=True)
            if result is not None:
                filter_groups.append(result)

    string_resolution_errors: list[dict[str, Any]] = []
    numeric_resolution_errors: list[dict[str, Any]] = []
    resolved_string_attrs: dict[str, str | None] = {}
    resolved_numeric_attrs: dict[str, str | None] = {}

    # Resolve custom attribute names to Tekla names, then add string filters
    if custom_string_filters:
        string_queries = list(custom_string_filters.keys())
        if string_queries:
            resolution = TemplateAttributeParser.resolve_attributes(string_queries)
            errors = resolution.get("errors", [])
            string_resolution_errors = errors
            # `resolved` holds only the names that resolved, in the order their queries
            # succeeded. Align them to the non-failed queries - a positional zip against
            # all queries would shift names onto the wrong attributes once one query fails
            failed_queries = {e["query"] for e in errors}
            successful_queries = [q for q in string_queries if q not in failed_queries]
            resolved_map = dict(zip(successful_queries, resolution["resolved"]))
            for query in string_queries:
                resolved_string_attrs[query] = resolved_map.get(query)

        for field_name, filter_option in custom_string_filters.items():
            resolved_name = resolved_string_attrs.get(field_name)
            if resolved_name:
                expression = TemplateFilterExpressions.CustomString(resolved_name)
                filter_option = to_filter_option(filter_option, StringFilterOption)
                result = build_filter_group(expression, filter_option)
                if result is not None:
                    filter_groups.append(result)

    # Same for numeric filters
    if custom_numeric_filters:
        numeric_queries = list(custom_numeric_filters.keys())
        if numeric_queries:
            resolution = TemplateAttributeParser.resolve_attributes(numeric_queries)
            errors = resolution.get("errors", [])
            numeric_resolution_errors = errors
            # See the string-filter block above: align resolved names to the non-failed
            # queries so a single failed query does not shift names onto wrong attributes
            failed_queries = {e["query"] for e in errors}
            successful_queries = [q for q in numeric_queries if q not in failed_queries]
            resolved_map = dict(zip(successful_queries, resolution["resolved"]))
            for query in numeric_queries:
                resolved_numeric_attrs[query] = resolved_map.get(query)

        for field_name, filter_option in custom_numeric_filters.items():
            resolved_name = resolved_numeric_attrs.get(field_name)
            if resolved_name:
                expression = TemplateFilterExpressions.CustomNumber(resolved_name)
                filter_option = to_filter_option(filter_option, NumericFilterOption)
                result = build_filter_group(expression, filter_option, is_numeric=True)
                if result is not None:
                    filter_groups.append(result)

    # Combine all filter groups into final filter
    if len(filter_groups) == 1:
        filter_collection.Add(BinaryFilterExpressionItem(filter_groups[0], BinaryFilterOperatorType.BOOLEAN_AND))
    elif len(filter_groups) > 1:
        combined = BinaryFilterExpressionCollection()
        group_operator = BinaryFilterOperatorType.BOOLEAN_OR if combine_with == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        logger.debug("Combining %d filter groups with %s", len(filter_groups), combine_with)
        for fg in filter_groups:
            if fg is not None:
                combined.Add(BinaryFilterExpressionItem(fg, group_operator))
        if combined.Count > 0:
            filter_collection.Add(BinaryFilterExpressionItem(combined, BinaryFilterOperatorType.BOOLEAN_AND))

    objects_to_select = model.get_objects_by_filter(filter_collection)
    TeklaModel.select_objects(objects_to_select)

    count = objects_to_select.GetSize()
    has_resolution_errors = bool(string_resolution_errors or numeric_resolution_errors)

    return ToolResult(
        structured_content={
            "status": "partial" if has_resolution_errors else ("success" if count else "warning"),
            "selected_count": count,
            "string_resolution_errors": string_resolution_errors,
            "numeric_resolution_errors": numeric_resolution_errors,
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_filter_name(
    filter_name: Annotated[str, Field(description="Name of the Tekla filter to apply")],
) -> ToolResult:
    """
    Selects elements applying an existing Tekla filter.

    Use the `tekla://filters/selection` resource to discover available filters.
    """
    model = TeklaModel()
    objects_to_select = model.get_objects_by_filter(filter_name)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by named filter", objects_to_select.GetSize())
    return ToolResult(
        structured_content={
            "status": "success" if objects_to_select.GetSize() else "warning",
            "selected_count": objects_to_select.GetSize(),
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_guid(
    guids: Annotated[list[str], Field(description="List of GUIDs to select (e.g. from `get_elements_properties`)")],
) -> ToolResult:
    """
    Selects elements by their GUID.
    """
    model = TeklaModel()
    objects_to_select = ArrayList()
    selected_guids: list[str] = []
    missing_guids: list[str] = []

    for guid in guids:
        obj = model.get_object_by_guid(guid)
        if obj is not None:
            objects_to_select.Add(obj)
            selected_guids.append(guid)
        else:
            missing_guids.append(guid)

    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s/%s elements by GUID (missing: %s)", len(selected_guids), len(guids), missing_guids)

    status = "success" if selected_guids and not missing_guids else ("partial" if selected_guids else "warning")
    return ToolResult(
        structured_content={
            "status": status,
            "requested_count": len(guids),
            "selected_count": len(selected_guids),
            "selected_guids": selected_guids,
            "missing_guids": missing_guids,
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_assemblies_or_main_parts(
    mode: Annotated[SelectionMode, Field(description="Selection mode: 'Assembly' or 'Main Part'")],
) -> ToolResult:
    """
    Selects assemblies or main parts for the selected elements.
    """
    selected_objects = TeklaModel().get_selected_objects()

    processed_count = 0
    selected_object_types = "selected_assemblies" if mode == "Assembly" else "selected_main_parts"

    filtered_parts = ArrayList()
    for selected_object in wrap_model_objects(selected_objects):
        try:
            assembly = selected_object.get_top_level_assembly()
        except TypeError:
            logger.error("Failed to get top level assembly for the element %s", selected_object.guid)
            continue
        if assembly is None:
            logger.debug("No top-level assembly for %s, skipping", selected_object.guid)
            continue
        if mode == "Assembly":
            filtered_parts.Add(assembly.model_object)
        elif mode == "Main Part":
            try:
                filtered_parts.Add(assembly.main_part.model_object)
            except ValueError:
                logger.warning("Assembly %s has no main part, skipping", assembly.guid)
                continue
        processed_count += 1

    TeklaModel.select_objects(filtered_parts)
    logger.info("Selected %s elements as '%s'", filtered_parts.Count, mode)
    return ToolResult(
        structured_content={
            "status": "success" if filtered_parts.Count else "warning",
            "selected_count": selected_objects.GetSize(),
            "processed_count": processed_count,
            f"{selected_object_types}_count": filtered_parts.Count,
        }
    )
