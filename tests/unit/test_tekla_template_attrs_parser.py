"""
Unit tests for TemplateAttributeParser.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.
"""

import os
from unittest.mock import patch

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import ReportProperty
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser


@pytest.fixture(autouse=True)
def enable_embeddings():
    """Enable embeddings for these tests that rely on semantic matching."""
    with patch("tekla_mcp_server.tekla.template_attrs_parser.is_embeddings_enabled", return_value=True):
        yield


@pytest.fixture(autouse=True)
def reset_parser():
    """Reset the parser state before each test."""
    TemplateAttributeParser._descriptions_cache = {}
    TemplateAttributeParser._embeddings_cache = {}
    TemplateAttributeParser._semantic_loaded = False
    yield
    TemplateAttributeParser._descriptions_cache = {}
    TemplateAttributeParser._embeddings_cache = {}
    TemplateAttributeParser._semantic_loaded = False


@pytest.mark.parametrize(
    "attr_name,expected_type,expected_unit",
    [
        ("ASSEMBLY_TOP_LEVEL", str, None),
        ("AREA", float, "m2"),
        ("ASSEMBLY_TOP_LEVEL_UNFORMATTED_BASEPOINT", float, "mm"),
        ("SHIPMENT_NUMBER", str, None),
    ],
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
    [
        ("weight", "WEIGHT"),
        ("total weight", "WEIGHT_TOTAL"),
        ("area", "AREA"),
        ("gross area", "AREA_GROSS"),
        ("net area", "AREA_NET"),
        ("bars total weight", "WEIGHT_TOTAL"),
        ("net weight", "WEIGHT_NET"),
        ("object height", "HEIGHT"),
        ("object length", "LENGTH"),
        ("object width", "WIDTH"),
        ("model name", "MODEL"),
        ("project address", "ADDRESS"),
        # ("assembly position", "ASSEMBLY_POS"),  # Not working well, needs more tuning
        ("if object is added to pour unit", "ADDED_TO_POUR_UNIT"),
        ("rebar assembly type", "REBAR_ASSEMBLY_TYPE"),
        # ("position number for a reinforcing bar", "REBAR_POS"),  # Not working well, needs more tuning
        ("length of threaded part of bolt shaft", "BOLT_THREAD_LENGTH"),
        ("material type", "MATERIAL_TYPE"),
        ("thickness of plate", "PLATE_THICKNESS"),
        ("torsional constant of profile", "TORSIONAL_CONSTANT"),
        ("bottom level of single part", "BOTTOM_LEVEL"),
        ("bottom level of an assembly", "ASSEMBLY_BOTTOM_LEVEL"),
    ],
)
def test_semantic_match(user_input, expected_attr):
    """Semantic matching on attribute names and descriptions."""
    rp = TemplateAttributeParser.parse(user_input)

    assert isinstance(rp, ReportProperty)
    assert rp.name == expected_attr
