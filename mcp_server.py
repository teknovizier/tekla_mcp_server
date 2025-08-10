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
    select_elements_by_guid,
    select_assemblies_or_main_parts,
    draw_names_on_elements,
    insert_boolean_parts_as_real_parts,
    set_udas_on_elements,
    get_assemblies_props,
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
    Selects specified elements based on their type or Tekla class, name, and matching criteria.

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

        name_match_type_object = StringMatchTypeModel(value=name_match_type)
        profile_match_type_object = StringMatchTypeModel(value=profile_match_type)
        return select_elements_by_filter(element_type, name, name_match_type_object.to_enum(), profile, profile_match_type_object.to_enum())

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
        mode_object = SelectionModeModel(value=mode)
        return select_assemblies_or_main_parts(selected_objects, mode_object.to_enum())

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def draw_elements_names() -> dict[str, Any]:
    """
    Draws temporary element names in the Tekla model.
    """
    try:
        selected_objects = TeklaModel().get_selected_objects()
        return draw_names_on_elements(selected_objects)

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
        mode_object = UDASetModeModel(value=mode)
        return set_udas_on_elements(selected_objects, udas, mode_object.to_enum())

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_assemblies_properties():
    """
    Retrieves key properties for the selected assemblies in the Tekla model.

    The returned data to be presented in a Markdown table format, each row represents one assembly, with columns for:
    - Assembly Position
    - GUID
    - Main Part Name
    - Profile
    - Material
    - Finish
    - Class
    - Weight, kg

    Weight rounded to one decimal place.
    """
    try:
        selected_objects = TeklaModel().get_selected_objects()
        return get_assemblies_props(selected_objects)

    except Exception as e:
        return {"status": "error", "message": str(e)}


# Run the MCP server locally
if __name__ == "__main__":
    mcp.run()
