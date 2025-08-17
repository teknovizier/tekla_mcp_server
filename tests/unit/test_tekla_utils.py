"""
Unit tests for Tekla utility functions.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.

Tested modules:
- tekla_utils.py
"""

import os
import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from models import ReportProperty
from tekla_utils import TeklaModelObject, parse_template_attribute, get_wall_pairs
from init import load_dlls

# Tekla OpenAPI imports
load_dlls()
from Tekla.Structures.Model import Beam, Position
from Tekla.Structures.Geometry3d import Point


def mock_beam(x, y, z, name="TEST_WALL"):
    """Helper for mocking beams."""
    beam = Beam()
    beam.Profile.ProfileString = "3000*200"
    beam.Material.MaterialString = "Concrete_Undefined"
    beam.Class = "1"
    beam.Name = name
    beam.Position.Depth = Position.DepthEnum.FRONT
    beam.StartPoint = Point(x, y, z)
    beam.EndPoint = Point(x + 2000, y, z)
    beam.Insert()
    return beam


# Tests for `TeklaModelObject`
def test_is_part_property():
    """Checks that a beam object is correctly identified as a part."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.is_part is True
    assert obj.is_assembly is False


def test_is_assembly_property():
    """Checks that an assembly object is correctly identified as an assembly."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1.GetAssembly())
    assert obj.is_assembly is True
    assert obj.is_part is False


def test_position_property():
    """Checks that the position property is correctly retrieved."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.position is not None


def test_guid_property():
    """Checks that the GUID property is a non-null string of length 36."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.guid is not None
    assert isinstance(obj.guid, str)
    assert len(obj.guid) == 36


def test_name_property():
    """Checks that the name property is correctly retrieved."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.name == "TEST_WALL1"


def test_profile_property():
    """Checks that the profile property is correctly retrieved."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.profile == "3000*200"


def test_material_property():
    """Checks that the material property is correctly retrieved."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.material == "Concrete_Undefined"


def test_finish_property():
    """Checks that the finish property is correctly retrieved."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.finish == ""


def test_tekla_class_property():
    """Checks that the tekla_class property is correctly retrieved."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.tekla_class == "1"


def test_main_part_property():
    """Checks that the main part of an assembly is a TeklaModelObject wrapping a Beam."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1.GetAssembly())
    main_part = obj.main_part
    assert isinstance(main_part, TeklaModelObject)
    assert isinstance(main_part.model_object, Beam)


def test_cog_property():
    """Checks that the center of gravity (COG) is correctly calculated."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    cog = obj.cog
    assert (cog.X, cog.Y, cog.Z) == (1000.0, 0.0, 1500.0)


def test_weight_property():
    """Checks that the total and rebar weights are correctly returned."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    total_weight, rebar_weight = obj.weight
    assert total_weight == pytest.approx(2880.0, abs=0.1)
    assert rebar_weight == 0.0


def test_get_top_level_assembly():
    """Checks that the top-level assembly is correctly retrieved."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assembly = obj.get_top_level_assembly()
    assert assembly.is_assembly
    assert assembly.model_object.Equals(wall1.GetAssembly())


def test_get_report_property_weight_property():
    """Checks that a report property can be retrieved correctly."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.get_report_property("WEIGHT", float) == pytest.approx(2880.0, abs=0.1)


def test_get_user_property_invalid():
    """Checks that accessing an invalid user property raises AttributeError."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    with pytest.raises(AttributeError):
        obj.get_user_property("InvalidProperty", str)


def test_get_user_property_test_property():
    """Checks that a user-defined property can be retrieved correctly."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    obj.set_user_property("TestProperty", "TestValue")
    assert obj.get_user_property("TestProperty", str) == "TestValue"


def test_set_user_property_test_property():
    """Checks that setting a user-defined property returns True on success."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    obj = TeklaModelObject(wall1)
    assert obj.set_user_property("TestProperty", "TestValue") is True


# Tests for `parse_template_attribute`
@pytest.mark.parametrize(
    "attr_name,expected_type,expected_unit",
    [("ASSEMBLY_TOP_LEVEL", str, None), ("AREA", float, "m2"), ("ASSEMBLY_TOP_LEVEL_UNFORMATTED_BASEPOINT", float, "mm"), ("SHIPMENT_NUMBER", str, None)],
)
def test_parse_template_attribute(attr_name, expected_type, expected_unit):
    """Checks that `parse_template_attribute` returns correct template attributes properties."""
    rp = parse_template_attribute(attr_name)

    assert isinstance(rp, ReportProperty)
    assert rp.name == attr_name
    assert rp.data_type == expected_type
    assert rp.unit == expected_unit


# Tests for `get_wall_pairs`
def test_pair_two_matching_walls():
    """Checks pairing of two matching walls."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    wall2 = mock_beam(0, 0, 3000, "TEST_WALL2")
    result = get_wall_pairs([wall1, wall2])
    assert result == [(wall1, wall2)]


def test_pair_multiple_walls():
    """Checks pairing of multiple wall pairs."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    wall2 = mock_beam(0, 0, 3000, "TEST_WALL2")
    wall3 = mock_beam(5000, 0, 0, "TEST_WALL3")
    wall4 = mock_beam(5000, 0, 3000, "TEST_WALL4")
    result = get_wall_pairs([wall1, wall2, wall3, wall4])
    assert (wall1, wall2) in result
    assert (wall3, wall4) in result
    assert len(result) == 2


def test_less_than_two_elements_raises_error():
    """Checks error for less than two elements."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    with pytest.raises(ValueError):
        get_wall_pairs([wall1])


def test_more_than_two_floors_raises_error():
    """Checks error for more than two floors."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    wall2 = mock_beam(0, 0, 3000, "TEST_WALL2")
    wall3 = mock_beam(0, 0, 6000, "TEST_WALL3")
    with pytest.raises(ValueError):
        get_wall_pairs([wall1, wall2, wall3])


def test_z_coordinate_mismatch_raises_error():
    """Checks error for Z coordinate mismatch."""
    wall = mock_beam(0, 0, 0, "TEST_WALL")
    wall.EndPoint.Z = 100  # mismatch
    with pytest.raises(ValueError):
        get_wall_pairs([wall, wall])


def test_non_beam_objects_are_ignored():
    """Checks that non-beam objects are ignored."""
    wall1 = mock_beam(0, 0, 0, "TEST_WALL1")
    wall2 = mock_beam(0, 0, 3000, "TEST_WALL2")
    not_beam = object()
    result = get_wall_pairs([wall1, wall2, not_beam])
    assert result == [(wall1, wall2)]
