"""
This module contains unit tests for various functions, including component placement, selection, and modifications.

Tested modules:
- tekla_mcp.py: Functions for managing Tekla components (lifting anchors, custom details, etc.)
"""

import os
import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from fastmcp import Client

from models import LiftingAnchors

from init import load_dlls
from mcp_server import mcp
from tekla_utils import get_tekla_model

# Tekla OpenAPI imports
load_dlls()
from System.Collections import ArrayList
from Tekla.Structures.Geometry3d import Point
from Tekla.Structures.Model import Beam, Position
from Tekla.Structures.Model.UI import ModelObjectSelector, ViewHandler


def create_test_beam(name, start_point, end_point, profile, material="Concrete_Undefined", depth_enum=Position.DepthEnum.FRONT, class_type="1"):
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


def select_elements(elements):
    """
    Utility function to select an element.
    """
    selector = ModelObjectSelector()
    model_objects = ArrayList()
    for element in elements:
        model_objects.Add(element)
    selector.Select(model_objects)


@pytest.fixture(scope="module")
def model_objects():
    """
    Fixture: Test setup and teardown.
    """
    model = get_tekla_model()
    test_wall1 = create_test_beam("TEST_WALL1", Point(0, 0, 0), Point(2000, 0, 0), "3000*200")
    test_wall2 = create_test_beam("TEST_WALL2", Point(0, 0, 3020), Point(2000, 0, 3020), "3000*200")
    test_wall3 = create_test_beam("TEST_WALL3", Point(2000, 0, 0), Point(4000, 0, 0), "3000*200")
    test_wall4 = create_test_beam("TEST_WALL4", Point(2000, 0, 3020), Point(4000, 0, 3020), "3000*200")
    test_sw1 = create_test_beam("TEST_SW1", Point(4000, 0, 0), Point(6000, 0, 0), "3000*200", class_type="8")
    test_slab1 = create_test_beam("TEST_SLAB1", Point(1000, 0, 3020), Point(1000, 6000, 3020), "UPB200(200X1200)", class_type="3")

    model.CommitChanges()

    yield {"model": model, "walls": [test_wall1, test_wall2, test_wall3, test_wall4], "test_wall1": test_wall1, "test_wall2": test_wall2, "test_sw1": test_sw1, "test_slab1": test_slab1}

    for obj in [test_wall1, test_wall2, test_wall3, test_wall4, test_sw1, test_slab1]:
        if obj.Identifier.IsValid():
            obj.Delete()
    model.CommitChanges()


@pytest.mark.asyncio
async def test_put_wall_lifting_anchors_walls(model_objects):
    """
    Validates the `put_wall_lifting_anchors` function for standard walls.

    Steps:
    - Selects a test wall (`self.test_wall1`).
    - Applies default lifting anchor placement.
    - Tests with a 10% safety margin.
    - Ensures that the operation returns a "success" status.
    """
    select_elements([model_objects["test_wall1"]])

    async with Client(mcp) as client:
        # Default parameters
        result1 = await client.call_tool("put_wall_lifting_anchors", {"component": LiftingAnchors()})
        assert result1.data["status"] == "success"

        # Custom safety margin
        result2 = await client.call_tool("put_wall_lifting_anchors", {"component": LiftingAnchors(safety_margin=10)})
        assert result2.data["status"] == "success"


@pytest.mark.asyncio
async def test_put_wall_lifting_anchors_sandwich(model_objects):
    """
    Validates the `put_wall_lifting_anchors` function for sandwich walls.

    Steps:
    - Selects a test sandwich wall (`self.test_sw1`).
    - Applies default lifting anchor placement.
    - Ensures the operation completes successfully.
    """
    select_elements([model_objects["test_sw1"]])
    async with Client(mcp) as client:
        result = await client.call_tool("put_wall_lifting_anchors", {"component": LiftingAnchors()})
        assert result.data["status"] == "success"


@pytest.mark.asyncio
async def test_remove_wall_lifting_anchors(model_objects):
    """
    Tests the removal of wall lifting anchors using `remove_wall_lifting_anchors`.

    Steps:
    - Places lifting anchors on `self.test_wall1`.
    - Calls `remove_wall_lifting_anchors()`.
    - Ensures that the function successfully removes the anchors.
    """
    select_elements([model_objects["test_wall1"]])
    async with Client(mcp) as client:
        _ = await client.call_tool("put_wall_lifting_anchors", {"component": LiftingAnchors()})
        result2 = await client.call_tool("remove_wall_lifting_anchors")
        assert result2.data["status"] == "success"


@pytest.mark.asyncio
async def test_put_custom_detail_components(model_objects):
    """
    Tests the `put_custom_detail_components` function.

    Steps:
    - Selects `self.test_wall1` and `self.test_wall2`.
    - Adds a predefined custom detail (`DIR_ARR`).
    - Ensures successful placement.
    """
    select_elements([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("put_custom_detail_components", {"component_name": "DIR_ARR"})
        assert result.data["status"] == "success"


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"element_type": []}, "error"),
        ({"element_type": [-777]}, "error"),
        ({"element_type": "Tribune"}, "error"),
        ({"element_type": [1]}, "success"),
        ({"element_type": 1}, "success"),
        ({"element_type": [1, 8]}, "success"),
        ({"element_type": "Wall"}, "success"),
    ],
)
@pytest.mark.asyncio
async def test_select_elements_filter_basic(kwargs, expected):
    """
    Tests the `select_elements_using_filter` function, ensuring it correctly selects elements based on various parameters.

    Steps:
    - Validates behavior when no elements are provided (should return "error").
    - Ensures non-existing classes return "error".
    - Checks selection of specific element types (`WALL`, `TRIBUNE`, etc.).
    """
    async with Client(mcp) as client:
        result = await client.call_tool("select_elements_using_filter", kwargs)
        assert result.data["status"] == expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"element_type": "Wall", "name": "TEST_WALL2"}, 1),
        ({"element_type": [8], "name": "TEST_WALL2"}, None),
        ({"element_type": 8, "name": "TEST_WALL2"}, None),
        ({"element_type": [1], "name": "TEST_WALL2"}, 1),
        ({"name": "TEST_WALL2"}, 1),
        ({"name": "EST_WALL2", "name_match_type": "Ends With"}, 1),
        ({"name": "TEST_WALL2", "name_match_type": "Contains"}, 1),
    ],
)
@pytest.mark.asyncio
async def test_select_elements_by_name(kwargs, expected):
    """
    Steps:
    - Validates selection by type and name, ensuring correct matching methods (`STARTS_WITH`, `ENDS_WITH`, `CONTAINS`).
    """
    async with Client(mcp) as client:
        result = await client.call_tool("select_elements_using_filter", kwargs)
        assert result.data["status"] == ("success" if expected else "error")
        if expected:
            assert result.data["selected_elements"] == expected


@pytest.mark.asyncio
async def test_select_elements_by_profile():
    """
    Steps:
    - Validates selection by profile, ensuring correct matching methods.
    """
    async with Client(mcp) as client:
        result = await client.call_tool("select_elements_using_filter", {"element_type": "Wall", "profile": "3000*200", "profile_match_type": "Is Equal"})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 4


@pytest.mark.parametrize(
    "name,match_type,expected",
    [
        ("TEST_WALL", "Contains", "success"),
        ("TEST_WALL8585", "Starts With", "error"),
        ("TEST_WALL8585", "Ends With", "error"),
        ("TEST_WALL", "Is Equal", "error"),
    ],
)
@pytest.mark.asyncio
async def test_select_elements_name_matching(name, match_type, expected):
    """
    Steps:
    - Validates selection by name, ensuring correct matching methods.
    """
    async with Client(mcp) as client:
        result = await client.call_tool("select_elements_using_filter", {"name": name, "name_match_type": match_type})
        assert result.data["status"] == expected


@pytest.mark.asyncio
async def test_select_elements_using_guid(model_objects):
    """
    Tests the `select_elements_using_guid` function, ensuring it correctly selects elements based on their GUID.

    Steps:
    - Tests invalid inputs like a single integer or string instead of a list.
    - Checks selection of specific elements.
    """
    async with Client(mcp) as client:
        # Invalid inputs
        result = await client.call_tool("select_elements_using_guid", {"guids": []})
        assert result.data["status"] == "error"

        result = await client.call_tool("select_elements_using_guid", {"guids": [""]})
        assert result.data["status"] == "error"

        result = await client.call_tool("select_elements_using_guid", {"guids": ["TEST_WALL2"]})
        assert result.data["status"] == "error"

        # Valid single GUID
        wall2_guid = model_objects["test_wall2"].Identifier.GUID.ToString()
        result = await client.call_tool("select_elements_using_guid", {"guids": [wall2_guid]})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 1

        # Valid multiple GUIDs
        wall1_guid = model_objects["test_wall1"].Identifier.GUID.ToString()
        result = await client.call_tool("select_elements_using_guid", {"guids": [wall1_guid, wall2_guid]})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2


@pytest.mark.parametrize("mode, expected_count", [("Assembly", 2), ("Main Part", 2)])
@pytest.mark.asyncio
async def test_select_elements_assemblies(model_objects, mode, expected_count):
    """
    Tests the `select_elements_assemblies_or_main_parts` function to ensure correct assembly selection.

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Verifies selection behavior under different modes.
    """
    select_elements([model_objects["test_wall1"], model_objects["test_wall2"]])

    async with Client(mcp) as client:
        result = await client.call_tool("select_elements_assemblies_or_main_parts", {"mode": mode})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == expected_count


@pytest.mark.asyncio
async def test_draw_elements_names(model_objects):
    """
    Tests the `draw_elements_names` function to ensure it correctly labels elements.

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Calls drawing method and refreshes views.
    """
    select_elements([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("draw_elements_names")
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2

        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)


@pytest.mark.asyncio
async def test_convert_cut_parts_to_real_parts(model_objects):
    """
    Tests the `convert_cut_parts_to_real_parts` function.

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Verifies it returns "error" when no cut parts are present.
    """
    select_elements([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("convert_cut_parts_to_real_parts")
        assert result.data["status"] == "error"


@pytest.mark.asyncio
async def test_set_elements_udas(model_objects):
    """
    Tests the `set_elements_udas` function with OVERWRITE and KEEP modes.

    Steps:
    1. Set initial UDAs and verify.
    2. Try KEEP mode (should preserve values).
    3. Use OVERWRITE to update values.
    """
    wall = model_objects["test_wall1"]
    select_elements([wall])

    async with Client(mcp) as client:
        # Initial UDA assignment using OVERWRITE mod
        initial_udas = {"TEST_UDA1": "TEST_VALUE_1", "TEST_UDA2": "TEST_VALUE_2"}
        result = await client.call_tool("set_elements_udas", {"udas": initial_udas, "mode": "Overwrite Existing Values"})
        assert result.data["status"] == "success"
        assert result.data["processed_elements"] == 1
        assert result.data["updated_attributes"] == 2

        exists, value = wall.GetUserProperty("TEST_UDA1", str())
        assert exists and value == "TEST_VALUE_1"
        exists, value = wall.GetUserProperty("TEST_UDA2", str())
        assert exists and value == "TEST_VALUE_2"

        # KEEP mode: should not overwrite
        update_attempt = {"TEST_UDA1": "TEST_VALUE_1_UPD", "TEST_UDA2": "TEST_VALUE_2_UPD"}
        result = await client.call_tool("set_elements_udas", {"udas": update_attempt, "mode": "Keep Existing Values"})

        exists, value = wall.GetUserProperty("TEST_UDA1", str())
        assert exists and value == "TEST_VALUE_1"
        exists, value = wall.GetUserProperty("TEST_UDA2", str())
        assert exists and value == "TEST_VALUE_2"

        # OVERWRITE mode: now it should update
        result = await client.call_tool("set_elements_udas", {"udas": update_attempt, "mode": "Overwrite Existing Values"})

        exists, value = wall.GetUserProperty("TEST_UDA1", str())
        assert exists and value == "TEST_VALUE_1_UPD"
        exists, value = wall.GetUserProperty("TEST_UDA2", str())
        assert exists and value == "TEST_VALUE_2_UPD"
