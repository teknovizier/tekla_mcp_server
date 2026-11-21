"""
Helpers for constructing Tekla `BinaryFilterExpressionCollection` objects.

`build_filter_expression` turns a filter tree (`FilterGroup` / `FilterCondition`)
into one expression, so every tool that filters by criteria builds it the same way.
It takes Tekla attribute names as they are, resolving names is the caller's job.
"""

import math
from datetime import datetime
from typing import Any

from tekla_mcp_server.filter_fields import CATEGORIES, CUSTOM_MEMBERS, FIELDS, OBJECT_TYPES
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    FilterCondition,
    FilterGroup,
    FilterNode,
    NumericFilterOption,
    NumericMatchType,
    StringFilterOption,
    StringMatchType,
    simplify_filter_tree,
    specialize_filter_tree,
)
from tekla_mcp_server.tekla import loader
from tekla_mcp_server.tekla.interop import to_number_list
from tekla_mcp_server.tekla.loader import (
    BinaryFilterExpression,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    BinaryFilterOperatorType,
    BooleanConstantFilterExpression,
    BooleanOperatorType,
    DateTimeConstantFilterExpression,
    DateTimeOperatorType,
    NumericConstantFilterExpression,
    NumericOperatorType,
    ObjectFilterExpressions,
    StringConstantFilterExpression,
    StringOperatorType,
    SystemDateTime,
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


# Tekla rejects deeper filters with TOO_MANY_NESTED_COLLECTIONS. The outermost collection counts as one level
MAX_NESTING_DEPTH = 3

BOOLEAN_OPERATORS = {"Is Equal": BooleanOperatorType.IS_EQUAL, "Is Not Equal": BooleanOperatorType.IS_NOT_EQUAL}

DATE_OPERATORS = {
    "Is Equal": DateTimeOperatorType.IS_EQUAL,
    "Is Not Equal": DateTimeOperatorType.IS_NOT_EQUAL,
    "Earlier Than": DateTimeOperatorType.EARLIER_THAN,
    "Earlier Or Equal": DateTimeOperatorType.EARLIER_OR_EQUAL,
    "Later Than": DateTimeOperatorType.LATER_THAN,
    # Tekla's own spelling of the member
    "Later Or Equal": DateTimeOperatorType.LATER_OR_EQUEL,
}


def _left_expression(condition: FilterCondition) -> Any:
    """
    Create the Tekla expression for the field or attribute of a condition.

    Args:
        condition: Validated condition

    Returns:
        The left-hand side expression

    Raises:
        ValueError: If the field must be expanded by the caller first
    """
    if condition.field is not None:
        spec = FIELDS[condition.field]
        if spec.expanded:
            raise ValueError(f"'{condition.field}' must be expanded into other conditions before building")
        factory = getattr(getattr(loader, spec.expression_class), spec.member)
        return factory(spec.argument) if spec.argument else factory()
    category_class = getattr(loader, CATEGORIES[condition.category])
    return getattr(category_class, CUSTOM_MEMBERS[condition.kind])(condition.attribute)


def _object_type_condition(object_types: list[str]) -> Any:
    """
    Create one condition matching any of the given object types.

    Args:
        object_types: Keys of `OBJECT_TYPES`

    Returns:
        `BinaryFilterExpression` comparing the object type with one value or a list
    """
    codes = [OBJECT_TYPES[t] for t in object_types]
    constant = NumericConstantFilterExpression(codes[0]) if len(codes) == 1 else NumericConstantFilterExpression(to_number_list(codes))
    return BinaryFilterExpression(ObjectFilterExpressions.Type(), NumericOperatorType.IS_EQUAL, constant)


def _quoted(value: str) -> str:
    """
    Quote a text value that contains whitespace.

    Tekla splits an unquoted value at spaces into alternatives, so 'LIGHTWEIGHT BLOCK' would
    match 'LIGHTWEIGHT' or 'BLOCK'. Quotes keep the words together.

    Args:
        value: Text value

    Returns:
        The value, in double quotes when it contains whitespace and is not quoted yet
    """
    if any(c.isspace() for c in value) and not (len(value) >= 2 and value[0] == value[-1] == '"'):
        return f'"{value}"'
    return value


def _condition_expression(condition: FilterCondition) -> Any:
    """
    Create the binary expression for one condition.

    Args:
        condition: Validated condition

    Returns:
        `BinaryFilterExpression` comparing the field or attribute with the value or value list
    """
    left = _left_expression(condition)
    values = condition.values
    if condition.field is not None and FIELDS[condition.field].values:
        values = [FIELDS[condition.field].values[str(v)] for v in values]

    kind = condition.kind
    if kind == "boolean":
        return BinaryFilterExpression(left, BOOLEAN_OPERATORS[condition.op], BooleanConstantFilterExpression(bool(values[0])))
    if kind == "date":
        moment = datetime.fromisoformat(str(values[0]))
        constant = DateTimeConstantFilterExpression(SystemDateTime(moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second))
        return BinaryFilterExpression(left, DATE_OPERATORS[condition.op], constant)
    # The model has already converted the values to the field kind. A list becomes one value list row
    if kind == "numeric" and all(isinstance(v, (int, float)) for v in values):
        constant = NumericConstantFilterExpression(values[0]) if len(values) == 1 else NumericConstantFilterExpression(to_number_list(values))
        return BinaryFilterExpression(left, NUMERIC_MATCH_TYPE_MAPPING[NumericMatchType(condition.op)], constant)
    # Tekla reads a text value as space separated alternatives, so a list is written the way its own
    # filter files store one: quoted items joined by spaces. The API's list constructor loses the quotes
    constant = StringConstantFilterExpression(" ".join(_quoted(str(v)) for v in values))
    return BinaryFilterExpression(left, STRING_MATCH_TYPE_MAPPING[StringMatchType(condition.op)], constant)


def _alternatives(node: FilterNode) -> list[list[Any]]:
    """
    Split a tree into OR-joined alternatives, each a list of AND-joined items.

    Tekla binds AND tighter than OR, so 'a && b || c' means '(a && b) || c'. Writing an 'any'
    group as chains of its items saves the brackets of every 'all' group inside it. Items that
    are 'any' groups themselves keep their brackets.

    Args:
        node: Simplified filter group or condition

    Returns:
        The alternatives, at least one
    """
    items = node.items if isinstance(node, FilterGroup) and node.is_any else [node]
    return [list(item.items) if isinstance(item, FilterGroup) and not item.is_any else [item] for item in items]


def _add_chains(collection: BinaryFilterExpressionCollection, chains: list[list[Any]]) -> int:
    """
    Append OR-joined chains of AND-joined items to a collection without extra brackets.

    Args:
        collection: Collection to append to (mutated in place)
        chains: Alternatives, each a list of conditions, groups or ready Tekla expressions

    Returns:
        Levels of brackets the items add below `collection`, 0 when every item is a condition
    """
    and_, or_ = BinaryFilterOperatorType.BOOLEAN_AND, BinaryFilterOperatorType.BOOLEAN_OR
    depth = 0
    for chain_index, chain in enumerate(chains):
        for item_index, item in enumerate(chain):
            # The operator joins an item with the next one, so a chain's last item carries the OR
            last_in_chain = item_index == len(chain) - 1
            operator = or_ if last_in_chain and chain_index < len(chains) - 1 else and_
            if isinstance(item, FilterGroup):
                group, group_depth = _build_group(item)
                collection.Add(BinaryFilterExpressionItem(group, operator))
                depth = max(depth, group_depth)
            elif isinstance(item, FilterCondition):
                collection.Add(BinaryFilterExpressionItem(_condition_expression(item), operator))
            else:
                collection.Add(BinaryFilterExpressionItem(item, operator))
    return depth


def _build_group(group: FilterGroup) -> tuple[BinaryFilterExpressionCollection, int]:
    """
    Build a bracketed collection for a group.

    Args:
        group: Simplified group

    Returns:
        Tuple of the collection and its nesting depth with the collection itself counted as 1
    """
    collection = BinaryFilterExpressionCollection()
    return collection, 1 + _add_chains(collection, _alternatives(group))


def build_filter_expression(tree: FilterNode, object_types: list[str]) -> BinaryFilterExpressionCollection:
    """
    Build a Tekla filter expression from a filter tree.

    The result matches objects of any of `object_types` that satisfy the tree. A condition on a
    category tied to one object type (e.g. 'part' or 'bolt') is ignored for the other types, and
    `object.type` conditions are decided per type. Types whose reduced trees are equal share one
    branch. Tekla allows at most `MAX_NESTING_DEPTH` levels of brackets, so the expression relies on
    AND binding tighter than OR instead of brackets wherever it can.

    Args:
        tree: Validated filter group or single condition
        object_types: Keys of `OBJECT_TYPES`, at least one

    Returns:
        The built expression

    Raises:
        ValueError: If `object_types` is empty or unknown, no type can match, or the tree nests deeper than Tekla allows
    """
    if not object_types:
        raise ValueError(f"At least one object type is required. Choose from: {sorted(OBJECT_TYPES)}")
    unknown = [t for t in object_types if t not in OBJECT_TYPES]
    if unknown:
        raise ValueError(f"Unknown object types {unknown}. Choose from: {sorted(OBJECT_TYPES)}")

    # Group the types by what the tree means for them
    branches: dict[str, tuple[list[str], FilterNode | None]] = {}
    simplified = simplify_filter_tree(tree)
    for object_type in dict.fromkeys(object_types):
        reduced = specialize_filter_tree(simplified, object_type)
        if reduced is False:
            continue
        node = None if reduced is True or reduced is None else reduced
        key = "" if node is None else node.model_dump_json()
        branches.setdefault(key, ([], node))[0].append(object_type)
    if not branches:
        raise ValueError(f"No object of the types {object_types} can match this filter. Check its `object.type` conditions")

    # Every alternative of every branch starts with its object type condition, so the whole filter
    # is one OR chain of AND chains and needs brackets only for 'any' groups inside an 'all'
    chains = [[_object_type_condition(types), *alternative] for types, node in branches.values() for alternative in (_alternatives(node) if node is not None else [[]])]
    expression = BinaryFilterExpressionCollection()
    depth = 1 + _add_chains(expression, chains)

    if depth > MAX_NESTING_DEPTH:
        raise ValueError(
            f"The filter nests {depth} levels of brackets, but Tekla allows at most {MAX_NESTING_DEPTH}. "
            "Flatten it, e.g. by using list values, moving conditions out of nested groups, or selecting fewer object types at once."
        )
    logger.debug("Built filter for object types %s in %d branches with depth %d", object_types, len(branches), depth)
    return expression
