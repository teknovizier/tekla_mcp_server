"""
Functional tests for Tekla operations via MCP server.

This module validates end-to-end behavior of component placement, selection, and modification
within a Tekla Structures model using the MCP server interface. It interacts with real model
objects and tests asynchronous workflows.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.

Tested modules:
- mcp_server.py
"""

import json
import os
import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from fastmcp import Client

from mcp_server import mcp
from models import LiftingAnchors

from tekla_loader import Point, Beam, Position, ViewHandler
from tekla_utils import TeklaModel, TeklaModelObject


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


@pytest.fixture(scope="module")
def model_objects():
    """
    Fixture: Test setup and teardown.
    """
    model = TeklaModel()
    test_wall1 = create_test_beam("TEST_WALL1", Point(0, 0, 0), Point(2000, 0, 0), "3000*200")
    test_wall2 = create_test_beam("TEST_WALL2", Point(0, 0, 3020), Point(2000, 0, 3020), "3000*200")
    test_wall3 = create_test_beam("TEST_WALL3", Point(2000, 0, 0), Point(4000, 0, 0), "3000*200")
    test_wall4 = create_test_beam("TEST_WALL4", Point(2000, 0, 3020), Point(4000, 0, 3020), "3000*200")
    test_sw1 = create_test_beam("TEST_SW1", Point(4000, 0, 0), Point(6000, 0, 0), "3000*200", class_type="8")
    test_slab1 = create_test_beam("TEST_SLAB1", Point(1000, 0, 3020), Point(1000, 6000, 3020), "P20(200X1200)", class_type="3")

    void1 = create_test_beam("VOID_TEST_WALL3", Point(3000, 0, 1000), Point(3000, 200, 1000), "D400", class_type="0")
    void2 = create_test_beam("VOID_FLOATING", Point(3000, 0, 10000), Point(3000, 200, 10000), "D400", class_type="0")

    model.commit_changes()

    yield {
        "model": model,
        "walls": [test_wall1, test_wall2, test_wall3, test_wall4],
        "test_wall1": test_wall1,
        "test_wall2": test_wall2,
        "test_wall3": test_wall3,
        "test_wall4": test_wall4,
        "test_sw1": test_sw1,
        "test_slab1": test_slab1,
        "void1": void1,
        "void2": void2,
    }

    for obj in [test_wall1, test_wall2, test_wall3, test_wall4, test_sw1, test_slab1, void1, void2]:
        if obj.Identifier.IsValid():
            obj.Delete()
    model.commit_changes()


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
    TeklaModel.select_objects([model_objects["test_wall1"]])

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
    TeklaModel.select_objects([model_objects["test_sw1"]])
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
    TeklaModel.select_objects([model_objects["test_wall1"]])
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
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
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
async def test_select_elements_using_filter_name(model_objects):
    """
    Tests the `select_elements_using_filter_name` function, ensuring it correctly selects elements based on the existing filter settings.

    Steps:
    - Checks selection of specific elements.
    """
    async with Client(mcp) as client:
        # Invalid filter
        result = await client.call_tool("select_elements_using_filter_name", {"filter_name": "non_standard"})
        assert result.data["status"] == "error"

        # Valid filter
        result = await client.call_tool("select_elements_using_filter_name", {"filter_name": "standard"})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"]


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
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    async with Client(mcp) as client:
        result = await client.call_tool("select_elements_assemblies_or_main_parts", {"mode": mode})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == expected_count


@pytest.mark.asyncio
async def test_draw_elements_labels(model_objects):
    """
    Tests that `draw_elements_labels` function can be run.

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Calls drawing method without arguments.
    - Verifies success and redraws views.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("draw_elements_labels")
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2

        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)


@pytest.mark.asyncio
async def test_draw_elements_labels_with_label(model_objects):
    """
    Tests that `draw_elements_labels` function can be run with a specific label value (`Profile`).

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Calls drawing method with label argument.
    - Verifies success and redraws views.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    async with Client(mcp) as client:
        result = await client.call_tool("draw_elements_labels", {"label": "Profile"})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2

        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)


@pytest.mark.asyncio
async def test_draw_elements_labels_with_valid_custom_label(model_objects):
    """
    Tests that `draw_elements_labels` function can be run with a specific custom label value (`AREA_NET`).

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Calls drawing method with `custom_label` argument.
    - Verifies success and redraws views.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    async with Client(mcp) as client:
        result = await client.call_tool("draw_elements_labels", {"label": "Custom", "custom_label": "AREA_NET"})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2

        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)


@pytest.mark.asyncio
async def test_draw_elements_labels_with_invalid_custom_label(model_objects):
    """
    Tests that `draw_elements_labels` handles an invalid custom label (`InvalidProperty`).

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Calls drawing method with invalid `custom_label` argument.
    - Asserts that the response status is `error` and that two elements were selected.
    - Redraws views.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    async with Client(mcp) as client:
        result = await client.call_tool("draw_elements_labels", {"label": "Custom", "custom_label": "InvalidProperty"})
        assert result.data["status"] == "error"

        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)


@pytest.mark.asyncio
async def test_zoom_to_selection(model_objects):
    """
    Tests that `zoom_to_selection` function can be run.

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Calls a method.
    - Verifies success and redraws views.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("zoom_to_selection")
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2

        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)


@pytest.mark.asyncio
async def test_show_only_selected(model_objects):
    """
    Tests that `show_only_selected` function can be run.

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Calls a drawing method.
    - Verifies success and redraws views.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("show_only_selected")
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2

        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)


@pytest.mark.asyncio
async def test_cut_elements_with_zero_class_parts(model_objects):
    """
    Tests the `cut_elements_with_zero_class_parts` tool.

    Steps:
    1. Selects `TEST_WALL3` and `TEST_WALL4`.
    2. Run the cut tool.
    3. Verifies success.
    """
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    async with Client(mcp) as client:
        result = await client.call_tool("cut_elements_with_zero_class_parts", {"delete_cutting_parts": False})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2
        assert result.data["processed_elements"] == 1  # Only `TEST_WALL1` should be cut
        assert result.data["performed_cuts"] >= 1  # At least one cut should be applied


@pytest.mark.asyncio
async def test_convert_cut_parts_to_real_parts_without_cuts(model_objects):
    """
    Tests the `convert_cut_parts_to_real_parts` function when no cuts are present.

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Verifies that the tool returns "error" because no cuts exist.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("convert_cut_parts_to_real_parts")
        assert result.data["status"] == "error"


@pytest.mark.asyncio
async def test_convert_cut_parts_to_real_parts_with_cut(model_objects):
    """
    Tests the `convert_cut_parts_to_real_parts` function when a valid cut part exists.

    Steps:
    - Selects `TEST_WALL3`, which is intersected by `VOID_CUT_WALL3`.
    - Verifies that the conversion tool returns "success" after the cut is applied.
    """
    TeklaModel.select_objects([model_objects["test_wall3"]])
    async with Client(mcp) as client:
        result = await client.call_tool("convert_cut_parts_to_real_parts")
        assert result.data["status"] == "success"
        assert result.data["processed_elements"] >= 1


@pytest.mark.asyncio
async def test_convert_cut_parts_to_real_parts(model_objects):
    """
    Tests the `convert_cut_parts_to_real_parts` function.

    Steps:
    - Selects `TEST_WALL1` and `TEST_WALL2`.
    - Verifies it returns "error" when no cut parts are present.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
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
    TeklaModel.select_objects([wall])

    async with Client(mcp) as client:
        # Initial UDA assignment using OVERWRITE mod
        initial_udas = {"TEST_UDA1": "TEST_VALUE_1", "TEST_UDA2": "TEST_VALUE_2"}
        result = await client.call_tool("set_elements_udas", {"udas": initial_udas, "mode": "Overwrite Existing Values"})
        assert result.data["status"] == "success"
        assert result.data["processed_elements"] == 1
        assert result.data["updated_attributes"] == 2

        wall = TeklaModelObject(wall)
        value = wall.get_user_property("TEST_UDA1", str)
        assert value == "TEST_VALUE_1"
        value = wall.get_user_property("TEST_UDA2", str)
        assert value == "TEST_VALUE_2"

        # KEEP mode: should not overwrite
        update_attempt = {"TEST_UDA1": "TEST_VALUE_1_UPD", "TEST_UDA2": "TEST_VALUE_2_UPD"}
        result = await client.call_tool("set_elements_udas", {"udas": update_attempt, "mode": "Keep Existing Values"})

        value = wall.get_user_property("TEST_UDA1", str)
        assert value == "TEST_VALUE_1"
        value = wall.get_user_property("TEST_UDA2", str)
        assert value == "TEST_VALUE_2"

        # OVERWRITE mode: now it should update
        result = await client.call_tool("set_elements_udas", {"udas": update_attempt, "mode": "Overwrite Existing Values"})

        value = wall.get_user_property("TEST_UDA1", str)
        assert value == "TEST_VALUE_1_UPD"
        value = wall.get_user_property("TEST_UDA2", str)
        assert value == "TEST_VALUE_2_UPD"


@pytest.mark.asyncio
async def test_get_all_elements_udas_empty(model_objects):
    """
    Tests the `get_all_elements_udas` MCP tool: empty UDAs.
    """
    elements_to_select = [
        model_objects["test_sw1"],
        model_objects["test_slab1"],
    ]
    TeklaModel.select_objects(elements_to_select)
    async with Client(mcp) as client:
        result = await client.call_tool("get_all_elements_udas")

        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2
        assert result.data["processed_elements"] == 2

        # Check assemblies
        for assembly in result.data["assemblies"]:
            assert not assembly["udas"]

        # Check parts
        for part in result.data["parts"]:
            assert not part["udas"]


@pytest.mark.asyncio
async def test_get_elements_properties_basic_assembly_properties(model_objects):
    """
    Tests the `get_elements_properties` MCP tool: basic assembly properties.
    """
    elements_to_select = [
        model_objects["test_wall1"],
        model_objects["test_wall2"],
        model_objects["test_sw1"],
        model_objects["test_slab1"],
    ]
    TeklaModel.select_objects(elements_to_select)
    async with Client(mcp) as client:
        await client.call_tool("select_elements_assemblies_or_main_parts", {"mode": "Assembly"})
        result = await client.call_tool("get_elements_properties")

        assert result.data["status"] == "success"
        assert result.data["selected_elements"] >= 4
        assert result.data["processed_elements"] == 4

        assemblies = json.loads(result.data["assemblies_list"])
        assert isinstance(assemblies, list)
        assert len(assemblies) == 4

        for assembly in assemblies:
            assert isinstance(assembly["guid"], str)
            assert isinstance(assembly["position"], str)
            assert isinstance(assembly["name"], str)
            assert isinstance(assembly["profile"], str)
            assert isinstance(assembly["material"], str)
            assert isinstance(assembly["finish"], str)
            assert isinstance(assembly["tekla_class"], str)


@pytest.mark.asyncio
async def test_get_elements_properties_known_values_for_assemblies(model_objects):
    """
    Tests the `get_elements_properties` MCP tool: known values for assemblies.
    """
    elements_to_select = [
        model_objects["test_wall1"],
        model_objects["test_wall2"],
        model_objects["test_sw1"],
        model_objects["test_slab1"],
    ]
    TeklaModel.select_objects(elements_to_select)
    async with Client(mcp) as client:
        await client.call_tool("select_elements_assemblies_or_main_parts", {"mode": "Assembly"})
        result = await client.call_tool("get_elements_properties")

        assemblies = json.loads(result.data["assemblies_list"])
        names = [a["name"] for a in assemblies]
        profiles = {a["name"]: a["profile"] for a in assemblies}
        classes = {a["name"]: a["tekla_class"] for a in assemblies}
        weights = {a["name"]: a["weight"] for a in assemblies}

        assert "TEST_WALL1" in names
        assert "TEST_WALL2" in names
        assert "TEST_SW1" in names
        assert "TEST_SLAB1" in names

        assert profiles["TEST_WALL1"] == "3000*200"
        assert profiles["TEST_WALL2"] == "3000*200"
        assert profiles["TEST_SW1"] == "3000*200"
        assert profiles["TEST_SLAB1"] == "P20(200X1200)"

        assert classes["TEST_WALL1"] == "1"
        assert classes["TEST_WALL2"] == "1"
        assert classes["TEST_SW1"] == "8"
        assert classes["TEST_SLAB1"] == "3"

        assert weights["TEST_WALL1"] == pytest.approx(2880.0, abs=0.1)
        assert weights["TEST_WALL2"] == pytest.approx(2880.0, abs=0.1)
        assert weights["TEST_SW1"] == pytest.approx(2880.0, abs=50.0)
        assert weights["TEST_SLAB1"] == pytest.approx(1761.8, abs=0.1)


@pytest.mark.asyncio
async def test_get_elements_properties_valid_custom_properties(model_objects):
    """
    Tests the `get_elements_properties` MCP tool: valid custom properties.
    """
    elements_to_select = [
        model_objects["test_wall1"],
        model_objects["test_wall2"],
        model_objects["test_sw1"],
        model_objects["test_slab1"],
    ]
    TeklaModel.select_objects(elements_to_select)
    async with Client(mcp) as client:
        await client.call_tool("select_elements_assemblies_or_main_parts", {"mode": "Assembly"})
        result = await client.call_tool("get_elements_properties", {"custom_props_definitions": ["ASSEMBLY_TOP_LEVEL"]})

        assemblies = json.loads(result.data["assemblies_list"])
        top_levels = {a["name"]: prop["value"] for a in assemblies for prop in a["custom_properties"] if prop["name"] == "ASSEMBLY_TOP_LEVEL"}
        assert top_levels["TEST_WALL1"] == " +3.000"
        assert top_levels["TEST_WALL2"] == " +6.020"
        assert top_levels["TEST_SW1"] == " +3.000"
        assert top_levels["TEST_SLAB1"] == " +3.220"


@pytest.mark.asyncio
async def test_get_elements_properties_invalid_and_missing_custom_properties(model_objects):
    """
    Tests the `get_elements_properties` MCP tool: invalid and missing custom properties.
    """
    elements_to_select = [
        model_objects["test_wall1"],
        model_objects["test_wall2"],
        model_objects["test_sw1"],
        model_objects["test_slab1"],
    ]
    TeklaModel.select_objects(elements_to_select)
    async with Client(mcp) as client:
        await client.call_tool("select_elements_assemblies_or_main_parts", {"mode": "Assembly"})
        result = await client.call_tool(
            "get_elements_properties",
            {"custom_props_definitions": ["ASSEMBLY_TOP_LEVEL", "ASSEMBLY_TOP_LEVELL", "NON_EXISTENT_PROPERTY"]},
        )

        assemblies = json.loads(result.data["assemblies_list"])
        errors = result.data["custom_properties_errors"]
        assert errors

        for assembly in assemblies:
            props = assembly["custom_properties"]

            def get_prop_value(prop_name: str, default="N/A"):
                return next((p["value"] for p in props if p["name"] == prop_name), default)

            assert get_prop_value("ASSEMBLY_TOP_LEVELL") == "N/A"
            assert get_prop_value("NON_EXISTENT_PROPERTY") == "N/A"
            assert get_prop_value("ASSEMBLY_TOP_LEVEL") != "N/A"

        for _, prop_errors in errors.items():
            for key, msg in prop_errors.items():
                assert isinstance(key, str)
                assert isinstance(msg, str)
