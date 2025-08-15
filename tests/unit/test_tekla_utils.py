"""
Unit tests for Tekla utility functions.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.

Tested modules:
- tekla_utils.py
"""

import os
import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from models import ReportProperty
from tekla_utils import _template_attribute_cache, get_wall_pairs, parse_template_attribute
from init import load_dlls

# Tekla OpenAPI imports
load_dlls()
from Tekla.Structures.Model import Beam


def mock_beam(x, y, z, name="TEST_WALL"):
    """Helper for mocking beams."""
    beam = Beam()
    beam.StartPoint.X = x
    beam.StartPoint.Y = y
    beam.StartPoint.Z = z
    beam.EndPoint.X = x
    beam.EndPoint.Y = y
    beam.EndPoint.Z = z
    beam.Name = name
    return beam


def test_pair_two_matching_walls():
    """Checks pairing of two matching walls."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    wall2 = mock_beam(0, 0, 3000, "TEST_WALL2")
    result = get_wall_pairs([wall1, wall2])
    assert result == [(wall1, wall2)]


def test_pair_multiple_walls():
    """Checks pairing of multiple wall pairs."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    wall2 = mock_beam(0, 0, 3000, "TEST_WALL2")
    wall3 = mock_beam(5000, 0, 0, "TEST_WALL3")
    wall4 = mock_beam(5000, 0, 3000, "TEST_WALL4")
    result = get_wall_pairs([wall1, wall2, wall3, wall4])
    assert (wall1, wall2) in result
    assert (wall3, wall4) in result
    assert len(result) == 2


def test_less_than_two_elements_raises_error():
    """Checks error for less than two elements."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    with pytest.raises(ValueError):
        get_wall_pairs([wall1])


def test_more_than_two_floors_raises_error():
    """Checks error for more than two floors."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    wall2 = mock_beam(0, 0, 3000, "TEST_WALL2")
    wall3 = mock_beam(0, 0, 6000, "TEST_WALL3")
    with pytest.raises(ValueError):
        get_wall_pairs([wall1, wall2, wall3])


def test_z_coordinate_mismatch_raises_error():
    """Checks error for Z coordinate mismatch."""
    wall = mock_beam(0, 0, 0, "TEST_WALL")
    wall.EndPoint.Z = 100  # mismatch
    with pytest.raises(ValueError):
        get_wall_pairs([wall, wall])


def test_non_beam_objects_are_ignored():
    """Checks that non-beam objects are ignored."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    wall2 = mock_beam(0, 0, 3000, "TEST_WALL2")
    not_beam = object()
    result = get_wall_pairs([wall1, wall2, not_beam])
    assert result == [(wall1, wall2)]


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the attribute cache before and after each test."""
    _template_attribute_cache.clear()
    yield
    _template_attribute_cache.clear()


@pytest.mark.parametrize(
    "attr_name,expected_type,expected_unit",
    [("ASSEMBLY_TOP_LEVEL", str, None), ("AREA", float, "m2"), ("ASSEMBLY_TOP_LEVEL_UNFORMATTED_BASEPOINT", float, "mm"), ("SHIPMENT_NUMBER", str, None)],
)
def test_parse_template_attribute(attr_name, expected_type, expected_unit):
    """Checks that `parse_template_attribute` returns correct template attributes properties."""
    rp = parse_template_attribute(attr_name)

    assert isinstance(rp, ReportProperty)
    assert rp.name == attr_name
    assert rp.data_type == expected_type
    assert rp.unit == expected_unit
