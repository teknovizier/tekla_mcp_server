"""
Unit tests for Tekla model object wrappers.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.

Tested modules:
- tekla_model_object.py
"""

import os
import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from typing import Any
from unittest.mock import MagicMock

from tekla_mcp_server.tekla.loader import Beam, Position, Point
from tekla_mcp_server.tekla.model_object import wrap_model_object, TeklaPart


created_elements: Any = []


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
    return wrap_model_object(mock_beam(0, 0, 0, "TEST_WALL1"))


def test_position_property(wall1):
    """Checks that the position property is correctly retrieved."""
    assert wall1.position is not None


def test_id_property(wall1):
    """Checks that the ID property is an int."""
    assert wall1.guid is not None
    assert isinstance(wall1.id, int)


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
    """Checks that the main part of an assembly is a TeklaPart wrapping a Beam."""
    main_part = wall1.get_top_level_assembly().main_part
    assert isinstance(main_part, TeklaPart)
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
    assert assembly.model_object.Equals(wall1.model_object.GetAssembly())


def test_get_report_property_weight_property(wall1):
    """Checks that a report property can be retrieved correctly."""
    assert wall1.get_report_property("WEIGHT") == pytest.approx(2880.0, abs=0.1)


def test_get_report_property_invalid(wall1):
    """Checks that accessing an invalid report property raises AttributeError."""
    with pytest.raises(ValueError):
        wall1.get_report_property("INVALID_PROPERTY_NAME")


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


def test_has_spatial_overlap_no_overlap(wall1):
    """Checks that has_spatial_overlap returns False when there is no overlap."""
    other_beam = mock_beam(10000, 10000, 10000, "TEST_WALL_OTHER")
    other_wall = wrap_model_object(other_beam)
    assert wall1.has_spatial_overlap(other_wall) is False


def test_wrap_model_object_returns_tekla_part(wall1):
    """Checks that wrap_model_object returns TeklaPart for a Beam."""
    from tekla_mcp_server.tekla.model_object import wrap_model_object, TeklaPart

    wrapped = wrap_model_object(wall1.model_object)
    assert isinstance(wrapped, TeklaPart)


def test_wrap_model_object_returns_none_for_unsupported():
    """Checks that wrap_model_object returns None for unsupported types."""
    from tekla_mcp_server.tekla.model_object import wrap_model_object

    mock_obj = MagicMock()
    mock_obj.GetTypeName.return_value = "UnsupportedType"
    result = wrap_model_object(mock_obj)
    assert result is None


def test_wrap_model_objects_generator():
    """Checks that wrap_model_objects yields wrapped objects."""
    from tekla_mcp_server.tekla.model_object import wrap_model_objects, TeklaPart

    mock_beam1 = mock_beam(0, 0, 0, "TEST_WALL_GEN1")
    mock_beam2 = mock_beam(5000, 0, 0, "TEST_WALL_GEN2")
    mock_enumerator = [mock_beam1, mock_beam2]
    wrapped_list = list(wrap_model_objects(mock_enumerator))
    assert len(wrapped_list) == 2
    assert all(isinstance(w, TeklaPart) for w in wrapped_list)
