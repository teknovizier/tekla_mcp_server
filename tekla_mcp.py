"""
MCP Server for Tekla

This server facilitates interaction with Tekla Structures, allowing users to
speed-up modeling processes.
"""

from typing import Any, Callable, Union
from mcp.server.fastmcp import FastMCP


from models import (
    StringMatchType,
    PrecastElementType,
    ComponentType,
    LiftingAnchors,
    CustomDetailComponent,
)

from utils import (
    get_model_and_selected_objects,
    process_detail_or_component,
    process_seam_or_connection,
    insert_lifting_anchors,
    remove_lifting_anchors,
    remove_components,
    insert_custom_detail_component,
    select_elements_by_filter,
    get_selected_elements_as_assemblies,
    draw_names_on_elements,
    insert_boolean_parts_as_real_parts,
)


mcp = FastMCP("Tekla MCP Server")


# Helper functions
def manage_components_on_selected_objects(callback: Callable[..., int], component: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """
    Applies a component operation to selected objects in the Tekla model using a specified callback function.
    """
    try:
        model, selected_objects = get_model_and_selected_objects()
        c_counter = 0
        if component.component_type in [ComponentType.DETAIL, ComponentType.COMPONENT]:
            c_counter = process_detail_or_component(selected_objects, callback, model, component, *args, **kwargs)
        elif component.component_type in [ComponentType.SEAM, ComponentType.CONNECTION]:
            c_counter = process_seam_or_connection(selected_objects, callback, model, component, *args, **kwargs)
        else:
            pass  # For other types do nothing
        if c_counter:
            return {"status": "success", "component_amount": c_counter}
        else:
            return {"status": "error", "message": "no components processed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# MCP tools
@mcp.tool()
def put_wall_lifting_anchors(component: LiftingAnchors) -> dict[str, Any]:
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
def select_elements(element_type: Union[list[int], PrecastElementType] = None, name: str = None, name_match_type: StringMatchType = StringMatchType.IS_EQUAL) -> dict[str, Any]:
    """
    Selects specified elements based on their type or Tekla class, name, and matching criteria.
    """
    try:
        count = select_elements_by_filter(element_type, name, name_match_type)
        if count:
            return {"status": "success", "selected_elements": count}
        return {"status": "error", "message": "No elements have been selected."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def select_elements_assemblies() -> dict[str, Any]:
    """
    Selects assemblies selected elements belong to.
    """
    try:
        _, selected_objects = get_model_and_selected_objects()
        count = get_selected_elements_as_assemblies(selected_objects)
        if count:
            return {"status": "success", "selected_elements": count}
        else:
            return {"status": "error", "message": "No elements have been selected."}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def draw_elements_names() -> dict[str, Any]:
    """
    Draws temporary element names in the Tekla model.
    """
    try:
        _, selected_objects = get_model_and_selected_objects()
        count = draw_names_on_elements(selected_objects)
        if count:
            return {"status": "success", "selected_elements": count}
        return {"status": "error", "message": "No element names have been drawn."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def convert_cut_parts_to_real_parts() -> dict[str, Any]:
    """
    Finds boolean parts and inserts them as real model objects.
    """
    try:
        model, selected_objects = get_model_and_selected_objects()
        count = insert_boolean_parts_as_real_parts(model, selected_objects)
        if count:
            return {"status": "success", "inserted_parts": count}
        else:
            return {"status": "error", "message": "No cut parts have been created."}

    except Exception as e:
        return {"status": "error", "message": str(e)}


# Run the MCP server locally
if __name__ == "__main__":
    mcp.run()
