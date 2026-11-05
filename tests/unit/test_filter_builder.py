"""
Unit tests for filter_builder helpers.

The tests build real Tekla filter collections from the Tekla DLLs, so they are
skipped in CI environments where Tekla is not available. No running Tekla model
is needed. The built expressions keep their operator and constant in non-public
properties, so they are read back through .NET reflection.
"""

import os
from typing import Any

import pytest
from pydantic import ValidationError

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import NumericFilterOption, NumericMatchType, StringFilterOption, StringMatchType
from tekla_mcp_server.tekla.filter_builder import (
    NUMERIC_MATCH_TYPE_MAPPING,
    STRING_MATCH_TYPE_MAPPING,
    _parse_numeric_string,
    add_filter,
    build_filter_group,
    to_filter_option,
)
from tekla_mcp_server.tekla.loader import (
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    BinaryFilterOperatorType,
    NumericOperatorType,
    ObjectFilterExpressions,
    PartFilterExpressions,
    TeklaStructuresDatabaseTypeEnum,
)

# The loader import has initialized pythonnet, so the System namespace is importable now
from System.Reflection import BindingFlags  # noqa: E402

_ALL_MEMBERS = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance


def _get(obj: Any, name: str) -> Any:
    """
    Read a property of a .NET object, including non-public ones.

    Args:
        obj: .NET object to read from
        name: Property name

    Returns:
        The property value
    """
    return obj.GetType().GetProperty(name, _ALL_MEMBERS).GetValue(obj)


def _describe(collection: Any) -> list[dict[str, Any]]:
    """
    Convert a filter collection into plain dicts that tests can compare.

    Args:
        collection: `BinaryFilterExpressionCollection` to describe

    Returns:
        One dict per item with the joining operator and either the expression
        parts (`left`, `op`, `kind`, `value`) or a nested `items` list
    """
    result = []
    for item in collection:
        expression = _get(item, "FilterExpression")
        entry: dict[str, Any] = {"join": str(_get(item, "BinaryFilterItemOperatorType"))}
        if expression.GetType().Name == "BinaryFilterExpressionCollection":
            entry["items"] = _describe(expression)
        else:
            right = _get(expression, "Right")
            entry.update(
                left=_get(_get(expression, "Left"), "Value"),
                op=str(_get(expression, "Operator")),
                kind="string" if right.GetType().Name == "StringConstantFilterExpression" else "numeric",
                value=_get(right, "Value"),
            )
        result.append(entry)
    return result


def _single(collection: Any) -> dict[str, Any]:
    """
    Describe a collection that must contain exactly one item.

    Args:
        collection: `BinaryFilterExpressionCollection` with one item

    Returns:
        The description of that item
    """
    items = _describe(collection)
    assert len(items) == 1
    return items[0]


class TestParseNumericString:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("7", 7),
            ("007", 7),
            ("-12", -12),
            (" 42 ", 42),
            ("3.5", 3.5),
            ("-0.25", -0.25),
            ("1e3", 1000.0),
            ("abc", "abc"),
            ("1.2.3", "1.2.3"),
            ("nan", "nan"),
            ("inf", "inf"),
            ("", ""),
        ],
    )
    def test_parse(self, value, expected):
        result = _parse_numeric_string(value)
        assert result == expected
        assert type(result) is type(expected)


class TestToFilterOption:
    def test_dict_is_validated(self):
        option = to_filter_option({"conditions": {"match_type": "Contains", "value": "BEAM"}}, StringFilterOption)
        assert isinstance(option, StringFilterOption)
        assert option.get_values() == "BEAM"

    def test_instance_passes_through(self):
        option = NumericFilterOption(conditions={"match_type": "Greater Than", "value": 5})
        assert to_filter_option(option, NumericFilterOption) is option

    def test_invalid_dict_raises(self):
        with pytest.raises(ValidationError):
            to_filter_option({"conditions": {"match_type": "Bogus", "value": "x"}}, StringFilterOption)


class TestAddFilterStrings:
    def test_string_without_match_type_is_string_equal(self):
        collection = BinaryFilterExpressionCollection()
        add_filter(collection, PartFilterExpressions.Name(), "BEAM")
        assert _single(collection) == {"join": "BOOLEAN_AND", "left": "Part.Name", "op": "IS_EQUAL", "kind": "string", "value": "BEAM"}

    def test_numeric_looking_string_without_match_type_stays_string(self):
        """'007' on a string attribute must not become the number 7."""
        collection = BinaryFilterExpressionCollection()
        add_filter(collection, PartFilterExpressions.Name(), "007")
        item = _single(collection)
        assert item["kind"] == "string"
        assert item["value"] == "007"

    @pytest.mark.parametrize("match_type", list(StringMatchType))
    def test_every_string_match_type_maps_to_its_operator(self, match_type):
        collection = BinaryFilterExpressionCollection()
        add_filter(collection, PartFilterExpressions.Name(), "123", match_type)
        item = _single(collection)
        assert item["op"] == str(STRING_MATCH_TYPE_MAPPING[match_type])
        assert item["kind"] == "string"
        assert item["value"] == "123"

    def test_string_match_type_on_number_raises(self):
        with pytest.raises(TypeError, match="no numeric operator"):
            add_filter(BinaryFilterExpressionCollection(), PartFilterExpressions.Class(), 11, StringMatchType.CONTAINS)


class TestAddFilterNumbers:
    def test_int_without_match_type_is_numeric_equal(self):
        collection = BinaryFilterExpressionCollection()
        add_filter(collection, PartFilterExpressions.Class(), 11)
        assert _single(collection) == {"join": "BOOLEAN_AND", "left": "Part.Class", "op": "IS_EQUAL", "kind": "numeric", "value": "11"}

    def test_float_value(self):
        collection = BinaryFilterExpressionCollection()
        add_filter(collection, PartFilterExpressions.Class(), 2500.5, NumericMatchType.SMALLER_THAN)
        item = _single(collection)
        assert (item["op"], item["kind"], item["value"]) == ("SMALLER_THAN", "numeric", "2500.5")

    @pytest.mark.parametrize("match_type", list(NumericMatchType))
    def test_every_numeric_match_type_maps_to_its_operator(self, match_type):
        collection = BinaryFilterExpressionCollection()
        add_filter(collection, PartFilterExpressions.Class(), 11, match_type)
        assert _single(collection)["op"] == str(NUMERIC_MATCH_TYPE_MAPPING[match_type])

    @pytest.mark.parametrize("match_type", [NumericMatchType.GREATER_THAN, NumericOperatorType.GREATER_THAN])
    def test_numeric_string_with_numeric_match_type_is_parsed(self, match_type):
        collection = BinaryFilterExpressionCollection()
        add_filter(collection, PartFilterExpressions.Class(), "011", match_type)
        item = _single(collection)
        assert (item["op"], item["kind"], item["value"]) == ("GREATER_THAN", "numeric", "11")

    @pytest.mark.parametrize("match_type", [NumericMatchType.IS_EQUAL, NumericMatchType.GREATER_THAN, NumericOperatorType.IS_EQUAL])
    def test_non_numeric_string_with_numeric_match_type_raises(self, match_type):
        """'Is Equal' is shared by both StrEnums, so it must not fall back to a string comparison."""
        collection = BinaryFilterExpressionCollection()
        with pytest.raises(TypeError, match="is not a number"):
            add_filter(collection, PartFilterExpressions.Class(), "abc", match_type)
        assert collection.Count == 0

    def test_tekla_enum_value_is_numeric_equal(self):
        collection = BinaryFilterExpressionCollection()
        add_filter(collection, ObjectFilterExpressions.Type(), TeklaStructuresDatabaseTypeEnum.PART)
        item = _single(collection)
        assert (item["left"], item["op"], item["kind"]) == ("ObjectType", "IS_EQUAL", "numeric")
        assert item["value"] == str(int(TeklaStructuresDatabaseTypeEnum.PART))


class TestAddFilterCollection:
    def test_items_are_appended_with_their_join_operator(self):
        collection = BinaryFilterExpressionCollection()
        add_filter(collection, ObjectFilterExpressions.Type(), TeklaStructuresDatabaseTypeEnum.PART)
        add_filter(collection, PartFilterExpressions.Name(), "A", operator=BinaryFilterOperatorType.BOOLEAN_OR)
        add_filter(collection, PartFilterExpressions.Class(), 11)
        assert [(i["left"], i["join"]) for i in _describe(collection)] == [
            ("ObjectType", "BOOLEAN_AND"),
            ("Part.Name", "BOOLEAN_OR"),
            ("Part.Class", "BOOLEAN_AND"),
        ]


class TestBuildFilterGroup:
    def test_single_string_condition(self):
        option = StringFilterOption(conditions={"match_type": "Starts With", "value": "MCP_"})
        group = build_filter_group(PartFilterExpressions.Name(), option)
        assert _describe(group) == [{"join": "BOOLEAN_OR", "left": "Part.Name", "op": "STARTS_WITH", "kind": "string", "value": "MCP_"}]

    @pytest.mark.parametrize("logic,join", [("OR", "BOOLEAN_OR"), ("AND", "BOOLEAN_AND")])
    def test_conditions_joined_by_logic(self, logic, join):
        option = StringFilterOption(
            conditions=[{"match_type": "Is Equal", "value": "A"}, {"match_type": "Ends With", "value": "1601"}],
            logic=logic,
        )
        group = build_filter_group(PartFilterExpressions.Name(), option)
        assert [(i["op"], i["value"], i["join"]) for i in _describe(group)] == [("IS_EQUAL", "A", join), ("ENDS_WITH", "1601", join)]

    def test_numeric_string_value_stays_string_in_string_group(self):
        """A string option with a numeric-looking value must build a string expression."""
        option = StringFilterOption(conditions={"match_type": "Is Equal", "value": "2"})
        item = _single(build_filter_group(PartFilterExpressions.Name(), option))
        assert (item["kind"], item["value"]) == ("string", "2")

    def test_numeric_group(self):
        option = NumericFilterOption(
            conditions=[{"match_type": "Greater Or Equal", "value": 10}, {"match_type": "Smaller Than", "value": 20.5}],
        )
        group = build_filter_group(PartFilterExpressions.Class(), option, is_numeric=True)
        assert [(i["op"], i["kind"], i["value"], i["join"]) for i in _describe(group)] == [
            ("GREATER_OR_EQUAL", "numeric", "10", "BOOLEAN_AND"),
            ("SMALLER_THAN", "numeric", "20.5", "BOOLEAN_AND"),
        ]

    def test_empty_conditions_return_none(self):
        """Validation forbids an empty list, but a constructed option must still not produce an empty group."""
        option = StringFilterOption.model_construct(conditions=[], logic="OR")
        assert build_filter_group(PartFilterExpressions.Name(), option) is None

    def test_group_nests_into_parent_collection(self):
        option = StringFilterOption(conditions=[{"match_type": "Is Equal", "value": "A"}, {"match_type": "Is Equal", "value": "B"}])
        parent = BinaryFilterExpressionCollection()
        add_filter(parent, ObjectFilterExpressions.Type(), TeklaStructuresDatabaseTypeEnum.PART)
        parent.Add(BinaryFilterExpressionItem(build_filter_group(PartFilterExpressions.Name(), option), BinaryFilterOperatorType.BOOLEAN_AND))
        described = _describe(parent)
        assert described[0]["left"] == "ObjectType"
        assert [i["value"] for i in described[1]["items"]] == ["A", "B"]
