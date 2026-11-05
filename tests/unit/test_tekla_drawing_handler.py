"""
Unit tests for TeklaDrawingHandler wrapper.

Importing the wrapper loads the Tekla DLLs, so these tests are skipped in CI
environments where Tekla is not available. The .NET DrawingHandler is mocked,
so no running Tekla model is needed.
"""

import importlib
import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.providers.drawings_provider import get_drawings_properties
from tekla_mcp_server.tekla.wrappers.drawing_handler import TeklaDrawingHandler

MODULE = "tekla_mcp_server.tekla.wrappers.drawing_handler"


def _drawing(mark: str) -> MagicMock:
    """
    Build a mocked wrapped drawing with the given mark.

    Args:
        mark: Drawing mark

    Returns:
        The mocked drawing
    """
    drawing = MagicMock()
    drawing.mark = mark
    return drawing


@pytest.fixture
def handler() -> Iterator[TeklaDrawingHandler]:
    """A handler backed by a connected mock DrawingHandler with drawings A1, A2 and G1."""
    net_handler = MagicMock()
    net_handler.GetConnectionStatus.return_value = True
    drawings = [_drawing("A1"), _drawing("A2"), _drawing("G1")]
    with patch(f"{MODULE}.DrawingHandler", return_value=net_handler), patch(f"{MODULE}.wrap_drawings", return_value=drawings):
        yield TeklaDrawingHandler()


class TestGetDrawingsByMarks:
    def test_all_marks_found(self, handler):
        result = handler.get_drawings_by_marks(["G1", "A1"])
        assert [d.mark for d in result] == ["A1", "G1"]

    def test_duplicate_marks_are_found_once(self, handler):
        result = handler.get_drawings_by_marks(["A1", "A1"])
        assert [d.mark for d in result] == ["A1"]

    def test_partly_missing_marks_raise_and_name_them(self, handler):
        with pytest.raises(ValueError, match=r"not found: \['TYPO', 'A9'\]"):
            handler.get_drawings_by_marks(["A1", "TYPO", "A9", "TYPO"])

    def test_all_marks_missing_raise_and_name_them(self, handler):
        with pytest.raises(ValueError, match=r"not found: \['X1'\]"):
            handler.get_drawings_by_marks(["X1"])

    def test_empty_marks_raise(self, handler):
        with pytest.raises(ValueError, match="No drawings found or selected"):
            handler.get_drawings_by_marks([])

    def test_none_uses_selection(self, handler):
        result = handler.get_drawings_by_marks(None)
        handler.handler.GetDrawingSelector.return_value.GetSelected.assert_called_once()
        assert len(result) == 3

    def test_empty_selection_raises(self, handler):
        with patch(f"{MODULE}.wrap_drawings", return_value=[]):
            with pytest.raises(ValueError, match="No drawings found or selected"):
                handler.get_drawings_by_marks(None)


class TestFindDrawingsByMarks:
    def test_returns_found_and_missing(self, handler):
        found, missing = handler.find_drawings_by_marks(["A2", "TYPO", "G1", "TYPO", "X9"])
        assert [d.mark for d in found] == ["A2", "G1"]
        assert missing == ["TYPO", "X9"]

    def test_nothing_missing(self, handler):
        found, missing = handler.find_drawings_by_marks(["A1"])
        assert [d.mark for d in found] == ["A1"]
        assert missing == []

    def test_nothing_found_does_not_raise(self, handler):
        found, missing = handler.find_drawings_by_marks(["X1"])
        assert found == []
        assert missing == ["X1"]


class TestGetDrawingsPropertiesMissingMarks:
    """The read-only tool returns what it found instead of failing on one wrong mark."""

    @pytest.fixture
    def provider_handler(self) -> Iterator[MagicMock]:
        provider = importlib.import_module("tekla_mcp_server.providers.drawings_provider")
        with patch.object(provider, "TeklaDrawingHandler") as handler_class:
            yield handler_class.return_value

    @staticmethod
    def _with_dict(mark: str) -> MagicMock:
        drawing = _drawing(mark)
        drawing.to_dict.return_value = {"mark": mark}
        return drawing

    def test_partial_when_some_marks_missing(self, provider_handler):
        provider_handler.find_drawings_by_marks.return_value = ([self._with_dict("A1")], ["TYPO"])

        result = get_drawings_properties(marks=["A1", "TYPO"]).structured_content

        assert result["status"] == "partial"
        assert result["drawings"] == [{"mark": "A1"}]
        assert result["missing_marks"] == ["TYPO"]
        provider_handler.get_drawings_by_marks.assert_not_called()

    def test_success_when_all_found(self, provider_handler):
        provider_handler.find_drawings_by_marks.return_value = ([self._with_dict("A1")], [])

        result = get_drawings_properties(marks=["A1"]).structured_content

        assert result["status"] == "success"
        assert result["missing_marks"] == []

    def test_error_when_no_mark_found(self, provider_handler):
        provider_handler.find_drawings_by_marks.return_value = ([], ["X1", "X2"])

        result = get_drawings_properties(marks=["X1", "X2"]).structured_content

        assert result["status"] == "error"
        assert "['X1', 'X2']" in result["message"]

    def test_selection_used_without_marks(self, provider_handler):
        provider_handler.get_drawings_by_marks.return_value = [self._with_dict("G1")]

        result = get_drawings_properties().structured_content

        provider_handler.get_drawings_by_marks.assert_called_once_with(None)
        provider_handler.find_drawings_by_marks.assert_not_called()
        assert result["status"] == "success"
        assert result["missing_marks"] == []
