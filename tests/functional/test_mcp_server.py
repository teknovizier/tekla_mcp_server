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
from unittest.mock import patch

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from fastmcp import Client

from tekla_mcp_server.mcp_server import mcp

from tekla_mcp_server.models import StringMatchType
from tekla_mcp_server.tekla.loader import Point, Beam, Position, ViewHandler
from tekla_mcp_server.tekla.loader import BinaryFilterExpressionCollection, PartFilterExpressions, ObjectFilterExpressions, TeklaStructuresDatabaseTypeEnum
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tekla.model_object import wrap_model_object
from tekla_mcp_server.mcp_tools import add_filter


@pytest.fixture(autouse=True)
def enable_embeddings():
    """Enable embeddings for these tests that rely on semantic matching."""
    with patch("tekla_mcp_server.tekla.component_props_mapper.is_embeddings_enabled", return_value=True):
        yield


def create_mcp_test_beam(name, start_point, end_point, profile, material="Concrete_Undefined", depth_enum=Position.DepthEnum.FRONT, class_type="1"):
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


def cleanup_mcp_test_objects():
    """
    Utility function to clean up all MCP test objects by name pattern.
    Handles cases where objects were converted or modified during tests.
    """
    model = TeklaModel()

    filter_collection = BinaryFilterExpressionCollection()
    add_filter(filter_collection, ObjectFilterExpressions.Type(), TeklaStructuresDatabaseTypeEnum.PART)
    add_filter(filter_collection, PartFilterExpressions.Name(), "MCP_TEST_", StringMatchType.STARTS_WITH)

    test_objects = model.get_objects_by_filter(filter_collection)

    if test_objects:
        for test_obj in test_objects:
            test_obj.Delete()

        model.commit_changes()


@pytest.fixture(scope="module")
def model_objects():
    """
    Fixture: Test setup and teardown.
    """
    model = TeklaModel()
    test_wall1 = create_mcp_test_beam("MCP_TEST_WALL1", Point(0, 0, 0), Point(2000, 0, 0), "3000*200")
    test_wall2 = create_mcp_test_beam("MCP_TEST_WALL2", Point(0, 0, 3020), Point(2000, 0, 3020), "3000*200")
    test_wall3 = create_mcp_test_beam("MCP_TEST_WALL3", Point(2000, 0, 0), Point(4000, 0, 0), "3000*200")
    test_wall4 = create_mcp_test_beam("MCP_TEST_WALL4", Point(2000, 0, 3020), Point(4000, 0, 3020), "3000*200")

    # Identical walls for testing compare_elements identical comparisons
    test_wall5 = create_mcp_test_beam("MCP_TEST_WALL5", Point(0, 0, 6040), Point(2000, 0, 6040), "3000*200")
    test_wall6 = create_mcp_test_beam("MCP_TEST_WALL6", Point(0, 0, 9060), Point(2000, 0, 9060), "3000*200")
    # Wall with different profile for testing compare_elements different profile
    test_wall7 = create_mcp_test_beam("MCP_TEST_WALL7", Point(0, 0, 12080), Point(2000, 0, 12080), "2000*150")

    test_sw1 = create_mcp_test_beam("MCP_TEST_SW1", Point(4000, 0, 0), Point(6000, 0, 0), "3000*200", class_type="8")
    test_slab1 = create_mcp_test_beam("MCP_TEST_SLAB1", Point(1000, 0, 3020), Point(1000, 6000, 3020), "P20(200X1200)", class_type="3")

    void1 = create_mcp_test_beam("MCP_TEST_VOID_WALL3", Point(3000, 0, 1000), Point(3000, 200, 1000), "D400", class_type="0")
    void2 = create_mcp_test_beam("MCP_TEST_VOID_FLOATING", Point(3000, 0, 10000), Point(3000, 200, 10000), "D400", class_type="0")

    model.commit_changes()

    yield {
        "model": model,
        "walls": [test_wall1, test_wall2, test_wall3, test_wall4],
        "test_wall1": test_wall1,
        "test_wall2": test_wall2,
        "test_wall3": test_wall3,
        "test_wall4": test_wall4,
        "test_wall5": test_wall5,
        "test_wall6": test_wall6,
        "test_wall7": test_wall7,
        "test_sw1": test_sw1,
        "test_slab1": test_slab1,
        "void1": void1,
        "void2": void2,
    }

    cleanup_mcp_test_objects()
    model.commit_changes()


@pytest.mark.asyncio
async def test_put_lifting_anchors_walls(model_objects):
    """
    Validates the `put_components` function for lifting anchors on standard walls.

    Steps:
    - Selects a test wall (`self.test_wall1`).
    - Applies default lifting anchor placement.
    - Ensures that the operation returns a "success" status.
    """
    TeklaModel.select_objects([model_objects["test_wall1"]])

    async with Client(mcp) as client:
        # Use put_components with Lifting Anchor name
        result1 = await client.call_tool("put_components", {"component_name": "Lifting Anchor"})
        assert result1.data["status"] == "success"


@pytest.mark.asyncio
async def test_put_lifting_anchors_sandwich(model_objects):
    """
    Validates the `put_components` function for lifting anchors on sandwich walls.

    Steps:
    - Selects a test sandwich wall (`self.test_sw1`).
    - Applies default lifting anchor placement.
    - Ensures the operation completes successfully.
    """
    TeklaModel.select_objects([model_objects["test_sw1"]])
    async with Client(mcp) as client:
        result = await client.call_tool("put_components", {"component_name": "Lifting Anchor"})
        assert result.data["status"] == "success"


@pytest.mark.asyncio
async def test_remove_lifting_anchors(model_objects):
    """
    Tests the removal of lifting anchors using `remove_components`.

    Steps:
    - Places lifting anchors on `self.test_wall1`.
    - Calls `remove_components()` with Lifting Anchor name.
    - Ensures that the function successfully removes the anchors.
    """
    TeklaModel.select_objects([model_objects["test_wall1"]])
    async with Client(mcp) as client:
        _ = await client.call_tool("put_components", {"component_name": "Lifting Anchor"})
        result2 = await client.call_tool("remove_components", {"component_name": "Lifting Anchor"})
        assert result2.data["status"] == "success"


@pytest.mark.asyncio
async def test_put_components_invalid_component(model_objects):
    """
    Tests `put_components` with an invalid component name.

    Steps:
    - Selects `self.test_wall1`.
    - Calls `put_components` with non-existent component name.
    - Verifies that it returns an error status.
    """
    TeklaModel.select_objects([model_objects["test_wall1"]])
    async with Client(mcp) as client:
        result = await client.call_tool("put_components", {"component_name": "NonExistentComponent"})
        assert result.data["status"] == "error"


@pytest.mark.asyncio
async def test_put_components_with_mapped_properties(model_objects):
    """
    Tests attribute mapping in `put_components` for Border Rebar.

    Steps:
    - Selects `self.test_wall1`.
    - Calls `put_components` with "Border Rebar" and custom_properties using user-friendly names.
    - Verifies successful placement.
    """
    TeklaModel.select_objects([model_objects["test_wall1"]])
    async with Client(mcp) as client:
        result = await client.call_tool("put_components", {"component_name": "Border Rebar", "custom_properties": {"rebar size": "10", "rebar grade": "B500B"}})
        assert result.data["status"] == "success"


@pytest.mark.asyncio
async def test_put_components_without_attribute_mapping(model_objects):
    """
    Tests `put_components` with explicit config attribute names (no mapping needed).

    Steps:
    - Selects `self.test_wall1`.
    - Calls `put_components` with direct config attribute names.
    - Verifies successful placement.
    """
    TeklaModel.select_objects([model_objects["test_wall1"]])
    async with Client(mcp) as client:
        result = await client.call_tool("put_components", {"component_name": "Border Rebar", "custom_properties": {"SBSize_list": "12", "SBGrade_list": "B500B"}})
        assert result.data["status"] == "success"


@pytest.mark.asyncio
async def test_put_components_partial_attribute_mapping(model_objects):
    """
    Tests attribute mapping when some keys map and some don't.

    Steps:
    - Selects `self.test_wall1`.
    - Provides mix of mappable and non-mappable keys.
    - Verifies placement.
    """
    TeklaModel.select_objects([model_objects["test_wall1"]])
    async with Client(mcp) as client:
        result = await client.call_tool("put_components", {"component_name": "Border Rebar", "custom_properties": {"rebar size": "10", "unknown attribute": "value"}})
        assert result.data["status"] == "warning"


@pytest.mark.asyncio
async def test_put_components(model_objects):
    """
    Tests the `put_components` function.

    Steps:
    - Selects `self.test_wall1` and `self.test_wall2`.
    - Adds a predefined custom detail (`DIR_ARR`).
    - Ensures successful placement.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("put_components", {"component_name": "DIR_ARR"})
        assert result.data["status"] == "success"


@pytest.mark.asyncio
async def test_remove_components(model_objects):
    """
    Tests the removal of components using `remove_components`.

    Steps:
    - Places `DIR_ARR` components on `self.test_wall1`.
    - Calls `remove_components()`.
    - Ensures that the function successfully removes the components.
    """
    TeklaModel.select_objects([model_objects["test_wall1"]])
    async with Client(mcp) as client:
        _ = await client.call_tool("put_components", {"component_name": "DIR_ARR"})
        result2 = await client.call_tool("remove_components", {"component_name": "DIR_ARR"})
        assert result2.data["status"] == "success"


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
    Tests the `select_elements_by_filter` function, ensuring it correctly selects elements based on various parameters.

    Steps:
    - Validates behavior when no elements are provided (should return "error").
    - Ensures non-existing classes return "error".
    - Checks selection of specific element types (`WALL`, `TRIBUNE`, etc.).
    """
    async with Client(mcp) as client:
        result = await client.call_tool("select_elements_by_filter", kwargs)
        assert result.data["status"] == expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"element_type": "Wall", "name": "MCP_TEST_WALL2"}, 1),
        ({"element_type": [8], "name": "MCP_TEST_WALL2"}, None),
        ({"element_type": 8, "name": "MCP_TEST_WALL2"}, None),
        ({"element_type": [1], "name": "MCP_TEST_WALL2"}, 1),
        ({"name": "MCP_TEST_WALL2"}, 1),
        ({"name": "EST_WALL2", "name_match_type": "Ends With"}, 1),
        ({"name": "MCP_TEST_WALL2", "name_match_type": "Contains"}, 1),
    ],
)
@pytest.mark.asyncio
async def test_select_elements_by_name(kwargs, expected):
    """
    Steps:
    - Validates selection by type and name, ensuring correct matching methods (`STARTS_WITH`, `ENDS_WITH`, `CONTAINS`).
    """
    async with Client(mcp) as client:
        result = await client.call_tool("select_elements_by_filter", kwargs)
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
        result = await client.call_tool("select_elements_by_filter", {"element_type": "Wall", "profile": "3000*200", "profile_match_type": "Is Equal"})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 6


@pytest.mark.parametrize(
    "name,match_type,expected",
    [
        ("MCP_TEST_WALL", "Contains", "success"),
        ("MCP_TEST_WALL8585", "Starts With", "error"),
        ("MCP_TEST_WALL8585", "Ends With", "error"),
        ("MCP_TEST_WALL", "Is Equal", "error"),
    ],
)
@pytest.mark.asyncio
async def test_select_elements_name_matching(name, match_type, expected):
    """
    Steps:
    - Validates selection by name, ensuring correct matching methods.
    """
    async with Client(mcp) as client:
        result = await client.call_tool("select_elements_by_filter", {"name": name, "name_match_type": match_type})
        assert result.data["status"] == expected


@pytest.mark.asyncio
async def test_select_elements_by_filter_name(model_objects):
    """
    Tests the `select_elements_by_filter_name` function, ensuring it correctly selects elements based on the existing filter settings.

    Steps:
    - Checks selection of specific elements.
    """
    async with Client(mcp) as client:
        # Invalid filter
        result = await client.call_tool("select_elements_by_filter_name", {"filter_name": "non_standard"})
        assert result.data["status"] == "error"

        # Valid filter
        result = await client.call_tool("select_elements_by_filter_name", {"filter_name": "standard"})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"]


@pytest.mark.asyncio
async def test_select_elements_by_guid(model_objects):
    """
    Tests the `select_elements_by_guid` function, ensuring it correctly selects elements based on their GUID.

    Steps:
    - Tests invalid inputs like a single integer or string instead of a list.
    - Checks selection of specific elements.
    """
    async with Client(mcp) as client:
        # Invalid inputs
        result = await client.call_tool("select_elements_by_guid", {"guids": []})
        assert result.data["status"] == "error"

        result = await client.call_tool("select_elements_by_guid", {"guids": [""]})
        assert result.data["status"] == "error"

        result = await client.call_tool("select_elements_by_guid", {"guids": ["MCP_TEST_WALL2"]})
        assert result.data["status"] == "error"

        # Valid single GUID
        wall2_guid = model_objects["test_wall2"].Identifier.GUID.ToString()
        result = await client.call_tool("select_elements_by_guid", {"guids": [wall2_guid]})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 1

        # Valid multiple GUIDs
        wall1_guid = model_objects["test_wall1"].Identifier.GUID.ToString()
        result = await client.call_tool("select_elements_by_guid", {"guids": [wall1_guid, wall2_guid]})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2


@pytest.mark.parametrize("mode, expected_count", [("Assembly", 2), ("Main Part", 2)])
@pytest.mark.asyncio
async def test_select_elements_assemblies(model_objects, mode, expected_count):
    """
    Tests the `select_elements_assemblies_or_main_parts` function to ensure correct assembly selection.

    Steps:
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
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
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
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
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
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
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
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
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
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
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
    - Calls a tool.
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
async def test_redraw_view():
    """
    Tests that `redraw_view` function can be run.
    """
    async with Client(mcp) as client:
        result = await client.call_tool("redraw_view")
        assert result.data["status"] == "success"


@pytest.mark.asyncio
async def test_show_only_selected(model_objects):
    """
    Tests that `show_only_selected` function can be run.

    Steps:
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
    - Calls a tool.
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
async def test_hide_selected_parts(model_objects):
    """
    Tests that `hide_selected` function can hide selected parts.

    Steps:
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
    - Calls `hide_selected` tool.
    - Verifies success and redraws views.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("hide_selected")
        assert result.data["status"] == "success"
        assert result.data["hidden_elements"] == 2

        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)


@pytest.mark.asyncio
async def test_color_selected(model_objects):
    """
    Tests that `color_selected` function can color selected parts.

    Steps:
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
    - Calls `color_selected` tool with red color.
    - Verifies success and redraws views.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("color_selected", {"red": 255, "green": 0, "blue": 0})
        assert result.data["status"] == "success"
        assert result.data["colored_elements"] == 2

        view_enum = ViewHandler.GetAllViews()
        while view_enum.MoveNext():
            ViewHandler.RedrawView(view_enum.Current)


@pytest.mark.asyncio
async def test_cut_elements_with_zero_class_parts(model_objects):
    """
    Tests the `cut_elements_with_zero_class_parts` tool.

    Steps:
    1. Selects `MCP_TEST_WALL3` and `MCP_TEST_WALL4`.
    2. Run the cut tool.
    3. Verifies success.
    """
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    async with Client(mcp) as client:
        result = await client.call_tool("cut_elements_with_zero_class_parts", {"delete_cutting_parts": False})
        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2
        assert result.data["processed_elements"] == 1  # Only `MCP_TEST_WALL1` should be cut
        assert result.data["performed_cuts"] >= 1  # At least one cut should be applied


@pytest.mark.asyncio
async def test_convert_cut_parts_to_real_parts_without_cuts(model_objects):
    """
    Tests the `convert_cut_parts_to_real_parts` function when no cuts are present.

    Steps:
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
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
    - Selects `MCP_TEST_WALL3`, which is intersected by `MCP_TEST_VOID_WALL3`.
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
    - Selects `MCP_TEST_WALL1` and `MCP_TEST_WALL2`.
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
        initial_udas = {"MCP_TEST_UDA1": "MCP_TEST_VALUE_1", "MCP_TEST_UDA2": "MCP_TEST_VALUE_2"}
        result = await client.call_tool("set_elements_udas", {"udas": initial_udas, "mode": "Overwrite Existing Values"})
        assert result.data["status"] == "success"
        assert result.data["processed_elements"] == 1
        assert result.data["updated_attributes"] == 2

        wall = wrap_model_object(wall)
        value = wall.get_user_property("MCP_TEST_UDA1", str)
        assert value == "MCP_TEST_VALUE_1"
        value = wall.get_user_property("MCP_TEST_UDA2", str)
        assert value == "MCP_TEST_VALUE_2"

        # KEEP mode: should not overwrite
        update_attempt = {"MCP_TEST_UDA1": "MCP_TEST_VALUE_1_UPD", "MCP_TEST_UDA2": "MCP_TEST_VALUE_2_UPD"}
        result = await client.call_tool("set_elements_udas", {"udas": update_attempt, "mode": "Keep Existing Values"})

        value = wall.get_user_property("MCP_TEST_UDA1", str)
        assert value == "MCP_TEST_VALUE_1"
        value = wall.get_user_property("MCP_TEST_UDA2", str)
        assert value == "MCP_TEST_VALUE_2"

        # OVERWRITE mode: now it should update
        result = await client.call_tool("set_elements_udas", {"udas": update_attempt, "mode": "Overwrite Existing Values"})

        value = wall.get_user_property("MCP_TEST_UDA1", str)
        assert value == "MCP_TEST_VALUE_1_UPD"
        value = wall.get_user_property("MCP_TEST_UDA2", str)
        assert value == "MCP_TEST_VALUE_2_UPD"


@pytest.mark.asyncio
async def test_get_elements_udas_empty(model_objects):
    """
    Tests the `get_elements_udas` MCP tool: empty UDAs.

    Steps:
    - Selects `MCP_TEST_SW1` and `MCP_TEST_SLAB1`.
    - Calls `get_elements_udas`.
    - Verifies that no UDAs are returned.
    """
    elements_to_select = [
        model_objects["test_sw1"],
        model_objects["test_slab1"],
    ]
    TeklaModel.select_objects(elements_to_select)
    async with Client(mcp) as client:
        result = await client.call_tool("get_elements_udas")

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

    Steps:
    - Selects `MCP_TEST_WALL1`, `MCP_TEST_WALL2`, `MCP_TEST_SW1`, and `MCP_TEST_SLAB1`.
    - Calls `select_elements_assemblies_or_main_parts` with "Assembly" mode.
    - Calls `get_elements_properties`.
    - Verifies the response contains expected assembly data.
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

    Steps:
    - Selects `MCP_TEST_WALL1`, `MCP_TEST_WALL2`, `MCP_TEST_SW1`, and `MCP_TEST_SLAB1`.
    - Calls `select_elements_assemblies_or_main_parts` with "Assembly" mode.
    - Calls `get_elements_properties`.
    - Verifies the returned values match expected profiles, classes, and weights.
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

        assert "MCP_TEST_WALL1" in names
        assert "MCP_TEST_WALL2" in names
        assert "MCP_TEST_SW1" in names
        assert "MCP_TEST_SLAB1" in names

        assert profiles["MCP_TEST_WALL1"] == "3000*200"
        assert profiles["MCP_TEST_WALL2"] == "3000*200"
        assert profiles["MCP_TEST_SW1"] == "3000*200"
        assert profiles["MCP_TEST_SLAB1"] == "P20(200X1200)"

        assert classes["MCP_TEST_WALL1"] == "1"
        assert classes["MCP_TEST_WALL2"] == "1"
        assert classes["MCP_TEST_SW1"] == "8"
        assert classes["MCP_TEST_SLAB1"] == "3"

        assert weights["MCP_TEST_WALL1"] == pytest.approx(2880.0, abs=0.1)
        assert weights["MCP_TEST_WALL2"] == pytest.approx(2880.0, abs=0.1)
        assert weights["MCP_TEST_SW1"] == pytest.approx(2880.0, abs=50.0)
        assert weights["MCP_TEST_SLAB1"] == pytest.approx(1761.8, abs=0.1)


@pytest.mark.asyncio
async def test_get_elements_properties_valid_custom_properties(model_objects):
    """
    Tests the `get_elements_properties` MCP tool: valid custom properties.

    Steps:
    - Selects `MCP_TEST_WALL1`, `MCP_TEST_WALL2`, `MCP_TEST_SW1`, and `MCP_TEST_SLAB1`.
    - Calls `select_elements_assemblies_or_main_parts` with "Assembly" mode.
    - Calls `get_elements_properties` with custom property definition "ASSEMBLY_TOP_LEVEL".
    - Verifies the custom property values are correctly retrieved.
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
        assert top_levels["MCP_TEST_WALL1"] == " +3.000"
        assert top_levels["MCP_TEST_WALL2"] == " +6.020"
        assert top_levels["MCP_TEST_SW1"] == " +3.000"
        assert top_levels["MCP_TEST_SLAB1"] == " +3.220"


@pytest.mark.asyncio
async def test_get_elements_properties_invalid_and_missing_custom_properties(model_objects):
    """
    Tests the `get_elements_properties` MCP tool: invalid and missing custom properties.

    Steps:
    - Selects `MCP_TEST_WALL1`, `MCP_TEST_WALL2`, `MCP_TEST_SW1`, and `MCP_TEST_SLAB1`.
    - Calls `select_elements_assemblies_or_main_parts` with "Assembly" mode.
    - Calls `get_elements_properties` with a mix of valid, invalid, and non-existent custom properties.
    - Verifies that invalid properties return "N/A" and errors are captured.
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

        for assembly in assemblies:
            props = assembly["custom_properties"]

            def get_prop_value(prop_name: str, default="N/A"):
                return next((p["value"] for p in props if p["name"] == prop_name), default)

            assert get_prop_value("ASSEMBLY_TOP_LEVELL") == "N/A"
            assert get_prop_value("NON_EXISTENT_PROPERTY") == "N/A"
            assert get_prop_value("ASSEMBLY_TOP_LEVEL") != "N/A"

        errors = result.data["invalid_custom_property_definitions"]
        assert errors


@pytest.mark.asyncio
async def test_get_elements_cut_parts_with_cuts(model_objects):
    """
    Tests the `get_elements_cut_parts` MCP tool: elements with cut parts.

    Steps:
    1. Selects `test_wall3` which has a boolean cut from `void1`.
    2. Calls `get_elements_cut_parts`.
    3. Verifies the response contains the expected cut parts data.
    """
    TeklaModel.select_objects([model_objects["test_wall3"]])
    async with Client(mcp) as client:
        result = await client.call_tool("get_elements_cut_parts")

        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 1
        assert result.data["processed_elements"] == 1
        assert result.data["total_cut_parts"] >= 1

        cut_parts = json.loads(result.data["cut_parts_list"])
        assert isinstance(cut_parts, list)
        assert len(cut_parts) >= 1

        # Verify the structure of cut parts
        for cut_part in cut_parts:
            assert "profile" in cut_part
            assert "count" in cut_part
            assert isinstance(cut_part["profile"], str)
            assert isinstance(cut_part["count"], int)


@pytest.mark.asyncio
async def test_get_elements_cut_parts_without_cuts(model_objects):
    """
    Tests the `get_elements_cut_parts` MCP tool: elements without cut parts.

    Steps:
    1. Selects `test_wall1` which has no boolean cuts.
    2. Calls `get_elements_cut_parts`.
    3. Verifies the response indicates no cut parts were found.
    """
    TeklaModel.select_objects([model_objects["test_wall1"]])
    async with Client(mcp) as client:
        result = await client.call_tool("get_elements_cut_parts")

        assert result.data["status"] == "warning"
        assert result.data["selected_elements"] == 1
        assert result.data["processed_elements"] == 1
        assert result.data["total_cut_parts"] == 0

        cut_parts = json.loads(result.data["cut_parts_list"])
        assert isinstance(cut_parts, list)
        assert len(cut_parts) == 0


@pytest.mark.asyncio
async def test_get_elements_cut_parts_multiple_elements(model_objects):
    """
    Tests the `get_elements_cut_parts` MCP tool: multiple elements with cuts.

    Steps:
    1. Selects `test_wall3` and `test_wall4` where only `test_wall3` has a cut.
    2. Calls `get_elements_cut_parts`.
    3. Verifies the response correctly counts cuts across all selected elements.
    """
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    async with Client(mcp) as client:
        result = await client.call_tool("get_elements_cut_parts")

        assert result.data["status"] == "success"
        assert result.data["selected_elements"] == 2
        assert result.data["processed_elements"] == 2
        assert result.data["total_cut_parts"] >= 1

        cut_parts = json.loads(result.data["cut_parts_list"])
        assert isinstance(cut_parts, list)
        assert len(cut_parts) >= 1


@pytest.mark.asyncio
async def test_compare_identical_parts(model_objects):
    """
    Compare two identical parts - should report as identical.

    Steps:
    1. Selects test_wall5 and test_wall6 (identical profile/class).
    2. Calls compare_elements.
    3. Verifies identical is True.
    """
    TeklaModel.select_objects([model_objects["test_wall5"], model_objects["test_wall6"]])
    async with Client(mcp) as client:
        result = await client.call_tool("compare_elements")

        assert result.data["status"] == "success"
        assert result.data["identical"] is True
        assert result.data["message"] == "Elements are identical"
        assert "part_a_snapshot" not in result.data
        assert "part_b_snapshot" not in result.data


@pytest.mark.asyncio
async def test_compare_different_parts_different_profile(model_objects):
    """
    Compare two parts with different profiles - should report differences.

    Steps:
    1. Selects test_wall1 (3000*200) and test_wall7 (2000*150).
    2. Calls compare_elements.
    3. Verifies identical is False.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall7"]])
    async with Client(mcp) as client:
        result = await client.call_tool("compare_elements")

        assert result.data["status"] == "success"
        assert result.data["identical"] is False
        assert result.data["message"] == "Elements have differences"
        assert "part_a_snapshot" in result.data
        assert "part_b_snapshot" in result.data


@pytest.mark.asyncio
async def test_compare_different_parts_different_position(model_objects):
    """
    Compare two parts with different positions - should report differences.

    Steps:
    1. Selects test_wall1 and test_wall2 (different Z positions).
    2. Calls compare_elements.
    3. Verifies identical is False.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        result = await client.call_tool("compare_elements")

        assert result.data["status"] == "success"
        assert result.data["identical"] is False


@pytest.mark.asyncio
async def test_compare_identical_assemblies(model_objects):
    """
    Compare two identical assemblies - should report as identical.

    Steps:
    1. Selects test_wall5 and test_wall6.
    2. Calls select_elements_assemblies_or_main_parts with "Assembly" mode.
    3. Calls compare_elements.
    4. Verifies identical is True.
    """
    TeklaModel.select_objects([model_objects["test_wall5"], model_objects["test_wall6"]])
    async with Client(mcp) as client:
        await client.call_tool("select_elements_assemblies_or_main_parts", {"mode": "Assembly"})
        result = await client.call_tool("compare_elements")

        assert result.data["status"] == "success"
        assert result.data["identical"] is True
        assert result.data["message"] == "Elements are identical"


@pytest.mark.asyncio
async def test_compare_different_assemblies(model_objects):
    """
    Compare two different assemblies - should report differences.

    Steps:
    1. Selects test_wall1 and test_wall2.
    2. Calls select_elements_assemblies_or_main_parts with "Assembly" mode.
    3. Calls compare_elements.
    4. Verifies identical is False.
    """
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    async with Client(mcp) as client:
        await client.call_tool("select_elements_assemblies_or_main_parts", {"mode": "Assembly"})
        result = await client.call_tool("compare_elements")

        assert result.data["status"] == "success"
        assert result.data["identical"] is False


@pytest.mark.asyncio
async def test_compare_three_elements(model_objects):
    """
    Select three elements - should error (requires exactly 2).

    Steps:
    1. Selects test_wall1, test_wall2, test_wall3.
    2. Calls compare_elements.
    3. Verifies error status with message about more than two elements.
    """
    TeklaModel.select_objects(
        [
            model_objects["test_wall1"],
            model_objects["test_wall2"],
            model_objects["test_wall3"],
        ]
    )
    async with Client(mcp) as client:
        result = await client.call_tool("compare_elements")

        assert result.data["status"] == "error"
        assert "More than two elements" in result.data["message"]


@pytest.mark.asyncio
async def test_compare_single_element(model_objects):
    """
    Select one element - should error (requires exactly 2).

    Steps:
    1. Selects only test_wall1.
    2. Calls compare_elements.
    3. Verifies error status with message about only one element.
    """
    TeklaModel.select_objects([model_objects["test_wall1"]])
    async with Client(mcp) as client:
        result = await client.call_tool("compare_elements")

        assert result.data["status"] == "error"
        assert "Only one element" in result.data["message"]
