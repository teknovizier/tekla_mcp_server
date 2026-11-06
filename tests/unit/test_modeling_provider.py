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
