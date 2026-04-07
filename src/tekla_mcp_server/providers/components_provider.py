"""
Components tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.models import BaseComponent
from tekla_mcp_server.tools.components import (
    manage_components_on_selected_objects,
    tool_get_components,
    tool_modify_components,
    tool_put_components,
    tool_remove_components,
)
from tekla_mcp_server.utils import log_mcp_tool_call


components_provider = LocalProvider()


@components_provider.tool()
@log_mcp_tool_call
def put_components(
    component_name: str,
    properties_set: str | None = None,
    custom_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Inserts Tekla components into the selected objects.

    ## INPUT
    - `component_name` [Required]: The Tekla name of the component (e.g., "Lifting Anchor", "Mesh Bars")
    - `properties_set` [Optional]: The name of the Tekla component properties set to use (standard by default)
    - `custom_properties` [Optional]: Custom properties to apply to the component (dict)

    ## INSTRUCTIONS
    - First read `component://schema` to discover available components.
    - Then read `component://schema/{component_key}` to get custom properties for a specific component.
    - Use Tekla config keys (e.g., `SpacBarsBottPri`, `BottGradePri`) as property names, NOT user-friendly descriptions.
    - Example: For "Mesh Bars", read the schema to get: `SpacBarsBottPri` for "bottom primary bars spacing", `BottGradePri` for "bottom primary bars reinforcement grade".
    """
    try:
        component: BaseComponent = BaseComponent(name=component_name, properties_set=properties_set, custom_properties=custom_properties)
    except ValueError as e:
        return {"status": "error", "message": "Invalid custom_properties", "errors": str(e)}

    return manage_components_on_selected_objects(tool_put_components, component)


@components_provider.tool()
@log_mcp_tool_call
def remove_components(component_name: str) -> dict[str, Any]:
    """
    Removes Tekla components from selected objects.

    ## INPUT
    - `component_name` [Required]: The Tekla name of the component (e.g., "Lifting Anchor", "Mesh Bars")
    """
    component: BaseComponent = BaseComponent(name=component_name)
    return manage_components_on_selected_objects(tool_remove_components, component)


@components_provider.tool()
@log_mcp_tool_call
def get_components() -> dict[str, Any]:
    """
    Gets all components attached to the currently selected elements.

    Returns component information including:
    - Component name and number
    - Whether the component is supported by config
    - Full schema with descriptions and types (if supported)
    - Actual attribute values from the component instance
    """
    return tool_get_components()


@components_provider.tool()
@log_mcp_tool_call
def modify_components(
    component_name: str,
    custom_properties: dict[str, Any],
) -> dict[str, Any]:
    """
    Modifies attributes of existing components on selected elements.

    ## INPUT
    - `component_name` [Required]: The Tekla name of the component (e.g., "Lifting Anchor")
    - `custom_properties` [Required]: Properties to update (dict with Tekla config keys and new values)

    ## INSTRUCTIONS
    - First call `get_components` to see current component values
    - Then call this tool with only the properties the user wants to change
    - Use Tekla config keys (e.g., `RecessLength`, `RecessHeight`), NOT user-friendly descriptions
    - Only properties in `custom_properties` will be modified; all others remain unchanged
    """
    try:
        component: BaseComponent = BaseComponent(name=component_name, custom_properties=custom_properties)
    except ValueError as e:
        return {"status": "error", "message": "Invalid custom_properties", "errors": str(e)}

    return manage_components_on_selected_objects(tool_modify_components, component)
