"""
Selection tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Annotated, Any

from fastmcp.server.providers import LocalProvider
from pydantic import Field

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    ElementTypeModel,
    SelectionMode,
    ElementType,
    NumericMatchType,
    StandardStringFilterKey,
    StringFilterOption,
    StringMatchType,
    NumericFilterOption,
)
from tekla_mcp_server.utils import log_mcp_tool_call
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects
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
    StringConstantFilterExpression,
    TeklaStructuresDatabaseTypeEnum,
    TemplateFilterExpressions,
)
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.utils import (
    NUMERIC_MATCH_TYPE_MAPPING,
    STRING_MATCH_TYPE_MAPPING,
)


selection_provider = LocalProvider()


def _to_filter_option(val: Any, model_class: type[StringFilterOption] | type[NumericFilterOption]) -> StringFilterOption | NumericFilterOption:
    if isinstance(val, dict):
        return model_class.model_validate(val)
    return val


def validate_exactly_two_selected(count: int) -> None:
    if count == 0:
        raise ValueError("No elements selected. Please select two elements.")
    if count == 1:
        raise ValueError("Only one element selected. Please select two elements.")
    if count > 2:
        raise ValueError(f"More than two elements selected. Expected 2, got {count}.")


def add_filter(
    filter_collection: BinaryFilterExpressionCollection,
    filter_expression: Any,
    value: str | int | float,
    match_type: StringMatchType | NumericMatchType | NumericOperatorType | None = None,
    operator: BinaryFilterOperatorType = BinaryFilterOperatorType.BOOLEAN_AND,
) -> None:
    if not isinstance(value, (str, int, float)):
        expr = BinaryFilterExpression(filter_expression, NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(value))
        filter_collection.Add(BinaryFilterExpressionItem(expr, operator))
        return

    is_string_filter = False
    if match_type is not None:
        if isinstance(match_type, StringMatchType):
            is_string_filter = True
        elif isinstance(match_type, NumericMatchType):
            is_string_filter = False

    if isinstance(value, str) and not is_string_filter:
        try:
            if value.replace(".", "").replace("-", "").isdigit():
                value = float(value) if "." in value else int(value)
        except ValueError:
            pass

    if isinstance(value, str):
        if match_type is None:
            match_type = StringMatchType.IS_EQUAL
        op = STRING_MATCH_TYPE_MAPPING.get(match_type)
        expr = BinaryFilterExpression(filter_expression, op, StringConstantFilterExpression(value))
    elif isinstance(value, (int, float)):
        if match_type is None:
            match_type = NumericOperatorType.IS_EQUAL
        if isinstance(match_type, NumericOperatorType):
            op = match_type
        else:
            op = NUMERIC_MATCH_TYPE_MAPPING.get(match_type)
        expr = BinaryFilterExpression(filter_expression, op, NumericConstantFilterExpression(value))
    else:
        raise ValueError(f"Unsupported value type: {type(value)}")

    filter_collection.Add(BinaryFilterExpressionItem(expr, operator))


validate_exactly_two_selected = validate_exactly_two_selected


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@log_mcp_tool_call
def select_elements_by_filter(
    element_type: Annotated[str | ElementType | None, Field(description="Named element type (e.g., 'Wall', 'Steel Beam')")] = None,
    tekla_classes: Annotated[int | list[int] | None, Field(description="Tekla class numbers")] = None,
    standard_string_filters: Annotated[dict[str, Any] | None, Field(description="Dict of standard Tekla properties to filter options")] = None,
    custom_string_filters: Annotated[dict[str, Any] | None, Field(description="Dict of custom attribute names to StringFilterOption")] = None,
    custom_numeric_filters: Annotated[dict[str, Any] | None, Field(description="Dict of custom property names to NumericFilterOption")] = None,
    combine_with: Annotated[str, Field(description="How to combine filter groups: 'AND' or 'OR'")] = "AND",
) -> dict[str, Any]:
    """
    Selects elements in the Tekla model using standard properties, custom attributes and numeric ranges.
    """
    if combine_with not in {"AND", "OR"}:
        raise ValueError(f"Invalid combine_with '{combine_with}'. Must be 'AND' or 'OR'.")

    if not any((element_type, tekla_classes, standard_string_filters, custom_string_filters, custom_numeric_filters)):
        raise ValueError("At least one filter must be provided.")

    if isinstance(element_type, str):
        element_type = ElementTypeModel(value=element_type).to_enum()
    elif element_type is not None and not isinstance(element_type, ElementType):
        raise ValueError("element_type must be a string or ElementType")

    model = TeklaModel()

    valid_standard_keys = {k.value for k in StandardStringFilterKey}
    if standard_string_filters:
        for key in standard_string_filters:
            if key not in valid_standard_keys:
                raise ValueError(f"Invalid standard_string_filters key '{key}'. Must be one of: {valid_standard_keys}")

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

    filter_groups: list[BinaryFilterExpressionCollection] = []

    def build_filter_group(expression: Any, filter_option: StringFilterOption | NumericFilterOption, is_numeric: bool = False) -> BinaryFilterExpressionCollection:
        sub = BinaryFilterExpressionCollection()
        conditions = filter_option.conditions
        logic = filter_option.logic
        if not isinstance(conditions, list):
            conditions = [conditions]
        operator = BinaryFilterOperatorType.BOOLEAN_OR if logic == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        for cond in conditions:
            value = cond.value
            match_type_str = cond.match_type
            match_type = NumericMatchType(match_type_str) if is_numeric else StringMatchType(match_type_str)
            add_filter(sub, expression, value, match_type, operator=operator)
        return sub

    STANDARD_EXPRESSION_MAP = {
        "name": PartFilterExpressions.Name(),
        "profile": PartFilterExpressions.Profile(),
        "material": PartFilterExpressions.Material(),
        "finish": PartFilterExpressions.Finish(),
        "phase": TemplateFilterExpressions.CustomString("ASSEMBLY.PHASE"),
    }

    if element_type:
        element_type_classes: list[int] = []
        for material_types in get_config().element_types.values():
            for type_name, config in material_types.items():
                if element_type.name.replace(" ", "_").upper() in type_name.upper() or type_name.upper() in element_type.name.upper():
                    element_type_classes.extend(config.get("tekla_classes", []))
        type_sub = BinaryFilterExpressionCollection()
        for cls in element_type_classes:
            add_filter(type_sub, PartFilterExpressions.Class(), cls, NumericOperatorType.IS_EQUAL, operator=BinaryFilterOperatorType.BOOLEAN_OR)
        filter_groups.append(type_sub)

    if tekla_classes:
        if isinstance(tekla_classes, int):
            tekla_classes = [tekla_classes]
        type_sub = BinaryFilterExpressionCollection()
        for cls in tekla_classes:
            add_filter(type_sub, PartFilterExpressions.Class(), cls, NumericOperatorType.IS_EQUAL, operator=BinaryFilterOperatorType.BOOLEAN_OR)
        filter_groups.append(type_sub)

    if standard_string_filters:
        for key, filter_option in standard_string_filters.items():
            expression = STANDARD_EXPRESSION_MAP[key]
            filter_option = _to_filter_option(filter_option, StringFilterOption)
            filter_groups.append(build_filter_group(expression, filter_option))

    string_resolution_errors: list[dict[str, Any]] = []
    numeric_resolution_errors: list[dict[str, Any]] = []
    resolved_string_attrs: dict[str, str | None] = {}
    resolved_numeric_attrs: dict[str, str | None] = {}

    if custom_string_filters:
        string_queries = list(custom_string_filters.keys())
        if string_queries:
            resolution = TemplateAttributeParser.resolve_attributes(string_queries)
            errors = resolution.get("errors", [])
            string_resolution_errors = errors
            for query, resolved in zip(string_queries, resolution["resolved"]):
                if any(e["query"] == query for e in errors):
                    resolved_string_attrs[query] = None
                else:
                    resolved_string_attrs[query] = resolved

        for field_name, filter_option in custom_string_filters.items():
            resolved_name = resolved_string_attrs.get(field_name)
            if resolved_name:
                expression = TemplateFilterExpressions.CustomString(resolved_name)
                filter_option = _to_filter_option(filter_option, StringFilterOption)
                filter_groups.append(build_filter_group(expression, filter_option))

    if custom_numeric_filters:
        numeric_queries = list(custom_numeric_filters.keys())
        if numeric_queries:
            resolution = TemplateAttributeParser.resolve_attributes(numeric_queries)
            errors = resolution.get("errors", [])
            numeric_resolution_errors = errors
            for query, resolved in zip(numeric_queries, resolution["resolved"]):
                if any(e["query"] == query for e in errors):
                    resolved_numeric_attrs[query] = None
                else:
                    resolved_numeric_attrs[query] = resolved

        for field_name, filter_option in custom_numeric_filters.items():
            resolved_name = resolved_numeric_attrs.get(field_name)
            if resolved_name:
                expression = TemplateFilterExpressions.CustomNumber(resolved_name)
                filter_option = _to_filter_option(filter_option, NumericFilterOption)
                filter_groups.append(build_filter_group(expression, filter_option, is_numeric=True))

    if len(filter_groups) == 1:
        filter_collection.Add(BinaryFilterExpressionItem(filter_groups[0], BinaryFilterOperatorType.BOOLEAN_AND))
    elif len(filter_groups) > 1:
        combined = BinaryFilterExpressionCollection()
        group_operator = BinaryFilterOperatorType.BOOLEAN_OR if combine_with == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        for fg in filter_groups:
            combined.Add(BinaryFilterExpressionItem(fg, group_operator))
        filter_collection.Add(BinaryFilterExpressionItem(combined, BinaryFilterOperatorType.BOOLEAN_AND))

    objects_to_select = model.get_objects_by_filter(filter_collection)
    TeklaModel.select_objects(objects_to_select)

    count = objects_to_select.GetSize()
    has_resolution_errors = bool(string_resolution_errors or numeric_resolution_errors)

    return {
        "status": "partial" if has_resolution_errors else ("success" if count else "error"),
        "selected_elements": count,
        "string_resolution_errors": string_resolution_errors,
        "numeric_resolution_errors": numeric_resolution_errors,
    }


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@log_mcp_tool_call
def select_elements_by_filter_name(
    filter_name: Annotated[str, Field(description="Name of the Tekla filter to apply")],
) -> dict[str, Any]:
    """
    Selects elements applying an existing Tekla filter.
    """
    model = TeklaModel()
    objects_to_select = model.get_objects_by_filter(filter_name)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by named filter", objects_to_select.GetSize())
    return {
        "status": "success" if objects_to_select.GetSize() else "error",
        "selected_elements": objects_to_select.GetSize(),
    }


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@log_mcp_tool_call
def select_elements_by_guid(
    guids: Annotated[list[str], Field(description="List of GUIDs to select")],
) -> dict[str, Any]:
    """
    Selects elements by their GUID.
    """
    model = TeklaModel()
    objects_to_select = model.get_objects_by_guid(guids)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by GUID", objects_to_select.Count)
    return {
        "status": "success" if objects_to_select.Count else "error",
        "selected_elements": objects_to_select.Count,
    }


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@log_mcp_tool_call
def select_elements_assemblies_or_main_parts(
    mode: Annotated[SelectionMode, Field(description="Selection mode: 'Assembly' or 'Main Part'")],
) -> dict[str, Any]:
    """
    Selects assemblies or main parts for the selected elements.
    """
    selected_objects = TeklaModel().get_selected_objects()

    processed_elements = 0
    selected_object_types = ""

    filtered_parts = ArrayList()
    for selected_object in wrap_model_objects(selected_objects):
        try:
            assembly = selected_object.get_top_level_assembly()
        except TypeError:
            logger.warning("Failed to get top level assembly for the element %s", selected_object.guid)
            continue
        if mode == "Assembly":
            filtered_parts.Add(assembly.model_object)
            selected_object_types = "selected_assemblies"
        elif mode == "Main Part":
            filtered_parts.Add(assembly.main_part.model_object)
            selected_object_types = "selected_main_parts"
        processed_elements += 1

    TeklaModel.select_objects(filtered_parts)
    logger.info("Selected %s elements as '%s'", filtered_parts.Count, mode)
    return {
        "status": "success" if filtered_parts.Count else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        selected_object_types: filtered_parts.Count,
    }
