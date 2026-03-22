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
    """Checks that accessing an invalid report property raises KeyError."""
    with pytest.raises(KeyError):
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


def test_part_to_snapshot(wall1):
    """Checks that to_snapshot returns a valid PartSnapshot."""
    snapshot = wall1.to_snapshot()

    assert snapshot.id == wall1.id
    assert snapshot.guid == wall1.guid
    assert snapshot.pos == wall1.position
    assert isinstance(snapshot.report_properties, dict)
    assert isinstance(snapshot.user_properties, dict)
    assert isinstance(snapshot.cutparts, list)
    assert isinstance(snapshot.reinforcements, list)
    assert isinstance(snapshot.welds, list)


def test_part_to_snapshot_serializable(wall1):
    """Checks that PartSnapshot is JSON-serializable."""
    snapshot = wall1.to_snapshot()
    dumped = snapshot.model_dump()
    assert isinstance(dumped, dict)
    json_str = snapshot.model_dump_json()
    assert isinstance(json_str, str)


def test_assembly_to_snapshot(wall1):
    """Checks that assembly to_snapshot returns a valid AssemblySnapshot."""
    assembly = wall1.get_top_level_assembly()
    snapshot = assembly.to_snapshot()

    assert snapshot.id == assembly.id
    assert snapshot.guid == assembly.guid
    assert snapshot.pos == assembly.position
    assert isinstance(snapshot.report_properties, dict)
    assert isinstance(snapshot.user_properties, dict)
    assert snapshot.main_part is not None
    assert isinstance(snapshot.secondaries, list)
    assert isinstance(snapshot.subassemblies, list)


def test_assembly_to_snapshot_main_part(wall1):
    """Checks that assembly snapshot contains main part as PartSnapshot."""
    assembly = wall1.get_top_level_assembly()
    snapshot = assembly.to_snapshot()

    assert snapshot.main_part is not None
    assert snapshot.main_part.id == wall1.id
    assert snapshot.main_part.guid == wall1.guid


def test_assembly_to_snapshot_serializable(wall1):
    """Checks that AssemblySnapshot is JSON-serializable."""
    assembly = wall1.get_top_level_assembly()
    snapshot = assembly.to_snapshot()

    dumped = snapshot.model_dump()
    assert isinstance(dumped, dict)
    json_str = snapshot.model_dump_json()
    assert isinstance(json_str, str)


def test_assembly_set_properties_name(wall1):
    """Checks that assembly name can be changed using set_properties."""
    assembly = wall1.get_top_level_assembly()
    original_name = assembly.name

    changes = assembly.set_properties(name="NEW_ASSEMBLY_NAME")

    assert changes["name"] == 1
    assert assembly.name == "NEW_ASSEMBLY_NAME"

    assembly.set_properties(name=original_name)
    assert assembly.name == original_name


def test_assembly_set_properties_assembly_numbering(wall1):
    """Checks that assembly numbering can be changed using set_properties."""
    assembly = wall1.get_top_level_assembly()
    original_prefix = assembly.assembly_number.prefix
    original_start = assembly.assembly_number.start_number

    changes = assembly.set_properties(assembly_prefix="Z", assembly_start_number=999)

    assert changes["assembly_prefix"] == 1
    assert changes["assembly_start_number"] == 1
    assert assembly.assembly_number.prefix == "Z"
    assert assembly.assembly_number.start_number == 999

    assembly.set_properties(assembly_prefix=original_prefix, assembly_start_number=original_start)
    assert assembly.assembly_number.prefix == original_prefix
    assert assembly.assembly_number.start_number == original_start


def test_part_get_properties(wall1):
    """Checks that TeklaPart.get_properties returns all expected fields."""
    props = wall1.get_properties()

    assert "guid" in props
    assert "name" in props
    assert "position" in props
    assert "profile" in props
    assert "material" in props
    assert "finish" in props
    assert "tekla_class" in props
    assert "part_prefix" in props
    assert "part_start_number" in props
    assert "assembly_prefix" in props
    assert "assembly_start_number" in props
    assert "user_properties" in props
    assert "report_properties" in props

    assert props["name"] == "TEST_WALL1"
    assert props["profile"] == "3000*200"
    assert props["material"] == "Concrete_Undefined"
    assert props["tekla_class"] == "1"


def test_part_set_properties_profile(wall1):
    """Checks that TeklaPart profile can be changed using set_properties."""
    original_profile = wall1.profile

    changes = wall1.set_properties(profile="4000*300")
    assert changes["profile"] == 1
    assert wall1.profile == "4000*300"

    wall1.set_properties(profile=original_profile)
    assert wall1.profile == original_profile


def test_part_set_properties_material(wall1):
    """Checks that TeklaPart material can be changed using set_properties."""
    original_material = wall1.material

    changes = wall1.set_properties(material="CONCRETE-30")
    assert changes["material"] == 1
    assert wall1.material == "CONCRETE-30"

    wall1.set_properties(material=original_material)
    assert wall1.material == original_material


def test_part_set_properties_tekla_class(wall1):
    """Checks that TeklaPart class can be changed using set_properties."""
    original_class = wall1.tekla_class

    changes = wall1.set_properties(tekla_class="2")
    assert changes["tekla_class"] == 1
    assert wall1.tekla_class == "2"

    wall1.set_properties(tekla_class=original_class)
    assert wall1.tekla_class == original_class


def test_part_set_properties_finish(wall1):
    """Checks that TeklaPart finish can be changed using set_properties."""
    original_finish = wall1.finish

    changes = wall1.set_properties(finish="R")
    assert changes["finish"] == 1
    assert wall1.finish == "R"

    wall1.set_properties(finish=original_finish)
    assert wall1.finish == original_finish


def test_part_set_properties_part_numbering(wall1):
    """Checks that TeklaPart part numbering can be changed using set_properties."""
    original_prefix = wall1.part_number.prefix
    original_start = wall1.part_number.start_number

    changes = wall1.set_properties(part_prefix="X", part_start_number=500)
    assert changes["part_prefix"] == 1
    assert changes["part_start_number"] == 1
    assert wall1.part_number.prefix == "X"
    assert wall1.part_number.start_number == 500

    wall1.set_properties(part_prefix=original_prefix, part_start_number=original_start)
    assert wall1.part_number.prefix == original_prefix
    assert wall1.part_number.start_number == original_start


def test_part_set_properties_assembly_numbering(wall1):
    """Checks that TeklaPart assembly numbering can be changed using set_properties."""
    original_prefix = wall1.assembly_number.prefix
    original_start = wall1.assembly_number.start_number

    changes = wall1.set_properties(assembly_prefix="Y", assembly_start_number=600)
    assert changes["assembly_prefix"] == 1
    assert changes["assembly_start_number"] == 1
    assert wall1.assembly_number.prefix == "Y"
    assert wall1.assembly_number.start_number == 600

    wall1.set_properties(assembly_prefix=original_prefix, assembly_start_number=original_start)
    assert wall1.assembly_number.prefix == original_prefix
    assert wall1.assembly_number.start_number == original_start


def test_part_set_properties_user_properties(wall1):
    """Checks that TeklaPart user properties can be set using set_properties."""
    changes = wall1.set_properties(user_properties={"TestUDA_Part": "PartValue"})
    assert changes["udas"] == 1
    assert wall1.get_user_property("TestUDA_Part", str) == "PartValue"


def test_assembly_set_properties_user_properties(wall1):
    """Checks that TeklaAssembly user properties can be set using set_properties."""
    assembly = wall1.get_top_level_assembly()

    changes = assembly.set_properties(user_properties={"AssemblyUDA": "AssemblyValue"})
    assert changes["udas"] == 1
    assert assembly.get_user_property("AssemblyUDA", str) == "AssemblyValue"


def test_assembly_set_properties_multiple(wall1):
    """Checks that multiple TeklaAssembly properties can be changed at once."""
    assembly = wall1.get_top_level_assembly()
    original_name = assembly.name
    original_prefix = assembly.assembly_number.prefix
    original_start = assembly.assembly_number.start_number

    changes = assembly.set_properties(
        name="MCP_WALL_MULTI_ASSEMBLY_TEST",
        assembly_prefix="MULTI",
        assembly_start_number=999,
    )

    assert changes["name"] == 1
    assert changes["assembly_prefix"] == 1
    assert changes["assembly_start_number"] == 1
    assert assembly.name == "MCP_WALL_MULTI_ASSEMBLY_TEST"
    assert assembly.assembly_number.prefix == "MULTI"
    assert assembly.assembly_number.start_number == 999

    assembly.set_properties(
        name=original_name,
        assembly_prefix=original_prefix,
        assembly_start_number=original_start,
    )


def test_assembly_get_properties(wall1):
    """Checks that TeklaAssembly.get_properties returns correct fields for assembly."""
    assembly = wall1.get_top_level_assembly()
    props = assembly.get_properties()

    assert "guid" in props
    assert "name" in props
    assert "position" in props
    assert "assembly_prefix" in props
    assert "assembly_start_number" in props
    assert "user_properties" in props
    assert "report_properties" in props

    assert "profile" not in props
    assert "material" not in props
    assert "finish" not in props
    assert "tekla_class" not in props


def test_phase_property(wall1):
    """Checks that the phase property returns an integer."""
    phase = wall1.phase
    assert isinstance(phase, int)
    assert phase >= 0


def test_part_get_properties_includes_phase(wall1):
    """Checks that TeklaPart.get_properties includes phase field."""
    props = wall1.get_properties()
    assert "phase" in props
    assert isinstance(props["phase"], int)


def test_assembly_get_properties_includes_phase(wall1):
    """Checks that TeklaAssembly.get_properties includes phase field."""
    assembly = wall1.get_top_level_assembly()
    props = assembly.get_properties()
    assert "phase" in props
    assert isinstance(props["phase"], int)
    assert "part_prefix" not in props
    assert "part_start_number" not in props


def test_part_set_properties_phase(wall1):
    """Checks that TeklaPart phase can be changed using set_properties."""
    original_phase = wall1.phase

    changes = wall1.set_properties(phase=2)
    assert changes["phase"] == 1
    assert wall1.phase == 2

    wall1.set_properties(phase=original_phase)


def test_assembly_set_properties_phase(wall1):
    """Checks that TeklaAssembly phase can be changed using set_properties."""
    assembly = wall1.get_top_level_assembly()
    original_phase = assembly.phase

    changes = assembly.set_properties(phase=3)
    assert changes["phase"] == 1
    assert assembly.phase == 3

    assembly.set_properties(phase=original_phase)
