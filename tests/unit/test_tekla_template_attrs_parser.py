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
    TemplateAttributeParser._cache = {}
    TemplateAttributeParser._loaded = False
    TemplateAttributeParser._embeddings_cache = {}
    TemplateAttributeParser._semantic_loaded = False
    TemplateAttributeParser._model = None
    TemplateAttributeParser._semantic_match_cache = {}
    TemplateAttributeParser._parse_cache = {}
    yield
    TemplateAttributeParser._cache = {}
    TemplateAttributeParser._loaded = False
    TemplateAttributeParser._embeddings_cache = {}
    TemplateAttributeParser._semantic_loaded = False
    TemplateAttributeParser._model = None
    TemplateAttributeParser._semantic_match_cache = {}
    TemplateAttributeParser._parse_cache = {}


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
    """Checks that parsing returns correct template attributes properties."""
    rp = TemplateAttributeParser.parse(attr_name)

    assert isinstance(rp, ReportProperty)
    assert rp.name == attr_name
    assert rp.data_type == expected_type
    assert rp.unit == expected_unit


@pytest.mark.parametrize(
    "user_input,expected_attr",
    [
        ("name", "NAME"),
        ("object name", "NAME"),
        ("element name", "NAME"),
        ("material name", "MATERIAL"),
        ("weight", "WEIGHT"),
        ("model name", "MODEL"),
        ("if object is added to pour unit", "ADDED_TO_POUR_UNIT"),
        ("rebar assembly type", "REBAR_ASSEMBLY_TYPE"),
        ("position number for a reinforcing bar", "REBAR_POS"),
        ("length of threaded part of bolt shaft", "BOLT_THREAD_LENGTH"),
        ("torsional constant of profile", "TORSIONAL_CONSTANT"),
        ("bottom level of single part", "BOTTOM_LEVEL"),
        ("bottom level of an assembly", "ASSEMBLY_BOTTOM_LEVEL"),
        ("project address", "ADDRESS"),
        ("site address", "ADDRESS"),
        ("assembly position", "ASSEMBLY_POS"),
        ("assembly mark", "ASSEMBLY_POS"),
        ("beam length", "LENGTH"),
        ("member length", "LENGTH"),
        ("part width", "WIDTH"),
        ("object width", "WIDTH"),
        ("part height", "HEIGHT"),
        ("object height", "HEIGHT"),
        ("gross area", "AREA_GROSS"),
        ("area gross", "AREA_GROSS"),
        ("net area", "AREA_NET"),
        ("area net", "AREA_NET"),
        ("surface area", "AREA"),
        ("geometry area", "AREA"),
        ("area", "AREA"),
        ("global x positive area", "AREA_PGX"),
        ("area global x positive", "AREA_PGX"),
        ("material type", "MATERIAL_TYPE"),
        ("material grade", "GRADE"),
        ("steel grade", "GRADE"),
        ("profile", "PROFILE"),
        ("element profile", "PROFILE"),
        ("finish", "FINISH"),
        ("surface finish", "FINISH"),
        ("bolt diameter", "DIAMETER"),
        ("hook start", "HOOK_START"),
        ("rebar hook start", "HOOK_START"),
        ("hook end", "HOOK_END"),
        ("rebar hook end", "HOOK_END"),
        ("bars total weight", "WEIGHT_TOTAL"),
        ("total weight", "WEIGHT_TOTAL"),
        ("net weight", "WEIGHT_NET"),
        ("weight net", "WEIGHT_NET"),
        ("pour phase", "POUR_PHASE"),
        ("cast unit position", "CAST_UNIT_POS"),
        ("material", "MATERIAL"),
        ("material name", "MATERIAL"),
        ("phase", "PHASE"),
        ("object phase", "PHASE"),
        ("top level", "TOP_LEVEL"),
        ("bottom level", "BOTTOM_LEVEL"),
        ("maximum length of a reinforcing bar", "LENGTH_MAX"),
        ("max rebar length", "LENGTH_MAX"),
        ("lower weld length", "WELD_LENGTH2"),
        ("global x positive area", "AREA_PGX"),
        ("global y negative area", "AREA_NGY"),
        ("xy projection area net", "AREA_PROJECTION_XY_NET"),
        ("xz projection area gross", "AREA_PROJECTION_XZ_GROSS"),
        ("area in plan", "AREA_PLAN"),
        ("gross area", "AREA_GROSS"),
        ("net area", "AREA_NET"),
        ("perimeter length", "PERIMETER"),
        ("object volume", "VOLUME"),
        ("gross volume", "VOLUME_GROSS"),
        ("net volume", "VOLUME_NET"),
        ("net volume only concrete parts", "VOLUME_NET_ONLY_CONCRETE_PARTS"),
        ("center of gravity x", "COG_X"),
        ("center of gravity y", "COG_Y"),
        ("center of gravity z", "COG_Z"),
        ("bounding box max x", "BOUNDING_BOX_MAX_X"),
        ("bounding box min y", "BOUNDING_BOX_MIN_Y"),
        ("bounding box max z", "BOUNDING_BOX_MAX_Z"),
        ("web thickness", "WEB_THICKNESS"),
        ("thickness of web", "WEB_THICKNESS"),
        ("flange thickness", "FLANGE_THICKNESS"),
        ("plate thickness", "PLATE_THICKNESS"),
        ("thickness of plate", "PLATE_THICKNESS"),
        ("diameter", "DIAMETER"),
        ("inner diameter", "INNER_DIAMETER"),
        ("object length", "LENGTH"),
        ("object width", "WIDTH"),
        ("object height", "HEIGHT"),
        ("top level global", "TOP_LEVEL_GLOBAL"),
        ("bottom level global", "BOTTOM_LEVEL_GLOBAL")
    ],
)
def test_parse_template_attribute_match(user_input, expected_attr):
    """Checks the parsing of template attributes."""
    rp = TemplateAttributeParser.parse(user_input)

    assert isinstance(rp, ReportProperty)
    assert rp.name == expected_attr
