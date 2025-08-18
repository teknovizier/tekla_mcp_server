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

from tekla_loader import Beam, Position, Point
from tekla_utils import TeklaModelObject, parse_template_attribute, get_wall_pairs


created_elements = []


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    """
    Fixture that ensures all Tekla model objects created during
    the test module are deleted after the tests complete.
    """
    yield
    for element in created_elements:
        if element.Identifier.IsValid():
            element.Delete()


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
    created_elements.append(beam)
    return beam


@pytest.fixture
def wall1():
    """Returns a TeklaModelObject wrapping a mock beam."""
    return TeklaModelObject(mock_beam(0, 0, 0, "TEST_WALL1"))


# Tests for `TeklaModelObject`
def test_is_part_property(wall1):
    """Checks that a beam object is correctly identified as a part."""
    assert wall1.is_part is True
    assert wall1.is_assembly is False


def test_is_assembly_property(wall1):
    """Checks that an assembly object is correctly identified as an assembly."""
    assembly = wall1.get_top_level_assembly()
    assert assembly.is_assembly is True
    assert assembly.is_part is False


def test_position_property(wall1):
    """Checks that the position property is correctly retrieved."""
    assert wall1.position is not None


def test_guid_property(wall1):
    """Checks that the GUID property is a non-null string of length 36."""
    assert wall1.guid is not None
    assert isinstance(wall1.guid, str)
    assert len(wall1.guid) == 36


def test_basic_properties(wall1):
    """Checks that basic properties are correctly retrieved."""
    assert wall1.name == "TEST_WALL1"
    assert wall1.profile == "3000*200"
    assert wall1.material == "Concrete_Undefined"
    assert wall1.finish == ""
    assert wall1.tekla_class == "1"


def test_main_part_property(wall1):
    """Checks that the main part of an assembly is a TeklaModelObject wrapping a Beam."""
    main_part = wall1.get_top_level_assembly().main_part
    assert isinstance(main_part, TeklaModelObject)
    assert isinstance(main_part.model_object, Beam)


def test_cog_property(wall1):
    """Checks that the center of gravity (COG) is correctly calculated."""
    cog = wall1.cog
    assert (cog.X, cog.Y, cog.Z) == (1000.0, 0.0, 1500.0)


def test_weight_property(wall1):
    """Checks that the total and rebar weights are correctly returned."""
    total_weight, rebar_weight = wall1.weight
    assert total_weight == pytest.approx(2880.0, abs=0.1)
    assert rebar_weight == 0.0


def test_get_top_level_assembly(wall1):
    """Checks that the top-level assembly is correctly retrieved."""
    assembly = wall1.get_top_level_assembly()
    assert assembly.is_assembly
    assert assembly.model_object.Equals(wall1.model_object.GetAssembly())


def test_get_report_property_weight_property(wall1):
    """Checks that a report property can be retrieved correctly."""
    assert wall1.get_report_property("WEIGHT", float) == pytest.approx(2880.0, abs=0.1)


def test_get_user_property_invalid(wall1):
    """Checks that accessing an invalid user property raises AttributeError."""
    with pytest.raises(AttributeError):
        wall1.get_user_property("InvalidProperty", str)


def test_get_user_property_test_property(wall1):
    """Checks that a user-defined property can be retrieved correctly."""
    wall1.set_user_property("TestProperty", "TestValue")
    assert wall1.get_user_property("TestProperty", str) == "TestValue"


def test_set_user_property_test_property(wall1):
    """Checks that setting a user-defined property returns True on success."""
    assert wall1.set_user_property("TestProperty", "TestValue") is True


def test_get_all_user_properties_empty(wall1):
    """Checks that an empty dictionary is returned when no user-defined properties exist."""
    assert not wall1.get_all_user_properties()


def test_get_all_user_properties_test_property(wall1):
    """Checks that a user-defined property can be retrieved correctly."""
    wall1.set_user_property("TestProperty", "TestValue")
    assert len(wall1.get_all_user_properties()) == 1
    assert wall1.get_all_user_properties()["TestProperty"] == "TestValue"


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
