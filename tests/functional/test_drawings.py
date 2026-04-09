"""
Functional tests for drawings_provider.

Tests drawing retrieval and property retrieval operations.
"""

import pytest

from tekla_mcp_server.providers.drawings_provider import get_drawings, get_drawing_properties


class TestGetDrawings:
    """Tests for get_drawings function."""

    def test_get_drawings_no_filters(self):
        """Call get_drawings without any arguments."""
        result = get_drawings()

        assert result["status"] == "success"
        assert result["matched_count"] >= 3

    def test_get_drawings_castunit_type(self):
        """Test filtering by CastUnit drawing type."""
        result = get_drawings(drawing_type="CastUnit")

        assert result["status"] == "success"
        assert result["matched_count"] > 0

    def test_get_drawings_unknown_type(self):
        """Test filtering by Unknown drawing type - should return 0."""
        result = get_drawings(drawing_type="Unknown")

        assert result["status"] == "success"
        assert result["matched_count"] == 0

    def test_get_drawings_with_mark_filter(self):
        """Test filtering by mark using StringFilterOption."""
        result = get_drawings(mark_filter={"conditions": {"match_type": "Starts With", "value": "["}, "logic": "AND"})

        assert result["status"] == "success"


class TestGetDrawingProperties:
    """Tests for get_drawing_properties function."""

    def test_get_drawing_properties_no_args(self):
        """Call get_drawing_properties without arguments (no selection)."""
        result = get_drawing_properties()

        assert result["selected_count"] == 0
        assert result["drawings"] == []

    def test_get_drawing_properties_with_mark(self):
        """Get a GA drawing and check its properties."""
        drawings_result = get_drawings(drawing_type="GA")
        marks = drawings_result.get("marks", [])

        if not marks:
            pytest.skip("No GA drawings available in model")

        result = get_drawing_properties(marks=[marks[0]])

        assert result["selected_count"] == 1
        assert len(result["drawings"]) == 1
        assert result["drawings"][0]["drawing_type"] == "GA"
