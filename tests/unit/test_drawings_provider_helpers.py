"""
Unit tests for pure helpers in `providers.drawings_provider`.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available, since `drawings_provider` transitively imports `tekla/loader.py`.
"""

import os
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.providers.drawings_provider import (
    _classify_unmarked_category,
    _describe_wrapped_object,
    _dimension_lost_all_anchors,
    _run_export_macro,
    _run_print_macro,
    _wait_for_new_files,
)
from tekla_mcp_server.tekla.loader import BoltArray, BoltXYList
from tekla_mcp_server.tekla.wrappers.model_object import BoltedParts, PartReference, TeklaBoltGroup


class _StubModelObject:
    """Stand-in for DrawingModelObject - .NET types don't satisfy
    isinstance against a MagicMock spec, so we patch the module name."""


class _RelatedEnum:
    """Minimal .NET-style enumerator over a fixed list."""

    def __init__(self, items):
        self._items = list(items)
        self._i = -1

    def MoveNext(self) -> bool:
        self._i += 1
        return self._i < len(self._items)

    @property
    def Current(self):
        return self._items[self._i]


def _dim_with_related(items):
    """Stub dimension with GetRelatedObjects yielding `items`."""
    dim = MagicMock()
    dim.GetRelatedObjects.return_value = _RelatedEnum(items)
    return dim


def test_dimension_lost_all_anchors_true_when_no_related_objects():
    # All anchors deleted -> empty list -> dangling
    assert _dimension_lost_all_anchors(_dim_with_related([])) is True


def test_dimension_lost_all_anchors_false_when_a_model_object_remains():
    # A live model object representation -> still anchored
    with patch("tekla_mcp_server.providers.drawings_provider.DrawingModelObject", _StubModelObject):
        assert _dimension_lost_all_anchors(_dim_with_related([_StubModelObject()])) is False


def test_dimension_lost_all_anchors_true_when_only_non_model_objects():
    # Non-model objects (e.g. annotations) do not count as anchors
    assert _dimension_lost_all_anchors(_dim_with_related([object(), object()])) is True


def test_dimension_lost_all_anchors_returns_none_on_api_error():
    # An API error yields None (indeterminate): callers fail open to the
    # geometric test but count it as a degraded check. This is the
    # anti-false-positive choice, at the cost of a dangle whose enumeration throws
    dim = MagicMock()
    dim.GetRelatedObjects.side_effect = RuntimeError("COM boom")
    assert _dimension_lost_all_anchors(dim) is None


def test_returns_immediately_when_already_satisfied(tmp_path):
    """No waiting needed if enough matching files already exist."""
    (tmp_path / "a.pdf").write_text("a")
    (tmp_path / "b.pdf").write_text("b")
    before: set = set()
    produced = _wait_for_new_files(tmp_path, "*.pdf", before, expected_count=2, timeout=5)
    assert sorted(p.name for p in produced) == ["a.pdf", "b.pdf"]


def test_excludes_before_snapshot(tmp_path):
    """Files present in `before` are not counted as new."""
    existing = tmp_path / "existing.pdf"
    existing.write_text("x")
    before = {existing}
    (tmp_path / "new.pdf").write_text("y")
    produced = _wait_for_new_files(tmp_path, "*.pdf", before, expected_count=1, timeout=5)
    assert [p.name for p in produced] == ["new.pdf"]


def test_filters_by_pattern(tmp_path):
    """Only files matching the glob pattern are counted."""
    (tmp_path / "a.pdf").write_text("a")
    (tmp_path / "a.txt").write_text("a")
    produced = _wait_for_new_files(tmp_path, "*.pdf", set(), expected_count=1, timeout=5)
    assert [p.name for p in produced] == ["a.pdf"]


def test_tolerates_missing_directory(tmp_path):
    """A directory that doesn't exist yet is treated as zero matches, not an error."""
    missing = tmp_path / "does_not_exist"
    produced = _wait_for_new_files(missing, "*.pdf", set(), expected_count=1, timeout=0.1)
    assert produced == []


def test_times_out_with_fewer_than_expected(tmp_path):
    """Returns whatever was found, rather than raising, if the deadline has already passed."""
    (tmp_path / "a.pdf").write_text("a")
    # timeout=0 exercises the "deadline already elapsed" path without paying for the
    # function's hardcoded 2s poll interval.
    produced = _wait_for_new_files(tmp_path, "*.pdf", set(), expected_count=2, timeout=0)
    assert [p.name for p in produced] == ["a.pdf"]


def test_wait_message_logged_only_when_waiting(tmp_path, caplog):
    """`wait_message` is logged when the loop has to wait, not when already satisfied."""
    (tmp_path / "a.pdf").write_text("a")
    with caplog.at_level("INFO"):
        _wait_for_new_files(tmp_path, "*.pdf", set(), expected_count=1, timeout=5, wait_message="should not appear")
    assert "should not appear" not in caplog.text

    with caplog.at_level("INFO"):
        _wait_for_new_files(tmp_path, "*.pdf", set(), expected_count=5, timeout=0, wait_message="waiting now")
    assert "waiting now" in caplog.text


# (runner, main macro, close macro, tmp file name)
_DOCUMENT_MANAGER_RUNNERS = [
    (_run_export_macro, "TeklaMCPExportDrawings.cs", "TeklaMCPCloseExportDialog.cs", "export.tmp"),
    (_run_print_macro, "TeklaMCPPrintDrawings.cs", "TeklaMCPClosePrintDialog.cs", "print.tmp"),
]


def _patch_document_manager(tmp_path, calls: list[str], start_status: str = "success", macro_result: str | None = "OK"):
    """
    Patch the macro plumbing of `drawings_provider`, recording every call in order.

    The main macro writes `macro_result` to its result file like the real macro does,
    or writes nothing when `macro_result` is None.
    """

    def _run_macro(macro_name):
        calls.append(f"run:{macro_name}")
        if "Close" in macro_name:
            return MagicMock(structured_content={"status": "success"})
        if start_status == "success" and macro_result is not None:
            result_name = "export.result" if "Export" in macro_name else "print.result"
            (tmp_path / result_name).write_text(macro_result, encoding="utf-8")
        return MagicMock(structured_content={"status": start_status})

    module = "tekla_mcp_server.providers.drawings_provider"
    return (
        patch(f"{module}.ensure_macro_installed"),
        patch(f"{module}.get_mcp_data_dir", return_value=tmp_path),
        patch(f"{module}.run_macro", side_effect=_run_macro),
        patch(f"{module}.wait_for_macro", side_effect=lambda name: calls.append(f"wait:{name}")),
    )


@pytest.mark.parametrize("runner,macro,close_macro,tmp_name", _DOCUMENT_MANAGER_RUNNERS)
def test_document_manager_macro_waits_before_poll_and_closes_after(tmp_path, runner, macro, close_macro, tmp_name):
    """The macro is awaited before polling, and the tmp file lives until it has finished."""
    calls: list[str] = []

    def _poll():
        # The macro must have finished, and its input file must still be there for it
        assert (tmp_path / tmp_name).exists()
        calls.append("poll")
        return "result"

    p1, p2, p3, p4 = _patch_document_manager(tmp_path, calls)
    with p1, p2, p3, p4:
        assert runner("C:\\Model", "SETTING", ["A1"], _poll) == "result"

    assert calls == [f"run:{macro}", f"wait:{macro}", "poll", f"run:{close_macro}", f"wait:{close_macro}"]
    assert not (tmp_path / tmp_name).exists()


@pytest.mark.parametrize("runner,macro,close_macro,tmp_name", _DOCUMENT_MANAGER_RUNNERS)
def test_document_manager_dialog_closed_when_poll_fails(tmp_path, runner, macro, close_macro, tmp_name):
    """A failing poll still closes the dialog and removes the tmp file."""
    calls: list[str] = []

    def _poll():
        raise RuntimeError("no file appeared")

    p1, p2, p3, p4 = _patch_document_manager(tmp_path, calls)
    with p1, p2, p3, p4, pytest.raises(RuntimeError, match="no file appeared"):
        runner("C:\\Model", "SETTING", ["A1"], _poll)

    assert calls[-2:] == [f"run:{close_macro}", f"wait:{close_macro}"]
    assert not (tmp_path / tmp_name).exists()


@pytest.mark.parametrize("runner,macro,close_macro,tmp_name", _DOCUMENT_MANAGER_RUNNERS)
def test_document_manager_no_close_when_macro_did_not_start(tmp_path, runner, macro, close_macro, tmp_name):
    """A macro that failed to start opened no dialog, so nothing is waited on or closed."""
    calls: list[str] = []
    p1, p2, p3, p4 = _patch_document_manager(tmp_path, calls, start_status="error")
    with p1, p2, p3, p4, pytest.raises(RuntimeError):
        runner("C:\\Model", "SETTING", ["A1"], lambda: None)

    assert calls == [f"run:{macro}"]
    assert not (tmp_path / tmp_name).exists()


@pytest.mark.parametrize("runner,macro,close_macro,tmp_name", _DOCUMENT_MANAGER_RUNNERS)
def test_document_manager_macro_error_raises_without_polling(tmp_path, runner, macro, close_macro, tmp_name):
    """An 'ERROR:' result (e.g. a mark missing from Document Manager) raises, skips the poll and still closes the dialog."""
    calls: list[str] = []
    poll = MagicMock()
    p1, p2, p3, p4 = _patch_document_manager(tmp_path, calls, macro_result="ERROR: drawings not found in Document Manager: [10]")
    with p1, p2, p3, p4, pytest.raises(RuntimeError, match=r"drawings not found in Document Manager: \[10\]"):
        runner("C:\\Model", "SETTING", ["[10]"], poll)

    poll.assert_not_called()
    assert calls[-2:] == [f"run:{close_macro}", f"wait:{close_macro}"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("runner,macro,close_macro,tmp_name", _DOCUMENT_MANAGER_RUNNERS)
def test_document_manager_missing_result_raises(tmp_path, runner, macro, close_macro, tmp_name):
    """A macro that wrote no result file, e.g. an outdated installed copy, is reported as a failure."""
    calls: list[str] = []
    p1, p2, p3, p4 = _patch_document_manager(tmp_path, calls, macro_result=None)
    with p1, p2, p3, p4, pytest.raises(RuntimeError, match="without writing"):
        runner("C:\\Model", "SETTING", ["A1"], MagicMock())


class _WrappedStub:
    """Minimal stand-in for a wrapped model object - exposes only set attributes."""

    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def test_describe_wrapped_omits_none_and_missing_fields():
    """None-valued and absent attributes are omitted, present ones kept (omit-when-None)."""
    wrapped = _WrappedStub(name="B-1", position=None)
    out = _describe_wrapped_object(wrapped, ("name", "position", "profile"))
    assert out == {"name": "B-1"}


def test_describe_wrapped_respects_field_tuple():
    """Only attributes named in `fields` are read, even when others exist."""
    wrapped = _WrappedStub(name="B-1", position="2", profile="HEA200")
    out = _describe_wrapped_object(wrapped, ("name", "position"))
    assert out == {"name": "B-1", "position": "2"}


def test_describe_wrapped_appends_bolt_fields():
    """A TeklaBoltArray gets standard/size/count/connected_parts appended."""
    bolt = MagicMock(spec=TeklaBoltGroup)
    bolt.bolt_standard = "M16"
    bolt.bolt_size = 16.0
    bolt.bolt_count = 6
    bolt.connected_parts = BoltedParts(
        part_to_be_bolted=PartReference(guid="g1", name="BEAM", position="1"),
        part_to_bolt_to=PartReference(guid="g2", name="PLATE", position="2"),
    )
    # Empty field tuple isolates the bolt branch from the attribute loop
    out = _describe_wrapped_object(bolt, ())
    assert out == {
        "bolt_standard": "M16",
        "bolt_size": 16.0,
        "bolt_count": 6,
        "connected_parts": asdict(bolt.connected_parts),
    }


def test_classify_unmarked_category_covers_all_bolt_groups():
    """Every bolt arrangement is classified as 'bolts', not just rectangular BoltArray."""
    # Real instances: isinstance against pythonnet .NET types cannot be mocked.
    # BoltXYList is a BoltGroup but not a BoltArray - the old BoltArray-only check missed it.
    assert _classify_unmarked_category(BoltXYList()) == "bolts"
    assert _classify_unmarked_category(BoltArray()) == "bolts"
