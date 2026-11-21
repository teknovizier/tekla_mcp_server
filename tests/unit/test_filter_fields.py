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
    OBJECT_TYPES,
    OPS_BY_KIND,
    VALUE_OPS,
    WELD_TYPES,
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
