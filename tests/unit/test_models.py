"""
Unit tests for core models.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from pydantic_core import ValidationError

from tekla_mcp_server.models import (
    ElementType,
    ElementTypes,
    FilterCondition,
    FilterGroup,
    BaseComponent,
    ReportProperty,
    PartSnapshot,
    AssemblySnapshot,
    ReinforcementSnapshot,
    StringFilterOption,
    NumericFilterOption,
    OffsetInput,
    PointInput,
    PositionInput,
    _coerce_custom_property,
    simplify_filter_tree,
    specialize_filter_tree,
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
    assert ElementTypes.get_element_type_by_class(input_val) == expected


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
        ElementTypes.get_element_type_by_class(input_val)


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
def test_element_type_enum_valid(input_val, expected_enum):
    """
    Checks ElementType enum accepts valid values.
    """
    assert ElementType(input_val).name == expected_enum


@pytest.mark.parametrize(
    "input_val",
    [
        "Walll",
        "Slab",
        "",
        "Random",
    ],
)
def test_element_type_enum_invalid(input_val):
    """
    Checks ElementType enum raises error for invalid values.
    """
    with pytest.raises(ValueError):
        ElementType(input_val)


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


def _make_rebar_snapshot(**kwargs) -> ReinforcementSnapshot:
    """Helper: construct a ReinforcementSnapshot with sensible required-field defaults."""
    defaults = {
        "id": 1,
        "guid": "g1",
        "pos": "R1",
        "rebar_type": "BaseRebarGroup",
        "father_guid": None,
    }
    defaults.update(kwargs)
    return ReinforcementSnapshot(**defaults)


class TestReinforcementSnapshotNormalize:
    def test_floats_normalized(self):
        snapshot = _make_rebar_snapshot(
            report_properties={"weight": 123.456, "count": 5.0},
        )
        result = snapshot.normalize(100)
        assert result.report_properties["weight"] == 100.0
        assert result.report_properties["count"] == 0.0

    def test_non_floats_unchanged(self):
        snapshot = _make_rebar_snapshot(
            rebar_type="RebarMesh",
            report_properties={"grade": "B500B"},
            user_properties={"notes": "test"},
        )
        result = snapshot.normalize(100)
        assert result.report_properties["grade"] == "B500B"
        assert result.user_properties["notes"] == "test"

    def test_normalize_preserves_identity_fields(self):
        snapshot = _make_rebar_snapshot(
            rebar_type="SingleRebar",
            father_guid="father-guid-123",
        )
        result = snapshot.normalize(100)
        assert result.father_guid == "father-guid-123"
        assert result.rebar_type == "SingleRebar"

    def test_to_diff_view_contains_expected_keys(self):
        snapshot = _make_rebar_snapshot(
            father_guid="fg1",
            report_properties={"weight": 50.0},
            user_properties={"STATUS": "OK"},
        )
        dv = snapshot.to_diff_view()
        assert "pos" in dv
        assert "rebar_type" in dv
        assert "report_properties" in dv
        assert "user_properties" in dv
        # father_guid is a relationship pointer, not a rebar property — must NOT be in
        # the diff view or compare_elements will report false positives for rebars
        # from different parent parts that are otherwise identical.
        assert "father_guid" not in dv

    def test_empty_report_properties(self):
        snapshot = _make_rebar_snapshot(rebar_type="RebarStrand", father_guid=None)
        result = snapshot.normalize(100)
        assert result.report_properties == {}
        assert result.user_properties == {}
        assert result.father_guid is None

    def test_all_fields_required(self):
        """Verify no implicit defaults - consistent with PartSnapshot / AssemblySnapshot."""
        with pytest.raises(ValidationError):
            ReinforcementSnapshot(id=1, guid="g", pos="R1")  # missing rebar_type etc.


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

    def test_zero_tolerance_keeps_values_exact(self):
        snapshot = PartSnapshot(id=1, guid="g1", pos="P1", report_properties={"x": 123.456})
        result = snapshot.normalize(0)
        assert result.report_properties["x"] == 123.456

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_values_pass_through(self, value):
        snapshot = PartSnapshot(id=1, guid="g1", pos="P1", report_properties={"x": value})
        result = snapshot.normalize(0.1)
        assert result.report_properties["x"] is value


class TestFilterOptionEmptyConditions:
    """Empty condition lists are rejected instead of failing later with IndexError."""

    @pytest.mark.parametrize("model_class", [StringFilterOption, NumericFilterOption])
    def test_empty_list_raises(self, model_class):
        with pytest.raises(ValidationError):
            model_class(conditions=[])

    def test_single_item_list_accepted(self):
        option = StringFilterOption(conditions=[{"match_type": "Is Equal", "value": "A"}])
        assert option.get_match_type() == "Is Equal"
        assert option.get_values() == ["A"]

    def test_numeric_single_condition_accepted(self):
        option = NumericFilterOption(conditions={"match_type": "Greater Than", "value": 5})
        assert option.to_dict() == {"match_type": "Greater Than", "value": 5.0}


class TestCoerceCustomProperty:
    """Tests for lossless custom property coercion."""

    @pytest.mark.parametrize(
        "value,expected_type,expected",
        [
            (3, "int", 3),
            ("3", "int", 3),
            (3.0, "int", 3),
            ("3.0", "int", 3),
            (10**20, "int", 10**20),
            # An on/off flag sent as a bool is stored by Tekla as 1/0
            (True, "int", 1),
            (False, "int", 0),
            (2, "float", 2.0),
            ("2.5", "float", 2.5),
            (2.5, "float", 2.5),
            ("B500B", "str", "B500B"),
            (12, "str", "12"),
            (1.5, "str", "1.5"),
        ],
    )
    def test_valid_values(self, value, expected_type, expected):
        result = _coerce_custom_property(value, expected_type)
        assert result == expected
        assert type(result) is type(expected)

    @pytest.mark.parametrize(
        "value,expected_type",
        [
            (2.7, "int"),
            ("2.7", "int"),
            (False, "float"),
            (True, "float"),
            (True, "str"),
            (None, "str"),
            (None, "int"),
            ({"a": 1}, "str"),
            ([1], "int"),
            ("abc", "int"),
            ("abc", "float"),
            (float("nan"), "float"),
            ("inf", "int"),
        ],
    )
    def test_invalid_values_raise(self, value, expected_type):
        with pytest.raises((ValueError, TypeError)):
            _coerce_custom_property(value, expected_type)


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

    def test_coerces_without_mutating_input(self):
        """Values are coerced into a copy, the caller's dict stays unchanged."""
        props = {"TopAsBott": "1", "SpacBarsBottPri": "150"}
        component = BaseComponent(name="MeshBars", custom_properties=props)
        assert component.custom_properties == {"TopAsBott": 1, "SpacBarsBottPri": 150.0}
        assert props == {"TopAsBott": "1", "SpacBarsBottPri": "150"}

    def test_fractional_int_raises(self):
        """A fraction for an int property is rejected instead of truncated."""
        with pytest.raises(ValidationError) as exc_info:
            BaseComponent(name="MeshBars", custom_properties={"TopAsBott": 2.7})
        assert "Invalid value for 'TopAsBott'" in str(exc_info.value)

    def test_none_for_str_raises(self):
        """None is not silently turned into the string 'None'."""
        with pytest.raises(ValidationError) as exc_info:
            BaseComponent(name="MeshBars", custom_properties={"BottGradePri": None})
        assert "Invalid value for 'BottGradePri'" in str(exc_info.value)

    def test_invalid_name_reports_only_name_error(self):
        """A failed 'name' does not add a misleading custom_properties error."""
        with pytest.raises(ValidationError) as exc_info:
            BaseComponent(name=123, custom_properties={"TopAsBott": 1})
        errors = exc_info.value.errors()
        assert [e["loc"] for e in errors] == [("name",)]


class TestGetNumberingForClass:
    """Tests for ElementTypes.get_default_numbering function."""

    @pytest.mark.parametrize(
        "tekla_class, expected_keys",
        [
            (1, ["assembly_number"]),  # CONCRETE_WALL - only assembly
            (100, ["assembly_number", "part_number"]),  # STEEL_BEAM - both
            (101, ["assembly_number", "part_number"]),  # STEEL_COLUMN - both
            (999, None),  # Unknown class - should return None
        ],
    )
    def test_get_default_numbering_returns_expected_keys(self, tekla_class, expected_keys):
        """Test that get_default_numbering returns correct keys based on class."""
        from tekla_mcp_server.models import ElementTypes

        result = ElementTypes.get_default_numbering(tekla_class)

        if expected_keys is None:
            assert result is None
        else:
            assert result is not None
            for key in expected_keys:
                assert key in result

    def test_concrete_wall_numbering_only_has_assembly(self):
        """Concrete wall should only have assembly_number, no part_number."""
        from tekla_mcp_server.models import ElementTypes

        result = ElementTypes.get_default_numbering(1)
        assert result is not None
        assert "assembly_number" in result
        assert "part_number" not in result
        assert result["assembly_number"].prefix == "W"
        assert result["assembly_number"].start_number == 1

    def test_steel_beam_numbering_has_both(self):
        """Steel beam should have both part_number and assembly_number."""
        from tekla_mcp_server.models import ElementTypes

        result = ElementTypes.get_default_numbering(100)
        assert result is not None
        assert "assembly_number" in result
        assert "part_number" in result
        assert result["assembly_number"].prefix == "SBA"
        assert result["assembly_number"].start_number == 1
        assert result["part_number"].prefix == "SB"
        assert result["part_number"].start_number == 1

    def test_unknown_class_returns_none(self):
        """Unknown class should return None."""
        from tekla_mcp_server.models import ElementTypes

        result = ElementTypes.get_default_numbering(9999)
        assert result is None


class TestTeklaBeamInputNumbering:
    """Tests for TeklaBeamInput numbering fields."""

    def test_beam_input_with_numbering_series(self):
        """Test BeamInput accepts NumberingSeries."""
        from tekla_mcp_server.models import BeamInput, NumberingSeries, PointInput

        part_number = NumberingSeries(prefix="B", start_number=1)
        assembly_number = NumberingSeries(prefix="BA", start_number=1)

        beam = BeamInput(
            start_point=PointInput(x=0, y=0, z=0),
            end_point=PointInput(x=5000, y=0, z=0),
            profile="HEA200",
            material="S235JR",
            tekla_class=100,
            part_number=part_number,
            assembly_number=assembly_number,
        )

        assert beam.part_number.prefix == "B"
        assert beam.part_number.start_number == 1
        assert beam.assembly_number.prefix == "BA"
        assert beam.assembly_number.start_number == 1

    def test_beam_input_without_numbering(self):
        """Test BeamInput works without numbering (None defaults)."""
        from tekla_mcp_server.models import BeamInput, PointInput

        beam = BeamInput(
            start_point=PointInput(x=0, y=0, z=0),
            end_point=PointInput(x=5000, y=0, z=0),
            profile="HEA200",
            material="S235JR",
            tekla_class=100,
        )

        assert beam.part_number is None
        assert beam.assembly_number is None

    def test_column_input_with_numbering(self):
        """Test ColumnInput accepts NumberingSeries."""
        from tekla_mcp_server.models import ColumnInput, NumberingSeries, PointInput

        part_number = NumberingSeries(prefix="C", start_number=1)

        column = ColumnInput(
            base_point=PointInput(x=0, y=0, z=0),
            height=3000,
            profile="400*400",
            material="C30/37",
            tekla_class=10,
            part_number=part_number,
        )

        assert column.part_number.prefix == "C"
        assert column.assembly_number is None

    def test_panel_input_with_assembly_numbering(self):
        """Test PanelInput accepts assembly numbering (concrete)."""
        from tekla_mcp_server.models import NumberingSeries, PanelInput, PointInput

        assembly_number = NumberingSeries(prefix="W", start_number=1)

        panel = PanelInput(
            start_point=PointInput(x=0, y=0, z=0),
            end_point=PointInput(x=3000, y=0, z=0),
            profile="3000*200",
            material="C30/37",
            tekla_class=1,
            assembly_number=assembly_number,
        )

        assert panel.part_number is None
        assert panel.assembly_number.prefix == "W"


class TestGetElementTypesList:
    """Tests for Config.get_element_types_list method."""

    def test_returns_minimal_format(self):
        """Test that get_element_types_list returns minimal format for discovery."""
        from tekla_mcp_server.config import get_config

        result = get_config().get_element_types_list()
        assert isinstance(result, list)
        assert len(result) > 0

        concrete_wall = next((e for e in result if e["type"] == "CONCRETE_WALL"), None)
        assert concrete_wall is not None
        assert "material" in concrete_wall
        assert "type" in concrete_wall
        assert "tekla_classes" in concrete_wall
        assert "assembly_prefix" not in concrete_wall
        assert "name" not in concrete_wall

        steel_beam = next((e for e in result if e["type"] == "STEEL_BEAM"), None)
        assert steel_beam is not None
        assert "material" in steel_beam
        assert "type" in steel_beam
        assert "tekla_classes" in steel_beam
        assert "part_prefix" not in steel_beam
        assert "name" not in steel_beam


class TestNumberingAutoDetectionLogic:
    """Tests for numbering auto-detection logic without Tekla API."""

    def test_user_provides_only_assembly_gets_part_from_config(self):
        """When user provides assembly but no part, part should come from config."""
        from tekla_mcp_server.models import ElementTypes, NumberingSeries

        user_part = None
        user_assembly = NumberingSeries(prefix="MYA", start_number=99)
        tekla_class = 100  # STEEL_BEAM

        numbering = ElementTypes.get_default_numbering(tekla_class)
        assert numbering is not None

        resolved_part = user_part
        resolved_assembly = user_assembly
        if resolved_assembly is None or resolved_part is None:
            if resolved_assembly is None:
                resolved_assembly = numbering.get("assembly_number")
            if resolved_part is None:
                resolved_part = numbering.get("part_number")

        assert resolved_part is not None
        assert resolved_part.prefix == "SB"
        assert resolved_assembly.prefix == "MYA"
        assert resolved_assembly.start_number == 99

    def test_user_provides_only_part_gets_assembly_from_config(self):
        """When user provides part but no assembly, assembly should come from config."""
        from tekla_mcp_server.models import ElementTypes, NumberingSeries

        user_part = NumberingSeries(prefix="MY-P", start_number=88)
        user_assembly = None
        tekla_class = 100

        numbering = ElementTypes.get_default_numbering(tekla_class)
        assert numbering is not None

        resolved_part = user_part
        resolved_assembly = user_assembly
        if resolved_assembly is None or resolved_part is None:
            if resolved_assembly is None:
                resolved_assembly = numbering.get("assembly_number")
            if resolved_part is None:
                resolved_part = numbering.get("part_number")

        assert resolved_part.prefix == "MY-P"
        assert resolved_part.start_number == 88
        assert resolved_assembly is not None
        assert resolved_assembly.prefix == "SBA"

    def test_user_provides_both_uses_user_values(self):
        """When user provides both, config values are ignored."""
        from tekla_mcp_server.models import ElementTypes, NumberingSeries

        user_part = NumberingSeries(prefix="MY-P", start_number=10)
        user_assembly = NumberingSeries(prefix="MYA", start_number=20)
        tekla_class = 100

        numbering = ElementTypes.get_default_numbering(tekla_class)
        assert numbering is not None

        resolved_part = user_part
        resolved_assembly = user_assembly
        if resolved_assembly is None or resolved_part is None:
            if resolved_assembly is None:
                resolved_assembly = numbering.get("assembly_number")
            if resolved_part is None:
                resolved_part = numbering.get("part_number")

        assert resolved_part.prefix == "MY-P"
        assert resolved_part.start_number == 10
        assert resolved_assembly.prefix == "MYA"
        assert resolved_assembly.start_number == 20

    def test_user_provides_neither_gets_config(self):
        """When user provides neither, both come from config."""
        from tekla_mcp_server.models import ElementTypes

        user_part = None
        user_assembly = None
        tekla_class = 100

        numbering = ElementTypes.get_default_numbering(tekla_class)
        assert numbering is not None

        resolved_part = user_part
        resolved_assembly = user_assembly
        if resolved_assembly is None or resolved_part is None:
            if resolved_assembly is None:
                resolved_assembly = numbering.get("assembly_number")
            if resolved_part is None:
                resolved_part = numbering.get("part_number")

        assert resolved_part.prefix == "SB"
        assert resolved_assembly.prefix == "SBA"

    def test_unknown_class_returns_none_no_override(self):
        """When class not in config, returns None and no override happens."""
        from tekla_mcp_server.models import ElementTypes

        tekla_class = 9999

        numbering = ElementTypes.get_default_numbering(tekla_class)
        assert numbering is None


class TestGetDefaultNameForClass:
    """Tests for get_default_name_for_class function."""

    def test_concrete_wall_returns_name(self):
        """Concrete wall class should return default name."""
        from tekla_mcp_server.models import ElementTypes

        result = ElementTypes.get_default_name(1)
        assert result == "WALL"

    def test_steel_beam_returns_name(self):
        """Steel beam class should return default name."""
        from tekla_mcp_server.models import ElementTypes

        result = ElementTypes.get_default_name(100)
        assert result == "BEAM"

    def test_unknown_class_returns_none(self):
        """Unknown class should return None."""
        from tekla_mcp_server.models import ElementTypes

        result = ElementTypes.get_default_name(9999)
        assert result is None


class TestNameAutoDetectionLogic:
    """Tests for name auto-detection logic without Tekla API."""

    def test_user_provides_name_uses_user_name(self):
        """When user provides name, it should be used."""
        from tekla_mcp_server.models import ElementTypes

        user_name = "MY_CUSTOM_NAME"
        tekla_class = 100

        default_name = ElementTypes.get_default_name(tekla_class)
        resolved_name = user_name if user_name else default_name

        assert resolved_name == "MY_CUSTOM_NAME"

    def test_user_provides_none_gets_default(self):
        """When user provides no name, default from config should be used."""
        from tekla_mcp_server.models import ElementTypes

        user_name = None
        tekla_class = 100

        default_name = ElementTypes.get_default_name(tekla_class)
        resolved_name = user_name if user_name else default_name

        assert resolved_name == "BEAM"

    def test_unknown_class_no_override(self):
        """When class not in config, no name override should happen."""
        from tekla_mcp_server.models import ElementTypes

        user_name = None
        tekla_class = 9999

        default_name = ElementTypes.get_default_name(tekla_class)
        resolved_name = user_name if user_name else default_name

        assert resolved_name is None


class FakeSelection:
    """Minimal stand-in for Tekla's ModelObjectEnumerator."""

    def __init__(self, items: list):
        self._items = items

    def GetSize(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items)


def _as(cls):
    """MagicMock whose __class__ makes isinstance(mock, cls) True."""
    m = MagicMock()
    m.__class__ = cls
    return m


def _run_compare(pairs, ignore_numbering=True):
    from tekla_mcp_server.providers.properties_provider import compare_elements

    raws = [r for r, _ in pairs]
    wrap_map = {id(r): w for r, w in pairs}

    with (
        patch("tekla_mcp_server.providers.properties_provider.TeklaModel") as mock_model_cls,
        patch("tekla_mcp_server.providers.properties_provider.wrap_model_object", side_effect=lambda o: wrap_map.get(id(o))),
    ):
        mock_model_cls.return_value.get_selected_objects.return_value = FakeSelection(raws)
        return compare_elements(ignore_numbering=ignore_numbering)


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skipping (Tekla not available in CI)")
class TestCompareElementsTypeHomogeneity:
    def test_part_and_reinforcement_rejected(self):
        from tekla_mcp_server.tekla.wrappers.model_object import TeklaPart, TeklaReinforcement

        result = _run_compare([(MagicMock(), _as(TeklaPart)), (MagicMock(), _as(TeklaReinforcement))])
        assert result.structured_content["status"] == "error"
        assert "mixed" in result.structured_content["message"].lower()

    def test_part_and_assembly_rejected(self):
        from tekla_mcp_server.tekla.wrappers.model_object import TeklaAssembly, TeklaPart

        result = _run_compare([(MagicMock(), _as(TeklaPart)), (MagicMock(), _as(TeklaAssembly))])
        assert result.structured_content["status"] == "error"
        assert "mixed" in result.structured_content["message"].lower()

    def test_error_message_names_both_categories(self):
        from tekla_mcp_server.tekla.wrappers.model_object import TeklaPart, TeklaReinforcement

        result = _run_compare([(MagicMock(), _as(TeklaPart)), (MagicMock(), _as(TeklaReinforcement))])
        msg = result.structured_content["message"].lower()
        assert "part" in msg
        assert "reinforcement" in msg

    def test_two_parts_not_rejected(self):
        from tekla_mcp_server.tekla.wrappers.model_object import TeklaPart

        result = _run_compare([(MagicMock(), _as(TeklaPart)), (MagicMock(), _as(TeklaPart))])
        assert "mixed" not in result.structured_content.get("message", "").lower()

    def test_two_reinforcements_not_rejected(self):
        from tekla_mcp_server.tekla.wrappers.model_object import TeklaReinforcement

        result = _run_compare([(MagicMock(), _as(TeklaReinforcement)), (MagicMock(), _as(TeklaReinforcement))])
        assert "mixed" not in result.structured_content.get("message", "").lower()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    ("model", "fields", "field"),
    [
        (PointInput, {"x": 0, "y": 0, "z": 0}, "x"),
        (OffsetInput, {"dx": 0, "dy": 0, "dz": 0}, "dz"),
        (PositionInput, {}, "plane_offset"),
        (PositionInput, {}, "rotation_offset"),
    ],
)
def test_placement_inputs_reject_non_finite(model, fields, field, bad):
    """Coordinates and offsets reject NaN and infinity, which would corrupt the placed geometry."""
    with pytest.raises(ValidationError):
        model(**{**fields, field: bad})


class TestFilterCondition:
    def test_field_condition(self):
        condition = FilterCondition(field="part.profile", op="Starts With", value="HEA")
        assert (condition.kind, condition.value) == ("string", "HEA")

    def test_attribute_defaults_to_part_category(self):
        assert FilterCondition(attribute="HEIGHT", op="Greater Than", value=2000).category == "part"

    @pytest.mark.parametrize("value,extra,kind", [(1, {}, "numeric"), (1.5, {}, "numeric"), (True, {}, "boolean"), ("x", {}, "string"), ("2026-01-31", {"type": "date"}, "date")])
    def test_attribute_kind_follows_value(self, value, extra, kind):
        op = "Is Equal"
        assert FilterCondition(attribute="A", op=op, value=value, **extra).kind == kind

    def test_number_becomes_text_for_string_field(self):
        assert FilterCondition(field="part.position_number", op="Is Equal", value=7).value == "7"

    @pytest.mark.parametrize("value,expected", [("5", 5), ("2.5", 2.5), (" 12 ", 12)])
    def test_numeric_text_becomes_number(self, value, expected):
        assert FilterCondition(field="part.class", op="Is Equal", value=value).value == expected

    def test_readable_value_is_lowercased(self):
        assert FilterCondition(field="bolt.site_workshop", op="Is Equal", value=" Site ").value == "site"

    @pytest.mark.parametrize(
        "data,message",
        [
            ({"op": "Is Equal", "value": 1}, "exactly one of `field` or `attribute`"),
            ({"field": "part.name", "attribute": "A", "op": "Is Equal", "value": "x"}, "exactly one of `field` or `attribute`"),
            ({"field": "part.nope", "op": "Is Equal", "value": 1}, "Unknown field 'part.nope'"),
            ({"attribute": "A", "category": "beam", "op": "Is Equal", "value": 1}, "Unknown category 'beam'"),
            ({"attribute": "  ", "op": "Is Equal", "value": 1}, "must not be empty"),
            ({"field": "part.class", "op": "Contains", "value": 1}, "does not apply to 'part.class'"),
            ({"field": "part.name", "op": "Greater Than", "value": "A"}, "does not apply to 'part.name'"),
            ({"field": "bolt.site_workshop", "op": "Contains", "value": "site"}, "does not apply"),
            ({"field": "bolt.site_workshop", "op": "Is Equal", "value": "factory"}, "Must be one of"),
            ({"field": "weld.type_above", "op": "Is Equal", "value": 10}, "Must be one of"),
            ({"field": "part.element_type", "op": "Starts With", "value": "Wall"}, "does not apply"),
            ({"field": "part.class", "op": "Is Equal", "value": "abc"}, "takes a number"),
            ({"field": "part.class", "op": "Is Equal", "value": True}, "does not take true or false"),
            ({"field": "part.class", "op": "Is Equal", "value": float("inf")}, "finite number"),
            ({"field": "part.name", "op": "Is Equal", "value": False}, "does not take true or false"),
            ({"attribute": "A", "op": "Is Equal", "value": "31.01.2026", "type": "date"}, "ISO date"),
            ({"field": "part.name", "op": "Is Equal", "value": "x", "type": "date"}, "applies to `attribute` conditions only"),
            ({"attribute": "A", "op": "Contains", "value": True}, "does not apply to 'A'"),
            ({"attribute": "A", "op": "Is Equal", "value": 1, "unexpected": 1}, "Extra inputs"),
        ],
    )
    def test_invalid_conditions(self, data, message):
        with pytest.raises(ValidationError, match=message):
            FilterCondition.model_validate(data)


class TestFilterGroup:
    def test_nested_groups(self):
        group = FilterGroup.model_validate({"all": [{"field": "part.name", "op": "Is Equal", "value": "A"}, {"any": [{"all": [{"field": "part.class", "op": "Is Equal", "value": 1}]}]}]})
        assert not group.is_any
        inner = group.items[1]
        assert isinstance(inner, FilterGroup) and inner.is_any
        assert isinstance(inner.items[0], FilterGroup)

    def test_items_are_parsed_as_conditions(self):
        group = FilterGroup.model_validate({"any": [{"attribute": "A", "op": "Is Equal", "value": 1}]})
        assert isinstance(group.items[0], FilterCondition)

    @pytest.mark.parametrize(
        "data,message",
        [
            ({}, "exactly one of `all` or `any`"),
            ({"all": [], "any": []}, "exactly one of `all` or `any`"),
            ({"all": []}, "at least one item"),
            ({"any": [{"field": "part.nope", "op": "Is Equal", "value": 1}]}, "Unknown field"),
            ({"all": [{"all": []}]}, "at least one item"),
            ({"or": [{"field": "part.name", "op": "Is Equal", "value": "A"}]}, "Extra inputs"),
        ],
    )
    def test_invalid_groups(self, data, message):
        with pytest.raises(ValidationError, match=message):
            FilterGroup.model_validate(data)


def _leaf(value: str) -> dict:
    """Build a part name condition dict."""
    return {"field": "part.name", "op": "Is Equal", "value": value}


def _shape(node) -> object:
    """Describe a filter tree as nested tuples of 'all'/'any' and leaf values."""
    if isinstance(node, FilterCondition):
        return node.value
    return ("any" if node.is_any else "all", [_shape(item) for item in node.items])


class TestSimplifyFilterTree:
    def test_condition_is_returned_as_is(self):
        condition = FilterCondition.model_validate(_leaf("A"))
        assert simplify_filter_tree(condition) is condition

    def test_single_item_group_is_unwrapped(self):
        assert _shape(simplify_filter_tree(FilterGroup.model_validate({"any": [_leaf("A")]}))) == "A"

    def test_same_kind_groups_are_merged(self):
        tree = FilterGroup.model_validate({"all": [_leaf("A"), {"all": [_leaf("B"), {"all": [_leaf("C")]}]}]})
        assert _shape(simplify_filter_tree(tree)) == ("all", ["A", "B", "C"])

    def test_different_kinds_stay_nested(self):
        tree = FilterGroup.model_validate({"all": [_leaf("A"), {"any": [_leaf("B"), _leaf("C")]}]})
        assert _shape(simplify_filter_tree(tree)) == ("all", ["A", ("any", ["B", "C"])])

    def test_unwrapping_can_enable_a_merge(self):
        tree = FilterGroup.model_validate({"any": [_leaf("A"), {"all": [{"any": [_leaf("B"), _leaf("C")]}]}]})
        assert _shape(simplify_filter_tree(tree)) == ("any", ["A", "B", "C"])


class TestFilterConditionLists:
    def test_numeric_list_items_are_converted(self):
        assert FilterCondition(field="part.class", op="Is Equal", value=["1", 8, "2.5"]).value == [1, 8, 2.5]

    def test_readable_list_is_lowercased(self):
        assert FilterCondition(field="bolt.site_workshop", op="Is Not Equal", value=["Site", " WORKSHOP"]).value == ["site", "workshop"]

    def test_attribute_list_kind(self):
        assert FilterCondition(attribute="A", op="Is Equal", value=[1, 2.5]).kind == "numeric"
        assert FilterCondition(attribute="A", op="Is Equal", value=[1, "x"]).kind == "string"

    def test_values_property(self):
        assert FilterCondition(field="part.name", op="Is Equal", value="A").values == ["A"]

    @pytest.mark.parametrize(
        "data,message",
        [
            ({"field": "part.class", "op": "Is Equal", "value": []}, "at least one value"),
            ({"field": "part.class", "op": "Is Equal", "value": [1, "x"]}, "takes a number"),
            ({"field": "bolt.site_workshop", "op": "Is Equal", "value": ["site", "factory"]}, "Must be one of"),
            ({"attribute": "A", "op": "Is Equal", "value": ["2026-01-31"], "type": "date"}, "single value, not a list"),
            ({"field": "part.class", "op": "Is Equal", "value": [1, True]}, "Input should be"),
        ],
    )
    def test_invalid_lists(self, data, message):
        with pytest.raises(ValidationError, match=message):
            FilterCondition.model_validate(data)


def _spec(node: dict, object_type: str):
    """Specialize a dict tree for one object type and describe the result."""
    tree = FilterGroup.model_validate(node) if "all" in node or "any" in node else FilterCondition.model_validate(node)
    result = specialize_filter_tree(tree, object_type)
    return result if result is None or isinstance(result, bool) else _shape(result)


PART_A = {"field": "part.name", "op": "Is Equal", "value": "A"}
BOLT_16 = {"field": "bolt.size", "op": "Is Equal", "value": 16}
ASM_B = {"field": "assembly.prefix", "op": "Is Equal", "value": "B"}


class TestSpecializeFilterTree:
    def test_own_category_condition_is_kept(self):
        assert _spec(PART_A, "part") == "A"

    def test_other_category_condition_does_not_apply(self):
        assert _spec(PART_A, "bolt") is None

    @pytest.mark.parametrize("node", [ASM_B, {"field": "object.phase", "op": "Is Equal", "value": 1}, {"attribute": "X", "category": "template", "op": "Is Equal", "value": 1}])
    def test_cross_type_conditions_apply_to_every_type(self, node):
        assert _spec(node, "bolt") is not None

    def test_drops_out_of_all(self):
        assert _spec({"all": [PART_A, BOLT_16]}, "part") == "A"

    def test_drops_out_of_any(self):
        assert _spec({"any": [PART_A, BOLT_16]}, "bolt") == 16

    def test_group_of_other_conditions_does_not_apply(self):
        assert _spec({"any": [PART_A, {"all": [PART_A]}]}, "bolt") is None

    @pytest.mark.parametrize("op,object_type,expected", [("Is Equal", "weld", True), ("Is Equal", "part", False), ("Is Not Equal", "weld", False), ("Is Not Equal", "part", True)])
    def test_object_type_condition_is_decided(self, op, object_type, expected):
        assert _spec({"field": "object.type", "op": op, "value": "weld"}, object_type) is expected

    def test_object_type_list(self):
        assert _spec({"field": "object.type", "op": "Is Equal", "value": ["weld", "bolt"]}, "bolt") is True

    def test_true_decides_any(self):
        assert _spec({"any": [{"field": "object.type", "op": "Is Equal", "value": "weld"}, ASM_B]}, "weld") is True

    def test_false_drops_out_of_any(self):
        assert _spec({"any": [{"field": "object.type", "op": "Is Equal", "value": "weld"}, ASM_B]}, "part") == "B"

    def test_false_decides_all(self):
        assert _spec({"all": [{"field": "object.type", "op": "Is Equal", "value": "weld"}, ASM_B]}, "part") is False

    def test_true_drops_out_of_all(self):
        assert _spec({"all": [{"field": "object.type", "op": "Is Equal", "value": "weld"}, ASM_B]}, "weld") == "B"

    def test_all_true_items_give_true(self):
        assert _spec({"all": [{"field": "object.type", "op": "Is Equal", "value": "weld"}, BOLT_16]}, "weld") is True

    def test_all_false_items_give_false(self):
        assert _spec({"any": [{"field": "object.type", "op": "Is Equal", "value": "weld"}, BOLT_16]}, "part") is False

    def test_result_is_simplified(self):
        node = {"all": [ASM_B, {"any": [PART_A, BOLT_16]}]}
        assert _spec(node, "part") == ("all", ["B", "A"])

    def test_nested_mixed_tree(self):
        node = {"any": [{"all": [PART_A, ASM_B]}, {"all": [BOLT_16, {"field": "object.type", "op": "Is Equal", "value": "bolt"}]}]}
        assert _spec(node, "part") == ("all", ["A", "B"])
        assert _spec(node, "bolt") == ("any", ["B", 16])
