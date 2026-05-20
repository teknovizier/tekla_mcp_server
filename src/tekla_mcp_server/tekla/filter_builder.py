"""
Helpers for constructing Tekla `BinaryFilterExpressionCollection` objects.
"""

from typing import Any

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
    NumericConstantFilterExpression,
    NumericOperatorType,
    StringConstantFilterExpression,
    StringOperatorType,
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


def add_filter(
    filter_collection: BinaryFilterExpressionCollection,
    filter_expression: Any,
    value: str | int | float,
    match_type: StringMatchType | NumericMatchType | NumericOperatorType | None = None,
    operator: BinaryFilterOperatorType = BinaryFilterOperatorType.BOOLEAN_AND,
) -> None:
    """
    Append one binary filter expression to a Tekla filter collection.

    Numeric-looking strings are coerced to int/float unless `match_type` is
    a `StringMatchType`. Non-scalar values (e.g. Tekla enums) get an `IS_EQUAL`
    numeric comparison.

    Args:
        filter_collection: Collection to append to (mutated in place).
        filter_expression: Left-hand-side expression (e.g. `PartFilterExpressions.Name()`).
        value: Value to compare against.
        match_type: Comparison operator; defaults to equality.
        operator: Boolean operator joining this item with previous entries.

    Raises:
        TypeError: If the value's type can't be mapped to a constant expression.
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
        raise TypeError(f"Unsupported value type in filter: {type(value).__name__}")

    filter_collection.Add(BinaryFilterExpressionItem(expr, operator))


def build_filter_group(expression: Any, filter_option: StringFilterOption | NumericFilterOption, is_numeric: bool = False) -> BinaryFilterExpressionCollection | None:
    """
    Build a sub-collection from a filter option's conditions.

    Conditions are joined by `BOOLEAN_OR` when `filter_option.logic == "OR"`,
    otherwise by `BOOLEAN_AND`.

    Args:
        expression: Left-hand-side expression shared by every condition.
        filter_option: Pydantic option carrying conditions and join logic.
        is_numeric: If True, parse `match_type` as `NumericMatchType`; else `StringMatchType`.

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
