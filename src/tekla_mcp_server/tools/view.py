"""
View tools for Tekla model operations.
"""

from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import ElementLabel, get_filters
from tekla_mcp_server.tekla.loader import (
    AABB,
    Color,
    GraphicsDrawer,
    List,
    ModelObject,
    ModelObjectEnumerator,
    ModelObjectVisualization,
    Operation,
    Point,
    TemporaryTransparency,
    ViewHandler,
)
from tekla_mcp_server.tekla.utils import get_active_views
from tekla_mcp_server.tekla.model_object import (
    TeklaAssembly,
    TeklaPart,
    wrap_model_objects,
)
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.utils import log_function_call


@log_function_call
def tool_draw_elements_labels(selected_objects: ModelObjectEnumerator, label: ElementLabel, custom_label: str | None = None) -> dict[str, Any]:
    """
    Draws labels for the given Tekla model objects using the GraphicsDrawer.

    Args:
        selected_objects: Enumerator of selected objects
        label: ElementLabel type to draw
        custom_label: Custom label template string (required if label is CUSTOM)
    """
    resolved_label = None
    unit = None
    resolution_errors: list[dict[str, Any]] = []
    skip_custom_label = False

    if label == ElementLabel.CUSTOM and custom_label:
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
        if label == ElementLabel.CUSTOM:
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
                    ElementLabel.WEIGHT: f"{selected_object.weight[0]:.1f} kg",
                }
                text = assembly_labels.get(label, ElementLabel.NAME)
            elif isinstance(selected_object, TeklaPart):
                part_labels = {
                    ElementLabel.POSITION: selected_object.position,
                    ElementLabel.GUID: selected_object.guid,
                    ElementLabel.NAME: selected_object.name,
                    ElementLabel.PROFILE: selected_object.profile,
                    ElementLabel.MATERIAL: selected_object.material,
                    ElementLabel.FINISH: selected_object.finish,
                    ElementLabel.WEIGHT: f"{selected_object.weight[0]:.1f} kg",
                    ElementLabel.CLASS: selected_object.tekla_class,
                }
                text = part_labels.get(label, ElementLabel.NAME)
            else:
                continue
        if drawer.DrawText(selected_object.cog, text, Color(*color_black)):
            drawn_labels += 1
        processed_elements += 1
    logger.info("Drawn '%s' labels on %s elements", label.value, drawn_labels)
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


@log_function_call
def tool_zoom_to_selection(selected_objects: ModelObjectEnumerator) -> dict[str, Any]:
    """
    Zooms the Tekla view to the provided model objects.

    Args:
        selected_objects: Enumerator of selected objects to zoom to
    """
    processed_elements = 0

    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")

    for selected_object in selected_objects:
        solid = selected_object.GetSolid()
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


@log_function_call
def tool_redraw_view() -> dict[str, Any]:
    """
    Redraws the currently active view in Tekla.
    """
    views = get_active_views()
    views_redrawn = 0

    for view in views:
        if ViewHandler.RedrawView(view):
            views_redrawn += 1

    logger.info("Redrawn %d active views", len(views))
    return {"status": "success", "views_redrawn": views_redrawn, "total_views": len(views)}


@log_function_call
def tool_apply_view_filter(filter_name: str) -> dict[str, Any]:
    """
    Applies a view filter to all visible views in Tekla.

    Args:
        filter_name: Name of the view filter to apply
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


@log_function_call
def tool_show_only_selected(selected_objects: ModelObjectEnumerator) -> dict[str, Any]:
    """
    Updates the Tekla view to show only the currently selected model objects.

    Args:
        selected_objects: Enumerator of selected objects to show
    """
    Operation.ShowOnlySelected(Operation.UnselectedModeEnum.Hidden)
    logger.info("Hidden all the elements except the selected ones")
    return {
        "status": "success",
        "selected_elements": selected_objects.GetSize(),
    }


@log_function_call
def tool_hide_selected(selected_objects: ModelObjectEnumerator) -> dict[str, Any]:
    """
    Hides selected elements in the Tekla view using ModelObjectVisualization.
    Works with both parts and assemblies.

    Args:
        selected_objects: Enumerator of selected objects to hide
    """
    objects_to_hide = []

    for obj in wrap_model_objects(selected_objects):
        if isinstance(obj, TeklaAssembly):
            objects_to_hide.extend(obj.get_all_children())
        elif isinstance(obj, TeklaPart):
            objects_to_hide.extend(obj.get_all_children(include_all=False))

    tekla_list = List[ModelObject]()
    for model_object in objects_to_hide:
        tekla_list.Add(model_object)
    ModelObjectVisualization.SetTransparency(tekla_list, TemporaryTransparency.HIDDEN)

    return {"status": "success", "hidden_elements": len(objects_to_hide)}


@log_function_call
def tool_color_selected(selected_objects: ModelObjectEnumerator, red: int, green: int, blue: int) -> dict[str, Any]:
    """
    Colors selected elements in the Tekla view using ModelObjectVisualization.
    Works with both parts and assemblies.

    Args:
        selected_objects: Enumerator of selected objects to color
        red: Red component of RGB color (0-255)
        green: Green component of RGB color (0-255)
        blue: Blue component of RGB color (0-255)
    """
    objects_to_color = []

    for obj in wrap_model_objects(selected_objects):
        if isinstance(obj, TeklaAssembly):
            objects_to_color.extend(obj.get_all_children())
        elif isinstance(obj, TeklaPart):
            objects_to_color.extend(obj.get_all_children(include_all=False))

    tekla_list = List[ModelObject]()
    for model_object in objects_to_color:
        tekla_list.Add(model_object)
    color = Color(red / 255.0, green / 255.0, blue / 255.0)
    ModelObjectVisualization.SetTemporaryState(tekla_list, color)

    return {"status": "success", "colored_elements": len(objects_to_color)}
