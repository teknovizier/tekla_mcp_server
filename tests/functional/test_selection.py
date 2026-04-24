"""
Functional tests for selection_provider.

Tests element selection by filter, GUID, and assembly/main part modes.
"""

import pytest

from tekla_mcp_server.providers.selection_provider import (
    select_elements_by_filter,
    select_elements_by_filter_name,
    select_elements_by_guid,
    select_elements_assemblies_or_main_parts,
)
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


def test_select_elements_by_filter_name(model_objects):
    """Tests select_elements_by_filter_name function."""
    result = select_elements_by_filter_name(filter_name="non_standard")
    assert result.structured_content["status"] == "warning"

    result = select_elements_by_filter_name(filter_name="standard")
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_elements"]


def test_select_elements_by_filter_no_filters_returns_error(model_objects):
    """Tests select_elements_by_filter when called without any filter parameters."""
    result = select_elements_by_filter()
    assert result.structured_content["status"] == "error"


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
    assert result.structured_content["status"] == "success"


@pytest.mark.parametrize("invalid_element_type", ["InvalidType", "NonExistent", "FakeWall"])
def test_select_elements_by_filter_invalid_element_type(model_objects, invalid_element_type):
    """Tests select_elements_by_filter with invalid element_type values."""
    result = select_elements_by_filter(element_type=invalid_element_type)
    assert result.structured_content["status"] == "error"


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
    assert result.structured_content["status"] == "success"


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
    assert result.structured_content["status"] == "success"


def test_select_elements_by_filter_custom_string_filters(model_objects):
    """Tests select_elements_by_filter with custom string filters."""
    kwargs = {
        "element_type": "Wall",
        "custom_string_filters": {},
    }
    result = select_elements_by_filter(**kwargs)
    assert result.structured_content["status"] == "success"


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
    assert result.structured_content["status"] == "success"


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
    assert result.structured_content["status"] == "success"


@pytest.mark.parametrize("combine_with", ["AND", "OR"])
def test_select_elements_by_filter_combined_filters(model_objects, combine_with):
    """Tests select_elements_by_filter with combined string and numeric filters."""
    result = select_elements_by_filter(
        element_type="Wall",
        standard_string_filters={"name": {"conditions": {"match_type": "Contains", "value": "MCP"}}},
        custom_numeric_filters={"HEIGHT": {"conditions": {"match_type": "Greater Than", "value": 2000.0}}},
        combine_with=combine_with,
    )
    assert result.structured_content["status"] == "success"


@pytest.mark.parametrize("invalid_logic", ["and", "or", "XOR", "", "NOT"])
def test_select_elements_by_filter_invalid_combine_with(model_objects, invalid_logic):
    """Tests select_elements_by_filter with invalid combine_with values."""
    result = select_elements_by_filter(
        element_type="Wall",
        standard_string_filters={"name": {"conditions": {"match_type": "Contains", "value": "MCP"}}},
        combine_with=invalid_logic,
    )
    assert result.structured_content["status"] == "error"


def test_select_elements_by_guid(model_objects):
    """Tests select_elements_by_guid function."""
    result = select_elements_by_guid(guids=[])
    assert result.structured_content["status"] == "warning"

    result = select_elements_by_guid(guids=[""])
    assert result.structured_content["status"] == "warning"

    result = select_elements_by_guid(guids=["MCP_TEST_WALL2"])
    assert result.structured_content["status"] == "warning"

    wall2_guid = model_objects["test_wall2"].Identifier.GUID.ToString()
    result = select_elements_by_guid(guids=[wall2_guid])
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_elements"] == 1

    wall1_guid = model_objects["test_wall1"].Identifier.GUID.ToString()
    result = select_elements_by_guid(guids=[wall1_guid, wall2_guid])
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_elements"] == 2


@pytest.mark.parametrize("mode,expected_count", [("Assembly", 2), ("Main Part", 2)])
def test_select_elements_assemblies(model_objects, mode, expected_count):
    """Tests select_elements_assemblies_or_main_parts function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = select_elements_assemblies_or_main_parts(mode=mode)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_elements"] == expected_count
