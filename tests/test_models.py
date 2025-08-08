"""
This module contains unit tests for models, including anchor placement and spacing calculations.

Tested modules:
- models.py: Contains classes for managing Tekla components such as lifting anchors.
"""

import pytest

from pydantic_core import ValidationError

from models import SelectionModeModel, UDASetModeModel, StringMatchTypeModel, ElementTypeModel, ComponentTypeModel, ElementType, LiftingAnchors


@pytest.fixture
def anchor_types():
    """
    Fixture: anchor types.
    """
    return {
        "A": {"element_type": ["WALL"], "active": True, "capacity": 1.5},
        "B": {"element_type": ["WALL"], "active": True, "capacity": 2.0},
        "C": {"element_type": ["WALL"], "active": True, "capacity": 0.5},
    }


@pytest.fixture
def element_type():
    """
    Fixture: default element type.
    """
    return ElementType.WALL


@pytest.mark.parametrize(
    "input_val,expected",
    [
        ("1", ("Concrete", "WALL")),
        ("100", ("Steel", "BEAM")),
        ("101", ("Steel", "COLUMN")),
        ("999999", None),
        ("not_a_number", None),
        (None, None),
        (1, ("Concrete", "WALL")),
        ("-1", None),
    ],
)
def test_get_element_type_by_class_cases(input_val, expected):
    """
    Unit tests for `get_element_type_by_class` utility function.

    Covers:
    - Valid class strings and integers
    - Invalid, non-integer, None, and edge cases
    """
    assert ElementTypeModel.get_element_type_by_class(input_val) == expected


def test_get_required_anchors_valid(anchor_types, element_type):
    """
    Tests `get_required_anchors()` with valid anchor types.

    Steps:
    - Calls `get_required_anchors()` with weight and thickness parameters.
    - Ensures at least two valid anchors are selected.
    """
    n, valid = LiftingAnchors.get_required_anchors(element_type.name, 2000, 10, anchor_types)
    assert "A" in valid
    assert n == 2


def test_get_required_anchors_try_four(element_type):
    """
    Tests `get_required_anchors()` when four anchors are required.

    Steps:
    - Uses an anchor type with **capacity=1.0** per anchor.
    - Calls the function with **element_weight=3600**.
    - Ensures the system correctly assigns four anchors.
    """
    anchor_types = {"A": {"element_type": ["WALL"], "active": True, "capacity": 1.0}}
    n, valid = LiftingAnchors.get_required_anchors(element_type.name, 3600, 10, anchor_types)
    assert n == 4
    assert "A" in valid


def test_get_required_anchors_not_valid(element_type):
    """
    Tests `get_required_anchors()` when no valid anchors exist.

    Steps:
    - Uses anchor types with insufficient capacity (**capacity=0.1** per anchor).
    - Calls the function with **element_weight=10000**.
    - Ensures a `ValueError` is raised due to inability to support the load.
    """
    anchor_types = {"A": {"element_type": ["WALL"], "active": True, "capacity": 0.1}}
    with pytest.raises(ValueError):
        LiftingAnchors.get_required_anchors(element_type.name, 10000, 10, anchor_types)


def test_calculate_anchor_placement_valid():
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
    assert distance_from_start == 500
    assert distance_from_end == 500
    assert double_anchor_spacing == 50


def test_calculate_anchor_placement_too_short():
    """
    Tests `calculate_anchor_placement()` when the element length is too short.

    Steps:
    - Calls the function with **element_length=1000**, **cog_x=500**, **min_edge_distance=900** and **four anchors**.
    - Ensures a `ValueError` is raised due to insufficient space for anchors.
    """
    with pytest.raises(ValueError):
        LiftingAnchors.calculate_anchor_placement(
            min_edge_distance=900,
            element_length=1000,
            cog_x=500,
            number_of_anchors=4,
        )


def test_calculate_anchor_placement_four_anchors_requested():
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
    assert distance_from_start == 1000
    assert distance_from_end == 1000
    assert double_anchor_spacing == 1000


def test_calculate_anchor_placement_distances_are_multiples_of_5():
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
    assert distance_from_start % 5 == 0
    assert distance_from_end % 5 == 0


@pytest.mark.parametrize(
    "input_val,expected_enum",
    [
        ("Assembly", "ASSEMBLY"),
        ("Main Part", "MAIN_PART"),
    ],
)
def test_selection_mode_model_valid(input_val, expected_enum):
    """Tests SelectionModeModel with valid values."""
    model = SelectionModeModel(value=input_val)
    assert model.to_enum().name == expected_enum


@pytest.mark.parametrize(
    "input_val",
    [
        "Assemblies",
        "Parts",
        "",
        "Random",
    ],
)
def test_selection_mode_model_invalid(input_val):
    """Tests SelectionModeModel with invalid values."""
    with pytest.raises(ValidationError):
        SelectionModeModel(value=input_val)


@pytest.mark.parametrize(
    "input_val,expected_enum",
    [
        ("Keep Existing Values", "KEEP"),
        ("Overwrite Existing Values", "OVERWRITE"),
    ],
)
def test_uda_set_mode_model_valid(input_val, expected_enum):
    """
    Checks UDASetModeModel accepts valid values and maps to correct enum.
    """
    model = UDASetModeModel(value=input_val)
    assert model.to_enum().name == expected_enum


@pytest.mark.parametrize(
    "input_val",
    [
        "Invalid Mode",
        "",
        "Keep",
        "Overwrite",
    ],
)
def test_uda_set_mode_model_invalid(input_val):
    """
    Checks UDASetModeModel raises error for invalid values.
    """
    with pytest.raises(ValidationError):
        UDASetModeModel(value=input_val)


@pytest.mark.parametrize(
    "input_val,expected_enum",
    [
        ("Is Equal", "IS_EQUAL"),
        ("Is Not Equal", "IS_NOT_EQUAL"),
        ("Contains", "CONTAINS"),
        ("Not Contains", "NOT_CONTAINS"),
        ("Starts With", "STARTS_WITH"),
        ("Not Starts With", "NOT_STARTS_WITH"),
        ("Ends With", "ENDS_WITH"),
        ("Not Ends With", "NOT_ENDS_WITH"),
    ],
)
def test_string_match_type_model_valid(input_val, expected_enum):
    """
    Checks StringMatchTypeModel accepts valid values and maps to correct enum.
    """
    model = StringMatchTypeModel(value=input_val)
    assert model.to_enum().name == expected_enum


@pytest.mark.parametrize(
    "input_val",
    [
        "Equals",
        "NotEquals",
        "",
        "is equal",
        "Random",
    ],
)
def test_string_match_type_model_invalid(input_val):
    """
    Checks StringMatchTypeModel raises error for invalid values.
    """
    with pytest.raises(ValidationError):
        StringMatchTypeModel(value=input_val)


@pytest.mark.parametrize(
    "input_val,expected_enum",
    [
        ("Wall", "WALL"),
        ("Sandwich Wall", "SANDWICH_WALL"),
        ("Stair Flight", "STAIR_FLIGHT"),
        ("Hollow Core Slab", "HCS"),
        ("Massive Slab", "MASSIVE_SLAB"),
        ("Column", "COLUMN"),
        ("Beam", "BEAM"),
        ("Filigree Wall", "FILIGREE_WALL"),
        ("Filigree Slab", "FILIGREE_SLAB"),
        ("Tribune", "TRIBUNE"),
        ("TT Slab", "TT_SLAB"),
        ("Balcony Slab", "BALCONY_SLAB"),
        ("Stair Landing", "STAIR_LANDING"),
        ("Curved Stair", "CURVED_STAIR"),
        ("Steel Beam", "STEEL_BEAM"),
        ("Steel Column", "STEEL_COLUMN"),
        ("Steel Truss", "STEEL_TRUSS"),
        ("Steel Brace", "STEEL_BRACE"),
    ],
)
def test_element_type_model_valid(input_val, expected_enum):
    """
    Checks ElementTypeModel accepts valid values and maps to correct enum.
    """
    model = ElementTypeModel(value=input_val)
    assert model.to_enum().name == expected_enum


@pytest.mark.parametrize(
    "input_val",
    [
        "Walll",
        "Slab",
        "",
        "Random",
    ],
)
def test_element_type_model_invalid(input_val):
    """
    Checks ElementTypeModel raises error for invalid values.
    """
    with pytest.raises(ValidationError):
        ElementTypeModel(value=input_val)


@pytest.mark.parametrize(
    "input_val,expected_enum",
    [
        ("Component", "COMPONENT"),
        ("Connection", "CONNECTION"),
        ("Custom Part", "CUSTOM_PART"),
        ("Detail", "DETAIL"),
        ("Seam", "SEAM"),
    ],
)
def test_component_type_model_valid(input_val, expected_enum):
    """
    Checks ComponentTypeModel accepts valid values and maps to correct enum.
    """
    model = ComponentTypeModel(value=input_val)
    assert model.to_enum().name == expected_enum


@pytest.mark.parametrize(
    "input_val",
    [
        "componentt",
        "details",
        "",
        "Random",
    ],
)
def test_component_type_model_invalid(input_val):
    """
    Checks ComponentTypeModel raises error for invalid values.
    """
    with pytest.raises(ValidationError):
        ComponentTypeModel(value=input_val)
