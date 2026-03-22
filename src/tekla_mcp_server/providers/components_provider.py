"""
Components tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.models import BaseComponent, LiftingAnchorsComponent
from tekla_mcp_server.tools.components import (
    manage_components_on_selected_objects,
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
        if component_name == "Lifting Anchor":
            component: BaseComponent = LiftingAnchorsComponent(properties_set=properties_set, custom_properties=custom_properties)
        else:
            component = BaseComponent(name=component_name, properties_set=properties_set, custom_properties=custom_properties)
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
    if component_name == "Lifting Anchor":
        component: BaseComponent = LiftingAnchorsComponent()
    else:
        component = BaseComponent(name=component_name)
    return manage_components_on_selected_objects(tool_remove_components, component)
