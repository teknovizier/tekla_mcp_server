"""
MCP Server for Tekla

This server facilitates interaction with Tekla Structures, allowing users to
speed-up modeling processes.
"""

from typing import Any
from collections.abc import Callable

from fastmcp import FastMCP

from models import (
    SelectionModeModel,
    UDASetModeModel,
    StringMatchTypeModel,
    ElementTypeModel,
    ElementLabelModel,
    ElementType,
    ComponentType,
    BaseComponent,
    LiftingAnchorsComponent,
)

from tools import (
    process_detail_or_component,
    process_seam_or_connection,
    tool_put_components,
    tool_remove_components,
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
def put_components(component_name: str, attributes_set: str | None = None, custom_attributes: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """
    Inserts Tekla components into the selected objects, using the given
    component name and an optional custom attributes.

    Supported standard components:
    - `Lifting Anchor`

    Args:
        component_name: The name of the Tekla component
        attributes_set: The name of the Tekla component attributes set to use
        custom_attributes: Custom attributes to apply to the component (dict or JSON string)
    """

    # Create appropriate component type based on name
    if component_name == "Lifting Anchor":
        component: BaseComponent = LiftingAnchorsComponent(attributes_set=attributes_set, custom_attributes=custom_attributes)
    else:
        component = BaseComponent(name=component_name, attributes_set=attributes_set, custom_attributes=custom_attributes)
    return manage_components_on_selected_objects(tool_put_components, component)


@mcp.tool()
def remove_components(component_name: str) -> dict[str, Any]:
    """
    Removes Tekla components from selected objects.

    Supported standard components:
    - `Lifting Anchor`

    Args:
        component_name: The name of the Tekla component
    """

    # Create appropriate component type based on name
    if component_name == "Lifting Anchor":
        component: BaseComponent = LiftingAnchorsComponent()
    else:
        component = BaseComponent(name=component_name)
    return manage_components_on_selected_objects(tool_remove_components, component)


@mcp.tool()
@log_mcp_tool_call
def select_elements_by_filter(
    element_type: str | int | list[int] | ElementType | None = None,
    name: str | None = None,
    name_match_type: str = "Is Equal",
    profile: str | None = None,
    profile_match_type: str = "Is Equal",
    material: str | None = None,
    material_match_type: str = "Is Equal",
    finish: str | None = None,
    finish_match_type: str = "Is Equal",
    phase: str | None = None,
    phase_match_type: str = "Is Equal",
) -> dict[str, Any]:
    """
    Selects elements based on their type or Tekla class, name, profile, material, finish, phase and matching criteria.

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
    - `Is Equal`: Checks for exact match.
    - `Is Not Equal`: Checks for exact mismatch.
    - `Contains`: Checks if one string is a substring of another.
    - `Not Contains`: Checks if one string is not a substring of another.
    - `Starts With`: Checks if a string starts with a specified substring.
    - `Not Starts With`: Checks if a string does not start with a specified substring.
    - `Ends With`: Checks if a string ends with a specified substring.
    - `Not Ends With`: Checks if a string does not end with a specified substring.
    """

    tekla_model = TeklaModel()

    if isinstance(element_type, str):
        element_type = ElementTypeModel(value=element_type).to_enum()

    name_match_type_enum = StringMatchTypeModel(value=name_match_type).to_enum()
    profile_match_type_enum = StringMatchTypeModel(value=profile_match_type).to_enum()
    material_match_type_enum = StringMatchTypeModel(value=material_match_type).to_enum()
    finish_match_type_enum = StringMatchTypeModel(value=finish_match_type).to_enum()
    phase_match_type_enum = StringMatchTypeModel(value=phase_match_type).to_enum()
    return tool_select_elements_by_filter(
        tekla_model,
        element_type,
        name,
        name_match_type_enum,
        profile,
        profile_match_type_enum,
        material,
        material_match_type_enum,
        finish,
        finish_match_type_enum,
        phase,
        phase_match_type_enum,
    )


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
def draw_elements_labels(label: str | None = None, custom_label: str | None = None) -> dict[str, Any]:
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
def get_elements_properties(custom_props_definitions: list[str] | None = None):
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
