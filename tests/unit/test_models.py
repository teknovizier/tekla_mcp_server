"""
Unit tests for core models.

This module verifies the correctness of data models and validation logic
used in Tekla component operations.

Tested modules:
- models.py
"""

import json
import pytest

from pydantic_core import ValidationError

from tekla_mcp_server.models import (
    SelectionModeModel,
    ElementTypeModel,
    ComponentTypeModel,
    ElementLabelModel,
    BaseComponent,
    ReportProperty,
    PartSnapshot,
    AssemblySnapshot,
)


@pytest.mark.parametrize(
    "input_val,expected",
    [
        ("1", ("MATERIAL_CONCRETE", "CONCRETE_WALL")),
        ("100", ("MATERIAL_STEEL", "STEEL_BEAM")),
        ("101", ("MATERIAL_STEEL", "STEEL_COLUMN")),
        (1, ("MATERIAL_CONCRETE", "CONCRETE_WALL")),
    ],
)
def test_get_element_type_by_class_valid(input_val, expected):
    """
    Unit tests for `get_element_type_by_class` utility function.

    Covers:
    - Valid class strings and integers
    """
    assert ElementTypeModel.get_element_type_by_class(input_val) == expected


@pytest.mark.parametrize(
    "input_val, expected_exception",
    [
        ("999999", ValueError),
        ("not_a_number", ValueError),
        (None, ValueError),
        ("-1", ValueError),
    ],
)
def test_get_element_type_by_class_raises(input_val, expected_exception):
    """
    Unit tests for `get_element_type_by_class` utility function.

    Covers:
    - Invalid, non-integer, None, and edge cases
    """
    with pytest.raises(expected_exception):
        ElementTypeModel.get_element_type_by_class(input_val)


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
        ("Wall", "CONCRETE_WALL"),
        ("Sandwich Wall", "CONCRETE_SANDWICH_WALL"),
        ("Stair Flight", "CONCRETE_STAIR_FLIGHT"),
        ("Hollow Core Slab", "CONCRETE_HCS"),
        ("Massive Slab", "CONCRETE_MASSIVE_SLAB"),
        ("Column", "CONCRETE_COLUMN"),
        ("Beam", "CONCRETE_BEAM"),
        ("Filigree Wall", "CONCRETE_FILIGREE_WALL"),
        ("Filigree Slab", "CONCRETE_FILIGREE_SLAB"),
        ("Tribune", "CONCRETE_TRIBUNE"),
        ("TT Slab", "CONCRETE_TT_SLAB"),
        ("Balcony Slab", "CONCRETE_BALCONY_SLAB"),
        ("Stair Landing", "CONCRETE_STAIR_LANDING"),
        ("Curved Stair", "CONCRETE_CURVED_STAIR"),
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


@pytest.mark.parametrize(
    "input_val,expected_enum",
    [
        ("Position", "POSITION"),
        ("GUID", "GUID"),
        ("Name", "NAME"),
        ("Profile", "PROFILE"),
        ("Material", "MATERIAL"),
        ("Finish", "FINISH"),
        ("Class", "CLASS"),
    ],
)
def test_element_label_model_valid(input_val, expected_enum):
    """
    Checks ElementLabelModel accepts valid values and maps to correct enum.
    """
    model = ElementLabelModel(value=input_val)
    assert model.to_enum().name == expected_enum


@pytest.mark.parametrize(
    "input_val",
    [
        "positionn",
        "guidd",
        "",
        "Unknown",
    ],
)
def test_element_label_model_invalid(input_val):
    """
    Checks ElementLabelModel raises error for invalid values.
    """
    with pytest.raises(ValueError):
        ElementLabelModel(value=input_val)


@pytest.mark.parametrize(
    "type_str, expected_type",
    [
        ("FLOAT", float),
        ("CHARACTER", str),
        ("INTEGER", int),
        ("unknown", str),  # fallback
    ],
)
def test_report_property_map_string_to_type(type_str, expected_type):
    """Ensure data_type strings are mapped to the correct Python types."""
    rp = ReportProperty(name="TEST", data_type=type_str, unit=None)
    assert rp.data_type is expected_type


def test_report_property_serialize_type_outputs_type_name():
    """Ensure JSON serialization outputs type name instead of type object."""
    rp = ReportProperty(name="LENGTH", data_type="FLOAT", unit="m", value=12.5)
    json_data = rp.model_dump_json()
    parsed = json.loads(json_data)
    assert parsed["data_type"] == "float"
    assert parsed["name"] == "LENGTH"
    assert parsed["unit"] == "m"
    assert parsed["value"] == 12.5


def test_report_property_invalid_data_type_raises():
    """Passing a non-string/non-type should fail."""
    with pytest.raises(Exception):
        ReportProperty(name="INVALID", data_type=12345, unit=None)


def test_report_property_none_for_optional_fields():
    """Unit and value should be allowed to be None."""
    rp = ReportProperty(name="EMPTY_UNIT", data_type="INTEGER", unit=None, value=None)
    assert rp.unit is None
    assert rp.value is None


def test_numbering_series():
    """Test NumberingSeries dataclass."""
    from tekla_mcp_server.models import NumberingSeries

    ns = NumberingSeries(prefix="P", start_number=1)
    assert ns.prefix == "P"
    assert ns.start_number == 1

    ns2 = NumberingSeries(prefix="A", start_number=42)
    assert ns2.prefix == "A"
    assert ns2.start_number == 42

    data = ns.model_dump()
    assert data["prefix"] == "P"
    assert data["start_number"] == 1


class TestPartSnapshotNormalize:
    @pytest.mark.parametrize(
        "input_val,tolerance,expected",
        [
            (1234.567, 100, 1200.0),
            (1234.567, 0.1, 1234.6),
            (1234.567, 1, 1235.0),
            (50.0, 100, 0.0),
            (-123.456, 100, -100.0),
            (0.0, 100, 0.0),
        ],
    )
    def test_float_rounding(self, input_val, tolerance, expected):
        snapshot = PartSnapshot(
            id=1,
            guid="g1",
            pos="P1",
            report_properties={"x": input_val},
        )
        result = snapshot.normalize(tolerance)
        assert result.report_properties["x"] == expected

    def test_dict_with_floats(self):
        snapshot = PartSnapshot(
            id=1,
            guid="g1",
            pos="P1",
            report_properties={"a": 123.456, "b": 789.012},
        )
        result = snapshot.normalize(100)
        assert result.report_properties["a"] == 100.0
        assert result.report_properties["b"] == 800.0

    def test_list_of_floats_normalized_and_sorted(self):
        snapshot = PartSnapshot(
            id=1,
            guid="g1",
            pos="P1",
            report_properties={"vals": [150.0, 50.0, 250.0]},
        )
        result = snapshot.normalize(100)
        assert result.report_properties["vals"] == [0.0, 200.0, 200.0]

    def test_non_floats_unchanged(self):
        snapshot = PartSnapshot(
            id=1,
            guid="g1",
            pos="P1",
            report_properties={"i": 42, "s": "text", "b": True, "lst": [1, "a"]},
            user_properties={"nested": {"x": 10}},
        )
        result = snapshot.normalize(100)
        assert result.report_properties["i"] == 42
        assert result.report_properties["s"] == "text"
        assert result.report_properties["b"] is True
        assert result.user_properties["nested"]["x"] == 10

    def test_cutparts_normalized(self):
        snapshot = PartSnapshot(
            id=1,
            guid="g1",
            pos="P1",
            cutparts=[{"length": 123.456, "angle": 45.789}],
        )
        result = snapshot.normalize(100)
        assert result.cutparts[0]["length"] == 100.0
        assert result.cutparts[0]["angle"] == 0.0

    def test_reinforcements_normalized(self):
        snapshot = PartSnapshot(
            id=1,
            guid="g1",
            pos="P1",
            reinforcements=[{"weight": 567.89, "count": 5}],
        )
        result = snapshot.normalize(100)
        assert result.reinforcements[0]["weight"] == 600.0
        assert result.reinforcements[0]["count"] == 5

    def test_welds_normalized(self):
        snapshot = PartSnapshot(
            id=1,
            guid="g1",
            pos="P1",
            welds=[{"size": 6.5, "type": "Fillet"}],
        )
        result = snapshot.normalize(10)
        assert result.welds[0]["size"] == 10.0
        assert result.welds[0]["type"] == "Fillet"

    def test_empty_dicts_and_lists(self):
        snapshot = PartSnapshot(id=1, guid="g1", pos="P1", report_properties={}, cutparts=[])
        result = snapshot.normalize(100)
        assert result.report_properties == {}
        assert result.cutparts == []


class TestAssemblySnapshotNormalize:
    def test_main_part_normalized(self):
        main_part = PartSnapshot(id=1, guid="g1", pos="P1", report_properties={"x": 123.456})
        assembly = AssemblySnapshot(id=10, guid="ga1", pos="A1", main_part=main_part)
        result = assembly.normalize(100)
        assert result.main_part.report_properties["x"] == 100.0

    def test_secondaries_normalized(self):
        sec1 = PartSnapshot(id=1, guid="g1", pos="P1", report_properties={"y": 150.0})
        sec2 = PartSnapshot(id=2, guid="g2", pos="P2", report_properties={"y": 250.0})
        assembly = AssemblySnapshot(id=10, guid="ga1", pos="A1", secondaries=[sec1, sec2])
        result = assembly.normalize(100)
        assert result.secondaries[0].report_properties["y"] == 200.0
        assert result.secondaries[1].report_properties["y"] == 200.0

    def test_subassemblies_normalized(self):
        sub = AssemblySnapshot(id=2, guid="ga2", pos="A2", report_properties={"z": 456.789})
        assembly = AssemblySnapshot(id=10, guid="ga1", pos="A1", subassemblies=[sub])
        result = assembly.normalize(100)
        assert result.subassemblies[0].report_properties["z"] == 500.0

    def test_nested_mixed_structure(self):
        main_part = PartSnapshot(id=1, guid="g1", pos="P1", report_properties={"x": 123.0})
        sec = PartSnapshot(id=2, guid="g2", pos="P2", report_properties={"y": 0.0})
        sub = AssemblySnapshot(id=3, guid="ga2", pos="A2", main_part=main_part, secondaries=[sec])
        assembly = AssemblySnapshot(id=10, guid="ga1", pos="A1", main_part=main_part, secondaries=[sec], subassemblies=[sub])
        result = assembly.normalize(100)
        assert result.main_part.report_properties["x"] == 100.0
        assert result.secondaries[0].report_properties["y"] == 0.0
        assert result.subassemblies[0].main_part.report_properties["x"] == 100.0

    def test_none_main_part_handled(self):
        assembly = AssemblySnapshot(id=10, guid="ga1", pos="A1", main_part=None)
        result = assembly.normalize(100)
        assert result.main_part is None


class TestNormalizeEdgeCases:
    @pytest.mark.parametrize(
        "input_val,tolerance,expected",
        [
            (0.001, 0.001, 0.001),
            (0.0005, 0.001, 0.0),
            (123.456789, 0.001, 123.457),
            (-0.001, 0.001, -0.001),
            (500.5, 0.5, 500.5),
        ],
    )
    def test_small_tolerance(self, input_val, tolerance, expected):
        snapshot = PartSnapshot(id=1, guid="g1", pos="P1", report_properties={"x": input_val})
        result = snapshot.normalize(tolerance)
        assert result.report_properties["x"] == expected

    def test_mixed_type_list(self):
        snapshot = PartSnapshot(
            id=1,
            guid="g1",
            pos="P1",
            report_properties={"vals": [1.5, "text", 2.5, True]},
        )
        result = snapshot.normalize(0.1)
        assert result.report_properties["vals"] == [True, 1.5, 2.5, "text"]

    def test_deeply_nested_dict(self):
        snapshot = PartSnapshot(
            id=1,
            guid="g1",
            pos="P1",
            report_properties={"l1": {"l2": {"l3": 123.456}}},
        )
        result = snapshot.normalize(100)
        assert result.report_properties["l1"]["l2"]["l3"] == 100.0


class TestBaseComponentCustomPropertiesValidation:
    """Tests for custom_properties validation in BaseComponent."""

    def test_valid_custom_properties(self):
        """Valid properties should pass."""
        component = BaseComponent(
            name="MeshBars",
            custom_properties={"TopAsBott": 0, "BottGradePri": "B500B"},
        )
        assert component.custom_properties == {"TopAsBott": 0, "BottGradePri": "B500B"}

    def test_unknown_property_raises(self):
        """Unknown property should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            BaseComponent(
                name="MeshBars",
                custom_properties={"unknown_prop": "value"},
            )
        assert "Unknown property: 'unknown_prop'" in str(exc_info.value)

    def test_invalid_type_raises(self):
        """Wrong type should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            BaseComponent(
                name="MeshBars",
                custom_properties={"TopAsBott": {"not": "an int"}},  # dict instead of int
            )
        assert "Invalid value for 'TopAsBott'" in str(exc_info.value)

    def test_none_custom_properties(self):
        """None should be allowed."""
        component = BaseComponent(name="MeshBars", custom_properties=None)
        assert component.custom_properties is None

    def test_unknown_component_skips_validation(self):
        """Unknown component should skip validation."""
        component = BaseComponent(
            name="Unknown Component",
            custom_properties={"any_prop": "any_value"},
        )
        assert component.custom_properties == {"any_prop": "any_value"}
