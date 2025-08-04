"""
This module contains unit tests for various functions, including component placement, selection, and modifications.

Tested modules:
- tekla_mcp.py: Functions for managing Tekla components (lifting anchors, custom details, etc.)
"""

import unittest

from models import (
    SelectionMode,
    UDASetMode,
    StringMatchType,
    PrecastElementType,
    LiftingAnchors,
)

from tekla_mcp import (
    put_wall_lifting_anchors,
    remove_wall_lifting_anchors,
    put_custom_detail_components,
    select_elements,
    select_elements_using_guid,
    select_elements_assemblies_or_main_parts,
    draw_elements_names,
    convert_cut_parts_to_real_parts,
    set_elements_udas,
)

from init import load_dlls
from utils import get_tekla_model

# Tekla OpenAPI imports
load_dlls()
from System.Collections import ArrayList
from Tekla.Structures.Geometry3d import Point
from Tekla.Structures.Model import Beam, Model, Position
from Tekla.Structures.Model.UI import ModelObjectSelector, ViewHandler


class UnitTests(unittest.TestCase):
    """
    Test suite for the utility functions used in Tekla Structures assistant.

    Includes test cases for:
    - Adding wall lifting anchors
    - Removing wall lifting anchors
    - Adding a custom component
    - Selecting specified elements
    - Selecting elements by GUID
    - Selecting assemblies the specified elements belong to
    """

    def create_test_beam(self, name, start_point, end_point, profile, material="Concrete_Undefined", depth_enum=Position.DepthEnum.FRONT, class_type="1"):
        """
        Utility function to create a beam.
        """
        beam = Beam()
        beam.Profile.ProfileString = profile
        beam.Material.MaterialString = material
        beam.Class = class_type
        beam.Name = name
        beam.Position.Depth = depth_enum
        beam.StartPoint = start_point
        beam.EndPoint = end_point
        beam.Insert()
        return beam

    def select_test_elements(self, elements):
        """
        Utility function to select an element.
        """
        selector = ModelObjectSelector()
        model_objects = ArrayList()
        for element in elements:
            model_objects.Add(element)
        selector.Select(model_objects)

    def setUp(self):
        self.model = get_tekla_model()

        # Create test walls
        self.test_wall1 = self.create_test_beam(name="TEST_WALL1", profile="3000*200", start_point=Point(0, 0, 0), end_point=Point(2000, 0, 0))
        self.test_wall2 = self.create_test_beam(name="TEST_WALL2", profile="3000*200", start_point=Point(0, 0, 3020), end_point=Point(2000, 0, 3020))
        self.test_wall3 = self.create_test_beam(name="TEST_WALL3", profile="3000*200", start_point=Point(2000, 0, 0), end_point=Point(4000, 0, 0))
        self.test_wall4 = self.create_test_beam(name="TEST_WALL4", profile="3000*200", start_point=Point(2000, 0, 3020), end_point=Point(4000, 0, 3020))

        # Create test sandwich walls
        self.test_sw1 = self.create_test_beam(name="TEST_SW1", profile="3000*200", start_point=Point(4000, 0, 0), end_point=Point(6000, 0, 0), class_type="8")

        # Create test slabs
        self.test_slab1 = self.create_test_beam(name="TEST_SLAB1", profile="UPB200(200X1200)", start_point=Point(1000, 0, 3020), end_point=Point(1000, 6000, 3020), class_type="3")

        # Commit changes to the model
        self.model.CommitChanges()

    def tearDown(self):
        self.test_wall1.Delete()
        self.test_wall2.Delete()
        self.test_wall3.Delete()
        self.test_wall4.Delete()

        self.test_sw1.Delete()

        self.test_slab1.Delete()

        # Commit changes to the model
        self.model.CommitChanges()

    def test_put_wall_lifting_anchors_walls(self):
        """
        Validates the `put_wall_lifting_anchors` function for standard walls.

        Steps:
        - Selects a test wall (`self.test_wall1`).
        - Applies default lifting anchor placement.
        - Tests with a 10% safety margin.
        - Ensures that the operation returns a "success" status.
        """
        self.select_test_elements([self.test_wall1])

        # Default settings
        component = LiftingAnchors()
        result = put_wall_lifting_anchors(component)
        self.assertEqual(result["status"], "success")

        # 10% safety margin
        component = LiftingAnchors(safety_margin=10)
        result = put_wall_lifting_anchors(component)
        self.assertEqual(result["status"], "success")

    def test_put_wall_lifting_anchors_sandwich_walls(self):
        """
        Validates the `put_wall_lifting_anchors` function for sandwich walls.

        Steps:
        - Selects a test sandwich wall (`self.test_sw1`).
        - Applies default lifting anchor placement.
        - Ensures the operation completes successfully.
        """
        self.select_test_elements([self.test_sw1])

        # Default settings
        component = LiftingAnchors()
        result = put_wall_lifting_anchors(component)
        self.assertEqual(result["status"], "success")

    def test_remove_wall_lifting_anchors(self):
        """
        Tests the removal of wall lifting anchors using `remove_wall_lifting_anchors`.

        Steps:
        - Places lifting anchors on `self.test_wall1`.
        - Calls `remove_wall_lifting_anchors()`.
        - Ensures that the function successfully removes the anchors.
        """
        self.select_test_elements([self.test_wall1])

        component = LiftingAnchors()
        put_wall_lifting_anchors(component)
        result = remove_wall_lifting_anchors()
        self.assertEqual(result["status"], "success")

    def test_put_custom_detail_components(self):
        """
        Tests the `put_custom_detail_components` function.

        Steps:
        - Selects `self.test_wall1` and `self.test_wall2`.
        - Adds a predefined custom detail (`DIR_ARR`).
        - Ensures successful placement.
        """
        self.select_test_elements([self.test_wall1, self.test_wall2])

        result = put_custom_detail_components("DIR_ARR")
        self.assertEqual(result["status"], "success")

    def test_select_elements(self):
        """
        Tests the `select_elements` function, ensuring it correctly selects elements based on various parameters.

        Steps:
        - Validates behavior when no elements are provided (should return "error").
        - Tests invalid inputs like a single integer instead of a list.
        - Ensures non-existing classes return "error".
        - Checks selection of specific element types (`WALL`, `TRIBUNE`, etc.).
        - Validates selection by name, ensuring correct matching methods (`STARTS_WITH`, `ENDS_WITH`, `CONTAINS`).
        """
        # Nothing is specified
        result = select_elements()
        self.assertEqual(result["status"], "error")

        result = select_elements([])
        self.assertEqual(result["status"], "error")

        # Check `int` instead of `list[int]`
        result = select_elements(1)
        self.assertEqual(result["status"], "error")

        # Check non-existing class
        result = select_elements([-777])
        self.assertEqual(result["status"], "error")

        # Check tribunes
        result = select_elements(PrecastElementType.TRIBUNE)
        self.assertEqual(result["status"], "error")

        # Check walls
        result = select_elements(PrecastElementType.WALL)
        self.assertEqual(result["status"], "success")

        result = select_elements([1])
        self.assertEqual(result["status"], "success")

        # Check walls and sandwich walls
        result = select_elements([1, 8])
        self.assertEqual(result["status"], "success")

        # Check wall `TEST_WALL2`
        result = select_elements(PrecastElementType.WALL, "TEST_WALL2")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 1)

        result = select_elements([8], "TEST_WALL2")
        self.assertEqual(result["status"], "error")

        result = select_elements([1], "TEST_WALL2")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 1)

        result = select_elements(name="TEST_WALL2")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 1)

        result = select_elements(name="EST_WALL2", name_match_type=StringMatchType.ENDS_WITH)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 1)

        result = select_elements(name="TEST_WALL2", name_match_type=StringMatchType.CONTAINS)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 1)

        # Check multiple other variations
        result = select_elements(name="TEST_WALL", name_match_type=StringMatchType.CONTAINS)
        self.assertEqual(result["status"], "success")

        result = select_elements(name="TEST_WALL8585", name_match_type=StringMatchType.STARTS_WITH)
        self.assertEqual(result["status"], "error")

        result = select_elements(name="TEST_WALL8585", name_match_type=StringMatchType.ENDS_WITH)
        self.assertEqual(result["status"], "error")

        result = select_elements(name="TEST_WALL", name_match_type=StringMatchType.IS_EQUAL)
        self.assertEqual(result["status"], "error")

        result = select_elements(name_match_type=StringMatchType.IS_EQUAL)
        self.assertEqual(result["status"], "error")

    def test_select_elements_using_guid(self):
        """
        Tests the `select_elements_using_guid` function, ensuring it correctly selects elements based on their GUID.

        Steps:
        - Tests invalid inputs like a single integer or string instead of a list.
        - Checks selection of specific elements.
        """
        result = select_elements_using_guid([])
        self.assertEqual(result["status"], "error")

        # Check `int` instead of `list[str]`
        result = select_elements_using_guid(0)
        self.assertEqual(result["status"], "error")

        # Check `str` instead of `list[str]`
        result = select_elements_using_guid("TEST_WALL2")
        self.assertEqual(result["status"], "error")

        # Check wall `TEST_WALL2`
        result = select_elements_using_guid([self.test_wall2.Identifier.GUID.ToString()])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 1)

        # Check walls `TEST_WALL1` and `TEST_WALL2`
        result = select_elements_using_guid([self.test_wall1.Identifier.GUID.ToString(), self.test_wall2.Identifier.GUID.ToString()])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 2)

    def test_select_elements_assemblies(self):
        """
        Tests the `select_elements_assemblies` function to ensure correct assembly selection.

        Steps:
        - Selects `self.test_wall1` and `self.test_wall2`.
        - Calls `select_elements_assemblies`.
        - Verifies that assemblies or main parts are selected correctly with "success" status.
        - Ensures the expected number of selected elements is correct.
        """
        self.select_test_elements([self.test_wall1, self.test_wall2])
        result = select_elements_assemblies_or_main_parts(SelectionMode.ASSEMBLY)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 2)

        self.select_test_elements([self.test_wall1, self.test_wall2])
        result = select_elements_assemblies_or_main_parts(SelectionMode.MAIN_PART)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 2)

    def test_draw_elements_names(self):
        """
        Tests the `draw_elements_names` function to ensure it correctly labels elements.

        Steps:
        - Selects two walls (`self.test_wall1`, `self.test_wall2`).
        - Calls `draw_elements_names()`, expecting a "success" response.
        - Validates correct selection count.
        - Refreshes all views using `ViewHandler.RedrawView()`.
        """
        self.select_test_elements([self.test_wall1, self.test_wall2])
        result = draw_elements_names()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_elements"], 2)

        # Redraw views
        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)

    def test_convert_cut_parts_to_real_parts(self):
        """
        Tests the `convert_cut_parts_to_real_parts` function.

        Steps:
        - Selects `self.test_wall1` and `self.test_wall2`, ensuring initial call returns "error."
        """
        self.select_test_elements([self.test_wall1, self.test_wall2])
        result = convert_cut_parts_to_real_parts()
        self.assertEqual(result["status"], "error")

    def test_set_elements_udas(self):
        """
        Tests the `set_elements_udas` function to ensure correct behavior for applying UDAs
        to Tekla model elements under different update modes.

        Steps:
        1. Select a test element (`self.test_wall1`).
        2. Set initial UDAs using OVERWRITE mode and verify values are written correctly.
        3. Attempt to set new UDAs using KEEP mode and confirm original values are preserved.
        4. Overwrite UDAs with new values using OVERWRITE mode and verify changes.
        """
        self.select_test_elements([self.test_wall1])

        # Initial UDA assignment using OVERWRITE mode
        test_udas = {"TEST_UDA1": "TEST_VALUE_1", "TEST_UDA2": "TEST_VALUE_2"}
        result = set_elements_udas(test_udas, UDASetMode.OVERWRITE)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["updated_elements"], 1)

        uda_exists, uda_value = self.test_wall1.GetUserProperty("TEST_UDA1", str())
        self.assertEqual(uda_exists, True)
        self.assertEqual(uda_value, "TEST_VALUE_1")

        uda_exists, uda_value = self.test_wall1.GetUserProperty("TEST_UDA2", str())
        self.assertEqual(uda_exists, True)
        self.assertEqual(uda_value, "TEST_VALUE_2")

        # Attempt to update UDAs using KEEP mode
        test_udas = {"TEST_UDA1": "TEST_VALUE_1_UPD", "TEST_UDA2": "TEST_VALUE_2_UPD"}
        result = set_elements_udas(test_udas, UDASetMode.KEEP)

        uda_exists, uda_value = self.test_wall1.GetUserProperty("TEST_UDA1", str())
        self.assertEqual(uda_exists, True)
        self.assertEqual(uda_value, "TEST_VALUE_1")

        uda_exists, uda_value = self.test_wall1.GetUserProperty("TEST_UDA2", str())
        self.assertEqual(uda_exists, True)
        self.assertEqual(uda_value, "TEST_VALUE_2")

        # Reassign UDAs using OVERWRITE mode
        test_udas = {"TEST_UDA1": "TEST_VALUE_1_UPD", "TEST_UDA2": "TEST_VALUE_2_UPD"}
        result = set_elements_udas(test_udas, UDASetMode.OVERWRITE)

        uda_exists, uda_value = self.test_wall1.GetUserProperty("TEST_UDA1", str())
        self.assertEqual(uda_exists, True)
        self.assertEqual(uda_value, "TEST_VALUE_1_UPD")

        uda_exists, uda_value = self.test_wall1.GetUserProperty("TEST_UDA2", str())
        self.assertEqual(uda_exists, True)
        self.assertEqual(uda_value, "TEST_VALUE_2_UPD")


if __name__ == "__main__":
    unittest.main()
