"""
Functional tests for drawings_provider.

Tests drawing retrieval, property retrieval, mark collision detection,
open/close drawing, view listing, move, scale, and delete operations.
"""

import os
import tempfile
from pathlib import Path

import pytest
from unittest.mock import patch

from tekla_mcp_server.config import get_export_output_dir
from tekla_mcp_server.models import ViewAttributes
from tekla_mcp_server.providers.drawings_provider import (
    align_section_views,
    check_for_unattached_dimensions,
    check_drawing_collisions,
    check_for_unmarked_objects,
    close_drawing,
    delete_clouds,
    delete_views,
    export_drawings,
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
    set_views_attributes,
    update_drawings,
)
from tekla_mcp_server.tekla.wrappers.drawing_handler import TeklaDrawingHandler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.utils import resolve_model_relative_dir


def _skip_if_drawings_selected():
    """
    Skip the test if Tekla's Document Manager currently has a drawing selected.

    Tools that take an optional `marks` list fall back to the Document
    Manager's current selection when `marks` is omitted or empty - so a
    "no marks and nothing selected" test only proves its point when nothing
    is selected. The Tekla Open API's `DrawingSelector` exposes only
    `GetSelected()`, with no way to clear the selection from code, so this
    suite cannot reset that precondition. It can only detect and skip when
    it isn't met (e.g. a drawing left selected from manual use).
    """
    handler = TeklaDrawingHandler()
    if list(handler.handler.GetDrawingSelector().GetSelected()):
        pytest.skip("A drawing is currently selected in the Tekla Document Manager - cannot test the 'nothing selected' path")


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


@pytest.fixture(scope="module")
def assembly_mark():
    """Return the mark of a assembly drawing in the model."""
    result = get_drawings(drawing_type="A")
    marks = result.structured_content.get("marks", [])
    if not marks:
        pytest.skip("No assembly drawings available in model")
    return marks[0]


class TestGetDrawings:
    """Tests for get_drawings function."""

    def test_get_drawings_no_filters(self):
        """Call get_drawings without any arguments."""
        result = get_drawings()

        assert result.structured_content["status"] == "success"
        assert result.structured_content["matched_count"] >= 3

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
        _skip_if_drawings_selected()
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


class TestPrintDrawings:
    """Tests for print_drawings function."""

    def test_print_drawings_no_drawings_selected(self):
        """Call without selecting any drawings."""
        _skip_if_drawings_selected()
        result = print_drawings()

        assert result.structured_content["status"] == "error"
        assert "no drawings" in result.structured_content["message"].lower()


class TestExportDrawings:
    """Tests for export_drawings function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Export requires no drawing to be open."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing(save=True)
        yield

    @pytest.fixture(autouse=True)
    def cleanup_exported_files(self):
        """
        Remove files this test creates in the configured export output folder.

        Leftover files from a prior test run cause Tekla's export dialog to
        prompt "Overwrite?" on the next on-the-go export, which the macro
        cannot answer and which the snapshot-diff misreports as 'partial'.
        """
        model_path = TeklaModel().model_path
        output_dir = Path(resolve_model_relative_dir(get_export_output_dir(), model_path))
        before = set(output_dir.glob("*")) if output_dir.is_dir() else set()
        yield
        if output_dir.is_dir():
            for path in set(output_dir.glob("*")) - before:
                path.unlink(missing_ok=True)

    def test_export_drawings_no_drawings_selected(self):
        """Call without selecting any drawings and no marks."""
        _skip_if_drawings_selected()
        result = export_drawings()

        assert result.structured_content["status"] == "error"
        assert "no drawings" in result.structured_content["message"].lower()

    def test_export_drawings_open_drawing_rejected(self, ga_mark):
        """Export is rejected while a drawing is open."""
        open_drawing(mark=ga_mark)
        try:
            result = export_drawings(marks=[ga_mark])
            assert result.structured_content["status"] == "error"
            assert "open" in result.structured_content["message"].lower()
        finally:
            close_drawing(save=False)

    def test_export_drawings_on_the_go_dxf(self, ga_mark):
        """On-the-go DXF export produces a file in the configured output folder."""
        result = export_drawings(marks=[ga_mark], drawing_format="dxf")
        sc = result.structured_content

        assert sc["status"] == "success"
        assert sc["format"] == "dxf"
        assert sc["exported"] >= 1
        assert all(name.endswith(".dxf") for name in sc["files"])

    def test_export_drawings_dwg_version(self, ga_mark):
        """DWG export at a non-default version produces a .dwg file."""
        result = export_drawings(marks=[ga_mark], drawing_format="dwg", version="2013")
        sc = result.structured_content

        assert sc["status"] == "success"
        assert sc["format"] == "dwg"
        assert sc["version"] == "2013"
        assert all(name.endswith(".dwg") for name in sc["files"])

    def test_export_drawings_invalid_version_rejected(self, ga_mark):
        """An unsupported version is rejected by enum validation."""
        result = export_drawings(marks=[ga_mark], version="2018")

        assert result.structured_content["status"] == "error"

    def test_export_drawings_invalid_version_string_rejected(self, ga_mark):
        """A non-numeric version string is rejected by enum validation."""
        result = export_drawings(marks=[ga_mark], version="abc")

        assert result.structured_content["status"] == "error"

    def test_export_drawings_invalid_format_rejected(self, ga_mark):
        """An unsupported format is rejected by enum validation."""
        result = export_drawings(marks=[ga_mark], drawing_format="pdf")

        assert result.structured_content["status"] == "error"

    def test_export_drawings_nonexistent_setting_rejected(self, ga_mark):
        """A named setting that does not exist in Document Manager is rejected."""
        result = export_drawings(marks=[ga_mark], export_settings="MCP_TEST_NONEXISTENT_SETTING")

        assert result.structured_content["status"] == "error"

    def test_export_drawings_dgn(self, ga_mark):
        """DGN export produces a .dgn file, defaulting to version 2010."""
        result = export_drawings(marks=[ga_mark], drawing_format="dgn")
        sc = result.structured_content

        assert sc["status"] == "success"
        assert sc["format"] == "dgn"
        assert sc["version"] == "2010"
        assert all(name.endswith(".dgn") for name in sc["files"])

    def test_export_drawings_dgn_with_version(self, ga_mark):
        """DGN accepts an explicit version, same as DWG/DXF."""
        result = export_drawings(marks=[ga_mark], drawing_format="dgn", version="2013")
        sc = result.structured_content

        assert sc["status"] == "success"
        assert sc["version"] == "2013"

    def test_export_drawings_rejects_non_existent_absolute_dir(self, ga_mark):
        """On-the-go export errors when output_dir is an absolute path that does not exist."""
        non_existent = os.path.join(tempfile.gettempdir(), "MCP_TEST_NONEXISTENT_12345")
        assert not os.path.isdir(non_existent)
        with patch("tekla_mcp_server.providers.drawings_provider.get_export_output_dir", return_value=non_existent):
            with patch("tekla_mcp_server.providers.drawings_provider.get_default_export_settings", return_value=""):
                result = export_drawings(marks=[ga_mark])
                sc = result.structured_content
                assert sc["status"] == "error"
                assert "does not exist" in sc["message"]

    def test_export_drawings_rejects_non_existent_relative_dir(self, ga_mark):
        """On-the-go export errors when output_dir is a relative path that does not exist."""
        with patch("tekla_mcp_server.providers.drawings_provider.get_export_output_dir", return_value=".\\MCP_TEST_NONEXISTENT_REL"):
            with patch("tekla_mcp_server.providers.drawings_provider.get_default_export_settings", return_value=""):
                result = export_drawings(marks=[ga_mark])
                sc = result.structured_content
                assert sc["status"] == "error"
                assert "does not exist" in sc["message"]

    def test_export_drawings_accepts_existing_absolute_dir(self, ga_mark):
        """On-the-go export succeeds when output_dir is an existing absolute path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tekla_mcp_server.providers.drawings_provider.get_export_output_dir", return_value=tmpdir):
                with patch("tekla_mcp_server.providers.drawings_provider.get_default_export_settings", return_value=""):
                    result = export_drawings(marks=[ga_mark], drawing_format="dxf")
                    sc = result.structured_content
                    assert sc["status"] == "success"
                    assert sc["format"] == "dxf"
                    assert sc["exported"] >= 1

    def test_export_drawings_rejects_non_existent_dir_dwg(self, ga_mark):
        """Error reported for non-existent dir regardless of format."""
        with patch("tekla_mcp_server.providers.drawings_provider.get_export_output_dir", return_value="Z:\\MCP_TEST_NONEXISTENT_DWG"):
            with patch("tekla_mcp_server.providers.drawings_provider.get_default_export_settings", return_value=""):
                result = export_drawings(marks=[ga_mark], drawing_format="dwg", version="2013")
                sc = result.structured_content
                assert sc["status"] == "error"
                assert "does not exist" in sc["message"]

    def test_export_drawings_rejects_non_existent_dir_dgn(self, ga_mark):
        """Error reported for non-existent dir with DGN format."""
        with patch("tekla_mcp_server.providers.drawings_provider.get_export_output_dir", return_value="Z:\\MCP_TEST_NONEXISTENT_DGN"):
            with patch("tekla_mcp_server.providers.drawings_provider.get_default_export_settings", return_value=""):
                result = export_drawings(marks=[ga_mark], drawing_format="dgn")
                sc = result.structured_content
                assert sc["status"] == "error"
                assert "does not exist" in sc["message"]


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
        assert "sheet_count" in result.structured_content
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
        # The sheet view has no label, frame origin, sheet number or display settings
        sheet_keys = common
        non_sheet_keys = common | {"label", "frame_origin_x", "frame_origin_y", "sheet_number", "display_settings"}
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


class TestSetViewsAttributes:
    """Tests for set_views_attributes function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_set_scale_no_open_drawing(self):
        """Setting attributes when no drawing is open raises an error."""
        result = set_views_attributes(views_attributes=[ViewAttributes(view_key="dummy", scale=20.0)])
        assert result.structured_content["status"] == "error"

    def test_set_scale_invalid_view_key(self, cu_mark):
        """Setting attributes on a non-existent view."""
        open_drawing(mark=cu_mark)
        result = set_views_attributes(views_attributes=[ViewAttributes(view_key="MCP_NONEXISTENT_VIEW", scale=20.0)])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_set_scale_empty_list(self):
        """An empty list raises an error."""
        result = set_views_attributes(views_attributes=[])
        assert result.structured_content["status"] == "error"

    def test_set_scale_on_non_sheet_view(self, cu_mark):
        """Set scale on a non-sheet view."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view available")
        result = set_views_attributes(views_attributes=[ViewAttributes(view_key=key, scale=20.0)])
        assert result.structured_content["status"] == "success"
        assert result.structured_content["succeeded"] == 1
        assert result.structured_content["results"][0]["updated"] == {"scale": 20.0}
        close_drawing(save=False)

    def test_set_boolean_attribute_on_non_sheet_view(self, cu_mark):
        """Set a non-scale display attribute on a non-sheet view."""
        open_drawing(mark=cu_mark)
        key = _first_non_sheet_view_key()
        if key is None:
            pytest.skip("No non-sheet view available")
        result = set_views_attributes(views_attributes=[ViewAttributes(view_key=key, reflected_view=True)])
        assert result.structured_content["status"] == "success"
        assert result.structured_content["succeeded"] == 1
        assert result.structured_content["results"][0]["updated"] == {"reflected_view": True}
        close_drawing(save=False)

    def test_set_scale_on_sheet_view_rejected(self, cu_mark):
        """The sheet view has no scale, so it is rejected, not scaled."""
        open_drawing(mark=cu_mark)
        views = get_drawing_views().structured_content["views"]
        sheet_key = next((v["view_key"] for v in views if v["is_sheet"]), None)
        if sheet_key is None:
            pytest.skip("No sheet view found")
        result = set_views_attributes(views_attributes=[ViewAttributes(view_key=sheet_key, scale=20.0)])
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
        updates = [ViewAttributes(view_key=v["view_key"], scale=30.0) for v in non_sheet]
        result = set_views_attributes(views_attributes=updates)
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


class TestDeleteClouds:
    """Tests for delete_clouds function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_open_drawing_raises(self):
        """Raises when no drawing is open."""
        result = delete_clouds()
        assert result.structured_content["status"] == "error"

    def test_empty_view_keys_processes_all_views(self, cu_mark):
        """An empty view_keys list processes all views, like omitting it."""
        open_drawing(mark=cu_mark)
        result = delete_clouds(view_keys=[])
        sc = result.structured_content
        assert sc["status"] == "success"
        assert sc["total_found"] == 0
        assert sc["total_deleted"] == 0
        assert sc["total_failed"] == 0
        assert sc["views"] == []
        close_drawing(save=False)

    def test_invalid_view_key_rejected(self, cu_mark):
        """A non-existent view_key is rejected."""
        open_drawing(mark=cu_mark)
        result = delete_clouds(view_keys=["MCP_NONEXISTENT_VIEW"])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_no_clouds_returns_success(self, cu_mark):
        """Drawing with no clouds returns success with zero counts."""
        open_drawing(mark=cu_mark)
        result = delete_clouds()
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
        result = delete_clouds()
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
        result = delete_clouds(view_keys=non_sheet_keys)
        assert result.structured_content["status"] in {"success", "partial"}
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

    def test_empty_view_keys_aligns_all(self, cu_mark):
        """An empty view_keys list aligns all section views, like omitting it."""
        open_drawing(mark=cu_mark)
        result = align_section_views(view_keys=[])
        sc = result.structured_content
        assert sc["status"] == "warning"
        assert sc["aligned_count"] == 0
        assert sc["moves"] == []
        assert isinstance(sc["skipped"], list)
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
        view_key = _first_non_section_view_key()
        if view_key is None:
            close_drawing(save=False)
            pytest.skip("No non-section view available in this drawing")
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


def _first_non_section_view_key():
    """Return view_key of the first non-sheet, non-section view, or None."""
    views = get_drawing_views().structured_content["views"]
    for v in views:
        if not v["is_sheet"] and v["view_type"] != "SectionView":
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
        _skip_if_drawings_selected()
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
        _skip_if_drawings_selected()
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
        _skip_if_drawings_selected()
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


class TestCheckDrawingCollisions:
    """Tests for check_drawing_collisions function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_drawings_selected(self):
        """No marks and nothing selected raises an error."""
        _skip_if_drawings_selected()
        result = check_drawing_collisions()
        assert result.structured_content["status"] == "error"

    def test_runs_on_one_drawing_and_response_has_required_fields(self, cu_mark):
        """Checking one drawing returns the expected report shape, then clean up any clouds drawn."""
        before = get_drawings_properties(marks=[cu_mark]).structured_content["drawings"][0]
        if before["up_to_date_status"] != "DrawingIsUpToDate":
            pytest.skip("Drawing is not up to date, cannot run collision check")

        result = check_drawing_collisions(marks=[cu_mark])
        sc = result.structured_content
        assert sc["status"] in {"success", "partial"}
        assert sc["drawings_selected"] == 1
        assert {"drawings_succeeded", "drawings_failed", "total_issues", "issues_by_category", "clouds_drawn", "cloud_failures", "per_drawing"}.issubset(sc.keys())

        # Clean up any clouds the check drew, so the scratch drawing stays clean
        if sc["clouds_drawn"] > 0:
            open_drawing(mark=cu_mark)
            delete_clouds()
            close_drawing(save=True)


class TestCheckForUnattachedDimensions:
    """Tests for check_for_unattached_dimensions function."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_drawings_selected(self):
        """No marks and nothing selected raises an error."""
        _skip_if_drawings_selected()
        result = check_for_unattached_dimensions()
        assert result.structured_content["status"] == "error"

    def test_rejects_open_drawing(self, cu_mark):
        """An open drawing blocks the check - the export needs the Document Manager."""
        open_drawing(mark=cu_mark)
        try:
            result = check_for_unattached_dimensions(marks=[cu_mark])
            assert result.structured_content["status"] == "error"
        finally:
            close_drawing(save=False)

    def test_runs_on_one_drawing_and_response_has_required_fields(self, cu_mark):
        """Checking one drawing returns the expected report shape, then clean up any clouds drawn."""
        before = get_drawings_properties(marks=[cu_mark]).structured_content["drawings"][0]
        if before["up_to_date_status"] != "DrawingIsUpToDate":
            pytest.skip("Drawing is not up to date, cannot run attachment check")

        result = check_for_unattached_dimensions(marks=[cu_mark])
        sc = result.structured_content
        assert sc["status"] in {"success", "partial"}
        assert sc["drawings_selected"] == 1
        assert {"drawings_succeeded", "drawings_failed", "dimension_points_checked", "total_unattached", "clouds_drawn", "cloud_failures", "per_drawing"}.issubset(sc.keys())

        # Each unattached point reported carries its sheet location and source view
        for drawing_result in sc["per_drawing"]:
            for pt in drawing_result.get("unattached_points", []):
                assert {"x", "y", "view"}.issubset(pt.keys())

        # Clean up any clouds the check drew, so the scratch drawing stays clean
        if sc["clouds_drawn"] > 0:
            open_drawing(mark=cu_mark)
            delete_clouds()
            close_drawing(save=True)


class TestCheckForUnmarkedObjects:
    """Tests for check_for_unmarked_objects function (cast unit drawing)."""

    @pytest.fixture(autouse=True)
    def ensure_no_open_drawing(self):
        """Close any open drawing before each test."""
        handler = TeklaDrawingHandler()
        if handler.get_active_drawing() is not None:
            handler.close_active_drawing()
        yield

    def test_no_open_drawing(self):
        """Checking when no drawing is open raises an error."""
        result = check_for_unmarked_objects()
        assert result.structured_content["status"] == "error"

    def test_invalid_view_key(self, assembly_mark):
        """A non-existent view_key is rejected."""
        open_drawing(mark=assembly_mark)
        result = check_for_unmarked_objects(view_keys=["MCP_NONEXISTENT_VIEW"])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_mix_of_valid_and_invalid_view_keys_is_rejected(self, assembly_mark):
        """One invalid key among otherwise-valid ones still fails the whole call."""
        open_drawing(mark=assembly_mark)
        views = get_drawing_views().structured_content["views"]
        valid_key = next(v["view_key"] for v in views if not v["is_sheet"])
        result = check_for_unmarked_objects(view_keys=[valid_key, "MCP_NONEXISTENT_VIEW"])
        assert result.structured_content["status"] == "error"
        close_drawing(save=False)

    def test_success_shape(self, assembly_mark):
        """A cast unit drawing returns the expected envelope."""
        open_drawing(mark=assembly_mark)
        sc = check_for_unmarked_objects().structured_content
        assert sc["status"] == "success"
        assert set(sc["counts_by_category"]).issubset({"parts", "reinforcement", "bolts"})
        assert sc["categories_checked"]
        close_drawing(save=False)

    def test_empty_view_keys_checks_every_non_sheet_view(self, assembly_mark):
        """An empty view_keys list checks every non-sheet view, like omitting it."""
        open_drawing(mark=assembly_mark)
        views = get_drawing_views().structured_content["views"]
        non_sheet_keys = {v["view_key"] for v in views if not v["is_sheet"]}
        sc = check_for_unmarked_objects(view_keys=[]).structured_content
        assert set(sc["view_keys_checked"]) == non_sheet_keys
        close_drawing(save=False)

    def test_duplicate_view_keys_are_not_double_counted(self, assembly_mark):
        """Repeating the same view_key must not double-count totals or unmarked entries."""
        open_drawing(mark=assembly_mark)
        views = get_drawing_views().structured_content["views"]
        valid_key = next(v["view_key"] for v in views if not v["is_sheet"])
        once = check_for_unmarked_objects(view_keys=[valid_key]).structured_content
        twice = check_for_unmarked_objects(view_keys=[valid_key, valid_key]).structured_content
        assert twice["view_keys_checked"] == [valid_key]
        assert twice["counts_by_category"] == once["counts_by_category"]
        assert len(twice["unmarked"]) == len(once["unmarked"])
        close_drawing(save=False)

    def test_categories_filter_scopes_counts_by_category(self, assembly_mark):
        """Scoping to one category must not pad counts_by_category with the others."""
        open_drawing(mark=assembly_mark)
        sc = check_for_unmarked_objects(categories=["parts"]).structured_content
        assert sc["categories_checked"] == ["parts"]
        assert set(sc["counts_by_category"]) == {"parts"}
        close_drawing(save=False)

    def test_all_literal_checks_every_category(self, assembly_mark):
        """categories=['all'] is equivalent to omitting categories."""
        open_drawing(mark=assembly_mark)
        sc = check_for_unmarked_objects(categories=["all"]).structured_content
        assert sorted(sc["categories_checked"]) == ["bolts", "parts", "reinforcement"]
        close_drawing(save=False)

    def test_limit_truncates_and_sets_has_more(self, assembly_mark):
        """limit caps returned unmarked items and flags has_more when more exist."""
        open_drawing(mark=assembly_mark)
        full = check_for_unmarked_objects().structured_content
        if len(full["unmarked"]) < 2:
            pytest.skip("Fewer than 2 unmarked objects in this drawing, cannot test truncation")
        sc = check_for_unmarked_objects(limit=1).structured_content
        assert len(sc["unmarked"]) == 1
        assert sc["has_more"] is True
        close_drawing(save=False)

    def test_unmarked_items_reference_real_view_objects(self, assembly_mark):
        """Every unmarked guid corresponds to an object actually shown in its view."""
        open_drawing(mark=assembly_mark)
        sc = check_for_unmarked_objects().structured_content
        if not sc["unmarked"]:
            pytest.skip("No unmarked objects in this drawing")
        by_view: dict[str, set[str]] = {}
        for item in sc["unmarked"]:
            by_view.setdefault(item["view_key"], set()).add(item["guid"])
        for view_key, guids in by_view.items():
            assert guids & _view_object_guids(view_key)
        close_drawing(save=False)

    def test_bolt_entries_carry_bolt_specific_fields_not_name_or_position(self, assembly_mark):
        """An unmarked bolt has null name/position but carries bolt_standard/bolt_size/connected_parts."""
        open_drawing(mark=assembly_mark)
        sc = check_for_unmarked_objects(categories=["bolts"]).structured_content
        bolts = [u for u in sc["unmarked"] if u["category"] == "bolts"]
        if not bolts:
            pytest.skip("No unmarked bolts in this drawing")
        for bolt in bolts:
            assert bolt["name"] is None
            assert bolt["position"] is None
            assert "bolt_standard" in bolt
            assert "bolt_size" in bolt
            assert set(bolt["connected_parts"]) == {"part_to_be_bolted", "part_to_bolt_to"}
            for connected in bolt["connected_parts"].values():
                assert set(connected) == {"guid", "name", "position"}
        close_drawing(save=False)

    def test_embedded_detail_units_use_mark_scope_assembly(self, assembly_mark):
        """An unmarked embedded detail is reported once, scoped at assembly level."""
        open_drawing(mark=assembly_mark)
        sc = check_for_unmarked_objects().structured_content
        details = [u for u in sc["unmarked"] if u["element_type"] == "EmbeddedDetail"]
        if not details:
            pytest.skip("No unmarked embedded detail in this drawing")
        for detail in details:
            assert detail["mark_scope"] == "assembly"
        close_drawing(save=False)
