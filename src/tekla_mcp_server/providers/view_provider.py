"""
View tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.models import ElementLabelModel
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tools.view import (
    tool_draw_elements_labels,
    tool_zoom_to_selection,
    tool_redraw_view,
    tool_show_only_selected,
    tool_hide_selected,
    tool_color_selected,
    tool_apply_view_filter,
)
from tekla_mcp_server.utils import log_mcp_tool_call


view_provider = LocalProvider()


@view_provider.tool()
@log_mcp_tool_call
def draw_elements_labels(label: str | None = None, custom_label: str | None = None) -> dict[str, Any]:
    """
    Draws temporary labels in the Tekla model.

    ## INPUT
    - `label` [Optional]: Type of label to draw
    - `custom_label` [Optional]: Any user-provided report property name.

    ## BEHAVIOR
    Treat any value provided by the user as the name of a Tekla attribute.
    If `custom_label` is provided, use it.
    Otherwise use `label`.

    ## VALID VALUES BY ELEMENT TYPE

    ### FOR ASSEMBLIES:
    - Position, GUID, Name, Weight

    ### FOR PARTS:
    - Position, GUID, Name, Profile, Material, Finish, Class, Weight

    Note: If a label is not applicable to the selected element type, it defaults to Name.
    """
    selected_objects = TeklaModel().get_selected_objects()

    if custom_label:
        label_value = "Custom"
    else:
        label_value = "Name" if label is None else label

    label_enum = ElementLabelModel(value=label_value).to_enum()
    return tool_draw_elements_labels(selected_objects, label_enum, custom_label)


@view_provider.tool()
@log_mcp_tool_call
def zoom_to_selection() -> dict[str, Any]:
    """
    Zooms the Tekla current view to fit the currently selected model objects.

    ## INPUT
    - No additional parameters required.
    """
    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    return tool_zoom_to_selection(selected_objects)


@view_provider.tool()
@log_mcp_tool_call
def redraw_view() -> dict[str, Any]:
    """
    Redraws the currently active view in Tekla.

    ## INPUT
    - No additional parameters required.

    ## INSTRUCTIONS
    - This tool MUST NOT be called immediately after the coloring tool.
    - If coloring was just applied, do not trigger a redraw.
    """
    return tool_redraw_view()


@view_provider.tool()
@log_mcp_tool_call
def apply_view_filter(filter_name: str) -> dict[str, Any]:
    """
    Applies a view filter to all visible views in Tekla.

    ## INPUT
    - `filter_name` [Required]: Name of the view filter to apply.
      Use tekla://filters/view to discover available filters.
    """
    return tool_apply_view_filter(filter_name)


@view_provider.tool()
@log_mcp_tool_call
def show_only_selected() -> dict[str, Any]:
    """
    Shows only the currently selected model objects in the Tekla current view, hiding all others.

    ## INPUT
    - No additional parameters required.
    """
    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    return tool_show_only_selected(selected_objects)


@view_provider.tool()
@log_mcp_tool_call
def hide_selected() -> dict[str, Any]:
    """
    Hides the selected elements in the Tekla view.

    ## INPUT
    - No additional parameters required.
    """
    selected_objects = TeklaModel().get_selected_objects()
    return tool_hide_selected(selected_objects)


@view_provider.tool()
@log_mcp_tool_call
def color_selected(red: int, green: int, blue: int) -> dict[str, Any]:
    """
    Colors the selected elements in the Tekla view with the specified color.

    ## INPUT
    - `red` [Required]: Red component (0-255)
    - `green` [Required]: Green component (0-255)
    - `blue` [Required]: Blue component (0-255)
    """
    selected_objects = TeklaModel().get_selected_objects()
    return tool_color_selected(selected_objects, red, green, blue)
