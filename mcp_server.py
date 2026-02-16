"""
MCP Server for Tekla

This server facilitates interaction with Tekla Structures, allowing users to
speed-up modeling processes.
"""

from typing import Any

from fastmcp import FastMCP

from models import (
    SelectionModeModel,
    UDASetModeModel,
    StringMatchTypeModel,
    ElementTypeModel,
    ElementLabelModel,
    ElementType,
    BaseComponent,
    LiftingAnchorsComponent,
)

from tools import (
    manage_components_on_selected_objects,
    tool_put_components,
    tool_remove_components,
    tool_select_elements_by_filter,
    tool_select_elements_by_filter_name,
    tool_select_elements_by_guid,
    tool_select_elements_assemblies_or_main_parts,
    tool_draw_elements_labels,
    tool_zoom_to_selection,
    tool_show_only_selected,
    tool_hide_selected,
    tool_cut_elements_with_zero_class_parts,
    tool_convert_cut_parts_to_real_parts,
    tool_set_elements_udas,
    tool_get_all_elements_udas,
    tool_get_elements_properties,
    tool_get_elements_cut_parts,
)
from tekla_utils import TeklaModel
from utils import log_mcp_tool_call
from component_props_mapper import map_properties


mcp = FastMCP("Tekla MCP Server")


# MCP tools
@mcp.tool()
def check_tekla_connection() -> dict[str, Any]:
    """
    Check Tekla connection status.

    Returns:
        - connected: boolean - whether Tekla is connected
        - model_path: str - path to opened model (if any)
        - message: str - status message
    """
    try:
        tekla_model = TeklaModel()
        return {
            "connected": True,
            "model_path": tekla_model.model.GetInfo().ModelPath,
            "message": "Connected to Tekla",
        }
    except ConnectionError as e:
        return {"connected": False, "model_path": None, "message": str(e)}
    except Exception as e:
        return {"connected": False, "model_path": None, "message": f"Error: {e}"}


@mcp.tool()
def put_components(
    component_name: str,
    properties_set: str | None = None,
    custom_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Inserts Tekla components into the selected objects, using the given
    component name and an optional custom properties.

    Args:
        component_name: The name of the Tekla component
        properties_set: The name of the Tekla component properties set to use
        custom_properties: Custom properties to apply to the component (dict)
    """

    resolved_custom_properties = custom_properties
    unmapped_keys = []
    if custom_properties:
        mapped = map_properties(custom_properties, component_name)
        if mapped:
            unmapped_keys = mapped.pop("unmapped_keys", [])
            resolved_custom_properties = mapped

    if component_name == "Lifting Anchor":
        component: BaseComponent = LiftingAnchorsComponent(properties_set=properties_set, custom_properties=resolved_custom_properties)
    else:
        component = BaseComponent(name=component_name, properties_set=properties_set, custom_properties=resolved_custom_properties)
    return manage_components_on_selected_objects(tool_put_components, component, unmapped_keys)


@mcp.tool()
def remove_components(component_name: str) -> dict[str, Any]:
    """
    Removes Tekla components from selected objects.

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
    label_value = "Name" if label is None else label
    label_enum = ElementLabelModel(value=label_value).to_enum()
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
def hide_selected() -> dict[str, Any]:
    """
    Hides the selected elements in the Tekla view.
    Works with both parts and assemblies.
    """
    selected_objects = TeklaModel().get_selected_objects()
    return tool_hide_selected(selected_objects)


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
    Sets user-defined attributes (UDAs) on selected elements.

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
def get_elements_properties(custom_props_definitions: list[str] | None = None) -> dict[str, Any]:
    """
    Retrieve key properties for selected Tekla elements (assemblies or parts).

    ## INPUT
    - `custom_properties` [Optional]: List of user-friendly property names.

    ### BEHAVIOR
    - Extract properties not in default columns; split multi-property phrases into separate items.
    - Example: ["gross weight", "assembly top and bottom level", "length"] → ["gross weight", "assembly top level", "assembly bottom level", "length"]
    - Only resolved custom properties appear in the table; unresolved ones are mentioned after the table.

    ## OUTPUT
    - Table format only; first row = headers, no JSON or extra text.
    - Leftmost "No" column with sequential row numbers starting from 1.

    ### DEFAULT COLUMNS
    - Position, GUID
    - Assemblies: Main Part Name, Profile, Material, Finish, Class
    - Parts: Name, Profile, Material, Finish, Class
    - Weight (kg), rounded to 3 decimals

    ### CUSTOM PROPERTIES
    - Use backend-resolved names exactly; append units if provided.
    - Float values should be rounded to 3 decimals.
    - Missing values = "N/A".
    - Example: ASSEMBLY_TOP_LEVEL, ASSEMBLY_BOTTOM_LEVEL_UNFORMATTED, WEIGHT_GROSS (kg)
    """

    selected_objects = TeklaModel().get_selected_objects()
    return tool_get_elements_properties(selected_objects, custom_props_definitions)


@mcp.tool()
@log_mcp_tool_call
def get_elements_cut_parts() -> dict[str, Any]:
    """
    Finds all cut parts in the selected elements and returns a summary grouped by profile.

    The returned data to be presented in a Markdown table format, with columns for:
    - Profile: The profile string of the cut part
    - Count: The number of cut parts with that profile

    Also, show total number of cut parts found across all profiles and total number of elements that were processed.
    """

    selected_objects = TeklaModel().get_selected_objects()
    return tool_get_elements_cut_parts(selected_objects)


# Run the MCP server locally
if __name__ == "__main__":
    mcp.run()
