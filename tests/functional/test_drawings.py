"""
Functional tests for drawings_provider.

Tests drawing retrieval, property retrieval, mark collision detection,
open/close drawing, view listing, move, scale, and delete operations.
"""

import pytest

from tekla_mcp_server.models import ViewScale
from tekla_mcp_server.providers.drawings_provider import (
    align_section_views,
    close_drawing,
    delete_view_clouds,
    delete_views,
    detect_collisions_between_marks,
    get_drawings,
    get_drawings_properties,
    get_drawing_views,
    get_view_annotations,
    get_view_objects,
    move_view,
    open_drawing,
    print_drawings,
    set_drawings_issue_state,
    set_drawings_properties,
    set_view_scales,
    update_drawings,
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


class TestGetDrawingsProperties:
    """Tests for get_drawings_properties function."""

    def test_get_drawings_properties_no_args(self):
        """Call get_drawings_properties without arguments (no selection)."""
        result = get_drawings_properties()

        assert result.structured_content["status"] == "error"

    def test_get_drawings_properties_with_mark(self):
        """Get a GA drawing and check its properties."""
        drawings_result = get_drawings(drawing_type="G")
        marks = drawings_result.structured_content.get("marks", [])

        if not marks:
            pytest.skip("No GA drawings available in model")

        result = get_drawings_properties(marks=[marks[0]])

        assert result.structured_content["selected_count"] == 1
        assert len(result.structured_content["drawings"]) == 1
        drawing = result.structured_content["drawings"][0]
        assert drawing["drawing_type"] == "G"
        # Revision_mark must always be present
        assert "revision_mark" in drawing
        assert drawing["revision_mark"] is None or isinstance(drawing["revision_mark"], str)
        # User-defined attributes must always be present as a dict
        assert isinstance(drawing["user_properties"], dict)


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
        """Sheet and non-sheet views expose different field sets."""
        open_drawing(mark=cu_mark)
        result = get_drawing_views()
        common = {"name", "view_key", "view_type", "is_sheet", "origin_x", "origin_y", "width", "height"}
        # The sheet view has no scale and no frame origin; model views add both.
        sheet_keys = common
        non_sheet_keys = common | {"scale", "frame_origin_x", "frame_origin_y"}
        for view in result.structured_content["views"]:
            expected = sheet_keys if view["is_sheet"] else non_sheet_keys
            assert set(view.keys()) == expected
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

    def test_set_scale_on_non_sheet_view(self, cu_mark):
        """Set scale on a non-sheet view."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view available")
        result = set_view_scales(view_scales=[ViewScale(view_key=key, scale=20.0)])
        assert result.structured_content["status"] == "success"
        assert result.structured_content["succeeded"] == 1
        assert result.structured_content["results"][0]["new_scale"] == 20.0
        close_drawing(save=False)

    def test_set_scale_on_sheet_view_rejected(self, cu_mark):
        """The sheet view has no scale, so it is rejected, not scaled."""
        open_drawing(mark=cu_mark)
        views = get_drawing_views().structured_content["views"]
        sheet_key = next((v["view_key"] for v in views if v["is_sheet"]), None)
        if sheet_key is None:
            pytest.skip("No sheet view found")
        result = set_view_scales(view_scales=[ViewScale(view_key=sheet_key, scale=20.0)])
        sc = result.structured_content
        assert sc["status"] == "error"
        assert sc["succeeded"] == 0
        assert sc["results"][0]["status"] == "failed"
        assert "sheet" in sc["results"][0]["message"].lower()
        close_drawing(save=False)

    def test_set_scale_multiple_non_sheet_views(self, cu_mark):
        """Set scale on all non-sheet views at once; the sheet is not included."""
        open_drawing(mark=cu_mark)
        views = get_drawing_views().structured_content["views"]
        non_sheet = [v for v in views if not v["is_sheet"]]
        if len(non_sheet) < 2:
            pytest.skip("Need at least 2 non-sheet views for multi-scale test")
        scales = [ViewScale(view_key=v["view_key"], scale=30.0) for v in non_sheet]
        result = set_view_scales(view_scales=scales)
        assert result.structured_content["status"] == "success"
        assert result.structured_content["succeeded"] == len(non_sheet)
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


class TestAlignSectionViews:
    """Tests for align_section_views function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_open_drawing(self):
        """Call without an open drawing raises an error."""
        result = align_section_views()
        assert result.structured_content["status"] == "error"

    def test_cu_drawing_aligned_zero(self, cu_mark):
        """CU drawing with no section views returns warning with 0 aligned."""
        open_drawing(mark=cu_mark)
        result = align_section_views()
        sc = result.structured_content
        assert sc["status"] == "warning"
        assert sc["aligned_count"] == 0
        assert sc["moves"] == []
        assert isinstance(sc["skipped"], list)
        close_drawing(save=False)

    def test_empty_view_keys_errors(self, cu_mark):
        """An empty view_keys list is rejected (omit it to align all)."""
        open_drawing(mark=cu_mark)
        result = align_section_views(view_keys=[])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_unknown_view_key_errors(self, cu_mark):
        """A view_keys entry that does not exist is rejected."""
        open_drawing(mark=cu_mark)
        result = align_section_views(view_keys=["NoSuchView_999999"])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_non_section_view_key_is_skipped(self, cu_mark):
        """A non-section view passed in view_keys is reported as skipped, not aligned."""
        open_drawing(mark=cu_mark)
        view_key = _first_non_sheet_view_key()
        assert view_key is not None
        result = align_section_views(view_keys=[view_key])
        sc = result.structured_content
        assert sc["aligned_count"] == 0
        assert any(s["view_key"] == view_key and "not a section view" in s["reason"] for s in sc["skipped"])
        close_drawing(save=False)


def _first_non_sheet_view_key():
    """Return view_key of the first non-sheet view in the open drawing, or None."""
    views = get_drawing_views().structured_content["views"]
    for v in views:
        if not v["is_sheet"]:
            return v["view_key"]
    return None


def _view_object_guids(view_key):
    """Every model-object GUID a view exposes: top-level guids plus embedded detail member guids."""
    objects = get_view_objects(view_key=view_key, limit=1000).structured_content["objects"]
    guids = set()
    for obj in objects:
        if obj.get("element_type") == "EmbeddedDetail":
            guids.update(p["guid"] for p in obj["parts"])
        else:
            guids.add(obj["guid"])
    return guids


class TestGetViewObjects:
    """Tests for get_view_objects function (cast unit drawing)."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_open_drawing(self):
        """Listing objects when no drawing is open raises an error."""
        result = get_view_objects(view_key="dummy")
        assert result.structured_content["status"] == "error"

    def test_invalid_view_key(self, cu_mark):
        """A non-existent view_key is rejected."""
        open_drawing(mark=cu_mark)
        result = get_view_objects(view_key="MCP_NONEXISTENT_VIEW")
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_success_returns_objects(self, cu_mark):
        """A cast unit view lists at least one model object."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view in cast unit drawing")
        sc = get_view_objects(view_key=key).structured_content
        assert sc["status"] == "success"
        assert sc["total_count"] >= 1
        assert sc["returned_count"] == len(sc["objects"])
        close_drawing(save=False)

    def test_every_object_has_guid_and_type(self, cu_mark):
        """Every returned object carries a guid and an element_type."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view in cast unit drawing")
        objects = get_view_objects(view_key=key).structured_content["objects"]
        for obj in objects:
            assert obj["guid"]
            assert obj["element_type"]
        close_drawing(save=False)

    def test_object_guids_are_unique(self, cu_mark):
        """Top-level object GUIDs are de-duplicated."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view in cast unit drawing")
        objects = get_view_objects(view_key=key).structured_content["objects"]
        guids = [o["guid"] for o in objects]
        assert len(guids) == len(set(guids))
        close_drawing(save=False)

    def test_limit_truncates(self, cu_mark):
        """limit caps returned_count and flags has_more when more exist."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view in cast unit drawing")
        full = get_view_objects(view_key=key).structured_content
        if full["total_count"] < 2:
            pytest.skip("View has fewer than 2 objects, cannot test truncation")
        sc = get_view_objects(view_key=key, limit=1).structured_content
        assert sc["returned_count"] <= 1
        assert sc["has_more"] is True
        close_drawing(save=False)

    def test_embedded_detail_shape(self, cu_mark):
        """When an embedded detail is present, parts carry guid+element_type and part_count matches."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view in cast unit drawing")
        objects = get_view_objects(view_key=key, limit=1000).structured_content["objects"]
        details = [o for o in objects if o.get("element_type") == "EmbeddedDetail"]
        if not details:
            pytest.skip("No embedded detail in this view")
        for d in details:
            assert d["part_count"] == len(d["parts"])
            for part in d["parts"]:
                assert part["guid"]
                assert part["element_type"]
            # No main-part properties leak onto the detail row
            assert "profile" not in d
            assert "material" not in d
        close_drawing(save=False)


class TestGetViewAnnotations:
    """Tests for get_view_annotations function (cast unit drawing)."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_open_drawing(self):
        """Reading annotations when no drawing is open raises an error."""
        result = get_view_annotations(view_key="dummy")
        assert result.structured_content["status"] == "error"

    def test_invalid_view_key(self, cu_mark):
        """A non-existent view_key is rejected."""
        open_drawing(mark=cu_mark)
        result = get_view_annotations(view_key="MCP_NONEXISTENT_VIEW")
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_success_shape(self, cu_mark):
        """A cast unit view returns the expected envelope."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view in cast unit drawing")
        sc = get_view_annotations(view_key=key).structured_content
        assert sc["status"] == "success"
        assert sc["returned_count"] == len(sc["annotations"])
        assert isinstance(sc["counts_by_category"], dict)
        close_drawing(save=False)

    def test_type_filter_marks_only(self, cu_mark):
        """type_filter='marks' returns only mark-category annotations."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view in cast unit drawing")
        annotations = get_view_annotations(view_key=key, type_filter="marks").structured_content["annotations"]
        for ann in annotations:
            assert ann["category"] == "marks"
        close_drawing(save=False)

    def test_marks_carry_target_guid(self, cu_mark):
        """Every mark annotation carries a target_guid (str or None)."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view in cast unit drawing")
        marks = get_view_annotations(view_key=key, type_filter="marks").structured_content["annotations"]
        if not marks:
            pytest.skip("No marks in this view")
        for mark in marks:
            assert "target_guid" in mark
            assert mark["target_guid"] is None or isinstance(mark["target_guid"], str)
        close_drawing(save=False)

    def test_mark_targets_join_to_view_objects(self, cu_mark):
        """At least one mark's target_guid resolves to a part shown in the view (coverage join)."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view in cast unit drawing")
        marks = get_view_annotations(view_key=key, type_filter="marks").structured_content["annotations"]
        target_guids = {m["target_guid"] for m in marks if m["target_guid"]}
        if not target_guids:
            pytest.skip("No marks resolve to a model object in this view")
        view_guids = _view_object_guids(key)
        assert target_guids & view_guids, "no mark target_guid matched a view object guid"
        close_drawing(save=False)


class TestSetDrawingsProperties:
    """Tests for set_drawings_properties function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_drawings_selected(self):
        """No marks and nothing selected raises an error."""
        result = set_drawings_properties(title1="MCP_TEST_TITLE1")
        assert result.structured_content["status"] == "error"

    def test_invalid_mark(self):
        """A non-existent mark raises an error."""
        result = set_drawings_properties(marks=["MCP_NONEXISTENT_DRAWING"], title1="MCP_TEST_TITLE1")
        assert result.structured_content["status"] == "error"

    def test_no_properties_provided(self, ga_mark):
        """Calling with only marks and no properties results in no modifications."""
        result = set_drawings_properties(marks=[ga_mark])
        sc = result.structured_content
        assert sc["status"] == "warning"
        assert sc["modified_count"] == 0
        assert sc["selected_count"] == 1

    def test_set_titles_and_uda(self, ga_mark):
        """Setting titles and a UDA succeeds and is reflected by get_drawings_properties afterwards."""
        before = get_drawings_properties(marks=[ga_mark]).structured_content["drawings"][0]
        handler = TeklaDrawingHandler()
        target_drawing = handler.get_drawings_by_marks([ga_mark])[0]
        try:
            checker_before = target_drawing.get_user_property("CHECKER", str)
        except AttributeError:
            checker_before = ""

        result = set_drawings_properties(
            marks=[ga_mark],
            title1="MCP_TEST_TITLE1",
            title2="MCP_TEST_TITLE2",
            title3="MCP_TEST_TITLE3",
            user_properties={"CHECKER": "MCP_TEST"},
        )
        sc = result.structured_content
        assert sc["status"] == "success"
        assert sc["modified_count"] == 1
        assert sc["changes_applied"]["title1"] == 1
        assert sc["changes_applied"]["title2"] == 1
        assert sc["changes_applied"]["title3"] == 1
        assert sc["changes_applied"]["udas"] == 1
        assert sc["property_errors"] == []

        after = get_drawings_properties(marks=[ga_mark]).structured_content["drawings"][0]
        assert after["title1"] == "MCP_TEST_TITLE1"
        assert after["title2"] == "MCP_TEST_TITLE2"
        assert after["title3"] == "MCP_TEST_TITLE3"
        assert after["user_properties"]["CHECKER"] == "MCP_TEST"

        # Restore original titles and UDA
        set_drawings_properties(
            marks=[ga_mark],
            title1=before["title1"],
            title2=before["title2"],
            title3=before["title3"],
            user_properties={"CHECKER": checker_before},
        )

    def test_set_name(self, ga_mark):
        """Setting the drawing name succeeds and is reflected by get_drawings_properties afterwards."""
        before = get_drawings_properties(marks=[ga_mark]).structured_content["drawings"][0]

        result = set_drawings_properties(marks=[ga_mark], name="MCP_TEST_NAME")
        sc = result.structured_content
        assert sc["status"] == "success"
        assert sc["modified_count"] == 1
        assert sc["changes_applied"]["name"] == 1
        assert sc["property_errors"] == []

        after = get_drawings_properties(marks=[ga_mark]).structured_content["drawings"][0]
        assert after["name"] == "MCP_TEST_NAME"

        # Restore original name
        set_drawings_properties(marks=[ga_mark], name=before["name"])

    def test_invalid_user_property_type(self, ga_mark):
        """An unsupported UDA value type is reported as a per-property error."""
        result = set_drawings_properties(marks=[ga_mark], user_properties={"CHECKER": [1, 2, 3]})
        sc = result.structured_content
        assert sc["property_errors"]
        errors = sc["property_errors"][0]["errors"]
        assert any(e["property"] == "uda:CHECKER" for e in errors)


class TestSetDrawingsIssueState:
    """Tests for set_drawings_issue_state function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_drawings_selected(self):
        """No marks and nothing selected raises an error."""
        result = set_drawings_issue_state(action="issue")
        assert result.structured_content["status"] == "error"

    def test_invalid_mark(self):
        """A non-existent mark raises an error."""
        result = set_drawings_issue_state(marks=["MCP_NONEXISTENT_DRAWING"], action="issue")
        assert result.structured_content["status"] == "error"

    def test_invalid_action(self, ga_mark):
        """An unsupported action value is rejected."""
        result = set_drawings_issue_state(marks=[ga_mark], action="invalid")
        assert result.structured_content["status"] == "error"

    def test_issue_then_unissue(self, ga_mark):
        """Issuing a drawing sets is_issued, unissuing reverts it."""
        # Make sure we start from a known (unissued) state
        set_drawings_issue_state(marks=[ga_mark], action="unissue")

        result = set_drawings_issue_state(marks=[ga_mark], action="issue")
        sc = result.structured_content
        assert sc["status"] == "success"
        assert sc["modified_count"] == 1
        assert sc["errors"] == []

        after_issue = get_drawings_properties(marks=[ga_mark]).structured_content["drawings"][0]
        assert after_issue["is_issued"] is True
        assert after_issue["issuing_date"] is not None

        result = set_drawings_issue_state(marks=[ga_mark], action="unissue")
        sc = result.structured_content
        assert sc["status"] == "success"
        assert sc["modified_count"] == 1
        assert sc["errors"] == []

        after_unissue = get_drawings_properties(marks=[ga_mark]).structured_content["drawings"][0]
        assert after_unissue["is_issued"] is False


class TestUpdateDrawings:
    """Tests for update_drawings function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_drawings_selected(self):
        """No marks and nothing selected raises an error."""
        result = update_drawings()
        assert result.structured_content["status"] == "error"

    def test_invalid_mark(self):
        """A non-existent mark raises an error."""
        result = update_drawings(marks=["MCP_NONEXISTENT_DRAWING"])
        assert result.structured_content["status"] == "error"

    def test_update_up_to_date_drawing(self, ga_mark):
        """Updating an already up-to-date, closed drawing is skipped, not an error."""
        before = get_drawings_properties(marks=[ga_mark]).structured_content["drawings"][0]
        if before["up_to_date_status"] != "DrawingIsUpToDate":
            pytest.skip("Drawing is not up to date, cannot test the skip path")

        result = update_drawings(marks=[ga_mark])
        sc = result.structured_content
        assert sc["status"] == "success"
        assert sc["selected_count"] == 1
        assert sc["modified_count"] == 0
        assert sc["skipped_count"] == 1
        assert sc["errors"] == []

        after = get_drawings_properties(marks=[ga_mark]).structured_content["drawings"][0]
        assert after["up_to_date_status"] == "DrawingIsUpToDate"
