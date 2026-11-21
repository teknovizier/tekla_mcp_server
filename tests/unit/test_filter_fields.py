"""
Unit tests for the filter field catalog.

The catalog is pure data, so these tests run in CI.
"""

import pytest

from tekla_mcp_server.filter_fields import (
    CATEGORIES,
    CATEGORY_OBJECT_TYPES,
    CUSTOM_MEMBERS,
    FIELDS,
    FILTER_FILE_EXTENSIONS,
    MAX_FILTER_NAME_LENGTH,
    OBJECT_TYPES,
    OPS_BY_KIND,
    VALUE_OPS,
    WELD_TYPES,
    normalize_filter_name,
)


class TestFields:
    @pytest.mark.parametrize("name", sorted(FIELDS))
    def test_field_is_well_formed(self, name):
        spec = FIELDS[name]
        category = name.split(".")[0]
        assert category in CATEGORIES
        assert spec.kind in OPS_BY_KIND
        assert spec.description
        # The report property fields go through the template category, every other field through its own
        if spec.argument is None:
            assert spec.expression_class == CATEGORIES[category]
        else:
            assert spec.expression_class == "TemplateFilterExpressions"

    @pytest.mark.parametrize("name", [n for n, s in FIELDS.items() if s.values])
    def test_readable_values_fit_the_kind(self, name):
        spec = FIELDS[name]
        expected_type = int if spec.kind == "numeric" else str
        assert all(isinstance(v, expected_type) for v in spec.values.values())
        assert all(word == word.lower() for word in spec.values)
        assert spec.ops == VALUE_OPS

    def test_ops_follow_the_kind_without_values(self):
        assert FIELDS["part.name"].ops == OPS_BY_KIND["string"]
        assert FIELDS["part.class"].ops == OPS_BY_KIND["numeric"]

    def test_expanded_field_takes_equality_only(self):
        assert FIELDS["part.element_type"].ops == VALUE_OPS

    def test_assembly_numbers_use_report_properties(self):
        assert FIELDS["assembly.start_number"].argument == "ASSEMBLY_START_NUMBER"
        assert FIELDS["assembly.phase"].argument == "ASSEMBLY.PHASE"
        assert FIELDS["assembly.phase"].kind == "numeric"

    def test_weld_types_have_unique_codes(self):
        assert len(set(WELD_TYPES.values())) == len(WELD_TYPES)


class TestCategories:
    def test_every_kind_has_a_custom_member(self):
        assert set(CUSTOM_MEMBERS) == set(OPS_BY_KIND)

    def test_guarded_categories_map_to_object_types(self):
        assert set(CATEGORY_OBJECT_TYPES) <= set(CATEGORIES)
        assert set(CATEGORY_OBJECT_TYPES.values()) <= set(OBJECT_TYPES)

    @pytest.mark.parametrize("category", ["assembly", "object"])
    def test_cross_type_categories_are_not_guarded(self, category):
        assert category not in CATEGORY_OBJECT_TYPES

    def test_weld_uses_the_welding_database_code(self):
        assert OBJECT_TYPES["weld"] == 13

    def test_template_category_is_for_report_properties(self):
        assert CATEGORIES["template"] == "TemplateFilterExpressions"
        assert "template" not in CATEGORY_OBJECT_TYPES

    def test_object_type_field_offers_every_object_type(self):
        assert FIELDS["object.type"].values == OBJECT_TYPES


class TestNormalizeFilterName:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("MCP_TEST_FILTER", "MCP_TEST_FILTER"),
            ("  padded  ", "padded"),
            ("#WALLS [COLD BENDED] ~x+y", "#WALLS [COLD BENDED] ~x+y"),
            ("with.SObjGrp", "with"),
            ("with.sobjgrp", "with"),
            ("dotted.name", "dotted.name"),
            ("CON", "CON"),
            ("A" * MAX_FILTER_NAME_LENGTH, "A" * MAX_FILTER_NAME_LENGTH),
        ],
    )
    def test_valid_names(self, name, expected):
        assert normalize_filter_name(name, "selection") == expected

    def test_view_extension_is_dropped_for_view_filters(self):
        assert normalize_filter_name("walls.VObjGrp", "view") == "walls"

    @pytest.mark.parametrize("name,filter_type", [("walls.VObjGrp", "selection"), ("walls.vobjgrp", "selection"), ("walls.SObjGrp", "view"), ("x.SObjGrp.VObjGrp", "selection")])
    def test_other_type_extension_is_rejected(self, name, filter_type):
        with pytest.raises(ValueError, match="filter extension"):
            normalize_filter_name(name, filter_type)

    @pytest.mark.parametrize(
        "name,message",
        [
            ("", "must not be empty"),
            ("   ", "must not be empty"),
            (".SObjGrp", "must not be empty"),
            ("A" * (MAX_FILTER_NAME_LENGTH + 1), "at most"),
            ("sub/dir", "without folders or a drive"),
            ("sub\\dir", "without folders or a drive"),
            ("..\\escape", "without folders or a drive"),
            ("C:name", "without folders or a drive"),
            ("C:\\abs\\name", "without folders or a drive"),
        ],
    )
    def test_invalid_names(self, name, message):
        with pytest.raises(ValueError, match=message):
            normalize_filter_name(name, "selection")

    def test_extensions_per_type(self):
        assert FILTER_FILE_EXTENSIONS == {"selection": ".SObjGrp", "view": ".VObjGrp"}
