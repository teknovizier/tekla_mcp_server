"""
View tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import ElementLabel, ElementLabelModel
from tekla_mcp_server.utils import log_mcp_tool_call
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import TeklaAssembly, TeklaPart, wrap_model_objects
from tekla_mcp_server.tekla.utils import get_filters, get_active_views, collect_children
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.loader import (
    AABB,
    Assembly,
    Part,
    Color,
    GraphicsDrawer,
    ModelObjectVisualization,
    Operation,
    Point,
    TemporaryTransparency,
    ViewHandler,
)


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

    resolved_label = None
    unit = None
    resolution_errors: list[dict[str, Any]] = []
    skip_custom_label = False

    if label_enum == ElementLabel.CUSTOM and custom_label:
        resolution = TemplateAttributeParser.resolve_attributes([custom_label])
        errors = resolution.get("errors", [])
        if errors:
            candidates = resolution.get("candidates", {})
            resolution_errors.append({"query": custom_label, "candidates": candidates.get(custom_label, [])})
            skip_custom_label = True
        else:
            resolved_label = resolution["resolved"][0]
            custom_property = TemplateAttributeParser.get_attribute(resolved_label)
            unit = f" {custom_property.unit}" if custom_property.unit else ""

    color_black = (0.0, 0.0, 0.0)
    drawer = GraphicsDrawer()
    processed_elements = 0
    drawn_labels = 0

    for selected_object in wrap_model_objects(selected_objects):
        if label_enum == ElementLabel.CUSTOM:
            if skip_custom_label:
                continue
            value = selected_object.get_report_property(resolved_label)
            text = f"{resolved_label} = {value}{unit}"
        else:
            if isinstance(selected_object, TeklaAssembly):
                assembly_labels = {
                    ElementLabel.POSITION: selected_object.position,
                    ElementLabel.GUID: selected_object.guid,
                    ElementLabel.NAME: selected_object.name,
                    ElementLabel.PHASE: str(selected_object.phase),
                    ElementLabel.WEIGHT: f"{selected_object.weight[0]:.1f} kg",
                }
                text = assembly_labels.get(label_enum, ElementLabel.NAME)
            elif isinstance(selected_object, TeklaPart):
                part_labels = {
                    ElementLabel.POSITION: selected_object.position,
                    ElementLabel.GUID: selected_object.guid,
                    ElementLabel.NAME: selected_object.name,
                    ElementLabel.PROFILE: selected_object.profile,
                    ElementLabel.MATERIAL: selected_object.material,
                    ElementLabel.FINISH: selected_object.finish,
                    ElementLabel.CLASS: selected_object.tekla_class,
                    ElementLabel.PHASE: str(selected_object.phase),
                    ElementLabel.WEIGHT: f"{selected_object.weight[0]:.1f} kg",
                }
                text = part_labels.get(label_enum, ElementLabel.NAME)
            else:
                continue
        if drawer.DrawText(selected_object.cog, text, Color(*color_black)):
            drawn_labels += 1
        processed_elements += 1
    logger.info("Drawn '%s' labels on %s elements", label_enum.value, drawn_labels)
    if drawn_labels and not resolution_errors:
        status = "success"
    elif drawn_labels and resolution_errors:
        status = "partial"
    else:
        status = "error"
    return {
        "status": status,
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "drawn_labels": drawn_labels,
        "resolution_errors": resolution_errors,
    }


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

    processed_elements = 0

    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")

    for selected_object in selected_objects:
        part = None
        if isinstance(selected_object, Part):
            part = selected_object
        elif isinstance(selected_object, Assembly):
            part = selected_object.GetMainPart()
        if part is None:
            continue

        solid = part.GetSolid()
        if solid is None:
            continue

        sp = solid.MinimumPoint
        ep = solid.MaximumPoint

        min_x = min(min_x, sp.X)
        min_y = min(min_y, sp.Y)
        min_z = min(min_z, sp.Z)
        max_x = max(max_x, ep.X)
        max_y = max(max_y, ep.Y)
        max_z = max(max_z, ep.Z)

        processed_elements += 1

    min_point = Point(min_x, min_y, min_z)
    max_point = Point(max_x, max_y, max_z)
    bbox = AABB(min_point, max_point)
    result = ViewHandler.ZoomToBoundingBox(bbox)
    logger.info("Zoomed to bounding box: %s", bbox)
    return {
        "status": "success" if result else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
    }


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
    views = get_active_views()
    views_redrawn = 0

    for view in views:
        if ViewHandler.RedrawView(view):
            views_redrawn += 1

    logger.info("Redrawn %d active views", len(views))
    return {"status": "success", "views_redrawn": views_redrawn, "total_views": len(views)}


@view_provider.tool()
@log_mcp_tool_call
def apply_view_filter(filter_name: str) -> dict[str, Any]:
    """
    Applies a view filter to all visible views in Tekla.

    ## INPUT
    - `filter_name` [Required]: Name of the view filter to apply.
      Use tekla://filters/view to discover available filters.
    """
    available = get_filters(".VObjGrp")
    if filter_name not in available:
        logger.warning("Invalid filter '%s' requested. Available filters: %s", filter_name, available)
        return {"status": "error", "message": f"Invalid filter '{filter_name}'", "available_filters": available}

    views = get_active_views()
    for view in views:
        view.ViewFilter = filter_name
        view.Modify()

    logger.info("Applied view filter '%s' to %d views", filter_name, len(views))
    return {"status": "success", "filter_name": filter_name, "views_modified": len(views)}


@view_provider.tool()
@log_mcp_tool_call
def show_only_selected() -> dict[str, Any]:
    """
    Shows only the currently selected model objects in the Tekla current view, hiding all others.

    ## INPUT
    - No additional parameters required.
    """
    selected_objects = TeklaModel().get_selected_objects()
    Operation.ShowOnlySelected(Operation.UnselectedModeEnum.Hidden)
    logger.info("Hidden all the elements except the selected ones")
    return {
        "status": "success",
        "selected_elements": selected_objects.GetSize(),
    }


@view_provider.tool()
@log_mcp_tool_call
def hide_selected() -> dict[str, Any]:
    """
    Hides the selected elements in the Tekla view.

    ## INPUT
    - No additional parameters required.
    """
    selected_objects = TeklaModel().get_selected_objects()
    tekla_list = collect_children(selected_objects)
    ModelObjectVisualization.SetTransparency(tekla_list, TemporaryTransparency.HIDDEN)

    return {"status": "success", "hidden_elements": tekla_list.Count}


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
    tekla_list = collect_children(selected_objects)
    color = Color(red / 255.0, green / 255.0, blue / 255.0)
    ModelObjectVisualization.SetTemporaryState(tekla_list, color)

    return {"status": "success", "colored_elements": tekla_list.Count}
