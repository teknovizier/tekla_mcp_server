"""
Selection tools for Tekla model operations.
"""

from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    ElementType,
    NumericMatchType,
    SelectionMode,
    StandardStringFilterKey,
    StringFilterOption,
    StringMatchType,
    NumericFilterOption,
    get_element_type_mapping,
)
from tekla_mcp_server.tekla.loader import (
    ArrayList,
    BinaryFilterExpression,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    BinaryFilterOperatorType,
    ModelObjectEnumerator,
    NumericConstantFilterExpression,
    NumericOperatorType,
    ObjectFilterExpressions,
    PartFilterExpressions,
    StringConstantFilterExpression,
    TeklaStructuresDatabaseTypeEnum,
    TemplateFilterExpressions,
)
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tekla.model_object import (
    wrap_model_objects,
)
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.utils import (
    NUMERIC_MATCH_TYPE_MAPPING,
    STRING_MATCH_TYPE_MAPPING,
)
from tekla_mcp_server.utils import log_function_call


def _to_filter_option(val: Any, model_class: type[StringFilterOption] | type[NumericFilterOption]) -> StringFilterOption | NumericFilterOption:
    """Convert dict input to Pydantic model if needed."""
    if isinstance(val, dict):
        return model_class.model_validate(val)
    return val


def validate_exactly_two_selected(count: int) -> None:
    """
    Validate that exactly two elements are selected.

    Args:
        count: Number of selected elements

    Raises:
        ValueError: If the count is not equal to 2.
    """
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
    """
    Adds a filter expression to the filter collection.

    For string filters: provide match_type as StringMatchType enum
    For numeric filters: provide match_type as NumericMatchType or NumericOperatorType enum
    For Tekla enum types (like TeklaStructuresDatabaseTypeEnum): uses default IS_EQUAL

    Args:
        filter_collection: The filter collection to add to
        filter_expression: The filter expression to add
        value: The value to filter by
        match_type: Enum for match type (StringMatchType, NumericMatchType, or NumericOperatorType)
        operator: Boolean operator to combine with previous filter (default BOOLEAN_AND)
    """
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


@log_function_call
def tool_select_elements_by_filter(
    model: TeklaModel,
    element_type: ElementType | None = None,
    tekla_classes: int | list[int] | None = None,
    standard_string_filters: dict[str, Any] | None = None,
    custom_string_filters: dict[str, Any] | None = None,
    custom_numeric_filters: dict[str, Any] | None = None,
    combine_with: str = "AND",
) -> dict[str, Any]:
    """
    Select element using standard Tekla properties, custom attributes, and numeric ranges.

    Args:
        model: TeklaModel instance
        element_type: Named element type (ElementType enum)
        tekla_classes: Tekla class number(s) - int or list of ints (e.g., 1, 8, 100)
        standard_string_filters: Dict of standard property names to StringFilterOption.
            Valid keys: name, profile, material, finish, phase
        custom_string_filters: Dict of custom string property names to StringFilterOption
        custom_numeric_filters: Dict of custom numeric property names to NumericFilterOption
        combine_with: How to combine filter groups - "AND" or "OR", default "AND"
    """
    if combine_with not in {"AND", "OR"}:
        raise ValueError(f"Invalid combine_with '{combine_with}'. Must be 'AND' or 'OR'.")

    if not any((element_type, tekla_classes, standard_string_filters, custom_string_filters, custom_numeric_filters)):
        raise ValueError("At least one filter must be provided.")

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

    def build_filter_group(
        expression: Any,
        filter_option: StringFilterOption | NumericFilterOption,
        is_numeric: bool = False,
    ) -> BinaryFilterExpressionCollection:
        sub = BinaryFilterExpressionCollection()
        conditions = filter_option.conditions
        logic = filter_option.logic
        if not isinstance(conditions, list):
            conditions = [conditions]
        operator = BinaryFilterOperatorType.BOOLEAN_OR if logic == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        for cond in conditions:
            value = cond.value
            match_type_str = cond.match_type
            if is_numeric:
                match_type = NumericMatchType(match_type_str)
            else:
                match_type = StringMatchType(match_type_str)
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
        if isinstance(element_type, ElementType):
            for mapping in get_element_type_mapping().values():
                if element_type.name in mapping:
                    element_type_classes.extend(mapping[element_type.name])
        else:
            raise ValueError("Invalid element_type.")
        type_sub = BinaryFilterExpressionCollection()
        for cls in element_type_classes:
            add_filter(
                type_sub,
                PartFilterExpressions.Class(),
                cls,
                NumericOperatorType.IS_EQUAL,
                operator=BinaryFilterOperatorType.BOOLEAN_OR,
            )
        filter_groups.append(type_sub)

    if tekla_classes:
        if isinstance(tekla_classes, int):
            tekla_classes = [tekla_classes]
        type_sub = BinaryFilterExpressionCollection()
        for cls in tekla_classes:
            add_filter(
                type_sub,
                PartFilterExpressions.Class(),
                cls,
                NumericOperatorType.IS_EQUAL,
                operator=BinaryFilterOperatorType.BOOLEAN_OR,
            )
        filter_groups.append(type_sub)

    if standard_string_filters:
        for key, filter_option in standard_string_filters.items():
            expression = STANDARD_EXPRESSION_MAP[key]
            filter_option = _to_filter_option(filter_option, StringFilterOption)
            filter_groups.append(build_filter_group(expression, filter_option))

    string_resolution_errors: list[dict[str, Any]] = []
    numeric_resolution_errors: list[dict[str, Any]] = []

    if custom_string_filters:
        string_queries = list(custom_string_filters.keys())
        if string_queries:
            resolution = TemplateAttributeParser.resolve_attributes(string_queries)
            errors = resolution.get("errors", [])
            string_resolution_errors = errors
            resolved_string_attrs: dict[str, str | None] = {}
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
            resolved_numeric_attrs: dict[str, str | None] = {}
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


@log_function_call
def tool_select_elements_by_filter_name(model: TeklaModel, filter_name: str) -> dict[str, Any]:
    """
    Selects elements in the Tekla model based on the existing filter.

    Args:
        model: TeklaModel instance
        filter_name: Name of the filter to use
    """
    objects_to_select = model.get_objects_by_filter(filter_name)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by named filter", objects_to_select.GetSize())
    return {
        "status": "success" if objects_to_select.GetSize() else "error",
        "selected_elements": objects_to_select.GetSize(),
    }


@log_function_call
def tool_select_elements_by_guid(model: TeklaModel, guids: list[str]) -> dict[str, Any]:
    """
    Selects elements in the Tekla model by their GUID.

    Args:
        model: TeklaModel instance
        guids: List of GUIDs to select
    """
    objects_to_select = model.get_objects_by_guid(guids)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by GUID", objects_to_select.Count)
    return {
        "status": "success" if objects_to_select.Count else "error",
        "selected_elements": objects_to_select.Count,
    }


@log_function_call
def tool_select_elements_assemblies_or_main_parts(selected_objects: ModelObjectEnumerator, mode: SelectionMode) -> dict[str, Any]:
    """
    Returns assemblies or main parts for the given selected objects.

    Args:
        selected_objects: Enumerator of selected objects
        mode: Selection mode (Assembly or MainPart)
    """
    processed_elements = 0
    selected_object_types = ""

    filtered_parts = ArrayList()
    for selected_object in wrap_model_objects(selected_objects):
        try:
            assembly = selected_object.get_top_level_assembly()
        except TypeError:
            logger.warning("Failed to get top level assembly for the element %s", selected_object.guid)
            continue
        if mode == SelectionMode.ASSEMBLY:
            filtered_parts.Add(assembly.model_object)
            selected_object_types = "selected_assemblies"
        elif mode == SelectionMode.MAIN_PART:
            filtered_parts.Add(assembly.main_part.model_object)
            selected_object_types = "selected_main_parts"
        processed_elements += 1

    TeklaModel.select_objects(filtered_parts)
    logger.info("Selected %s elements as '%s'", filtered_parts.Count, mode.value)
    return {
        "status": "success" if filtered_parts.Count else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        selected_object_types: filtered_parts.Count,
    }
