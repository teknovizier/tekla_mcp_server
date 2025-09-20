"""
MCP Server for Tekla

This server facilitates interaction with Tekla Structures, allowing users to
speed-up modeling processes.
"""

from typing import Any
from collections.abc import Callable

from fastmcp import FastMCP

from init import logger
from models import (
    SelectionModeModel,
    UDASetModeModel,
    StringMatchTypeModel,
    ElementTypeModel,
    ElementLabelModel,
    ComponentType,
    BaseComponent,
    LiftingAnchors,
)

from tools import (
    process_detail_or_component,
    process_seam_or_connection,
    tool_put_components,
    tool_remove_components,
    tool_put_wall_lifting_anchors,
    tool_remove_wall_lifting_anchors,
    tool_select_elements_by_filter,
    tool_select_elements_by_filter_name,
    tool_select_elements_by_guid,
    tool_select_elements_assemblies_or_main_parts,
    tool_draw_elements_labels,
    tool_zoom_to_selection,
    tool_show_only_selected,
    tool_cut_elements_with_zero_class_parts,
    tool_convert_cut_parts_to_real_parts,
    tool_set_elements_udas,
    tool_get_all_elements_udas,
    tool_get_elements_properties,
)
from tekla_utils import TeklaModel
from utils import log_mcp_tool_call


mcp = FastMCP("Tekla MCP Server")


# Helper functions
@log_mcp_tool_call
def manage_components_on_selected_objects(callback: Callable[..., int], component: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """
    Applies a component operation to selected objects in the Tekla model using a specified callback function.
    """

    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    result = {}
    if component.component_type in [ComponentType.DETAIL, ComponentType.COMPONENT]:
        result = process_detail_or_component(selected_objects, callback, tekla_model, component, *args, **kwargs)
    elif component.component_type in [ComponentType.SEAM, ComponentType.CONNECTION]:
        result = process_seam_or_connection(selected_objects, callback, tekla_model, component, *args, **kwargs)
    else:
        pass  # For other types do nothing
    return result


# MCP tools
@mcp.tool()
def put_components(component_name: str, component_properties: str | None) -> dict[str, Any]:
    """
    Inserts Tekla components into the selected objects, using the given
    component name and an optional custom set of properties.
    """

    component = BaseComponent(name=component_name, properties=component_properties)
    return manage_components_on_selected_objects(tool_put_components, component)


@mcp.tool()
def remove_components(component_name: str) -> dict[str, Any]:
    """
    Removes Tekla components from selected objects.
    """

    component = BaseComponent(name=component_name)
    return manage_components_on_selected_objects(tool_remove_components, component)


@mcp.tool()
def put_wall_lifting_anchors(component: LiftingAnchors = LiftingAnchors()) -> dict[str, Any]:
    """
    Inserts wall lifting anchors into selected objects, optionally removing old anchors.
    """

    if component.remove_old_components:
        remove_wall_lifting_anchors()
    return manage_components_on_selected_objects(tool_put_wall_lifting_anchors, component)


@mcp.tool()
def remove_wall_lifting_anchors() -> dict[str, Any]:
    """
    Removes wall lifting anchors from selected objects.
    """

    component = LiftingAnchors()
    return manage_components_on_selected_objects(tool_remove_wall_lifting_anchors, component)


@mcp.tool()
@log_mcp_tool_call
def select_elements_by_filter(
    element_type: int | list[int] | str = None,
    name: str = None,
    name_match_type: str = "Is Equal",
    profile: str = None,
    profile_match_type: str = "Is Equal",
) -> dict[str, Any]:
    """
    Selects elements based on their type or Tekla class, name, and matching criteria.

    Valid concrete element types:
    - `Wall`
    - `Sandwich Wall`
    - `Stair Flight`
    - `Hollow Core Slab`
    - `Massive Slab`
    - `Column`
    - `Beam`
    - `Filigree Wall`
    - `Filigree Slab`
    - `Tribune`
    - `TT Slab`
    - `Balcony Slab`
    - `Stair Landing`
    - `Curved Stair`

    Valid steel element types:
    - `Steel Beam`
    - `Steel Column`
    - `Steel Truss`
    - `Steel Brace`

    Valid match types:
    - `IS_EQUAL`: Checks for exact match.
    - `IS_NOT_EQUAL`: Checks for exact mismatch.
    - `CONTAINS`: Checks if one string is a substring of another.
    - `NOT_CONTAINS`: Checks if one string is not a substring of another.
    - `STARTS_WITH`: Checks if a string starts with a specified substring.
    - `NOT_STARTS_WITH`: Checks if a string does not start with a specified substring.
    - `ENDS_WITH`: Checks if a string ends with a specified substring.
    - `NOT_ENDS_WITH`: Checks if a string does not end with a specified substring.
    """

    tekla_model = TeklaModel()

    if isinstance(element_type, str):
        element_type = ElementTypeModel(value=element_type).to_enum()

    name_match_type_enum = StringMatchTypeModel(value=name_match_type).to_enum()
    profile_match_type_enum = StringMatchTypeModel(value=profile_match_type).to_enum()
    return tool_select_elements_by_filter(tekla_model, element_type, name, name_match_type_enum, profile, profile_match_type_enum)


@mcp.tool()
@log_mcp_tool_call
def select_elements_by_filter_name(filter_name: str) -> dict[str, Any]:
    """
    Selects elements applying an existing Tekla filter.
    """

    tekla_model = TeklaModel()
    return tool_select_elements_by_filter_name(tekla_model, filter_name)


@mcp.tool()
@log_mcp_tool_call
def select_elements_by_guid(guids: list[str]) -> dict[str, Any]:
    """
    Selects elements by their GUID.
    """

    tekla_model = TeklaModel()
    return tool_select_elements_by_guid(tekla_model, guids)


@mcp.tool()
@log_mcp_tool_call
def select_elements_assemblies_or_main_parts(mode: str) -> dict[str, Any]:
    """
    Selects assemblies selected elements belong to.

    Valid modes:
    - `Assembly`
    - `Main Part`
    """

    selected_objects = TeklaModel().get_selected_objects()
    mode_enum = SelectionModeModel(value=mode).to_enum()
    return tool_select_elements_assemblies_or_main_parts(selected_objects, mode_enum)


@mcp.tool()
@log_mcp_tool_call
def draw_elements_labels(label: str = None, custom_label: str = None) -> dict[str, Any]:
    """
    Draws temporary labels in the Tekla model.

    Valid labels:
    - `Position`
    - `GUID`
    - `Name` (default)
    - `Profile`
    - `Material`
    - `Finish`
    - `Class`
    - `Weight`
    - `Custom` (requires `custom_label` to be set)
    """

    selected_objects = TeklaModel().get_selected_objects()
    label = label or "Name"
    label_enum = ElementLabelModel(value=label).to_enum()
    return tool_draw_elements_labels(selected_objects, label_enum, custom_label)


@mcp.tool()
@log_mcp_tool_call
def zoom_to_selection() -> dict[str, Any]:
    """
    Zooms the Tekla current view to fit the currently selected model objects.
    """

    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    return tool_zoom_to_selection(selected_objects)


@mcp.tool()
@log_mcp_tool_call
def show_only_selected() -> dict[str, Any]:
    """
    Shows only the currently selected model objects in the Tekla current view, hiding all others.
    """

    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    return tool_show_only_selected(selected_objects)


@mcp.tool()
@log_mcp_tool_call
def cut_elements_with_zero_class_parts(delete_cutting_parts: bool = False) -> dict[str, Any]:
    """
    Performs boolean cuts on selected model objects using parts in class 0, with optional deletion of cutting parts.
    If `delete_cutting_parts` is set to True, the cutting parts used in the operation will be removed from the model after the cuts are applied.
    """

    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    return tool_cut_elements_with_zero_class_parts(tekla_model, selected_objects, delete_cutting_parts)


@mcp.tool()
@log_mcp_tool_call
def convert_cut_parts_to_real_parts() -> dict[str, Any]:
    """
    Finds boolean parts and inserts them as real model objects.
    """

    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    return tool_convert_cut_parts_to_real_parts(tekla_model, selected_objects)


@mcp.tool()
@log_mcp_tool_call
def set_elements_udas(udas: dict[str, Any], mode: str) -> dict[str, Any]:
    """
    Finds boolean parts and inserts them as real model objects.

    Valid modes:
    - `Keep Existing Values`
    - `Overwrite Existing Values`
    """

    selected_objects = TeklaModel().get_selected_objects()
    mode_enum = UDASetModeModel(value=mode).to_enum()
    return tool_set_elements_udas(selected_objects, udas, mode_enum)


@mcp.tool()
@log_mcp_tool_call
def get_all_elements_udas() -> dict[str, Any]:
    """
    Retrieves all UDAs for the selected elements (assemblies or parts) in the Tekla model.

    The returned data to be presented in a Markdown table format, each row represents one element, with columns for:
    - Position
    - GUID
    - Any available UDAs

    Each UDA is returned using its property name as the column header.
    If an attribute is missing, the corresponding cell to be left empty.
    """

    selected_objects = TeklaModel().get_selected_objects()
    return tool_get_all_elements_udas(selected_objects)


@mcp.tool()
@log_mcp_tool_call
def get_elements_properties(custom_props_definitions: list[str] = None):
    """
    Retrieves key properties for the selected elements (assemblies or parts) in the Tekla model.

    The returned data to be presented in a Markdown table format, each row represents one element, with columns for:
    - Position
    - GUID
    - For assemblies in `assemblies_list`: values are taken from the main part and labeled as:
        - Main Part Name
        - Main Part Profile
        - Main Part Material
        - Main Part Finish
        - Main Part Class
    - For parts in `parts_list`: values are labeled as:
        - Name
        - Profile
        - Material
        - Finish
        - Class
    - Weight (kg), rounded to one decimal place
    - Any available custom properties defined in `custom_props_definitions`

    Each custom property column header must include its unit in parentheses, if available. For example, if the property is "Area" and its unit is "m²", the column header should be "Area (m²)".
    If no unit is available, use just the property name.
    If a property fails to retrieve, display "N/A" in the corresponding cell.
    """

    selected_objects = TeklaModel().get_selected_objects()
    return tool_get_elements_properties(selected_objects, custom_props_definitions)


# Run the MCP server locally
if __name__ == "__main__":
    mcp.run()
