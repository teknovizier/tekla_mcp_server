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
    ComponentType,
    LiftingAnchors,
    CustomDetailComponent,
)

from tools import (
    process_detail_or_component,
    process_seam_or_connection,
    insert_lifting_anchors,
    remove_lifting_anchors,
    remove_components,
    insert_custom_detail_component,
    select_elements_by_filter,
    select_elements_by_filter_name,
    select_elements_by_guid,
    select_assemblies_or_main_parts,
    draw_labels_on_elements,
    zoom_to_selected_elements,
    show_only_selected_elements,
    insert_boolean_parts_as_real_parts,
    set_udas_on_elements,
    get_all_udas_for_elements,
    get_elements_props,
)
from tekla_utils import TeklaModel


mcp = FastMCP("Tekla MCP Server")


# Helper functions
def manage_components_on_selected_objects(callback: Callable[..., int], component: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """
    Applies a component operation to selected objects in the Tekla model using a specified callback function.
    """
    try:
        tekla_model = TeklaModel()
        selected_objects = tekla_model.get_selected_objects()
        result = {}
        if component.component_type in [ComponentType.DETAIL, ComponentType.COMPONENT]:
            result = process_detail_or_component(selected_objects, callback, tekla_model.model, component, *args, **kwargs)
        elif component.component_type in [ComponentType.SEAM, ComponentType.CONNECTION]:
            result = process_seam_or_connection(selected_objects, callback, tekla_model.model, component, *args, **kwargs)
        else:
            pass  # For other types do nothing
        return result

    except Exception as e:
        return {"status": "error", "message": str(e)}


# MCP tools
@mcp.tool()
def put_wall_lifting_anchors(component: LiftingAnchors = LiftingAnchors()) -> dict[str, Any]:
    """
    Inserts wall lifting anchors into selected objects, optionally removing old anchors.
    """
    if component.remove_old_components:
        remove_wall_lifting_anchors()
    return manage_components_on_selected_objects(insert_lifting_anchors, component)


@mcp.tool()
def remove_wall_lifting_anchors() -> dict[str, Any]:
    """
    Removes wall lifting anchors from selected objects.
    """
    component = LiftingAnchors()
    return manage_components_on_selected_objects(remove_lifting_anchors, component)


@mcp.tool()
def put_custom_detail_components(component_name: str) -> dict[str, Any]:
    """
    Inserts custom wall components into selected objects.
    """
    component = CustomDetailComponent(name=component_name)
    return manage_components_on_selected_objects(insert_custom_detail_component, component)


@mcp.tool()
def select_elements_using_filter(
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
    try:
        if isinstance(element_type, str):
            element_type = ElementTypeModel(value=element_type).to_enum()

        name_match_type_enum = StringMatchTypeModel(value=name_match_type).to_enum()
        profile_match_type_enum = StringMatchTypeModel(value=profile_match_type).to_enum()
        return select_elements_by_filter(element_type, name, name_match_type_enum, profile, profile_match_type_enum)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def select_elements_using_filter_name(filter_name: str) -> dict[str, Any]:
    """
    Selects elements applying an existing Tekla filter.
    """
    try:
        return select_elements_by_filter_name(filter_name)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def select_elements_using_guid(guids: list[str]) -> dict[str, Any]:
    """
    Selects elements by their GUID.
    """
    try:
        return select_elements_by_guid(guids)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def select_elements_assemblies_or_main_parts(mode: str) -> dict[str, Any]:
    """
    Selects assemblies selected elements belong to.

    Valid modes:
    - `Assembly`
    - `Main Part`
    """
    try:
        selected_objects = TeklaModel().get_selected_objects()
        mode_enum = SelectionModeModel(value=mode).to_enum()
        return select_assemblies_or_main_parts(selected_objects, mode_enum)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def draw_elements_labels(label: str = None) -> dict[str, Any]:
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
    """
    try:
        selected_objects = TeklaModel().get_selected_objects()
        label = label or "Name"
        label_enum = ElementLabelModel(value=label).to_enum()
        return draw_labels_on_elements(selected_objects, label_enum)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def zoom_to_selection() -> dict[str, Any]:
    """
    Zooms the Tekla current view to fit the currently selected model objects.
    """
    try:
        tekla_model = TeklaModel()
        selected_objects = tekla_model.get_selected_objects()
        return zoom_to_selected_elements(selected_objects)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def show_only_selected() -> dict[str, Any]:
    """
    Shows only the currently selected model objects in the Tekla current view, hiding all others.
    """
    try:
        tekla_model = TeklaModel()
        selected_objects = tekla_model.get_selected_objects()
        return show_only_selected_elements(selected_objects)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def convert_cut_parts_to_real_parts() -> dict[str, Any]:
    """
    Finds boolean parts and inserts them as real model objects.
    """
    try:
        tekla_model = TeklaModel()
        selected_objects = tekla_model.get_selected_objects()
        return insert_boolean_parts_as_real_parts(tekla_model.model, selected_objects)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def set_elements_udas(udas: dict[str, Any], mode: str) -> dict[str, Any]:
    """
    Finds boolean parts and inserts them as real model objects.

    Valid modes:
    - `Keep Existing Values`
    - `Overwrite Existing Values`
    """
    try:
        selected_objects = TeklaModel().get_selected_objects()
        mode_enum = UDASetModeModel(value=mode).to_enum()
        return set_udas_on_elements(selected_objects, udas, mode_enum)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
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
    try:
        selected_objects = TeklaModel().get_selected_objects()
        return get_all_udas_for_elements(selected_objects)

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
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
    try:
        selected_objects = TeklaModel().get_selected_objects()
        return get_elements_props(selected_objects, custom_props_definitions)

    except Exception as e:
        return {"status": "error", "message": str(e)}


# Run the MCP server locally
if __name__ == "__main__":
    mcp.run()
