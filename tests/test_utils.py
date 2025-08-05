"""
This module contains unit tests for utility functions.

Tested modules:
- utils.py: Contains utility classes and functions used for geometry manipulations.
"""

import pytest

from init import load_dlls
from utils import get_element_type_by_class, get_wall_pairs

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


@pytest.mark.parametrize(
    "input_val,expected",
    [
        ("1", ("Concrete", "WALL")),
        ("100", ("Steel", "BEAM")),
        ("101", ("Steel", "COLUMN")),
        ("999999", None),
        ("not_a_number", None),
        (None, None),
        (1, ("Concrete", "WALL")),
        ("-1", None),
    ],
)
def test_get_element_type_by_class_cases(input_val, expected):
    """
    Unit tests for `get_element_type_by_class` utility function.

    Covers:
    - Valid class strings and integers
    - Invalid, non-integer, None, and edge cases
    """
    assert get_element_type_by_class(input_val) == expected


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
