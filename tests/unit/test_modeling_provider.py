"""
Unit tests for the move/copy loop in `modeling_provider`.

The provider imports the Tekla wrappers, which load the Tekla DLLs, so these tests are
skipped in CI environments where Tekla is not available. The model, the selection and
the Tekla operations are mocked, so no running Tekla model is needed.
"""

import importlib
import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

# `providers/__init__` exports the provider object under the module's name, so load the module itself
mp = importlib.import_module("tekla_mcp_server.providers.modeling_provider")


def _part(part_id: int) -> MagicMock:
    """Build a mocked wrapped part with the given Tekla id."""
    part = MagicMock()
    part.id = part_id
    part.guid = f"guid-{part_id}"
    return part


@pytest.fixture
def operation() -> Iterator[MagicMock]:
    """Patch the model and `Operation`, and return the mocked `Operation`."""
    with patch.object(mp, "TeklaModel") as model_class, patch.object(mp, "Operation") as op:
        model_class.return_value.commit_changes.return_value = True
        yield op


def _run(copy: bool, parts_per_object: list[list[MagicMock]]) -> dict:
    """Run the move/copy loop over selected objects that expand to the given parts."""
    selected = [MagicMock() for _ in parts_per_object]
    with patch.object(mp, "wrap_model_objects", return_value=selected), patch.object(mp, "_collect_parts", side_effect=parts_per_object):
        return mp._move_or_copy_elements(1000.0, 0.0, 0.0, copy=copy).structured_content


@pytest.mark.parametrize("copy", [False, True])
def test_part_selected_with_its_assembly_is_handled_once(operation, copy):
    """A part reached through the part itself and through its assembly is moved or copied once."""
    part = _part(1)
    secondary = _part(2)

    result = _run(copy, [[part], [part, secondary]])

    call = operation.CopyObject if copy else operation.MoveObject
    assert [c.args[0] for c in call.call_args_list] == [part.model_object, secondary.model_object]
    assert (result["total"], result["succeeded"]) == (2, 2)
    assert [r["guid"] for r in result["results"]] == ["guid-1", "guid-2"]


def test_distinct_parts_are_all_moved(operation):
    parts = [_part(1), _part(2), _part(3)]

    result = _run(False, [[parts[0]], [parts[1], parts[2]]])

    assert operation.MoveObject.call_count == 3
    assert result["succeeded"] == 3


def _raw(part_id: int) -> MagicMock:
    """Build a mocked raw Tekla object with the given id."""
    raw = MagicMock()
    raw.Identifier.ID = part_id
    return raw


def _enumerator(items: list) -> MagicMock:
    """Build a mocked Tekla enumerator over the given items."""
    enumerator = MagicMock()
    iterator = iter(items)

    def move_next() -> bool:
        enumerator.Current = next(iterator, None)
        return enumerator.Current is not None

    enumerator.MoveNext.side_effect = move_next
    return enumerator


def _typed(cls: type, object_id: int, bolts: list | None = None, **raw_attributes) -> MagicMock:
    """Build a mocked wrapper of class `cls` whose raw object has the given attributes and bolt groups."""
    obj = MagicMock(spec=cls)
    obj.id = object_id
    obj.guid = f"guid-{object_id}"
    obj.model_object = MagicMock(**raw_attributes)
    obj.model_object.GetBolts.side_effect = lambda: _enumerator(bolts or [])
    return obj


def _raw_bolt(object_id: int, *bolted_ids: int) -> MagicMock:
    """Build a mocked raw bolt group bolting the parts with the given ids."""
    to, be, *others = [_raw(i) for i in bolted_ids] + [None] * (2 - len(bolted_ids))
    return MagicMock(Identifier=MagicMock(ID=object_id), PartToBoltTo=to, PartToBeBolted=be, OtherPartsToBolt=others)


def _bolt(object_id: int, *bolted_ids: int) -> MagicMock:
    """Build a mocked wrapped bolt group bolting the parts with the given ids."""
    raw = _raw_bolt(object_id, *bolted_ids)
    obj = _typed(mp.TeklaBoltGroup, object_id)
    obj.model_object = raw
    return obj


class TestCarrierIds:
    def test_rebar_and_cut_follow_their_father(self):
        assert mp._carrier_ids(_typed(mp.TeklaReinforcement, 10, Father=_raw(1))) == {1}
        assert mp._carrier_ids(_typed(mp.TeklaBooleanPart, 11, Father=_raw(1))) == {1}

    def test_weld_follows_its_secondary_part(self):
        assert mp._carrier_ids(_typed(mp.TeklaWeld, 12, MainObject=_raw(1), SecondaryObject=_raw(2))) == {2}

    def test_bolt_on_one_part_follows_it(self):
        assert mp._carrier_ids(_bolt(13, 1, 1)) == {1}

    def test_bolt_joining_several_parts_has_no_carrier(self):
        assert mp._carrier_ids(_bolt(14, 1, 2)) == set()

    def test_part_has_no_carrier(self):
        assert mp._carrier_ids(_typed(mp.TeklaPart, 1)) == set()


@pytest.mark.parametrize("copy", [False, True])
def test_children_of_a_moved_part_go_along_once(operation, copy):
    """A rebar, cut, weld and single-part bolt selected with their carrier part are not moved again."""
    host = _typed(mp.TeklaPart, 1)
    children = [
        _typed(mp.TeklaReinforcement, 10, Father=_raw(1)),
        _typed(mp.TeklaBooleanPart, 11, Father=_raw(1)),
        _typed(mp.TeklaWeld, 12, MainObject=_raw(2), SecondaryObject=_raw(1)),
        _bolt(13, 1, 1),
    ]

    # Children come first, so the carrier must be known before the loop reaches them
    result = _run(copy, [[child] for child in children] + [[host]])

    call = operation.CopyObject if copy else operation.MoveObject
    assert [c.args[0] for c in call.call_args_list] == [host.model_object]
    assert (result["total"], result["succeeded"]) == (1, 1)
    assert "4 more went along with their parts" in result["message"]


def test_children_without_a_moved_carrier_are_moved(operation):
    """A rebar of an unselected part, a weld on the main part only and a bolt joining two parts are moved themselves."""
    host = _typed(mp.TeklaPart, 1)
    others = [
        _typed(mp.TeklaReinforcement, 10, Father=_raw(99)),
        _typed(mp.TeklaWeld, 12, MainObject=_raw(1), SecondaryObject=_raw(2)),
        _bolt(13, 1, 2),
    ]

    result = _run(False, [[host]] + [[o] for o in others])

    assert operation.MoveObject.call_count == 4
    assert result["succeeded"] == 4
    assert "went along" not in result["message"]


class TestJointBolts:
    def test_unselected_bolt_joining_moved_parts_is_moved(self, operation):
        """Moving parts one by one leaves a bolt group joining them in place, so it is moved itself."""
        joint = _raw_bolt(20, 1, 2)
        main = _typed(mp.TeklaPart, 1, bolts=[joint])
        secondary = _typed(mp.TeklaPart, 2, bolts=[joint])

        result = _run(False, [[main, secondary]])

        assert [c.args[0] for c in operation.MoveObject.call_args_list] == [main.model_object, secondary.model_object, joint]
        assert (result["total"], result["succeeded"]) == (2, 2)
        assert "1 more went along with their parts" in result["message"]

    def test_selected_joint_bolt_is_moved_once(self, operation):
        joint = _raw_bolt(20, 1, 2)
        selected = _bolt(20, 1, 2)
        selected.model_object = joint
        main = _typed(mp.TeklaPart, 1, bolts=[joint])
        secondary = _typed(mp.TeklaPart, 2, bolts=[joint])

        _run(False, [[main, secondary], [selected]])

        assert [c.args[0] for c in operation.MoveObject.call_args_list].count(joint) == 1

    def test_bolt_to_a_part_that_stays_is_left_alone(self, operation):
        joint = _raw_bolt(20, 1, 3)
        main = _typed(mp.TeklaPart, 1, bolts=[joint])

        _run(False, [[main]])

        assert joint not in [c.args[0] for c in operation.MoveObject.call_args_list]

    def test_copy_does_not_copy_joint_bolts_again(self, operation):
        """A copy of the parts brings the bolt group joining them along."""
        joint = _raw_bolt(20, 1, 2)
        parts = [_typed(mp.TeklaPart, 1, bolts=[joint]), _typed(mp.TeklaPart, 2, bolts=[joint])]

        _run(True, [parts])

        assert operation.CopyObject.call_count == 2


class TestFailedCommit:
    """A failed commit does not undo what already ran in the open model, so results must not claim it did."""

    def test_move_keeps_its_results_and_warns(self, operation):
        with patch.object(mp, "TeklaModel") as model_class, patch.object(mp, "_redraw_active_views", return_value=True):
            model_class.return_value.commit_changes.return_value = False
            result = _run(False, [[_part(1)], [_part(2)]])

        assert (result["success"], result["succeeded"], result["failed"]) == (False, 2, 0)
        assert [r["guid"] for r in result["results"]] == ["guid-1", "guid-2"]
        assert result["message"].startswith("Moved 2 of 2 elements, but commit_changes() failed")
        assert "redrawn to show them" in result["message"] and "reverted" not in result["message"]

    def test_placement_keeps_its_results_and_warns(self):
        results = [mp.PlacementResult(success=True, guid="g1"), mp.PlacementResult(success=False, message="bad profile")]
        with patch.object(mp, "_redraw_active_views", return_value=True):
            content = mp._to_tool_result(results, 2, 1, "beams", commit_success=False).structured_content

        assert (content["success"], content["succeeded"], content["failed"]) == (False, 1, 1)
        assert content["results"][0] == {"success": True, "guid": "g1"}
        assert content["message"].startswith("Placed 1 of 2 beams, but commit_changes() failed")

    def test_successful_commit_has_no_note(self):
        content = mp._to_tool_result([mp.PlacementResult(success=True, guid="g1")], 1, 1, "beams", commit_success=True).structured_content
        assert (content["success"], content["message"]) == (True, "Placed 1 of 1 beams")


def test_failed_delete_commit_redraws_and_keeps_the_count():
    """Deletions run in the model before the commit, so a failed commit still reports them and redraws the view."""
    objects = [MagicMock(), MagicMock()]
    for obj in objects:
        obj.Delete.return_value = True
    with patch.object(mp, "TeklaModel") as model_class, patch.object(mp, "_redraw_active_views", return_value=True) as redraw:
        model_class.return_value.get_selected_objects.return_value = objects
        model_class.return_value.commit_changes.return_value = False
        content = mp.delete_elements().structured_content

    redraw.assert_called_once()
    assert content["status"] == "error"
    assert content["message"].startswith("Deleted 2 of 2 objects, but commit_changes() failed")
    assert "redrawn to show them" in content["message"]


class TestCheckGridAxis:
    def test_unsorted_coordinates_and_matching_labels_pass(self):
        mp._check_grid_axis("X", [10000.0, 0.0, 5000.0], ["C", "A", "B"])

    def test_no_labels_pass(self):
        mp._check_grid_axis("Z", [0.0, 3000.0], [])

    @pytest.mark.parametrize(
        "coordinates,labels,message",
        [
            ([0.0], [], "At least two X coordinates"),
            ([0.0, float("inf")], [], "must be finite"),
            ([0.0, 5000.0, 0.0], [], r"\[0.0\] are given more than once"),
            ([0.0, 5000.0], ["A"], "1 X labels given for 2 X coordinates"),
            ([0.0, 5000.0], ["A 1", "B"], "contain whitespace"),
            ([0.0, 5000.0], ["", "B"], "are empty"),
        ],
    )
    def test_invalid_axis_is_rejected(self, coordinates, labels, message):
        with pytest.raises(ValueError, match=message):
            mp._check_grid_axis("X", coordinates, labels)
