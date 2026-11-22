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


def test_every_host_failing_is_an_error():
    callback = MagicMock(side_effect=ValueError("Unsupported material type"))

    result = _run([_obj("STEEL1"), _obj("STEEL2")], callback)

    assert result["status"] == "error"
    assert [e["guid"] for e in result["errors"]] == ["STEEL1", "STEEL2"]


class FakeCustomPart(MagicMock):
    """Stand-in for `CustomPart`, which the wrappers have no class for."""


def _component(name: str, guid: str, deleted: bool = True) -> MagicMock:
    comp = MagicMock(Name=name)
    comp.Identifier.GUID = guid
    comp.Delete.return_value = deleted
    return comp


def _host(host_id: int, components: list[MagicMock]) -> FakePart:
    host = FakePart()
    host.Identifier.ID = host_id
    host.GetComponents.side_effect = lambda: iter(components)
    return host


class TestRemoveComponentsCleanup:
    def _remove(self, hosts: list, handler: MagicMock) -> dict:
        with (
            patch.object(cp, "Part", FakePart),
            patch.object(cp, "TeklaModel") as model_class,
            patch.object(cp.HandlerRegistry, "get", return_value=handler),
        ):
            model_class.return_value.get_selected_objects.return_value = hosts
            model_class.return_value.commit_changes.return_value = True
            return cp.remove_components(component_names=["lifting anchor"]).structured_content

    def test_part_that_still_holds_an_anchor_keeps_its_recesses(self):
        """The recess cleanup works per part, so a part where one anchor failed to delete is not cleaned."""
        clean = _host(1, [_component("Lifting Anchor", "a")])
        mixed = _host(2, [_component("Lifting Anchor", "b"), _component("Lifting Anchor", "c", deleted=False)])
        handler = MagicMock()
        handler.post_remove.return_value = 2

        result = self._remove([clean, mixed], handler)

        handler.post_remove.assert_called_once_with([clean])
        assert (result["removed"], result["failed_count"], result["cleaned_count"]) == ({"Lifting Anchor": 2}, 1, 2)

    def test_no_cleanup_when_every_host_keeps_an_anchor(self):
        handler = MagicMock()
        self._remove([_host(1, [_component("Lifting Anchor", "a"), _component("Lifting Anchor", "b", deleted=False)])], handler)
        handler.post_remove.assert_not_called()


def test_get_components_lists_custom_parts():
    """A CustomPart can hold components but has no wrapper class, so it must not be dropped."""
    custom = FakeCustomPart()
    custom.Identifier.GUID.ToString.return_value = "CUSTOM"
    custom.GetComponents.return_value = MagicMock(MoveNext=MagicMock(side_effect=[True, False]), Current=MagicMock(Name="Unconfigured", Number=7))
    with patch.object(cp, "CustomPart", FakeCustomPart), patch.object(cp, "TeklaModel") as model_class:
        model_class.return_value.get_selected_objects.return_value = [custom]
        result = cp.get_components().structured_content

    assert result["total_elements"] == 1
    assert result["elements"][0]["guid"] == "CUSTOM"
    assert [c["name"] for c in result["elements"][0]["components"]] == ["Unconfigured"]
