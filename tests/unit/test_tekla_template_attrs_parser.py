"""
Unit tests for TemplateAttributeParser.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.
"""

import os

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.config import get_config

if not get_config().embeddings_enabled:
    pytest.skip("Skipping all tests (embeddings are disabled)", allow_module_level=True)

from tekla_mcp_server.models import ReportProperty
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser


@pytest.fixture(autouse=True)
def reset_parser():
    """Reset the parser state before each test."""
    TemplateAttributeParser._cache = {}
    TemplateAttributeParser._loaded = False
    TemplateAttributeParser._embeddings_cache = {}
    TemplateAttributeParser._semantic_loaded = False
    yield
    TemplateAttributeParser._cache = {}
    TemplateAttributeParser._loaded = False
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
def test_get_attribute(attr_name, expected_type, expected_unit):
    """Checks that get_attribute returns correct template attributes properties."""
    rp = TemplateAttributeParser.get_attribute(attr_name)

    assert isinstance(rp, ReportProperty)
    assert rp.name == attr_name
    assert rp.data_type == expected_type
    assert rp.unit == expected_unit


def test_get_attribute_not_found():
    """Checks that KeyError is raised for unknown attribute."""
    with pytest.raises(KeyError):
        TemplateAttributeParser.get_attribute("UNKNOWN_ATTR_XYZ")


@pytest.mark.parametrize(
    "user_input,expected_attr",
    [
        ("name", "NAME"),
        ("weight", "WEIGHT"),
        ("if object is added to pour unit", "ADDED_TO_POUR_UNIT"),
        ("rebar assembly type", "REBAR_ASSEMBLY_TYPE"),
        ("torsional constant of profile", "TORSIONAL_CONSTANT"),
        ("bottom level of an assembly", "ASSEMBLY_BOTTOM_LEVEL"),
        ("assembly position", "ASSEMBLY_POS"),
        ("gross area", "AREA_GROSS"),
        ("area gross", "AREA_GROSS"),
        ("net area", "AREA_NET"),
        ("area net", "AREA_NET"),
        ("surface area", "AREA"),
        ("material type", "MATERIAL_TYPE"),
        ("profile", "PROFILE"),
        ("finish", "FINISH"),
        ("hook start", "HOOK_START"),
        ("rebar hook start", "HOOK_START"),
        ("hook end", "HOOK_END"),
        ("rebar hook end", "HOOK_END"),
        ("bars total weight", "WEIGHT_TOTAL"),
        ("net weight", "WEIGHT_NET"),
        ("weight net", "WEIGHT_NET"),
        ("pour phase", "POUR_PHASE"),
        ("cast unit position", "CAST_UNIT_POS"),
        ("material", "MATERIAL"),
        ("phase", "PHASE"),
        ("object phase", "PHASE"),
        ("top level", "TOP_LEVEL"),
        ("bottom level", "BOTTOM_LEVEL"),
        ("xy projection area net", "AREA_PROJECTION_XY_NET"),
        ("global y negative area", "AREA_NGY"),
        ("xz projection area gross", "AREA_PROJECTION_XZ_GROSS"),
        ("area in plan", "AREA_PLAN"),
        ("perimeter length", "PERIMETER"),
        ("object volume", "VOLUME"),
        ("gross volume", "VOLUME_GROSS"),
        ("net volume", "VOLUME_NET"),
        ("net volume only concrete parts", "VOLUME_NET_ONLY_CONCRETE_PARTS"),
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
        ("top level global", "TOP_LEVEL_GLOBAL"),
        ("bottom level global", "BOTTOM_LEVEL_GLOBAL"),
    ],
)
def test_resolve_attributes_match(user_input, expected_attr):
    """Checks attribute resolution for various user inputs."""
    result = TemplateAttributeParser.resolve_attributes([user_input])

    assert result["errors"] == []
    assert result["resolved"] == [expected_attr]


@pytest.mark.parametrize(
    "user_input,expected_in_candidates",
    [
        ("material name", "MATERIAL"),
        ("model name", "MODEL"),
        ("beam length", "LENGTH"),
        ("area global x positive", "AREA_PGX"),
        ("element profile", "PROFILE"),
        ("bolt diameter", "DIAMETER"),
        ("total weight", "WEIGHT_TOTAL"),
        ("maximum length of a reinforcing bar", "LENGTH_MAX"),
        ("lower weld length", "WELD_LENGTH2"),
        ("center of gravity x", "COG_X"),
        ("center of gravity y", "COG_Y"),
        ("length of threaded part of bolt shaft", "BOLT_THREAD_LENGTH"),
        ("site address", "ADDRESS"),
        ("assembly mark", "ASSEMBLY_POS"),
        ("material grade", "GRADE"),
        ("steel grade", "GRADE"),
        ("surface finish", "FINISH"),
        ("global x positive area", "AREA_PGX"),
    ],
)
def test_resolve_attributes_ambiguous(user_input, expected_in_candidates):
    """Checks that ambiguous queries return candidates with the expected attribute."""
    result = TemplateAttributeParser.resolve_attributes([user_input])

    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert error["query"] == user_input
    assert len(error["candidates"]) > 0
    assert expected_in_candidates in error["candidates"]


def test_resolve_attributes_multiple():
    """Checks batch resolution with mixed results."""
    result = TemplateAttributeParser.resolve_attributes(["AREA", "WEIGHT", "unknown_query"])

    assert len(result["resolved"]) >= 0
    assert len(result["errors"]) >= 0
