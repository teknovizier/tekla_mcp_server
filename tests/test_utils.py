"""
This module contains unit tests for utility functions.

Tested modules:
- utils.py: Contains utility classes and functions used for geometry manipulations.
"""

import unittest

from init import load_dlls
from utils import get_element_type_by_class, get_wall_pairs

# Tekla OpenAPI imports
load_dlls()
from Tekla.Structures.Model import Beam


class TestGetElementTypeByClass(unittest.TestCase):
    """
    Unit tests for `get_element_type_by_class` utility function.
    """

    def test_valid_concrete_wall(self):
        """Should return ("Concrete", "WALL") for class 1."""
        self.assertEqual(get_element_type_by_class("1"), ("Concrete", "WALL"))

    def test_valid_steel_beam(self):
        """Should return ("Steel", "BEAM") for class 100."""
        self.assertEqual(get_element_type_by_class("100"), ("Steel", "BEAM"))

    def test_valid_steel_column(self):
        """Should return ("Steel", "COLUMN") for class 101."""
        self.assertEqual(get_element_type_by_class("101"), ("Steel", "COLUMN"))

    def test_invalid_class_number(self):
        """Should return None for an unknown class number."""
        self.assertIsNone(get_element_type_by_class("999999"))

    def test_non_integer_input(self):
        """Should return None for non-integer input."""
        self.assertIsNone(get_element_type_by_class("not_a_number"))

    def test_none_input(self):
        """Should return None for None input."""
        self.assertIsNone(get_element_type_by_class(None))

    def test_integer_input(self):
        """Should work with integer input."""
        self.assertEqual(get_element_type_by_class(1), ("Concrete", "WALL"))

    def test_negative_class_number(self):
        """Should return None for negative class number."""
        self.assertIsNone(get_element_type_by_class("-1"))


class TestGetWallPairs(unittest.TestCase):
    """
    Unit tests for `get_wall_pairs` utility function.
    """

    def _mock_beam(self, x, y, z, name="TEST_WALL"):
        beam = Beam()
        beam.StartPoint.X = x
        beam.StartPoint.Y = y
        beam.StartPoint.Z = z
        beam.EndPoint.X = x
        beam.EndPoint.Y = y
        beam.EndPoint.Z = z
        beam.Name = name
        return beam

    def test_pair_two_matching_walls(self):
        """Checks pairing of two matching walls."""
        wall1 = self._mock_beam(0, 0, 0, "TEST_WALL1")
        wall2 = self._mock_beam(0, 0, 3000, "TEST_WALL2")
        result = get_wall_pairs([wall1, wall2])
        self.assertEqual(result, [(wall1, wall2)])

    def test_pair_multiple_walls(self):
        """Checks pairing of multiple wall pairs."""
        wall1 = self._mock_beam(0, 0, 0, "TEST_WALL1")
        wall2 = self._mock_beam(0, 0, 3000, "TEST_WALL2")
        wall3 = self._mock_beam(5000, 0, 0, "TEST_WALL3")
        wall4 = self._mock_beam(5000, 0, 3000, "TEST_WALL4")
        result = get_wall_pairs([wall1, wall2, wall3, wall4])
        self.assertIn((wall1, wall2), result)
        self.assertIn((wall3, wall4), result)
        self.assertEqual(len(result), 2)

    def test_less_than_two_elements(self):
        """Checks error for less than two elements."""
        wall1 = self._mock_beam(0, 0, 0, "TEST_WALL1")
        with self.assertRaises(ValueError):
            get_wall_pairs([wall1])

    def test_more_than_two_floors(self):
        """Checks error for more than two floors."""
        wall1 = self._mock_beam(0, 0, 0, "TEST_WALL1")
        wall2 = self._mock_beam(0, 0, 3000, "TEST_WALL2")
        wall3 = self._mock_beam(0, 0, 6000, "TEST_WALL3")
        with self.assertRaises(ValueError):
            get_wall_pairs([wall1, wall2, wall3])

    def test_z_coordinate_mismatch(self):
        """Checks error for Z coordinate mismatch."""
        wall = self._mock_beam(0, 0, 0, "TEST_WALL")
        wall.EndPoint.Z = 100  # Deliberate mismatch
        with self.assertRaises(ValueError):
            get_wall_pairs([wall, wall])

    def test_non_beam_objects_are_ignored(self):
        """Checks that non-beam objects are ignored."""
        wall1 = self._mock_beam(0, 0, 0, "TEST_WALL1")
        wall2 = self._mock_beam(0, 0, 3000, "TEST_WALL2")
        not_beam = object()
        result = get_wall_pairs([wall1, wall2, not_beam])
        self.assertEqual(result, [(wall1, wall2)])


if __name__ == "__main__":
    unittest.main()
