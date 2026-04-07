"""
Functional tests for Tekla operations via MCP server.

This module validates end-to-end behavior of component placement, selection, and modification
within a Tekla Structures model using the MCP server interface. It interacts with real model
objects and calls tools directly from providers (FastMCP 3.0 callable decorators pattern).

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.

Tested modules:
- providers/selection_provider.py
- providers/view_provider.py
- providers/properties_provider.py
- providers/components_provider.py
- providers/operations_provider.py
"""

import json
import os

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import StringMatchType
from tekla_mcp_server.providers.selection_provider import (
    select_elements_by_filter,
    select_elements_by_filter_name,
    select_elements_by_guid,
    select_elements_assemblies_or_main_parts,
)
from tekla_mcp_server.providers.view_provider import (
    draw_elements_labels,
    zoom_to_selection,
    redraw_view,
    show_only_selected,
    hide_selected,
    color_selected,
    apply_view_filter,
)
from tekla_mcp_server.providers.properties_provider import (
    get_elements_properties,
    set_elements_properties,
    get_elements_cut_parts,
    compare_elements,
)
from tekla_mcp_server.providers.components_provider import put_components, remove_components, get_components, modify_components
from tekla_mcp_server.providers.operations_provider import (
    cut_elements_with_zero_class_parts,
    convert_cut_parts_to_real_parts,
    run_macro,
)
from tekla_mcp_server.tekla.loader import Point, Beam, Position, ViewHandler
from tekla_mcp_server.tekla.loader import BinaryFilterExpressionCollection, PartFilterExpressions, ObjectFilterExpressions, TeklaStructuresDatabaseTypeEnum
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tools.selection import add_filter


def create_mcp_test_beam(name, start_point, end_point, profile, material="Concrete_Undefined", depth_enum=Position.DepthEnum.FRONT, class_type="1"):
    """Utility function to create a beam."""
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
    """Utility function to clean up all MCP test objects by name pattern."""
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
    """Fixture: Test setup and teardown."""
    model = TeklaModel()
    test_wall1 = create_mcp_test_beam("MCP_TEST_WALL1", Point(0, 0, 0), Point(2000, 0, 0), "3000*200")
    test_wall2 = create_mcp_test_beam("MCP_TEST_WALL2", Point(0, 0, 3020), Point(2000, 0, 3020), "3000*200")
    test_wall3 = create_mcp_test_beam("MCP_TEST_WALL3", Point(2000, 0, 0), Point(4000, 0, 0), "3000*200")
    test_wall4 = create_mcp_test_beam("MCP_TEST_WALL4", Point(2000, 0, 3020), Point(4000, 0, 3020), "3000*200")

    test_wall5 = create_mcp_test_beam("MCP_TEST_WALL5", Point(0, 0, 6040), Point(2000, 0, 6040), "3000*200")
    test_wall6 = create_mcp_test_beam("MCP_TEST_WALL5", Point(0, 0, 9060), Point(2000, 0, 9060), "3000*200")
    test_wall7 = create_mcp_test_beam("MCP_TEST_WALL7", Point(0, 0, 12080), Point(2000, 0, 12080), "2000*150")
    test_wall8 = create_mcp_test_beam("MCP_TEST_WALL8", Point(0, 200, 0), Point(2000, 200, 0), "3000*200")

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
        "test_wall8": test_wall8,
        "test_sw1": test_sw1,
        "test_slab1": test_slab1,
        "void1": void1,
        "void2": void2,
    }

    cleanup_mcp_test_objects()
    model.commit_changes()


# Components Tests
def test_put_lifting_anchors_walls(model_objects):
    """Tests put_components for lifting anchors on standard walls."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = put_components(component_name="Lifting Anchor")
    assert result["status"] == "success"


def test_put_lifting_anchors_sandwich(model_objects):
    """Tests put_components for lifting anchors on sandwich walls."""
    TeklaModel.select_objects([model_objects["test_sw1"]])
    result = put_components(component_name="Lifting Anchor")
    assert result["status"] == "success"


def test_remove_lifting_anchors(model_objects):
    """Tests remove_components for lifting anchors."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    put_components(component_name="Lifting Anchor")
    result = remove_components(component_name="Lifting Anchor")
    assert result["status"] == "success"


def test_put_components_invalid_component(model_objects):
    """Tests put_components with an invalid component name."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = put_components(component_name="NonExistentComponent")
    assert result["status"] == "error"


def test_put_components_with_custom_properties(model_objects):
    """Tests put_components for Mesh Bars with custom properties."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    result = put_components(component_name="MeshBars", custom_properties={"TopAsBott": "0"})
    assert result["status"] == "success"


def test_remove_components(model_objects):
    """Tests remove_components function."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    put_components(component_name="MeshBars")
    result = remove_components(component_name="MeshBars")
    assert result["status"] == "success"


def test_get_components_returns_components(model_objects):
    """Tests get_components returns component info for elements with components."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    put_components(component_name="MeshBars")
    result = get_components()
    assert result["status"] == "success"
    assert result["total_elements"] == 1
    assert result["total_components"] >= 1
    comp = result["elements"][0]["components"][0]
    assert comp["name"] == "MeshBars"
    assert comp["supported"] is True
    assert comp["config_key"] == "mesh_bars"
    assert comp["schema"] is not None


def test_get_components_empty_selection(model_objects):
    """Tests get_components with no elements selected."""
    TeklaModel.select_objects([])
    result = get_components()
    assert result["status"] == "error"


def test_get_components_supported_component(model_objects):
    """Tests get_components marks supported components correctly."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    put_components(component_name="MeshBars")
    result = get_components()
    assert result["status"] == "success"
    assert result["total_components"] >= 1
    comp_names = [c["name"] for c in result["elements"][0]["components"]]
    if "MeshBars" in comp_names:
        comp = next(c for c in result["elements"][0]["components"] if c["name"] == "MeshBars")
        assert comp["supported"] is True
        assert comp["config_key"] == "mesh_bars"
        assert comp["schema"] is not None


def test_modify_components_success(model_objects):
    """Tests modify_components modifies attributes on existing components."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    put_components(component_name="MeshBars")
    result = modify_components(
        component_name="MeshBars",
        custom_properties={"TopAsBott": 1, "NumberBarsBottSec": 4, "SpacBarsBottSec": 300.0, "BottDiaSec": "12"},
    )
    assert result["status"] == "success"
    assert result["processed_components"] >= 1

    result = get_components()
    comp = next(c for c in result["elements"][0]["components"] if c["name"] == "MeshBars")
    print(comp["attributes"])
    assert comp["attributes"]["TopAsBott"] == 1
    assert comp["attributes"]["NumberBarsBottSec"] == 4
    assert comp["attributes"]["SpacBarsBottSec"] == 300.0
    assert comp["attributes"]["BottDiaSec"] == "12"


def test_modify_components_no_matching_component(model_objects):
    """Tests modify_components returns error when component not found."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    result = modify_components(
        component_name="NonExistingComponent",
        custom_properties={"RecessLength": 200.0},
    )
    assert result["status"] == "error"
    assert result["processed_components"] == 0


def test_modify_components_invalid_properties(model_objects):
    """Tests modify_components returns error for invalid property names."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    put_components(component_name="MeshBars")
    result = modify_components(
        component_name="MeshBars",
        custom_properties={"NonExistentProperty": 123},
    )
    assert result["status"] == "error"



# Selection Tests
def test_select_elements_by_filter_name(model_objects):
    """Tests select_elements_by_filter_name function."""
    result = select_elements_by_filter_name(filter_name="non_standard")
    assert result["status"] == "error"

    result = select_elements_by_filter_name(filter_name="standard")
    assert result["status"] == "success"
    assert result["selected_elements"]


def test_select_elements_by_filter_no_filters_returns_error(model_objects):
    """Tests select_elements_by_filter when called without any filter parameters."""
    result = select_elements_by_filter()
    assert result["status"] == "error"


@pytest.mark.parametrize(
    "element_type,tekla_classes",
    [
        ("Wall", 1),
        ("Wall", [1]),
        ("Wall", [1, 8]),
        (None, 1),
    ],
)
def test_select_elements_by_filter_element_type_and_tekla_classes(model_objects, element_type, tekla_classes):
    """Tests select_elements_by_filter with element_type and tekla_classes parameters."""
    kwargs = {}
    if element_type:
        kwargs["element_type"] = element_type
    if tekla_classes:
        kwargs["tekla_classes"] = tekla_classes

    result = select_elements_by_filter(**kwargs)
    assert result["status"] == "success"


@pytest.mark.parametrize("invalid_element_type", ["InvalidType", "NonExistent", "FakeWall"])
def test_select_elements_by_filter_invalid_element_type(model_objects, invalid_element_type):
    """Tests select_elements_by_filter with invalid element_type values."""
    result = select_elements_by_filter(element_type=invalid_element_type)
    assert result["status"] == "error"


@pytest.mark.parametrize(
    "field,match_type,value",
    [
        ("name", "Contains", "MCP"),
        ("name", "Starts With", "MCP_TEST"),
        ("name", "Ends With", "WALL1"),
        ("name", "Not Contains", "INVALID"),
        ("name", "Is Not Equal", "OTHER_NAME"),
        ("profile", "Contains", "3000"),
        ("material", "Contains", "Concrete"),
        ("finish", "Is Not Equal", "PAINT"),
        ("phase", "Is Equal", "1"),
    ],
)
def test_select_elements_by_filter_standard_string_filters(model_objects, field, value, match_type):
    """Tests select_elements_by_filter with various standard string filter conditions."""
    result = select_elements_by_filter(
        element_type="Wall",
        standard_string_filters={field: {"conditions": {"match_type": match_type, "value": value}}},
    )
    assert result["status"] == "success"


@pytest.mark.parametrize("logic", ["AND", "OR"])
def test_select_elements_by_filter_string_multiple_conditions(model_objects, logic):
    """Tests select_elements_by_filter with multiple string filter conditions."""
    result = select_elements_by_filter(
        element_type="Wall",
        standard_string_filters={
            "name": {
                "conditions": [
                    {"match_type": "Contains", "value": "T"},
                    {"match_type": "Contains", "value": "E"},
                ],
                "logic": logic,
            }
        },
    )
    assert result["status"] == "success"


def test_select_elements_by_filter_custom_string_filters(model_objects):
    """Tests select_elements_by_filter with custom string filters."""
    kwargs = {
        "element_type": "Wall",
        "custom_string_filters": {},
    }
    result = select_elements_by_filter(**kwargs)
    assert result["status"] == "success"


@pytest.mark.parametrize(
    "prop",
    [
        {"name": "HEIGHT", "match_type": "Greater Than", "value": 2000.0},
        {"name": "WEIGHT", "match_type": "Greater Than", "value": 300.0},
        {"name": "LENGTH", "match_type": "Greater Than", "value": 1500.0},
    ],
)
def test_select_elements_by_filter_numeric_single_condition(model_objects, prop):
    """Tests select_elements_by_filter with numeric filter conditions."""
    result = select_elements_by_filter(
        element_type="Wall",
        custom_numeric_filters={
            prop["name"]: {
                "conditions": {
                    "match_type": prop["match_type"],
                    "value": prop["value"],
                }
            }
        },
    )
    assert result["status"] == "success"


@pytest.mark.parametrize("logic", ["AND", "OR"])
def test_select_elements_by_filter_numeric_multiple_conditions(model_objects, logic):
    """Tests select_elements_by_filter with multiple numeric conditions."""
    result = select_elements_by_filter(
        element_type="Wall",
        custom_numeric_filters={
            "HEIGHT": {
                "conditions": [
                    {"match_type": "Greater Than", "value": 1000.0},
                    {"match_type": "Smaller Than", "value": 5000.0},
                ],
                "logic": logic,
            }
        },
    )
    assert result["status"] == "success"


@pytest.mark.parametrize("combine_with", ["AND", "OR"])
def test_select_elements_by_filter_combined_filters(model_objects, combine_with):
    """Tests select_elements_by_filter with combined string and numeric filters."""
    result = select_elements_by_filter(
        element_type="Wall",
        standard_string_filters={"name": {"conditions": {"match_type": "Contains", "value": "MCP"}}},
        custom_numeric_filters={"HEIGHT": {"conditions": {"match_type": "Greater Than", "value": 2000.0}}},
        combine_with=combine_with,
    )
    assert result["status"] == "success"


@pytest.mark.parametrize("invalid_logic", ["and", "or", "XOR", "", "NOT"])
def test_select_elements_by_filter_invalid_combine_with(model_objects, invalid_logic):
    """Tests select_elements_by_filter with invalid combine_with values."""
    result = select_elements_by_filter(
        element_type="Wall",
        standard_string_filters={"name": {"conditions": {"match_type": "Contains", "value": "MCP"}}},
        combine_with=invalid_logic,
    )
    assert result["status"] == "error"


def test_select_elements_by_guid(model_objects):
    """Tests select_elements_by_guid function."""
    result = select_elements_by_guid(guids=[])
    assert result["status"] == "error"

    result = select_elements_by_guid(guids=[""])
    assert result["status"] == "error"

    result = select_elements_by_guid(guids=["MCP_TEST_WALL2"])
    assert result["status"] == "error"

    wall2_guid = model_objects["test_wall2"].Identifier.GUID.ToString()
    result = select_elements_by_guid(guids=[wall2_guid])
    assert result["status"] == "success"
    assert result["selected_elements"] == 1

    wall1_guid = model_objects["test_wall1"].Identifier.GUID.ToString()
    result = select_elements_by_guid(guids=[wall1_guid, wall2_guid])
    assert result["status"] == "success"
    assert result["selected_elements"] == 2


@pytest.mark.parametrize("mode,expected_count", [("Assembly", 2), ("Main Part", 2)])
def test_select_elements_assemblies(model_objects, mode, expected_count):
    """Tests select_elements_assemblies_or_main_parts function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = select_elements_assemblies_or_main_parts(mode=mode)
    assert result["status"] == "success"
    assert result["selected_elements"] == expected_count


# View Tests
def test_draw_elements_labels(model_objects):
    """Tests draw_elements_labels function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = draw_elements_labels()
    assert result["status"] == "success"
    assert result["selected_elements"] == 2

    view_enum = ViewHandler.GetAllViews()
    while view_enum.MoveNext():
        ViewHandler.RedrawView(view_enum.Current)


def test_draw_elements_labels_with_label(model_objects):
    """Tests draw_elements_labels with specific label."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = draw_elements_labels(label="Profile")
    assert result["status"] == "success"
    assert result["selected_elements"] == 2


def test_draw_elements_labels_with_valid_custom_label(model_objects):
    """Tests draw_elements_labels with custom_label."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = draw_elements_labels(label="Custom", custom_label="AREA_NET")
    assert result["status"] == "success"


def test_draw_elements_labels_with_invalid_custom_label(model_objects):
    """Tests draw_elements_labels with invalid custom_label."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = draw_elements_labels(label="Custom", custom_label="InvalidProperty")
    assert result["status"] == "error"


def test_zoom_to_selection(model_objects):
    """Tests zoom_to_selection function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = zoom_to_selection()
    assert result["status"] == "success"


def test_redraw_view():
    """Tests redraw_view function."""
    result = redraw_view()
    assert result["status"] == "success"


def test_apply_view_filter():
    """Tests apply_view_filter function."""
    result = apply_view_filter(filter_name="standard")
    assert result["status"] == "success"
    assert result["filter_name"] == "standard"


def test_show_only_selected(model_objects):
    """Tests show_only_selected function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = show_only_selected()
    assert result["status"] == "success"


def test_hide_selected_parts(model_objects):
    """Tests hide_selected function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = hide_selected()
    assert result["status"] == "success"


def test_color_selected(model_objects):
    """Tests color_selected function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = color_selected(red=255, green=0, blue=0)
    assert result["status"] == "success"


# Operations Tests
def test_cut_elements_with_zero_class_parts(model_objects):
    """Tests cut_elements_with_zero_class_parts tool."""
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    result = cut_elements_with_zero_class_parts(delete_cutting_parts=False)
    assert result["status"] == "success"
    assert result["selected_elements"] == 2


def test_convert_cut_parts_to_real_parts_without_cuts(model_objects):
    """Tests convert_cut_parts_to_real_parts when no cuts are present."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = convert_cut_parts_to_real_parts()
    assert result["status"] == "error"


def test_convert_cut_parts_to_real_parts_with_cut(model_objects):
    """Tests convert_cut_parts_to_real_parts when a valid cut part exists."""
    TeklaModel.select_objects([model_objects["test_wall3"]])
    result = convert_cut_parts_to_real_parts()
    assert result["status"] == "success"


def test_run_macro_nonexistent():
    """Tests that run_macro returns an error for non-existent macro."""
    result = run_macro(macro_name="NonExistentMacro.cs")
    assert result["status"] == "error"


# Properties Tests
def test_set_elements_properties(model_objects):
    """Tests set_elements_properties function with assemblies."""
    TeklaModel.select_objects([model_objects["test_wall7"]])

    result = set_elements_properties(name="MCP_TEST_NEW_NAME", profile="2000*150", material="C16/20", tekla_class="8", finish="FR")
    assert result["status"] == "success"
    assert result["processed_elements"] == 1
    assert result["modified_elements"] == 1
    assert result["changes_applied"]["name"] == 1
    assert result["changes_applied"]["profile"] == 1
    assert result["changes_applied"]["material"] == 1
    assert result["changes_applied"]["tekla_class"] == 1
    assert result["changes_applied"]["finish"] == 1

    TeklaModel.select_objects([model_objects["test_wall7"]])
    result = get_elements_properties()
    parts = json.loads(result["parts_list"])
    assert len(parts) == 1
    assert parts[0]["name"] == "MCP_TEST_NEW_NAME"
    assert parts[0]["profile"] == "2000*150"
    assert parts[0]["material"] == "C16/20"
    assert parts[0]["tekla_class"] == "8"
    assert parts[0]["finish"] == "FR"


def test_set_elements_properties_with_user_properties(model_objects):
    """Tests set_elements_properties with user_properties (UDAs)."""
    TeklaModel.select_objects([model_objects["test_wall1"]])

    user_props = {"MCP_TEST_UDA1": "TestValue1", "MCP_TEST_UDA2": "TestValue2"}
    result = set_elements_properties(user_properties=user_props)
    assert result["status"] == "success"
    assert result["processed_elements"] == 1
    assert result["changes_applied"]["udas"] == 2


def test_get_elements_properties_contains_required_fields(model_objects):
    """Tests that get_elements_properties returns all required fields for parts."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Part")
    result = get_elements_properties()

    parts = json.loads(result["parts_list"])
    assert len(parts) >= 1
    props = parts[0]

    assert "position" in props
    assert "guid" in props
    assert "name" in props
    assert "phase" in props
    assert "profile" in props
    assert "material" in props
    assert "finish" in props
    assert "tekla_class" in props
    assert "user_properties" in props
    assert "report_properties" in props


def test_get_elements_properties_with_report_props_definitions(model_objects):
    """Tests get_elements_properties with custom report property definitions."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")

    result = get_elements_properties(report_props_definitions=["ASSEMBLY_POS"])

    assemblies = json.loads(result["assemblies_list"])
    assert len(assemblies) == 2
    for assembly in assemblies:
        assert "position" in assembly
        assert assembly["position"] is not None


def test_set_elements_properties_all_part_properties(model_objects):
    """Tests setting ALL part properties and verifying all are read back correctly."""
    TeklaModel.select_objects([model_objects["test_wall1"]])

    result = set_elements_properties(
        name="MCP_PART_ALL_TEST",
        profile="2500*300",
        material="C50/60",
        tekla_class="9",
        finish="R",
        phase=2,
    )
    assert result["status"] == "success"
    assert result["modified_elements"] == 1
    assert result["changes_applied"]["name"] == 1
    assert result["changes_applied"]["profile"] == 1
    assert result["changes_applied"]["material"] == 1
    assert result["changes_applied"]["tekla_class"] == 1
    assert result["changes_applied"]["finish"] == 1
    assert result["changes_applied"]["phase"] == 1

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Part")
    result = get_elements_properties()
    parts = json.loads(result["parts_list"])
    assert len(parts) >= 1
    assert parts[0]["name"] == "MCP_PART_ALL_TEST"
    assert parts[0]["profile"] == "2500*300"
    assert parts[0]["material"] == "C50/60"
    assert parts[0]["tekla_class"] == "9"
    assert parts[0]["finish"] == "R"
    assert parts[0]["phase"] == 2


def test_set_elements_properties_all_assembly_properties(model_objects):
    """Tests setting ALL assembly properties and verifying all are read back correctly."""
    TeklaModel.select_objects([model_objects["test_wall1"]])

    result = set_elements_properties(
        name="MCP_ASSEMBLY_ALL_TEST",
        assembly_prefix="FULL",
        assembly_start_number=888,
        phase=3,
    )
    assert result["status"] == "success"
    assert result["modified_elements"] == 1
    assert result["changes_applied"]["name"] == 1
    assert result["changes_applied"]["assembly_prefix"] == 1
    assert result["changes_applied"]["assembly_start_number"] == 1
    assert result["changes_applied"]["phase"] == 1

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result = get_elements_properties()
    assemblies = json.loads(result["assemblies_list"])
    assert len(assemblies) >= 1
    assert assemblies[0]["name"] == "MCP_ASSEMBLY_ALL_TEST"
    assert assemblies[0]["assembly_prefix"] == "FULL"
    assert assemblies[0]["assembly_start_number"] == 888
    assert assemblies[0]["phase"] == 3


def test_parts_and_assemblies_have_different_properties(model_objects):
    """Tests that parts and assemblies have different property sets - no cross-contamination."""
    TeklaModel.select_objects([model_objects["test_wall1"]])

    set_elements_properties(
        name="MCP_TEST_CROSS_TEST",
        profile="3000*400",
        material="C30/37",
    )

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Part")
    result_parts = get_elements_properties()
    parts = json.loads(result_parts["parts_list"])

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result_assemblies = get_elements_properties()
    assemblies = json.loads(result_assemblies["assemblies_list"])

    assert len(parts) >= 1
    assert len(assemblies) >= 1

    assert parts[0]["name"] == "MCP_TEST_CROSS_TEST"
    assert parts[0]["profile"] == "3000*400"
    assert parts[0]["material"] == "C30/37"
    assert "assembly_prefix" in parts[0]
    assert "assembly_start_number" in parts[0]

    assert assemblies[0]["name"] == "MCP_TEST_CROSS_TEST"
    assert "profile" not in assemblies[0]
    assert "material" not in assemblies[0]
    assert "tekla_class" not in assemblies[0]
    assert "finish" not in assemblies[0]
    assert "assembly_prefix" in assemblies[0]
    assert "assembly_start_number" in assemblies[0]


def test_set_elements_properties_multiple_elements(model_objects):
    """Tests set_elements_properties on multiple elements."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    result = set_elements_properties(tekla_class="77")
    assert result["status"] == "success"
    assert result["processed_elements"] == 2
    assert result["modified_elements"] == 2
    assert result["changes_applied"]["tekla_class"] == 2


def test_set_elements_properties_empty_selection(model_objects):
    """Tests set_elements_properties with no elements selected."""
    TeklaModel.select_objects([])

    try:
        result = set_elements_properties(name="ShouldNotFail")
        assert result["status"] == "error"
    except ValueError as e:
        assert "No objects are currently selected" in str(e)


def test_get_elements_properties_parts_vs_assemblies(model_objects):
    """Tests that parts and assemblies are returned separately."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result_assemblies = get_elements_properties()

    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    select_elements_assemblies_or_main_parts(mode="Part")
    result_parts = get_elements_properties()

    assemblies = json.loads(result_assemblies["assemblies_list"])
    parts = json.loads(result_parts["parts_list"])

    assert len(assemblies) > 0
    assert len(parts) > 0


def test_get_elements_properties_numbering_fields(model_objects):
    """Tests that get_elements_properties returns numbering fields for parts and assemblies."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Part")
    result_parts = get_elements_properties()
    parts = json.loads(result_parts["parts_list"])

    assert len(parts) >= 1
    assert "part_prefix" in parts[0]
    assert "part_start_number" in parts[0]
    assert "assembly_prefix" in parts[0]
    assert "assembly_start_number" in parts[0]
    assert "phase" in parts[0]

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result_assemblies = get_elements_properties()
    assemblies = json.loads(result_assemblies["assemblies_list"])

    assert len(assemblies) >= 1
    assert "assembly_prefix" in assemblies[0]
    assert "assembly_start_number" in assemblies[0]
    assert "phase" in assemblies[0]
    assert "name" in assemblies[0]
    assert "position" in assemblies[0]
    assert "guid" in assemblies[0]


def test_set_elements_properties_numbering(model_objects):
    """Tests set_elements_properties with numbering parameters."""
    TeklaModel.select_objects([model_objects["test_wall7"]])

    result = set_elements_properties(
        assembly_prefix="TEST",
        assembly_start_number=100,
    )
    assert result["status"] == "success"
    assert result["changes_applied"]["assembly_prefix"] == 1
    assert result["changes_applied"]["assembly_start_number"] == 1

    TeklaModel.select_objects([model_objects["test_wall7"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result = get_elements_properties()
    assemblies = json.loads(result["assemblies_list"])
    assert assemblies[0]["assembly_prefix"] == "TEST"
    assert assemblies[0]["assembly_start_number"] == 100


def test_get_elements_properties_user_properties(model_objects):
    """Tests that user_properties field is populated."""
    TeklaModel.select_objects([model_objects["test_wall7"]])

    user_props = {"UDA_FOR_TEST": "TestValue123"}
    result = set_elements_properties(user_properties=user_props)
    assert result["status"] == "success"
    assert result["changes_applied"]["udas"] >= 1

    TeklaModel.select_objects([model_objects["test_wall7"]])
    select_elements_assemblies_or_main_parts(mode="Part")
    result = get_elements_properties()
    parts = json.loads(result["parts_list"])

    assert len(parts) >= 1
    assert "user_properties" in parts[0]


def test_get_elements_properties_both_assemblies_and_parts(model_objects):
    """Tests that selecting both assemblies and parts returns both lists in single call."""
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])

    select_elements_assemblies_or_main_parts(mode="Assembly")
    result_assemblies = get_elements_properties()
    assemblies = json.loads(result_assemblies["assemblies_list"])

    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    select_elements_assemblies_or_main_parts(mode="Main Part")
    result_parts = get_elements_properties()
    parts = json.loads(result_parts["parts_list"])

    assert len(assemblies) > 0, "Expected assemblies in result"
    assert len(parts) > 0, "Expected parts in result"


def test_get_elements_properties_basic_assembly_properties(model_objects):
    """Tests get_elements_properties: basic assembly properties."""
    TeklaModel.select_objects(
        [
            model_objects["test_wall1"],
            model_objects["test_wall2"],
            model_objects["test_sw1"],
            model_objects["test_slab1"],
        ]
    )
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result = get_elements_properties()

    assert result["status"] == "success"
    assemblies = json.loads(result["assemblies_list"])
    assert isinstance(assemblies, list)
    assert len(assemblies) == 4


def test_get_elements_properties_known_values_for_assemblies(model_objects):
    """Tests get_elements_properties: profile values for assemblies."""
    TeklaModel.select_objects(
        [
            model_objects["test_wall1"],
            model_objects["test_slab1"],
        ]
    )
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result = get_elements_properties()

    assemblies = json.loads(result["assemblies_list"])
    assert len(assemblies) >= 1

    names = [a["name"] for a in assemblies]
    assert "MCP_TEST_WALL1" in names or "MCP_TEST_SLAB1" in names


def test_get_elements_properties_valid_report_properties(model_objects):
    """Tests get_elements_properties: valid report properties with exact values."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")

    result = get_elements_properties(report_props_definitions=["ASSEMBLY_POS"])

    assemblies = json.loads(result["assemblies_list"])
    assert len(assemblies) >= 1
    assert "report_properties" in assemblies[0]
    assert len(assemblies[0]["report_properties"]) > 0


def test_get_elements_properties_invalid_and_missing_report_properties(model_objects):
    """Tests get_elements_properties: invalid report properties are tracked."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")

    result = get_elements_properties(report_props_definitions=["NON_EXISTENT_PROPERTY"])

    assert "resolution_errors" in result
    assert "extraction_errors" in result
    assert isinstance(result["resolution_errors"], list)
    assert isinstance(result["extraction_errors"], list)


def test_get_elements_cut_parts_with_cuts(model_objects):
    """Tests get_elements_cut_parts: elements with cut parts."""
    TeklaModel.select_objects([model_objects["test_wall3"]])
    result = get_elements_cut_parts()

    assert result["status"] == "success"
    assert result["selected_elements"] == 1


def test_get_elements_cut_parts_without_cuts(model_objects):
    """Tests get_elements_cut_parts: elements without cut parts."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = get_elements_cut_parts()

    assert result["status"] == "warning"
    assert result["selected_elements"] == 1
    assert result["total_cut_parts"] == 0


def test_compare_elements_numbering_not_up_to_date(model_objects):
    """Tests compare_elements when numbering is not up-to-date."""
    TeklaModel.select_objects([model_objects["test_wall5"], model_objects["test_wall6"]])
    result = compare_elements()

    assert result["status"] == "error"
    assert "numbering" in result["message"].lower()


def test_compare_identical_parts(model_objects):
    """Tests compare_elements: identical parts."""
    TeklaModel.select_objects([model_objects["test_wall5"], model_objects["test_wall6"]])
    result = compare_elements(ignore_numbering=True)

    assert result["status"] == "success"
    assert result["identical"] is True


def test_compare_different_parts_different_profile(model_objects):
    """Tests compare_elements: different profiles."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall7"]])
    result = compare_elements(ignore_numbering=True)

    assert result["status"] == "success"
    assert result["identical"] is False


def test_compare_three_elements(model_objects):
    """Tests compare_elements with three elements - should error."""
    TeklaModel.select_objects(
        [
            model_objects["test_wall1"],
            model_objects["test_wall2"],
            model_objects["test_wall3"],
        ]
    )
    result = compare_elements(ignore_numbering=True)

    assert result["status"] == "error"
    assert "More than two elements" in result["message"]
