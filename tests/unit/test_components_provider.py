"""
Unit tests for host selection in the component path of `components_provider`.

The provider loads the Tekla DLLs on import, so these tests are skipped in CI. No Tekla
objects are created: `Part` is replaced with a mock subclass, so no running Tekla is needed.
"""

import importlib
import os
from unittest.mock import MagicMock, patch

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

# `providers/__init__` exports the provider object under the module's name, so load the module itself
cp = importlib.import_module("tekla_mcp_server.providers.components_provider")


class FakePart(MagicMock):
    """Stand-in for `Part`: pythonnet checks `isinstance` against the CLR type, which a plain mock cannot pass."""


def _obj(guid: str, part: bool = True) -> MagicMock:
    obj = FakePart() if part else MagicMock()
    obj.Identifier.GUID.ToString.return_value = guid
    return obj


def _run(objects: list, callback: MagicMock) -> dict:
    selection = MagicMock()
    selection.__iter__.return_value = iter(objects)
    selection.GetSize.return_value = len(objects)
    with patch.object(cp, "Part", FakePart):
        return cp._process_detail_or_component(selection, callback, MagicMock(), MagicMock()).structured_content


def test_every_part_is_a_host_and_non_parts_are_skipped():
    beam, plate, assembly = _obj("BEAM"), _obj("PLATE"), _obj("ASM", part=False)
    callback = MagicMock(return_value=1)

    result = _run([beam, assembly, plate], callback)

    assert [c.args[2] for c in callback.call_args_list] == [beam, plate]
    assert result["status"] == "success"
    assert result["processed_count"] == 2
    assert result["skipped_objects"] == [{"guid": "ASM", "type": "MagicMock"}]


def test_only_non_parts_is_a_warning():
    callback = MagicMock()

    result = _run([_obj("ASM", part=False)], callback)

    callback.assert_not_called()
    assert result["status"] == "warning"


def test_handler_rejection_is_reported_per_host():
    callback = MagicMock(side_effect=[1, ValueError("Only concrete elements are supported.")])

    result = _run([_obj("WALL"), _obj("PLATE")], callback)

    assert result["status"] == "partial"
    assert result["errors"] == [{"guid": "PLATE", "error": "Only concrete elements are supported."}]
