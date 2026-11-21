"""
Unit tests for selection provider helpers.

The provider imports the Tekla loader, which loads the Tekla DLLs, so these tests
are skipped in CI environments where Tekla is not available. The tool itself is
covered by the functional tests.
"""

import importlib
import os

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import FilterCondition, FilterGroup

sp = importlib.import_module("tekla_mcp_server.providers.selection_provider")


def _condition(**data) -> FilterCondition:
    """Validate keyword arguments as a filter condition."""
    return FilterCondition.model_validate(data)


class TestExpandElementType:
    @pytest.fixture
    def wall_classes(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: [1, 8, 1])

    def test_is_equal_becomes_one_class_list(self, wall_classes):
        condition = sp._expand_element_type(_condition(field="part.element_type", op="Is Equal", value="Wall"))
        assert (condition.field, condition.op, condition.value) == ("part.class", "Is Equal", [1, 8])

    def test_is_not_equal_keeps_its_operator(self, wall_classes):
        assert sp._expand_element_type(_condition(field="part.element_type", op="Is Not Equal", value="Wall")).op == "Is Not Equal"

    def test_type_list_merges_classes(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: {"Wall": [1], "Sandwich Wall": [8, 52, 1]}[element_type])
        condition = sp._expand_element_type(_condition(field="part.element_type", op="Is Equal", value=["Wall", "Sandwich Wall"]))
        assert condition.value == [1, 8, 52]

    def test_type_without_classes_raises(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: [])
        with pytest.raises(ValueError, match="no Tekla classes configured"):
            sp._expand_element_type(_condition(field="part.element_type", op="Is Equal", value="Wall"))

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Invalid element_type"):
            sp._expand_element_type(_condition(field="part.element_type", op="Is Equal", value="NotAType"))


class TestPrepareTree:
    def test_element_type_is_expanded_in_nested_groups(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: [1])
        tree = FilterGroup.model_validate({"any": [{"all": [{"field": "part.element_type", "op": "Is Equal", "value": "Wall"}]}, {"attribute": "comment", "op": "Is Equal", "value": "x"}]})
        prepared = sp._prepare_tree(tree)
        assert prepared.is_any
        expanded_group, attribute = prepared.items
        assert (expanded_group.items[0].field, expanded_group.items[0].value) == ("part.class", [1])
        # Attribute names are kept exactly, case included
        assert attribute.attribute == "comment"
        # The caller's tree is left as it was
        assert tree.items[0].items[0].field == "part.element_type"

    def test_plain_condition_is_kept(self):
        condition = _condition(field="part.name", op="Is Equal", value="A")
        assert sp._prepare_tree(condition) is condition
