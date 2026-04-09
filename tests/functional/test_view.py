"""
Functional tests for view_provider.

Tests view operations like labeling, zooming, filtering, coloring, and hiding.
"""

from tekla_mcp_server.providers.view_provider import (
    draw_elements_labels,
    zoom_to_selection,
    redraw_view,
    show_only_selected,
    hide_selected,
    color_selected,
    apply_view_filter,
)
from tekla_mcp_server.tekla.loader import ViewHandler
from tekla_mcp_server.tekla.model import TeklaModel


def test_draw_elements_labels(model_objects):
    """Tests draw_elements_labels function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = draw_elements_labels()
    assert result["status"] == "success"
    assert result["selected_elements"] == 2

    view_enum = ViewHandler.GetAllViews()
    while view_enum.MoveNext():
        ViewHandler.RedrawView(view_enum.Current)


def test_draw_elements_labels_with_label(model_objects):
    """Tests draw_elements_labels with specific label."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = draw_elements_labels(label="Profile")
    assert result["status"] == "success"
    assert result["selected_elements"] == 2


def test_draw_elements_labels_with_valid_custom_label(model_objects):
    """Tests draw_elements_labels with custom_label."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = draw_elements_labels(label="Custom", custom_label="AREA_NET")
    assert result["status"] == "success"


def test_draw_elements_labels_with_invalid_custom_label(model_objects):
    """Tests draw_elements_labels with invalid custom_label."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = draw_elements_labels(label="Custom", custom_label="InvalidProperty")
    assert result["status"] == "error"


def test_zoom_to_selection(model_objects):
    """Tests zoom_to_selection function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = zoom_to_selection()
    assert result["status"] == "success"


def test_redraw_view():
    """Tests redraw_view function."""
    result = redraw_view()
    assert result["status"] == "success"


def test_apply_view_filter():
    """Tests apply_view_filter function."""
    result = apply_view_filter(filter_name="standard")
    assert result["status"] == "success"
    assert result["filter_name"] == "standard"


def test_show_only_selected(model_objects):
    """Tests show_only_selected function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = show_only_selected()
    assert result["status"] == "success"


def test_hide_selected_parts(model_objects):
    """Tests hide_selected function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = hide_selected()
    assert result["status"] == "success"


def test_color_selected(model_objects):
    """Tests color_selected function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = color_selected(red=255, green=0, blue=0)
    assert result["status"] == "success"
