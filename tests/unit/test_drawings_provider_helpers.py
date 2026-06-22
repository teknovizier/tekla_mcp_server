"""
Unit tests for pure helpers in `providers.drawings_provider`.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available, since `drawings_provider` transitively imports `tekla/loader.py`.
"""

import os

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.providers.drawings_provider import _wait_for_new_files


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
