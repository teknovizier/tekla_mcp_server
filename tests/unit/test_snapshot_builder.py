"""
Unit tests for `SnapshotBuilder` position helpers.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available, since `snapshot_builder` imports `tekla/loader.py`.
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.tekla.snapshot_builder import SnapshotBuilder


def _obj_at(x: float, y: float, z: float) -> MagicMock:
    """Model object stand-in whose coordinate system origin is at (x, y, z)."""
    obj = MagicMock()
    obj.GetCoordinateSystem.return_value = SimpleNamespace(Origin=SimpleNamespace(X=x, Y=y, Z=z))
    return obj


def _empty_enum() -> MagicMock:
    """.NET-style enumerator with no items."""
    enum = MagicMock()
    enum.MoveNext.return_value = False
    return enum


def test_get_origin_reads_coordinate_system():
    assert SnapshotBuilder._get_origin(_obj_at(1, 2, 3)) == (1.0, 2.0, 3.0)


def test_get_origin_none_on_failure():
    obj = MagicMock()
    obj.GetCoordinateSystem.side_effect = RuntimeError("no coordinate system")
    assert SnapshotBuilder._get_origin(obj) is None


def test_build_relative_position_subtracts_parent_origin():
    assert SnapshotBuilder._build_relative_position(_obj_at(10, 20, 30), _obj_at(1, 2, 3), {}) == {"dx": 9.0, "dy": 18.0, "dz": 27.0}


def test_build_relative_position_none_without_parent_origin():
    parent = MagicMock()
    parent.GetCoordinateSystem.side_effect = RuntimeError("no coordinate system")
    assert SnapshotBuilder._build_relative_position(_obj_at(10, 20, 30), parent, {}) is None


def test_parent_origin_read_once_for_many_children():
    """The cache makes every child after the first reuse the parent's origin."""
    parent = _obj_at(1, 2, 3)
    cache: dict = {}
    for i in range(5):
        SnapshotBuilder._build_relative_position(_obj_at(i, i, i), parent, cache)
    assert parent.GetCoordinateSystem.call_count == 1


def test_parent_origin_not_read_without_children():
    """A part with no cut parts and no welds never reads its own origin."""
    model_object = _obj_at(1, 2, 3)
    model_object.GetBooleans.return_value = _empty_enum()
    model_object.GetWelds.return_value = _empty_enum()
    part = SimpleNamespace(model_object=model_object)
    cache: dict = {}

    assert SnapshotBuilder._build_cutparts(part, cache) == []
    assert SnapshotBuilder._build_welds(part, cache) == []
    model_object.GetCoordinateSystem.assert_not_called()
