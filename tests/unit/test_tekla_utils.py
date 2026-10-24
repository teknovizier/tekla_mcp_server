"""
Unit tests for Tekla utility functions.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.
"""

import os
import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from typing import Any
from unittest.mock import MagicMock

from tekla_mcp_server.tekla.loader import Beam, Position, Point
from tekla_mcp_server.tekla.utils import expand_to_parts, get_wall_pairs
from tekla_mcp_server.tekla.wrappers.model_object import TeklaAssembly, TeklaPart, TeklaReinforcement


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


def _mock_part(guid: str) -> MagicMock:
    """Helper for a mocked TeklaPart with a fixed GUID."""
    part = MagicMock(spec=TeklaPart)
    part.guid = guid
    return part


def test_expand_to_parts_replaces_assembly_with_its_parts():
    """An assembly is replaced by all its parts."""
    inner, insulation, outer = _mock_part("inner"), _mock_part("insulation"), _mock_part("outer")
    assembly = MagicMock(spec=TeklaAssembly)
    assembly.get_all_parts.return_value = [inner, insulation, outer]
    assert expand_to_parts([assembly]) == ([inner, insulation, outer], [])


@pytest.mark.parametrize("include_embeds", [True, False])
def test_expand_to_parts_passes_include_embeds(include_embeds):
    """The embed filter is passed to the assembly expansion."""
    assembly = MagicMock(spec=TeklaAssembly)
    assembly.get_all_parts.return_value = []
    expand_to_parts([assembly], include_embeds=include_embeds)
    assembly.get_all_parts.assert_called_once_with(include_embeds)


def test_expand_to_parts_reports_skipped_objects():
    """Reinforcement and other non-part objects are dropped and reported with their GUID."""
    part = _mock_part("part")
    rebar = MagicMock(spec=TeklaReinforcement)
    rebar.guid = "rebar"
    parts, skipped = expand_to_parts([rebar, part])
    assert parts == [part]
    assert [s["guid"] for s in skipped] == ["rebar"]


def test_expand_to_parts_deduplicates_by_guid():
    """A part selected directly and through its assembly is returned once, in first-seen order."""
    main, secondary = _mock_part("main"), _mock_part("secondary")
    assembly = MagicMock(spec=TeklaAssembly)
    assembly.get_all_parts.return_value = [main, secondary]
    assert expand_to_parts([secondary, assembly]) == ([secondary, main], [])


def test_expand_to_parts_empty():
    """No objects give no parts."""
    assert expand_to_parts([]) == ([], [])
