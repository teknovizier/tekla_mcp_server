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
    _to_bolt_type_filter,
    add_filter,
    build_filter_expression,
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


class TestBoltTypeFilter:
    @pytest.mark.parametrize("value,expected", [("site", "0"), ("Workshop", "1"), (" SITE ", "0")])
    def test_value_is_translated(self, value, expected):
        option = StringFilterOption(conditions={"match_type": "Is Equal", "value": value})
        result = _to_bolt_type_filter(option)
        assert [c.value for c in result.conditions] == [expected]

    def test_several_conditions_keep_their_logic(self):
        option = StringFilterOption(conditions=[{"match_type": "Is Equal", "value": "site"}, {"match_type": "Is Equal", "value": "workshop"}], logic="OR")
        result = _to_bolt_type_filter(option)
        assert [c.value for c in result.conditions] == ["0", "1"]
        assert result.logic == "OR"

    def test_unknown_value_is_rejected(self):
        option = StringFilterOption(conditions={"match_type": "Is Equal", "value": "factory"})
        with pytest.raises(ValueError, match="factory"):
            _to_bolt_type_filter(option)


class TestBuildFilterExpression:
    @staticmethod
    def _class_filter(*classes: int) -> dict[str, Any]:
        return {"class": {"conditions": [{"match_type": "Is Equal", "value": c} for c in classes], "logic": "OR"}}

    def test_no_criteria_raises(self):
        with pytest.raises(ValueError, match="At least one filter"):
            build_filter_expression()

    def test_invalid_combine_with_raises(self):
        with pytest.raises(ValueError, match="combine_with"):
            build_filter_expression(standard_numeric_filters=self._class_filter(1), combine_with="XOR")

    def test_unknown_standard_key_raises(self):
        with pytest.raises(ValueError, match="standard_string_filters key 'bolt_standard'"):
            build_filter_expression(standard_string_filters={"bolt_standard": {"conditions": {"match_type": "Is Equal", "value": "7990"}}})

    def test_class_key_is_parts_only(self):
        with pytest.raises(ValueError, match="standard_numeric_filters key 'class'"):
            build_filter_expression(object_type="bolt", standard_numeric_filters=self._class_filter(1))

    def test_class_conditions_are_joined_by_or(self):
        expression = build_filter_expression(standard_numeric_filters=self._class_filter(1, 8))
        described = _describe(expression)
        assert described[0]["left"] == "ObjectType"
        assert [(i["op"], i["value"], i["join"]) for i in described[1]["items"]] == [("IS_EQUAL", "1", "BOOLEAN_OR"), ("IS_EQUAL", "8", "BOOLEAN_OR")]

    def test_custom_attribute_name_is_used_as_given(self):
        expression = build_filter_expression(custom_numeric_filters={"HEIGHT": {"conditions": {"match_type": "Greater Than", "value": 2000}}})
        item = _describe(expression)[1]["items"][0]
        assert (item["left"], item["op"], item["value"]) == ("TemplateCustomNumber", "GREATER_THAN", "2000")
        # The attribute name sits in the expression's `Properties` dictionary, not in `Value`
        group = _get(list(expression)[1], "FilterExpression")
        left = _get(_get(next(iter(group)), "FilterExpression"), "Left")
        assert "HEIGHT" in list(_get(left, "Properties").Values)

    @pytest.mark.parametrize("combine_with,join", [("AND", "BOOLEAN_AND"), ("OR", "BOOLEAN_OR")])
    def test_groups_joined_by_combine_with(self, combine_with, join):
        name_filter = {"name": {"conditions": {"match_type": "Is Equal", "value": "Wall"}}}
        expression = build_filter_expression(standard_string_filters=name_filter, standard_numeric_filters=self._class_filter(1), combine_with=combine_with)
        combined = _describe(expression)[1]["items"]
        assert [g["join"] for g in combined] == [join, join]
        assert [g["items"][0]["value"] for g in combined] == ["Wall", "1"]


class TestBuildFilterExpressionEdgeCases:
    NAME_FILTER = {"name": {"conditions": {"match_type": "Is Equal", "value": "Wall"}}}

    def test_invalid_object_type_raises(self):
        with pytest.raises(ValueError, match="Invalid object_type 'weld'"):
            build_filter_expression(object_type="weld", standard_string_filters=self.NAME_FILTER)

    def test_unknown_numeric_key_raises(self):
        with pytest.raises(ValueError, match="standard_numeric_filters key 'height'"):
            build_filter_expression(standard_numeric_filters={"height": {"conditions": {"match_type": "Is Equal", "value": 1}}})

    def test_part_keys_are_rejected_for_bolts(self):
        with pytest.raises(ValueError, match="standard_string_filters key 'name'"):
            build_filter_expression(object_type="bolt", standard_string_filters=self.NAME_FILTER)

    def test_bolt_type_is_rejected_for_parts(self):
        with pytest.raises(ValueError, match="standard_string_filters key 'bolt_type'"):
            build_filter_expression(standard_string_filters={"bolt_type": {"conditions": {"match_type": "Is Equal", "value": "site"}}})

    @pytest.mark.parametrize("combine_with", ["and", "or", "", "NOT"])
    def test_combine_with_is_case_sensitive(self, combine_with):
        with pytest.raises(ValueError, match="combine_with"):
            build_filter_expression(standard_string_filters=self.NAME_FILTER, combine_with=combine_with)

    def test_empty_dicts_count_as_no_criteria(self):
        with pytest.raises(ValueError, match="At least one filter"):
            build_filter_expression(standard_string_filters={}, standard_numeric_filters={}, custom_string_filters={}, custom_numeric_filters={})

    def test_filter_option_instances_are_accepted(self):
        option = StringFilterOption(conditions={"match_type": "Is Equal", "value": "Wall"})
        expression = build_filter_expression(standard_string_filters={"name": option})
        assert _describe(expression)[1]["items"][0]["value"] == "Wall"

    def test_invalid_filter_option_dict_raises(self):
        with pytest.raises(ValidationError):
            build_filter_expression(standard_string_filters={"name": {"conditions": {"match_type": "Bogus", "value": "Wall"}}})

    def test_text_value_in_numeric_filter_raises(self):
        """The filter option model rejects the text before any expression is built."""
        with pytest.raises(ValidationError):
            build_filter_expression(standard_numeric_filters={"part_start_number": {"conditions": {"match_type": "Greater Than", "value": "many"}}})

    def test_single_group_is_joined_with_and_even_for_or(self):
        described = _describe(build_filter_expression(standard_string_filters=self.NAME_FILTER, combine_with="OR"))
        assert len(described) == 2
        assert described[1]["join"] == "BOOLEAN_AND"
        assert described[1]["items"][0]["value"] == "Wall"

    def test_combined_groups_sit_under_and_after_type_filter(self):
        described = _describe(
            build_filter_expression(
                standard_string_filters=self.NAME_FILTER,
                standard_numeric_filters={"part_start_number": {"conditions": {"match_type": "Greater Than", "value": 5}}},
                combine_with="OR",
            )
        )
        assert len(described) == 2
        assert described[1]["join"] == "BOOLEAN_AND"
        assert len(described[1]["items"]) == 2

    def test_type_filter_differs_for_parts_and_bolts(self):
        part = _describe(build_filter_expression(standard_numeric_filters={"part_start_number": {"conditions": {"match_type": "Is Equal", "value": 1}}}))
        bolt = _describe(build_filter_expression(object_type="bolt", standard_numeric_filters={"phase": {"conditions": {"match_type": "Is Equal", "value": 1}}}))
        assert part[0]["left"] == bolt[0]["left"] == "ObjectType"
        assert part[0]["value"] != bolt[0]["value"]

    def test_bolt_type_values_are_translated(self):
        expression = build_filter_expression(object_type="bolt", standard_string_filters={"bolt_type": {"conditions": {"match_type": "Is Equal", "value": "Workshop"}}})
        assert _describe(expression)[1]["items"][0]["value"] == "1"

    def test_invalid_bolt_type_value_raises(self):
        with pytest.raises(ValueError, match="Invalid bolt_type filter value"):
            build_filter_expression(object_type="bolt", standard_string_filters={"bolt_type": {"conditions": {"match_type": "Is Equal", "value": "factory"}}})

    def test_bolt_custom_attributes_use_bolt_expressions(self):
        option = {"conditions": {"match_type": "Is Equal", "value": "A"}}
        part = _describe(build_filter_expression(custom_string_filters={"COMMENT": option}))
        bolt = _describe(build_filter_expression(object_type="bolt", custom_string_filters={"COMMENT": option}))
        assert part[1]["items"][0]["left"] != bolt[1]["items"][0]["left"]

    def test_custom_string_filter_builds_string_condition(self):
        expression = build_filter_expression(custom_string_filters={"COMMENT": {"conditions": {"match_type": "Contains", "value": "007"}}})
        item = _describe(expression)[1]["items"][0]
        assert (item["op"], item["kind"], item["value"]) == ("CONTAINS", "string", "007")

    def test_every_criteria_kind_becomes_its_own_group(self):
        expression = build_filter_expression(
            standard_string_filters=self.NAME_FILTER,
            standard_numeric_filters={"class": {"conditions": {"match_type": "Is Equal", "value": 1}}},
            custom_string_filters={"COMMENT": {"conditions": {"match_type": "Contains", "value": "x"}}},
            custom_numeric_filters={"HEIGHT": {"conditions": {"match_type": "Greater Than", "value": 1}}},
        )
        assert len(_describe(expression)[1]["items"]) == 4

    def test_inputs_are_not_mutated(self):
        filters = {"bolt_type": {"conditions": {"match_type": "Is Equal", "value": "site"}}}
        snapshot = {"bolt_type": {"conditions": {"match_type": "Is Equal", "value": "site"}}}
        build_filter_expression(object_type="bolt", standard_string_filters=filters)
        assert filters == snapshot
