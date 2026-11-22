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


def _part(cls: type, object_id: int, guid: str) -> MagicMock:
    """Build a mocked wrapper of class `cls`."""
    obj = MagicMock(spec=cls)
    obj.id, obj.guid = object_id, guid
    return obj


class TestCutDeletesOnlyOwnCutters:
    def _cut(self, cutters_by_guid: dict, target: MagicMock) -> dict:
        """Run `cut_elements_with_cutters` with `delete_cutting_parts` on one selected target."""
        model = MagicMock()
        model.get_selected_objects.return_value.GetSize.return_value = 1
        model.resolve_guids.return_value = (list(cutters_by_guid.values()), list(cutters_by_guid), [])
        model.commit_changes.return_value = True
        with (
            patch.object(operations_module, "TeklaModel", return_value=model),
            patch.object(operations_module, "wrap_model_object", side_effect=lambda raw: raw),
            patch.object(operations_module, "wrap_model_objects", return_value=[target]),
            patch.object(operations_module, "_solid_box"),
            patch.object(operations_module, "_overlapping_cutters", side_effect=lambda box, cutters, boxes: cutters),
        ):
            return operations_module.cut_elements_with_cutters(cutter_guids=list(cutters_by_guid), delete_cutting_parts=True).structured_content

    def test_cutter_from_a_cut_part_guid_is_kept(self):
        """The operative part of an existing cut is that cut, so deleting it would remove the cut from its own part."""
        operative = _part(operations_module.TeklaPart, 5, "cut-guid")
        cut_part = _part(operations_module.TeklaBooleanPart, 5, "cut-guid")
        cut_part.operative_part = operative
        plain = _part(operations_module.TeklaPart, 6, "plain-guid")
        target = _part(operations_module.TeklaPart, 1, "target")
        target.add_cut.return_value = True

        result = self._cut({"cut-guid": cut_part, "plain-guid": plain}, target)

        operative.delete.assert_not_called()
        plain.delete.assert_called_once()
        assert (result["performed_cuts_count"], result["deleted_cutters_count"], result["kept_cut_part_guids"]) == (2, 1, ["cut-guid"])


class TestBatchAttachConflictingTargets:
    def test_object_with_several_targets_is_not_attached(self):
        """An object has one parent, so pairs giving it two targets are skipped, the others still attach."""
        attach = MagicMock(return_value=None)
        pairs = [
            operations_module.AttachmentPair(object_guid="r", target_guid="t1"),
            operations_module.AttachmentPair(object_guid="R", target_guid="t2"),
            operations_module.AttachmentPair(object_guid="s", target_guid="t1"),
        ]
        with (
            patch.object(operations_module, "TeklaModel") as model_class,
            patch.object(operations_module, "normalize_guid", side_effect=str.lower),
            patch.object(operations_module, "_resolve_pair", side_effect=lambda model, o, t: (o, t, None)),
        ):
            model_class.return_value.commit_changes.return_value = True
            result = operations_module._batch_attach("rebars", pairs, attach, lambda obj, target: True).structured_content

        assert [c.args for c in attach.call_args_list] == [("s", "t1")]
        assert result["attached"] == ["s"]
        assert result["skipped"] == [{"object_guid": "r", "reason": "conflicting_targets", "target_guids": ["t1", "t2"]}]
        assert result["status"] == "partial"

    def test_repeated_identical_pair_is_not_a_conflict(self):
        attach = MagicMock(return_value=None)
        pairs = [operations_module.AttachmentPair(object_guid="r", target_guid="t1")] * 2
        with (
            patch.object(operations_module, "TeklaModel") as model_class,
            patch.object(operations_module, "normalize_guid", side_effect=str.lower),
            patch.object(operations_module, "_resolve_pair", side_effect=lambda model, o, t: (o, t, None)),
        ):
            model_class.return_value.commit_changes.return_value = True
            result = operations_module._batch_attach("rebars", pairs, attach, lambda obj, target: True).structured_content

        assert (result["attached"], result["skipped"]) == (["r"], [])
