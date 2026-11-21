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

sp = importlib.import_module("tekla_mcp_server.providers.selection_provider")


class TestResolveClassCriteria:
    @pytest.fixture
    def wall_classes(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: [1, 2, 1])

    def test_nothing_given_gives_no_classes(self):
        assert sp._resolve_class_criteria(None, [], "AND") == []

    def test_empty_element_type_string_is_ignored(self):
        assert sp._resolve_class_criteria("", [4], "AND") == [4]

    def test_classes_only_are_deduplicated(self):
        assert sp._resolve_class_criteria(None, [8, 8, 3], "AND") == [8, 3]

    def test_element_type_only(self, wall_classes):
        assert sp._resolve_class_criteria("Wall", [], "AND") == [1, 2]

    def test_and_keeps_shared_classes(self, wall_classes):
        assert sp._resolve_class_criteria("Wall", [2, 9, 2], "AND") == [2]

    def test_or_keeps_all_classes_once(self, wall_classes):
        assert sp._resolve_class_criteria("Wall", [2, 9, 9], "OR") == [1, 2, 9]

    def test_and_without_shared_class_raises(self, wall_classes):
        with pytest.raises(ValueError, match="no class in common"):
            sp._resolve_class_criteria("Wall", [9], "AND")

    def test_element_type_without_classes_raises(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: [])
        with pytest.raises(ValueError, match="no Tekla classes configured"):
            sp._resolve_class_criteria("Wall", [], "OR")

    def test_invalid_element_type_raises(self):
        with pytest.raises(ValueError, match="Invalid element_type"):
            sp._resolve_class_criteria("NotAType", [1], "OR")


class TestClassFilterOption:
    def test_one_or_condition_per_class(self):
        option = sp._class_filter_option([1, 8])
        assert option.logic == "OR"
        assert [(c.match_type, c.value) for c in option.conditions] == [("Is Equal", 1), ("Is Equal", 8)]


class TestResolveCustomFilters:
    def test_empty_input_skips_resolution(self, monkeypatch):
        monkeypatch.setattr(sp.TemplateAttributeParser, "resolve_attributes", lambda queries: pytest.fail("must not resolve"))
        assert sp._resolve_custom_filters({}) == ({}, [])

    def test_failed_query_does_not_shift_names(self, monkeypatch):
        error = {"query": "bad", "message": "not found"}
        monkeypatch.setattr(sp.TemplateAttributeParser, "resolve_attributes", lambda queries: {"resolved": ["HEIGHT", "WIDTH"], "errors": [error]})
        assert sp._resolve_custom_filters({"height": "h", "bad": "b", "width": "w"}) == ({"HEIGHT": "h", "WIDTH": "w"}, [error])

    def test_all_names_fail(self, monkeypatch):
        errors = [{"query": "a", "message": "not found"}, {"query": "b", "message": "not found"}]
        monkeypatch.setattr(sp.TemplateAttributeParser, "resolve_attributes", lambda queries: {"resolved": [], "errors": errors})
        assert sp._resolve_custom_filters({"a": 1, "b": 2}) == ({}, errors)

    def test_empty_resolved_name_is_dropped(self, monkeypatch):
        monkeypatch.setattr(sp.TemplateAttributeParser, "resolve_attributes", lambda queries: {"resolved": ["", "WIDTH"], "errors": []})
        assert sp._resolve_custom_filters({"a": 1, "width": 2}) == ({"WIDTH": 2}, [])

    def test_names_resolving_to_one_attribute_keep_the_last(self, monkeypatch):
        monkeypatch.setattr(sp.TemplateAttributeParser, "resolve_attributes", lambda queries: {"resolved": ["HEIGHT", "HEIGHT"], "errors": []})
        assert sp._resolve_custom_filters({"height": "first", "Height": "second"}) == ({"HEIGHT": "second"}, [])
