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

from tekla_mcp_server.filter_fields import OBJECT_TYPES
from tekla_mcp_server.models import FilterCondition, FilterGroup, NumericFilterOption, NumericMatchType, StringFilterOption, StringMatchType
from tekla_mcp_server.tekla.filter_builder import (
    NUMERIC_MATCH_TYPE_MAPPING,
    STRING_MATCH_TYPE_MAPPING,
    _parse_numeric_string,
    add_filter,
    build_filter_expression,
    to_filter_option,
)
from tekla_mcp_server.tekla.loader import (
    BinaryFilterExpressionCollection,
    BinaryFilterOperatorType,
    NumericOperatorType,
    ObjectFilterExpressions,
    PartFilterExpressions,
    TeklaStructuresDatabaseTypeEnum,
)

# The loader import has initialized pythonnet, so the System namespace is importable now
from System.Reflection import BindingFlags  # noqa: E402

_CONSTANT_KINDS = {
    "StringConstantFilterExpression": "string",
    "NumericConstantFilterExpression": "numeric",
    "BooleanConstantFilterExpression": "boolean",
    "DateTimeConstantFilterExpression": "date",
}

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
                kind=_CONSTANT_KINDS[right.GetType().Name],
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


PART_TYPE = str(int(TeklaStructuresDatabaseTypeEnum.PART))
BOLT_TYPE = str(int(TeklaStructuresDatabaseTypeEnum.BOLT))
REBAR_TYPE = str(int(TeklaStructuresDatabaseTypeEnum.REBAR))


def _tree(node: dict[str, Any]) -> FilterGroup | FilterCondition:
    """
    Validate a plain dict as a filter group or condition.

    Args:
        node: Group dict with 'all' or 'any', or a condition dict

    Returns:
        The validated model
    """
    return FilterGroup.model_validate(node) if "all" in node or "any" in node else FilterCondition.model_validate(node)


def _expression(node: dict[str, Any], object_types: list[str] | None = None) -> Any:
    """
    Build a tree into a Tekla expression.

    Args:
        node: Filter tree as a plain dict
        object_types: Object types, 'part' when omitted

    Returns:
        The built `BinaryFilterExpressionCollection`
    """
    return build_filter_expression(_tree(node), object_types or ["part"])


def _build(node: dict[str, Any], object_types: list[str] | None = None) -> list[dict[str, Any]]:
    """
    Build a tree and describe the result.

    Args:
        node: Filter tree as a plain dict
        object_types: Object types, 'part' when omitted

    Returns:
        `_describe` output of the built expression
    """
    return _describe(_expression(node, object_types))


def _properties(expression: Any) -> list[str]:
    """
    Return the values of an expression's non-public `Properties` dictionary.

    Args:
        expression: Left-hand side filter expression

    Returns:
        The stored values as strings, e.g. a custom attribute name
    """
    return [str(v) for v in _get(expression, "Properties").Values]


def _cond(field: str, op: str, value: Any) -> dict[str, Any]:
    """
    Build a condition dict.

    Args:
        field: Catalog field name
        op: Operator
        value: Value

    Returns:
        Condition dict
    """
    return {"field": field, "op": op, "value": value}


A = _cond("part.name", "Is Equal", "A")
B = _cond("part.class", "Is Equal", 1)
C = _cond("part.profile", "Is Equal", "C")
D = _cond("part.material", "Is Equal", "D")


class TestBuildFilterExpressionObjectTypes:
    def test_single_type_is_a_flat_first_item(self):
        described = _build(A)
        assert (described[0]["left"], described[0]["value"], described[0]["join"]) == ("ObjectType", PART_TYPE, "BOOLEAN_AND")

    def test_several_types_are_one_list_row_without_duplicates(self):
        described = _build(_cond("object.phase", "Is Equal", 1), ["part", "bolt", "part"])
        assert (described[0]["left"], described[0]["value"]) == ("ObjectType", f"{PART_TYPE}{BOLT_TYPE}")

    def test_no_type_raises(self):
        with pytest.raises(ValueError, match="At least one object type"):
            build_filter_expression(_tree(A), [])

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match=r"Unknown object types \['beam'\]"):
            build_filter_expression(_tree(A), ["beam"])

    @pytest.mark.parametrize("object_type", ["part", "assembly", "rebar", "bolt", "weld", "component", "reference_object", "pour_object", "pour_break", "pour_unit", "surface"])
    def test_every_object_type_builds(self, object_type):
        assert _build(_cond("object.phase", "Is Equal", 1), [object_type])[0]["left"] == "ObjectType"


class TestBuildFilterExpressionStructure:
    def test_root_all_items_are_inlined(self):
        described = _build({"all": [A, B]})
        assert [(d.get("value"), d["join"]) for d in described] == [(PART_TYPE, "BOOLEAN_AND"), ("A", "BOOLEAN_AND"), ("1", "BOOLEAN_AND")]

    def test_root_any_repeats_the_type_in_each_alternative(self):
        assert _chains(_build({"any": [A, B]})) == [[("ObjectType", PART_TYPE), ("Part.Name", "A")], [("ObjectType", PART_TYPE), ("Part.Class", "1")]]

    def test_same_kind_groups_are_merged(self):
        described = _build({"all": [{"all": [A]}, {"all": [B, {"all": [C]}]}]})
        assert [d.get("value") for d in described] == [PART_TYPE, "A", "1", "C"]

    def test_single_item_any_is_unwrapped(self):
        assert [d.get("value") for d in _build({"any": [A]})] == [PART_TYPE, "A"]

    def test_all_inside_any_needs_no_brackets(self):
        assert _chains(_build({"any": [A, {"all": [B, C]}]})) == [
            [("ObjectType", PART_TYPE), ("Part.Name", "A")],
            [("ObjectType", PART_TYPE), ("Part.Class", "1"), ("Part.Profile", "C")],
        ]

    def test_any_inside_all_keeps_its_brackets(self):
        assert _chains(_build({"all": [A, {"any": [B, {"all": [C, D]}]}]})) == [
            [("ObjectType", PART_TYPE), ("Part.Name", "A"), ("(", [[("Part.Class", "1")], [("Part.Profile", "C"), ("Part.Material", "D")]])]
        ]

    def test_three_levels_are_allowed(self):
        deep = {"all": [A, {"any": [B, {"all": [C, {"any": [D, A]}]}]}]}
        inner = _chains(_build(deep))[0][2][1]
        assert inner[1][1] == ("(", [[("Part.Material", "D")], [("Part.Name", "A")]])

    def test_four_levels_raise(self):
        deeper = {"all": [A, {"any": [B, {"all": [C, {"any": [D, {"all": [A, {"any": [B, C]}]}]}]}]}]}
        with pytest.raises(ValueError, match="nests 4 levels of brackets, but Tekla allows at most 3"):
            _build(deeper)

    @pytest.mark.parametrize(
        "field,op,value,expected_op,kind",
        [
            ("part.profile", "Starts With", "HEA", "STARTS_WITH", "string"),
            ("part.class", "Greater Or Equal", 10, "GREATER_OR_EQUAL", "numeric"),
            ("rebar.diameter", "Smaller Than", 12.5, "SMALLER_THAN", "numeric"),
            ("part.position_number", "Is Equal", "007", "IS_EQUAL", "string"),
        ],
    )
    def test_field_operators_and_kinds(self, field, op, value, expected_op, kind):
        condition = _build(_cond(field, op, value), [field.split(".")[0]])[1]
        assert (condition["op"], condition["kind"], condition["value"]) == (expected_op, kind, str(value))

    def test_assembly_start_number_uses_report_property(self):
        condition = list(_expression(_cond("assembly.start_number", "Greater Than", 50)))[1]
        assert "ASSEMBLY_START_NUMBER" in _properties(_get(_get(condition, "FilterExpression"), "Left"))

    def test_expanded_field_must_not_reach_builder(self):
        with pytest.raises(ValueError, match="must be expanded"):
            _build(_cond("part.element_type", "Is Equal", "Wall"))


class TestBuildFilterExpressionValues:
    @pytest.mark.parametrize(
        "field,value,expected",
        [
            ("bolt.site_workshop", "Site", "0"),
            ("bolt.site_workshop", "workshop", "1"),
            ("weld.welding_site", "workshop", "1"),
            ("weld.type_above", "fillet", "10"),
            ("weld.type_below", "none", "0"),
            ("part.primary_part", "yes", "1"),
        ],
    )
    def test_readable_values_are_mapped(self, field, value, expected):
        assert _build(_cond(field, "Is Equal", value), [field.split(".")[0]])[1]["value"] == expected

    def test_numeric_coded_value_builds_numeric_condition(self):
        assert _build(_cond("weld.type_above", "Is Not Equal", "fillet"), ["weld"])[1]["kind"] == "numeric"

    def test_string_coded_value_builds_string_condition(self):
        assert _build(_cond("bolt.site_workshop", "Is Equal", "site"), ["bolt"])[1]["kind"] == "string"


class TestBuildFilterExpressionAttributes:
    @pytest.mark.parametrize(
        "value,extra,kind",
        [(2000, {}, "numeric"), (2.5, {}, "numeric"), ("A1", {}, "string"), (True, {}, "boolean"), ("2026-01-31", {"type": "date"}, "date")],
    )
    def test_attribute_kind_follows_value(self, value, extra, kind):
        op = "Is Equal"
        assert _build({"attribute": "MY_UDA", "op": op, "value": value, **extra})[1]["kind"] == kind

    def test_attribute_name_is_used_as_given(self):
        condition = list(_expression({"attribute": "MCP_TEST_UDA", "category": "assembly", "op": "Contains", "value": "x"}))[1]
        assert "MCP_TEST_UDA" in _properties(_get(_get(condition, "FilterExpression"), "Left"))

    @pytest.mark.parametrize("op,expected", [("Earlier Than", "EARLIER_THAN"), ("Later Or Equal", "LATER_OR_EQUAL")])
    def test_date_operators(self, op, expected):
        assert _build({"attribute": "MY_DATE", "op": op, "value": "2026-01-31T08:30:00", "type": "date"})[1]["op"] == expected

    def test_boolean_operator(self):
        condition = _build({"attribute": "MY_FLAG", "op": "Is Not Equal", "value": False})[1]
        assert (condition["op"], condition["kind"]) == ("IS_NOT_EQUAL", "boolean")


WELD_TYPE = str(int(TeklaStructuresDatabaseTypeEnum.WELDING))
ASSEMBLY_TYPE = str(int(TeklaStructuresDatabaseTypeEnum.ASSEMBLY))
BOLT_16 = _cond("bolt.size", "Is Equal", 16)


def _chains(described: list[dict[str, Any]]) -> list[list[tuple[Any, Any]]]:
    """
    Split described items into OR-joined chains of AND-joined items.

    Args:
        described: `_describe` output of one collection

    Returns:
        One list per chain with (left, value) of each condition, or ('(', chains) for a bracketed group
    """
    chains: list[list[tuple[Any, Any]]] = []
    current: list[tuple[Any, Any]] = []
    for item in described:
        current.append(("(", _chains(item["items"])) if "items" in item else (item.get("left"), item.get("value")))
        if item["join"] == "BOOLEAN_OR":
            chains.append(current)
            current = []
    chains.append(current)
    return chains


def _branches(node: dict[str, Any], object_types: list[str]) -> list[list[tuple[Any, Any]]]:
    """
    Build a tree with several object type branches and return the chains.

    Args:
        node: Filter tree as a plain dict
        object_types: Object types that give different branches

    Returns:
        One list per chain with (left, value) of each item
    """
    return _chains(_build(node, object_types))


class TestObjectTypeCodes:
    @pytest.mark.parametrize(
        "name,member",
        [
            ("part", "PART"),
            ("assembly", "ASSEMBLY"),
            ("rebar", "REBAR"),
            ("bolt", "BOLT"),
            ("weld", "WELDING"),
            ("component", "COMPONENT"),
            ("reference_object", "FOREIGN_OBJECT"),
            ("pour_object", "DB_POUR_OBJECT"),
            ("pour_break", "DB_POUR_BREAK"),
            ("pour_unit", "DB_POUR_UNIT"),
            ("surface", "SURFACE_OBJECT"),
        ],
    )
    def test_codes_match_the_database_enum(self, name, member):
        assert OBJECT_TYPES[name] == int(getattr(TeklaStructuresDatabaseTypeEnum, member))


class TestBuildFilterExpressionTypeSemantics:
    def test_same_meaning_for_all_types_is_one_branch_with_a_type_list(self):
        described = _build(_cond("assembly.prefix", "Is Equal", "B"), ["part", "bolt"])
        assert [(d.get("left"), d.get("value")) for d in described] == [("ObjectType", f"{PART_TYPE}\x02{BOLT_TYPE}"), ("Assembly.Prefix", "B")]

    def test_condition_of_another_type_drops_out_of_any(self):
        assert _branches({"any": [A, BOLT_16]}, ["part", "bolt"]) == [[("ObjectType", PART_TYPE), ("Part.Name", "A")], [("ObjectType", BOLT_TYPE), ("BoltSize", "16")]]

    def test_type_without_own_conditions_raises_instead_of_being_selected_whole(self):
        with pytest.raises(ValueError, match=r"applies to the object types \['bolt'\]"):
            _build({"all": [A]}, ["part", "bolt"])

    def test_mixed_and_chain_filters_each_type_by_its_own_conditions(self):
        rebar_class = _cond("rebar.class", "Is Equal", [44, 46])
        part_class = _cond("part.class", "Is Not Equal", [66, 107])
        assert _branches({"all": [rebar_class, part_class]}, ["rebar", "part"]) == [
            [("ObjectType", REBAR_TYPE), ("ReinforcingBarClass", "44\x0246")],
            [("ObjectType", PART_TYPE), ("Part.Class", "66\x02107")],
        ]

    @pytest.mark.parametrize("object_types", [["bolt"], ["assembly"]])
    def test_condition_of_an_unselected_type_raises_instead_of_selecting_the_whole_type(self, object_types):
        with pytest.raises(ValueError, match="would match all of them"):
            _build(_cond("part.profile", "Is Equal", "HEA300"), object_types)

    def test_object_type_condition_selects_a_whole_type(self):
        node = {"any": [_cond("object.type", "Is Equal", "weld"), _cond("part.class", "Is Equal", 999999)]}
        assert _branches(node, ["part", "weld"]) == [[("ObjectType", PART_TYPE), ("Part.Class", "999999")], [("ObjectType", WELD_TYPE)]]

    def test_object_type_not_equal_excludes_a_type(self):
        assert [d.get("value") for d in _build(_cond("object.type", "Is Not Equal", "part"), ["part", "bolt"])] == [BOLT_TYPE]

    def test_object_type_list(self):
        assert [d.get("value") for d in _build(_cond("object.type", "Is Equal", ["part", "weld"]), ["part", "bolt", "weld"])] == [f"{PART_TYPE}\x02{WELD_TYPE}"]

    def test_object_type_that_excludes_every_type_raises(self):
        with pytest.raises(ValueError, match="can match this filter"):
            _build(_cond("object.type", "Is Equal", "bolt"), ["part"])

    def test_report_property_applies_to_every_type(self):
        node = {"attribute": "MAINPART.CLASS_ATTR", "category": "template", "op": "Is Equal", "value": [18, 23]}
        described = _build(node, ["part", "assembly"])
        assert [d.get("value") for d in described] == [f"{PART_TYPE}\x02{ASSEMBLY_TYPE}", "18\x0223"]
        assert described[1]["left"] == "TemplateCustomNumber"

    def test_reduced_any_branch_is_spread_into_chains(self):
        # For parts the tree reduces to any[A, B], which needs no brackets once spread out
        assert _branches({"all": [{"any": [A, B]}, BOLT_16]}, ["part", "bolt"]) == [
            [("ObjectType", PART_TYPE), ("Part.Name", "A")],
            [("ObjectType", PART_TYPE), ("Part.Class", "1")],
            [("ObjectType", BOLT_TYPE), ("BoltSize", "16")],
        ]

    def test_any_inside_a_branch_all_keeps_one_level(self):
        node = {"all": [C, {"any": [A, B]}, BOLT_16]}
        assert _branches(node, ["part", "bolt"]) == [
            [("ObjectType", PART_TYPE), ("Part.Profile", "C"), ("(", [[("Part.Name", "A")], [("Part.Class", "1")]])],
            [("ObjectType", BOLT_TYPE), ("BoltSize", "16")],
        ]

    def test_branch_with_and_chain_fits(self):
        assert _branches({"any": [{"all": [A, B]}, BOLT_16]}, ["part", "bolt"])[0] == [("ObjectType", PART_TYPE), ("Part.Name", "A"), ("Part.Class", "1")]

    def test_any_branch_repeats_its_type(self):
        node = {"any": [A, B, BOLT_16]}
        assert _branches(node, ["part", "bolt"]) == [
            [("ObjectType", PART_TYPE), ("Part.Name", "A")],
            [("ObjectType", PART_TYPE), ("Part.Class", "1")],
            [("ObjectType", BOLT_TYPE), ("BoltSize", "16")],
        ]


class TestBuildFilterExpressionLists:
    def test_numeric_list_is_one_row(self):
        assert _build(_cond("part.class", "Is Equal", [18, 23, 31]))[1]["value"] == "18\x0223\x0231"

    def test_float_list(self):
        assert _build(_cond("rebar.diameter", "Is Equal", [10, 12.5]), ["rebar"])[1]["value"] == "10\x0212.5"

    def test_negative_list_keeps_its_operator(self):
        condition = _build(_cond("part.class", "Is Not Equal", [1, 8]))[1]
        assert (condition["op"], condition["value"]) == ("IS_NOT_EQUAL", "1\x028")

    def test_string_list_quotes_items_with_spaces(self):
        # Tekla stores the separating and the quoted spaces as \x02, like its own filter files
        assert _build(_cond("part.name", "Is Equal", ["WALL PLATE", "BRV?-*"]))[1]["value"] == '"WALL\x02PLATE"\x02BRV?-*'

    def test_readable_value_list_is_mapped(self):
        assert _build(_cond("weld.type_above", "Is Equal", ["fillet", "plug"]), ["weld"])[1]["value"] == "10\x0211"

    def test_attribute_list(self):
        condition = _build({"attribute": "COMMENT", "op": "Contains", "value": ["A", "B"]})[1]
        assert (condition["kind"], condition["value"]) == ("string", "A\x02B")


class TestQuoting:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("LIGHTWEIGHT BLOCK", '"LIGHTWEIGHT\x02BLOCK"'),
            ('"ALREADY QUOTED"', '"ALREADY\x02QUOTED"'),
            ("NOSPACE", "NOSPACE"),
            ("TAB\tSEP", '"TAB\tSEP"'),
            ("BRW*[1234567]-12*", "BRW*[1234567]-12*"),
        ],
    )
    def test_values_with_spaces_are_quoted(self, value, expected):
        assert _build(_cond("part.name", "Is Equal", value))[1]["value"] == expected
