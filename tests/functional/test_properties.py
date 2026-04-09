"""
Functional tests for properties_provider.

Tests getting and setting element properties, UDAs, numbering, cut parts, and comparison.
"""

import json

from tekla_mcp_server.providers.properties_provider import (
    get_elements_properties,
    set_elements_properties,
    get_elements_cut_parts,
    compare_elements,
)
from tekla_mcp_server.providers.selection_provider import select_elements_assemblies_or_main_parts
from tekla_mcp_server.tekla.model import TeklaModel


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
    from tekla_mcp_server.providers.operations_provider import cut_elements_with_zero_class_parts

    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    cut_elements_with_zero_class_parts(delete_cutting_parts=False)

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
