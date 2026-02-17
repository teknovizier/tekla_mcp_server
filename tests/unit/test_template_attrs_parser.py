"""
Unit tests for TemplateAttributeParser.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.
"""

import os
import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import ReportProperty
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser


@pytest.mark.parametrize(
    "attr_name,expected_type,expected_unit",
    [("ASSEMBLY_TOP_LEVEL", str, None), ("AREA", float, "m2"), ("ASSEMBLY_TOP_LEVEL_UNFORMATTED_BASEPOINT", float, "mm"), ("SHIPMENT_NUMBER", str, None)],
)
def test_parse_template_attribute(attr_name, expected_type, expected_unit):
    """Checks that `TemplateAttributeParser.parse` returns correct template attributes properties."""
    rp = TemplateAttributeParser.parse(attr_name)

    assert isinstance(rp, ReportProperty)
    assert rp.name == attr_name
    assert rp.data_type == expected_type
    assert rp.unit == expected_unit


@pytest.mark.parametrize(
    "user_input,expected_attr",
    [("weight", "WEIGHT"), ("total weight", "WEIGHT_TOTAL"), ("area", "AREA"), ("gross area", "AREA_GROSS"), ("net area", "AREA_NET")],
)
def test_parse_template_attribute_semantic_match(user_input, expected_attr):
    """Checks that `TemplateAttributeParser.parse` uses semantic matching when exact match fails."""
    rp = TemplateAttributeParser.parse(user_input)

    assert isinstance(rp, ReportProperty)
    assert rp.name == expected_attr


def test_parse_template_attribute_exact_match_takes_precedence():
    """Checks that exact match takes precedence over semantic match."""
    rp = TemplateAttributeParser.parse("WEIGHT")

    assert isinstance(rp, ReportProperty)
    assert rp.name == "WEIGHT"
