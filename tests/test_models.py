"""
This module contains unit tests for models, including anchor placement and spacing calculations.

Tested modules:
- models.py: Contains classes for managing Tekla components such as lifting anchors.
"""

import unittest

from models import (
    PrecastElementType,
    LiftingAnchors,
)


class TestLiftingAnchors(unittest.TestCase):
    """
    Unit tests for `LiftingAnchors` component.

    Validates anchor selection logic, required anchor calculations and placement constraints
    for precast elements.
    """

    def setUp(self):
        """
        Initializes anchor types and element type for testing.

        - Defines anchor variations with different capacities.
        - Sets default element type (`WALL`).
        """
        self.anchor_types = {
            "A": {"element_type": ["WALL"], "active": True, "capacity": 1.5},
            "B": {"element_type": ["WALL"], "active": True, "capacity": 2.0},
            "C": {"element_type": ["WALL"], "active": True, "capacity": 0.5},
        }
        self.element_type = PrecastElementType.WALL

    def test_get_required_anchors_valid(self):
        """
        Tests `get_required_anchors()` with valid anchor types.

        Steps:
        - Calls `get_required_anchors()` with weight and thickness parameters.
        - Ensures at least two valid anchors are selected.
        """
        n, valid = LiftingAnchors.get_required_anchors(self.element_type.name, 2000, 10, self.anchor_types)
        self.assertIn("A", valid)
        self.assertEqual(n, 2)

    def test_get_required_anchors_try_four(self):
        """
        Tests `get_required_anchors()` when four anchors are required.

        Steps:
        - Uses an anchor type with **capacity=1.0** per anchor.
        - Calls the function with **element_weight=3600**.
        - Ensures the system correctly assigns four anchors.
        """
        anchor_types = {"A": {"element_type": ["WALL"], "active": True, "capacity": 1.0}}
        n, valid = LiftingAnchors.get_required_anchors(self.element_type.name, 3600, 10, anchor_types)
        self.assertEqual(n, 4)
        self.assertIn("A", valid)

    def test_get_required_anchors_not_valid(self):
        """
        Tests `get_required_anchors()` when no valid anchors exist.

        Steps:
        - Uses anchor types with insufficient capacity (**capacity=0.1** per anchor).
        - Calls the function with **element_weight=10000**.
        - Ensures a `ValueError` is raised due to inability to support the load.
        """
        anchor_types = {"A": {"element_type": ["WALL"], "active": True, "capacity": 0.1}}
        with self.assertRaises(ValueError):
            LiftingAnchors.get_required_anchors(self.element_type.name, 10000, 10, anchor_types)

    def test_calculate_anchor_placement_valid(self):
        """
        Tests `calculate_anchor_placement()` with a valid case.

        Steps:
        - Calls the function with **element_length=2000**, **cog_x=1000**, **min_edge_distance=50** and **two anchors**.
        - Validates correct distance from start and end.
        - Ensures anchors are placed symmetrically.
        """
        res = LiftingAnchors.calculate_anchor_placement(
            min_edge_distance=50,
            element_length=2000,
            cog_x=1000,
            number_of_anchors=2,
        )
        distance_from_start, distance_from_end, double_anchor_spacing = res
        self.assertEqual(distance_from_start, 500)
        self.assertEqual(distance_from_end, 500)
        self.assertEqual(double_anchor_spacing, 50)

    def test_calculate_anchor_placement_too_short(self):
        """
        Tests `calculate_anchor_placement()` when the element length is too short.

        Steps:
        - Calls the function with **element_length=1000**, **cog_x=500**, **min_edge_distance=900** and **four anchors**.
        - Ensures a `ValueError` is raised due to insufficient space for anchors.
        """
        with self.assertRaises(ValueError):
            LiftingAnchors.calculate_anchor_placement(
                min_edge_distance=900,
                element_length=1000,
                cog_x=500,
                number_of_anchors=4,
            )

    def test_calculate_anchor_placement_four_anchors_requested(self):
        """
        Tests `calculate_anchor_placement()` with an explicit request for four anchors.

        Steps:
        - Calls the function with **element_length=6000** and **cog_x=3000**.
        - Validates correct anchor spacing and positioning.
        """
        res = LiftingAnchors.calculate_anchor_placement(
            min_edge_distance=50,
            element_length=6000,
            cog_x=3000,
            number_of_anchors=4,
        )
        distance_from_start, distance_from_end, double_anchor_spacing = res
        self.assertEqual(distance_from_start, 1000)
        self.assertEqual(distance_from_end, 1000)
        self.assertEqual(double_anchor_spacing, 1000)

    def test_calculate_anchor_placement_distances_are_multiples_of_5(self):
        """
        Tests `calculate_anchor_placement()` to ensure placement distances are multiples of 5.

        Steps:
        - Calls the function with **element_length=4012**, **cog_x=2006**, **min_edge_distance=50** and **two anchors**.
        - Validates that both `distance_from_start` and `distance_from_end` are multiples of 5.
        """
        res = LiftingAnchors.calculate_anchor_placement(
            min_edge_distance=50,
            element_length=4012,
            cog_x=2006,
            number_of_anchors=2,
        )
        distance_from_start, distance_from_end, _ = res
        self.assertEqual(distance_from_start % 5, 0)
        self.assertEqual(distance_from_end % 5, 0)


if __name__ == "__main__":
    unittest.main()
