"""
Unit tests for the search planning of `find_nearby_elements` in operations_provider.

The module imports the Tekla DLLs, so the tests are skipped in CI.
"""

import importlib
import math
import os

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from unittest.mock import MagicMock, patch

import numpy as np

from tekla_mcp_server.geometry import OrientedBox, aabb
from tekla_mcp_server.providers.operations_provider import _NearbyUnit, _search_around

# `providers` exports a provider object named like the module, so the module is loaded by name
operations_module = importlib.import_module("tekla_mcp_server.providers.operations_provider")


def _beam(length: float = 10000.0) -> OrientedBox:
    """An 80 x 80 beam rotated 45 degrees in plan."""
    a = math.radians(45)
    return OrientedBox.from_local_extent((0, 0, 0), (math.cos(a), math.sin(a), 0), (-math.sin(a), math.cos(a), 0), (0, -40, -40), (length, 40, 40))


def _plate(x: float) -> OrientedBox:
    """A small axis-aligned plate."""
    return OrientedBox.from_local_extent((x, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 0), (200, 200, 10))


def _searches(boxes: list[OrientedBox], radius: float = 100.0) -> list[tuple[np.ndarray, np.ndarray]]:
    """Run `_search_around` on a unit made of the boxes and return the extents it searched."""
    unit = _NearbyUnit(element=MagicMock(guid="source"), parts=[(MagicMock(guid=f"p{i}"), box) for i, box in enumerate(boxes)], main_box=boxes[0])
    with patch.object(operations_module, "get_parts_in_extent", return_value=[]) as search:
        _search_around(unit, radius, own=set(), loaded=set())
    return [(call.args[0], call.args[1]) for call in search.call_args_list]


def _volume(extent: tuple[np.ndarray, np.ndarray]) -> float:
    return float(np.prod(extent[1] - extent[0]))


def test_long_rotated_beam_keeps_tight_searches_at_default_radius():
    """A 10 m beam at 45 degrees is searched in pieces, not over the whole 7 x 7 m bay."""
    beam = _beam()
    searches = _searches([beam])
    whole = _volume(aabb([beam], 100.0))
    assert len(searches) > 1
    assert sum(_volume(extent) for extent in searches) < whole / 5


def test_beam_with_end_plates_keeps_tight_searches():
    """End plates next to the beam do not push the source into one big search."""
    searches = _searches([_beam(), _plate(0.0), _plate(6900.0)])
    assert len(searches) > 2
    assert sum(_volume(extent) for extent in searches) < _volume(aabb([_beam()], 100.0)) / 5


def test_unit_with_many_parts_falls_back_to_one_search():
    """A unit needing more searches than the cap gets one search around its whole extent."""
    plates = [_plate(300.0 * i) for i in range(40)]
    searches = _searches(plates)
    assert len(searches) == 1
    lo, hi = searches[0]
    expected_lo, expected_hi = aabb(plates, 100.0)
    assert lo == pytest.approx(expected_lo) and hi == pytest.approx(expected_hi)
