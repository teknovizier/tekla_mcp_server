"""
Unit tests for pure helpers in `providers.drawings_provider`.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available, since `drawings_provider` transitively imports `tekla/loader.py`.
"""

import os
from dataclasses import asdict
from unittest.mock import MagicMock

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.providers.drawings_provider import _classify_unmarked_category, _describe_wrapped_object, _wait_for_new_files
from tekla_mcp_server.tekla.loader import BoltArray, BoltXYList
from tekla_mcp_server.tekla.wrappers.model_object import BoltedParts, PartReference, TeklaBoltGroup


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
