"""
Helpers for constructing Tekla `BinaryFilterExpressionCollection` objects.

`build_filter_expression` turns structured filter criteria into one expression,
so every tool that filters by criteria builds it the same way. It takes Tekla
property and attribute names as they are, resolving names is the caller's job.
"""

import math
from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    NumericFilterOption,
    NumericMatchType,
    StringFilterOption,
    StringMatchType,
)
from tekla_mcp_server.tekla.loader import (
    BinaryFilterExpression,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    BinaryFilterOperatorType,
    BoltFilterExpressions,
    NumericConstantFilterExpression,
    NumericOperatorType,
    ObjectFilterExpressions,
    PartFilterExpressions,
    StringConstantFilterExpression,
    StringOperatorType,
    TeklaStructuresDatabaseTypeEnum,
    TemplateFilterExpressions,
)


STRING_MATCH_TYPE_MAPPING = {
    StringMatchType.IS_EQUAL: StringOperatorType.IS_EQUAL,
    StringMatchType.IS_NOT_EQUAL: StringOperatorType.IS_NOT_EQUAL,
    StringMatchType.CONTAINS: StringOperatorType.CONTAINS,
    StringMatchType.NOT_CONTAINS: StringOperatorType.NOT_CONTAINS,
    StringMatchType.STARTS_WITH: StringOperatorType.STARTS_WITH,
    StringMatchType.NOT_STARTS_WITH: StringOperatorType.NOT_STARTS_WITH,
    StringMatchType.ENDS_WITH: StringOperatorType.ENDS_WITH,
    StringMatchType.NOT_ENDS_WITH: StringOperatorType.NOT_ENDS_WITH,
}

NUMERIC_MATCH_TYPE_MAPPING = {
    NumericMatchType.IS_EQUAL: NumericOperatorType.IS_EQUAL,
    NumericMatchType.IS_NOT_EQUAL: NumericOperatorType.IS_NOT_EQUAL,
    NumericMatchType.SMALLER_THAN: NumericOperatorType.SMALLER_THAN,
    NumericMatchType.SMALLER_OR_EQUAL: NumericOperatorType.SMALLER_OR_EQUAL,
    NumericMatchType.GREATER_THAN: NumericOperatorType.GREATER_THAN,
    NumericMatchType.GREATER_OR_EQUAL: NumericOperatorType.GREATER_OR_EQUAL,
}

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
    "class": PartFilterExpressions.Class(),
    "part_start_number": PartFilterExpressions.StartNumber(),
    "assembly_start_number": TemplateFilterExpressions.CustomNumber("ASSEMBLY_START_NUMBER"),
}

BOLT_STRING_EXPRESSION_MAP = {
    "bolt_standard": BoltFilterExpressions.Standard(),
    "bolt_type": BoltFilterExpressions.SiteWorkshop(),
}

# Tekla's site/workshop filter matches the `BoltTypeEnum` value as a string
BOLT_TYPE_FILTER_VALUES = {"site": "0", "workshop": "1"}

BOLT_NUMERIC_EXPRESSION_MAP = {
    "bolt_size": BoltFilterExpressions.Size(),
    "bolt_length": BoltFilterExpressions.Length(),
    "phase": BoltFilterExpressions.Phase(),
}

# Per object type: (database type, string map, numeric map, custom string factory, custom number factory)
OBJECT_TYPE_FILTERS: dict[str, tuple[Any, dict[str, Any], dict[str, Any], Any, Any]] = {
    "part": (
        TeklaStructuresDatabaseTypeEnum.PART,
        STANDARD_STRING_EXPRESSION_MAP,
        STANDARD_NUMERIC_EXPRESSION_MAP,
        TemplateFilterExpressions.CustomString,
        TemplateFilterExpressions.CustomNumber,
    ),
    "bolt": (
        TeklaStructuresDatabaseTypeEnum.BOLT,
        BOLT_STRING_EXPRESSION_MAP,
        BOLT_NUMERIC_EXPRESSION_MAP,
        BoltFilterExpressions.CustomString,
        BoltFilterExpressions.CustomNumber,
    ),
}


def to_filter_option(val: Any, model_class: type[StringFilterOption] | type[NumericFilterOption]) -> StringFilterOption | NumericFilterOption:
    """
    Coerce a dict into `model_class`, or pass it through if already an instance.

    Args:
        val: Dict matching `model_class`'s schema, or an existing instance.
        model_class: `StringFilterOption` or `NumericFilterOption`.

    Returns:
        An instance of `model_class`.

    Raises:
        pydantic.ValidationError: If `val` is a dict that fails validation.
    """
    if isinstance(val, dict):
        return model_class.model_validate(val)
    return val


def _parse_numeric_string(value: str) -> str | int | float:
    """
    Parse a string as an int or float for a numeric comparison.

    Args:
        value: String supplied as a filter value

    Returns:
        The parsed int or float, or `value` unchanged when it is not a finite
        number (the caller then rejects the string with a numeric match type)
    """
    text = value.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        return value
    return number if math.isfinite(number) else value


def add_filter(
    filter_collection: BinaryFilterExpressionCollection,
    filter_expression: Any,
    value: str | int | float,
    match_type: StringMatchType | NumericMatchType | NumericOperatorType | None = None,
    operator: BinaryFilterOperatorType = BinaryFilterOperatorType.BOOLEAN_AND,
) -> None:
    """
    Append one binary filter expression to a Tekla filter collection.

    Strings are coerced to int/float only when `match_type` is numeric. Without
    a `match_type`, strings get a string `IS_EQUAL` and numbers a numeric one.
    Non-scalar values (e.g. Tekla enums) get an `IS_EQUAL` numeric comparison.

    Args:
        filter_collection: Collection to append to (mutated in place).
        filter_expression: Left-hand-side expression (e.g. `PartFilterExpressions.Name()`).
        value: Value to compare against.
        match_type: Comparison operator. Defaults to equality.
        operator: Boolean operator joining this item with previous entries.

    Raises:
        TypeError: If `match_type` has no operator for the value's type, e.g. a
            `StringMatchType.CONTAINS` against a numeric value.
    """
    if not isinstance(value, (str, int, float)):
        expr = BinaryFilterExpression(filter_expression, NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(value))
        filter_collection.Add(BinaryFilterExpressionItem(expr, operator))
        return

    # Only an explicit numeric match type turns a string into a number. Without one,
    # a value like "007" must stay a string so it still matches string attributes
    if isinstance(value, str) and isinstance(match_type, (NumericMatchType, NumericOperatorType)):
        value = _parse_numeric_string(value)
        # Both match types are StrEnums, so 'Is Equal' would otherwise fall back to a string comparison
        if isinstance(value, str):
            raise TypeError(f"Match type '{match_type}' is numeric, but the value {value!r} is not a number")

    if isinstance(value, str):
        if match_type is None:
            match_type = StringMatchType.IS_EQUAL
        op = STRING_MATCH_TYPE_MAPPING.get(match_type)
        if op is None:
            raise TypeError(f"Match type '{match_type}' has no string operator, so it cannot be applied to the string value {value!r}")
        expr = BinaryFilterExpression(filter_expression, op, StringConstantFilterExpression(value))
    else:
        # int or float - the guard at the top has already excluded everything else
        if match_type is None:
            match_type = NumericOperatorType.IS_EQUAL
        if isinstance(match_type, NumericOperatorType):
            op = match_type
        else:
            op = NUMERIC_MATCH_TYPE_MAPPING.get(match_type)
        if op is None:
            raise TypeError(f"Match type '{match_type}' has no numeric operator, so it cannot be applied to the numeric value {value!r}")
        expr = BinaryFilterExpression(filter_expression, op, NumericConstantFilterExpression(value))

    filter_collection.Add(BinaryFilterExpressionItem(expr, operator))


def build_filter_group(expression: Any, filter_option: StringFilterOption | NumericFilterOption, is_numeric: bool = False) -> BinaryFilterExpressionCollection | None:
    """
    Build a sub-collection from a filter option's conditions.

    Conditions are joined by `BOOLEAN_OR` when `filter_option.logic == "OR"`,
    otherwise by `BOOLEAN_AND`.

    Args:
        expression: Left-hand-side expression shared by every condition.
        filter_option: Pydantic option carrying conditions and join logic.
        is_numeric: If True, parse `match_type` as `NumericMatchType`, otherwise as `StringMatchType`.

    Returns:
        The populated collection, or `None` if no conditions were added.
    """
    sub = BinaryFilterExpressionCollection()
    conditions = filter_option.conditions
    logic = filter_option.logic
    if not isinstance(conditions, list):
        conditions = [conditions]
    if not conditions:
        return None
    operator = BinaryFilterOperatorType.BOOLEAN_OR if logic == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
    for cond in conditions:
        value = cond.value
        match_type_str = cond.match_type
        match_type = NumericMatchType(match_type_str) if is_numeric else StringMatchType(match_type_str)
        add_filter(sub, expression, value, match_type, operator=operator)

    if sub.Count == 0:
        return None
    return sub


def _to_bolt_type_filter(filter_option: StringFilterOption) -> StringFilterOption:
    """
    Translate 'site' and 'workshop' in a `bolt_type` filter to the values Tekla matches.

    Args:
        filter_option: Filter option whose condition values are 'site' or 'workshop'

    Returns:
        A copy of the option with the values replaced

    Raises:
        ValueError: If a value is not 'site' or 'workshop'
    """
    conditions = filter_option.conditions if isinstance(filter_option.conditions, list) else [filter_option.conditions]
    mapped = []
    for condition in conditions:
        value = BOLT_TYPE_FILTER_VALUES.get(condition.value.strip().lower())
        if value is None:
            raise ValueError(f"Invalid bolt_type filter value '{condition.value}'. Must be one of: {sorted(BOLT_TYPE_FILTER_VALUES)}")
        mapped.append(condition.model_copy(update={"value": value}))
    return filter_option.model_copy(update={"conditions": mapped})


def build_filter_expression(
    object_type: str = "part",
    standard_string_filters: dict[str, Any] | None = None,
    standard_numeric_filters: dict[str, Any] | None = None,
    custom_string_filters: dict[str, Any] | None = None,
    custom_numeric_filters: dict[str, Any] | None = None,
    combine_with: str = "AND",
) -> BinaryFilterExpressionCollection:
    """
    Build a Tekla filter expression from structured filter criteria.

    The expression always restricts the object type, then joins the criteria groups with `combine_with`.

    Args:
        object_type: Key of `OBJECT_TYPE_FILTERS`, 'part' or 'bolt'
        standard_string_filters: Standard string property keys to filter options
        standard_numeric_filters: Standard numeric property keys to filter options
        custom_string_filters: Tekla custom attribute names to string filter options
        custom_numeric_filters: Tekla custom attribute names to numeric filter options
        combine_with: How to combine filter groups, 'AND' or 'OR'

    Returns:
        The built expression

    Raises:
        ValueError: If the criteria are invalid or produce no usable condition
    """
    standard_string_filters = standard_string_filters or {}
    standard_numeric_filters = standard_numeric_filters or {}
    custom_string_filters = custom_string_filters or {}
    custom_numeric_filters = custom_numeric_filters or {}

    # Validate combine_with and ensure at least one filter provided
    if combine_with not in {"AND", "OR"}:
        raise ValueError(f"Invalid combine_with '{combine_with}'. Must be 'AND' or 'OR'.")

    if not any((standard_string_filters, standard_numeric_filters, custom_string_filters, custom_numeric_filters)):
        raise ValueError("At least one filter must be provided.")

    if object_type not in OBJECT_TYPE_FILTERS:
        raise ValueError(f"Invalid object_type '{object_type}'. Must be one of: {sorted(OBJECT_TYPE_FILTERS)}")
    database_type, string_expression_map, numeric_expression_map, custom_string_expression, custom_number_expression = OBJECT_TYPE_FILTERS[object_type]

    # Base filter: always filter for the requested object type only
    filter_collection = BinaryFilterExpressionCollection()
    filter_collection.Add(
        BinaryFilterExpressionItem(
            BinaryFilterExpression(
                ObjectFilterExpressions.Type(),
                NumericOperatorType.IS_EQUAL,
                NumericConstantFilterExpression(database_type),
            )
        )
    )

    # Derive valid keys from expression maps
    valid_string_keys = frozenset(string_expression_map.keys())
    valid_numeric_keys = frozenset(numeric_expression_map.keys())

    # Validate input keys
    for key in standard_string_filters:
        if key not in valid_string_keys:
            raise ValueError(f"Invalid standard_string_filters key '{key}'. Must be one of: {valid_string_keys}")

    for key in standard_numeric_filters:
        if key not in valid_numeric_keys:
            raise ValueError(f"Invalid standard_numeric_filters key '{key}'. Must be one of: {valid_numeric_keys}")

    filter_groups: list[BinaryFilterExpressionCollection] = []

    # Add standard string filters (parts: name, profile, material, finish, phase, prefixes. Bolts: bolt_standard, bolt_type)
    for key, filter_option in standard_string_filters.items():
        filter_option = to_filter_option(filter_option, StringFilterOption)
        if object_type == "bolt" and key == "bolt_type":
            filter_option = _to_bolt_type_filter(filter_option)
        result = build_filter_group(string_expression_map[key], filter_option)
        if result is not None:
            filter_groups.append(result)

    # Add standard numeric filters (parts: class, start numbers. Bolts: bolt_size, bolt_length, phase)
    for key, filter_option in standard_numeric_filters.items():
        filter_option = to_filter_option(filter_option, NumericFilterOption)
        result = build_filter_group(numeric_expression_map[key], filter_option, is_numeric=True)
        if result is not None:
            filter_groups.append(result)

    # Add custom attribute filters
    for attribute_name, filter_option in custom_string_filters.items():
        filter_option = to_filter_option(filter_option, StringFilterOption)
        result = build_filter_group(custom_string_expression(attribute_name), filter_option)
        if result is not None:
            filter_groups.append(result)

    for attribute_name, filter_option in custom_numeric_filters.items():
        filter_option = to_filter_option(filter_option, NumericFilterOption)
        result = build_filter_group(custom_number_expression(attribute_name), filter_option, is_numeric=True)
        if result is not None:
            filter_groups.append(result)

    # Refuse rather than silently matching every object via the bare type filter
    if not filter_groups:
        raise ValueError("No usable filter conditions were produced - nothing was selected to avoid selecting the entire model.")

    # Combine all filter groups into final filter
    if len(filter_groups) == 1:
        filter_collection.Add(BinaryFilterExpressionItem(filter_groups[0], BinaryFilterOperatorType.BOOLEAN_AND))
    else:
        combined = BinaryFilterExpressionCollection()
        group_operator = BinaryFilterOperatorType.BOOLEAN_OR if combine_with == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        logger.debug("Combining %d filter groups with %s", len(filter_groups), combine_with)
        for fg in filter_groups:
            combined.Add(BinaryFilterExpressionItem(fg, group_operator))
        filter_collection.Add(BinaryFilterExpressionItem(combined, BinaryFilterOperatorType.BOOLEAN_AND))

    return filter_collection
