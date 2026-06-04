"""
Functional tests for drawings_provider.

Tests drawing retrieval, property retrieval, mark collision detection,
open/close drawing, view listing, move, scale, and delete operations.
"""

import pytest

from tekla_mcp_server.models import ViewScale
from tekla_mcp_server.providers.drawings_provider import (
    close_drawing,
    delete_view_clouds,
    delete_views,
    detect_collisions_between_marks,
    get_drawing_properties,
    get_drawings,
    get_drawing_views,
    move_view,
    open_drawing,
    print_drawings,
    set_view_scales,
)
from tekla_mcp_server.tekla.wrappers.drawing_handler import TeklaDrawingHandler


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    """Close any open drawing before and after the module runs."""
    handler = TeklaDrawingHandler()
    if handler.get_active_drawing() is not None:
        handler.close_active_drawing()
    yield
    if handler.get_active_drawing() is not None:
        handler.close_active_drawing()


@pytest.fixture(scope="module")
def ga_mark():
    """Return the mark of a GA drawing in the model."""
    result = get_drawings(drawing_type="G")
    marks = result.structured_content.get("marks", [])
    if not marks:
        pytest.skip("No GA drawings available in model")
    return marks[0]


@pytest.fixture(scope="module")
def cu_mark():
    """Return the mark of a cast unit drawing in the model."""
    result = get_drawings(drawing_type="C")
    marks = result.structured_content.get("marks", [])
    if not marks:
        pytest.skip("No cast unit drawings available in model")
    return marks[0]


class TestGetDrawings:
    """Tests for get_drawings function."""

    def test_get_drawings_no_filters(self):
        """Call get_drawings without any arguments."""
        result = get_drawings()

        assert result.structured_content["status"] == "success"
        assert result.structured_content["matched_count"] >= 3

    def test_get_drawings_ga_type(self):
        """Test filtering by GA drawing type."""
        result = get_drawings(drawing_type="G")

        assert result.structured_content["status"] == "success"
        assert result.structured_content["matched_count"] > 0

    def test_get_drawings_invalid_type(self):
        """Invalid drawing type is rejected."""
        result = get_drawings(drawing_type="U")

        assert result.structured_content["status"] == "error"

    def test_get_drawings_with_mark_filter(self):
        """Test filtering by mark using StringFilterOption."""
        result = get_drawings(mark_filter={"conditions": {"match_type": "Starts With", "value": "["}, "logic": "AND"})

        assert result.structured_content["status"] == "success"


class TestGetDrawingProperties:
    """Tests for get_drawing_properties function."""

    def test_get_drawing_properties_no_args(self):
        """Call get_drawing_properties without arguments (no selection)."""
        result = get_drawing_properties()

        assert result.structured_content["status"] == "error"

    def test_get_drawing_properties_with_mark(self):
        """Get a GA drawing and check its properties."""
        drawings_result = get_drawings(drawing_type="G")
        marks = drawings_result.structured_content.get("marks", [])

        if not marks:
            pytest.skip("No GA drawings available in model")

        result = get_drawing_properties(marks=[marks[0]])

        assert result.structured_content["selected_count"] == 1
        assert len(result.structured_content["drawings"]) == 1
        drawing = result.structured_content["drawings"][0]
        assert drawing["drawing_type"] == "G"
        # Revision_mark must always be present
        assert "revision_mark" in drawing
        assert drawing["revision_mark"] is None or isinstance(drawing["revision_mark"], str)


class TestDetectCollisionsBetweenMarks:
    """Tests for detect_collisions_between_marks function."""

    def test_detect_collisions_no_open_drawing(self):
        """Fails when no drawing is open."""
        result = detect_collisions_between_marks()

        assert result.structured_content["status"] == "error"
        assert "drawing" in result.structured_content["message"].lower()


class TestPrintDrawings:
    """Tests for print_drawings function."""

    def test_print_drawings_no_drawings_selected(self):
        """Call without selecting any drawings."""
        result = print_drawings()

        assert result.structured_content["status"] == "error"
        assert "no drawings" in result.structured_content["message"].lower()


class TestOpenCloseDrawing:
    """Tests for opening and closing drawings."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_open_drawing(self, ga_mark):
        """Open a GA drawing."""
        result = open_drawing(mark=ga_mark)
        assert result.structured_content["status"] == "success"
        assert result.structured_content["drawing_mark"] == ga_mark
        assert result.structured_content["drawing_type"] == "G"
        close_drawing(save=False)

    def test_open_drawing_already_open(self, ga_mark):
        """Opening when a drawing is already open raises an error."""
        open_drawing(mark=ga_mark)
        result = open_drawing(mark=ga_mark)
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_open_drawing_invalid_mark(self):
        """Opening with an invalid mark raises an error."""
        result = open_drawing(mark="MCP_NONEXISTENT_DRAWING")
        assert result.structured_content["status"] == "error"

    def test_close_drawing_no_open_drawing(self):
        """Closing when no drawing is open raises an error."""
        result = close_drawing()
        assert result.structured_content["status"] == "error"

    def test_close_drawing_with_save(self, ga_mark):
        """Close a drawing with save=True."""
        open_drawing(mark=ga_mark)
        result = close_drawing(save=True)
        assert result.structured_content["status"] == "success"
        assert result.structured_content["drawing_is_saved"] is True

    def test_close_drawing_without_save(self, ga_mark):
        """Close a drawing with save=False."""
        open_drawing(mark=ga_mark)
        result = close_drawing(save=False)
        assert result.structured_content["status"] == "success"
        assert result.structured_content["drawing_is_saved"] is False


class TestGetDrawingViews:
    """Tests for get_drawing_views function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_get_views_no_open_drawing(self):
        """Getting views when no drawing is open raises an error."""
        result = get_drawing_views()
        assert result.structured_content["status"] == "error"

    def test_get_views_success(self, cu_mark):
        """Get views from an open cast unit drawing."""
        open_drawing(mark=cu_mark)
        result = get_drawing_views()
        assert result.structured_content["status"] == "success"
        assert result.structured_content["view_count"] >= 1
        assert "sheet_width" in result.structured_content
        assert "sheet_height" in result.structured_content
        assert len(result.structured_content["views"]) >= 1
        close_drawing(save=False)

    def test_get_views_keys_are_unique(self, cu_mark):
        """Each view has a unique view_key."""
        open_drawing(mark=cu_mark)
        result = get_drawing_views()
        keys = [v["view_key"] for v in result.structured_content["views"]]
        assert len(keys) == len(set(keys))
        close_drawing(save=False)

    def test_get_views_all_have_required_fields(self, cu_mark):
        """Every view dict has all expected fields."""
        open_drawing(mark=cu_mark)
        result = get_drawing_views()
        required = {"name", "view_key", "view_type", "scale", "is_sheet", "origin_x", "origin_y", "width", "height"}
        for view in result.structured_content["views"]:
            assert required.issubset(view.keys())
        close_drawing(save=False)


class TestMoveView:
    """Tests for move_view function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_move_no_open_drawing(self):
        """Moving a view when no drawing is open raises an error."""
        result = move_view(view_key="dummy", dx=10, dy=10)
        assert result.structured_content["status"] == "error"

    def test_move_invalid_view_key(self, cu_mark):
        """Moving a non-existent view raises an error."""
        open_drawing(mark=cu_mark)
        result = move_view(view_key="MCP_NONEXISTENT_VIEW", dx=10, dy=10)
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def _first_non_sheet_view_key(self):
        """Return view_key of the first non-sheet view, or None."""
        views = get_drawing_views().structured_content["views"]
        for v in views:
            if not v["is_sheet"]:
                return v["view_key"]
        return None

    def test_move_non_sheet_view(self, cu_mark):
        """Move a non-sheet view by an offset."""
        open_drawing(mark=cu_mark)
        key = self._first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view available to move")
        result = move_view(view_key=key, dx=10, dy=5)
        assert result.structured_content["status"] == "success"
        assert result.structured_content["view_key"] == key
        assert result.structured_content["new_origin_x"] is not None
        assert result.structured_content["new_origin_y"] is not None
        close_drawing(save=False)


class TestSetViewScales:
    """Tests for set_view_scales function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_set_scale_no_open_drawing(self):
        """Setting scale when no drawing is open raises an error."""
        result = set_view_scales(view_scales=[ViewScale(view_key="dummy", scale=20.0)])
        assert result.structured_content["status"] == "error"

    def test_set_scale_invalid_view_key(self, cu_mark):
        """Setting scale on a non-existent view."""
        open_drawing(mark=cu_mark)
        result = set_view_scales(view_scales=[ViewScale(view_key="MCP_NONEXISTENT_VIEW", scale=20.0)])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_set_scale_empty_list(self):
        """An empty list raises an error."""
        result = set_view_scales(view_scales=[])
        assert result.structured_content["status"] == "error"

    def _first_view_key(self):
        """Return view_key of the first view."""
        views = get_drawing_views().structured_content["views"]
        return views[0]["view_key"] if views else None

    def test_set_scale_on_non_sheet_view(self, cu_mark):
        """Set scale on a non-sheet view."""
        open_drawing(mark=cu_mark)
        key = self._first_view_key()
        if key is None:
            pytest.skip("No views available")
        result = set_view_scales(view_scales=[ViewScale(view_key=key, scale=20.0)])
        assert result.structured_content["status"] == "success"
        assert result.structured_content["succeeded"] == 1
        assert result.structured_content["results"][0]["new_scale"] == 20.0
        close_drawing(save=False)

    def test_set_scale_multiple_views(self, cu_mark):
        """Set scale on all views at once."""
        open_drawing(mark=cu_mark)
        views = get_drawing_views().structured_content["views"]
        if len(views) < 2:
            pytest.skip("Need at least 2 views for multi-scale test")
        scales = [ViewScale(view_key=v["view_key"], scale=30.0) for v in views]
        result = set_view_scales(view_scales=scales)
        assert result.structured_content["status"] == "success"
        assert result.structured_content["succeeded"] == len(views)
        close_drawing(save=False)


class TestDeleteViews:
    """Tests for delete_views function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_delete_no_open_drawing(self):
        """Deleting views when no drawing is open raises an error."""
        result = delete_views(view_keys=["dummy"])
        assert result.structured_content["status"] == "error"

    def test_delete_invalid_view_key(self, cu_mark):
        """Deleting a non-existent view."""
        open_drawing(mark=cu_mark)
        result = delete_views(view_keys=["MCP_NONEXISTENT_VIEW"])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def _non_sheet_view_keys(self, count=1):
        """Return view_keys of non-sheet views, up to count."""
        views = get_drawing_views().structured_content["views"]
        keys = [v["view_key"] for v in views if not v["is_sheet"]]
        return keys[:count]

    def test_delete_single_non_sheet_view(self, cu_mark):
        """Delete a single non-sheet view."""
        open_drawing(mark=cu_mark)
        keys = self._non_sheet_view_keys()
        if not keys:
            pytest.skip("No non-sheet view available to delete")
        result = delete_views(view_keys=[keys[0]])
        assert result.structured_content["status"] == "success"
        assert result.structured_content["succeeded"] == 1
        remaining = get_drawing_views().structured_content["views"]
        assert all(v["view_key"] != keys[0] for v in remaining)
        close_drawing(save=False)

    def test_delete_empty_list_rejected(self):
        """An empty view_keys list is rejected before touching Tekla."""
        result = delete_views(view_keys=[])
        assert result.structured_content["status"] == "error"

    def test_delete_sheet_view_fails(self, cu_mark):
        """Deleting the sheet view should fail."""
        open_drawing(mark=cu_mark)
        views = get_drawing_views().structured_content["views"]
        sheet_key = next((v["view_key"] for v in views if v["is_sheet"]), None)
        if sheet_key is None:
            pytest.skip("No sheet view found")
        result = delete_views(view_keys=[sheet_key])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)


class TestDeleteViewClouds:
    """Tests for delete_view_clouds function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_open_drawing_raises(self):
        """Raises when no drawing is open."""
        result = delete_view_clouds()
        assert result.structured_content["status"] == "error"

    def test_empty_view_keys_rejected(self, cu_mark):
        """Empty view_keys list is rejected."""
        open_drawing(mark=cu_mark)
        result = delete_view_clouds(view_keys=[])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_invalid_view_key_rejected(self, cu_mark):
        """A non-existent view_key is rejected."""
        open_drawing(mark=cu_mark)
        result = delete_view_clouds(view_keys=["MCP_NONEXISTENT_VIEW"])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_no_clouds_returns_success(self, cu_mark):
        """Drawing with no clouds returns success with zero counts."""
        open_drawing(mark=cu_mark)
        result = delete_view_clouds()
        sc = result.structured_content
        assert sc["status"] == "success"
        assert sc["total_found"] == 0
        assert sc["total_deleted"] == 0
        assert sc["total_failed"] == 0
        assert sc["views"] == []
        close_drawing(save=False)

    def test_response_has_required_fields(self, cu_mark):
        """Response always contains the expected keys."""
        open_drawing(mark=cu_mark)
        result = delete_view_clouds()
        sc = result.structured_content
        assert {"status", "total_found", "total_deleted", "total_failed", "views"}.issubset(sc.keys())
        close_drawing(save=False)

    def test_specific_view_keys_accepted(self, cu_mark):
        """Passing valid view_keys is accepted and processed."""
        open_drawing(mark=cu_mark)
        views = get_drawing_views().structured_content["views"]
        non_sheet_keys = [v["view_key"] for v in views if not v["is_sheet"]]
        if not non_sheet_keys:
            pytest.skip("No non-sheet views available")
        result = delete_view_clouds(view_keys=non_sheet_keys)
        assert result.structured_content["status"] in {"success", "partial"}
        close_drawing(save=False)

    def test_delete_clouds_after_collision_detection(self, cu_mark):
        """Clouds inserted by detect_collisions_between_marks are removed."""
        open_drawing(mark=cu_mark)
        detect_result = detect_collisions_between_marks()
        clouds_inserted = detect_result.structured_content.get("total_collision_pairs", 0)
        if clouds_inserted == 0:
            pytest.skip("No collision clouds were inserted - cannot verify deletion")

        result = delete_view_clouds()
        sc = result.structured_content
        assert sc["status"] == "success"
        assert sc["total_found"] == clouds_inserted
        assert sc["total_deleted"] == clouds_inserted
        assert sc["total_failed"] == 0
        close_drawing(save=False)
