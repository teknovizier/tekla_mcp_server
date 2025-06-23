"""
This module contains unit tests for utility functions.

Tested modules:
- utils.py: Contains utility classes and functions used for geometry manipulations.
"""

import unittest

from utils import get_element_type_by_class


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


if __name__ == "__main__":
    unittest.main()
