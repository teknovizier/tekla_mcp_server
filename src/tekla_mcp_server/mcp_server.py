"""
MCP Server for Tekla

This server facilitates interaction with Tekla Structures, allowing users to
speed-up modeling processes.
"""

import json

from fastmcp import FastMCP
from fastmcp.resources import ResourceResult, ResourceContent
from fastmcp.server.transforms import ResourcesAsTools

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import get_base_components, get_macros
from tekla_mcp_server.providers import (
    selection_provider,
    view_provider,
    properties_provider,
    operations_provider,
    components_provider,
)


mcp = FastMCP("Tekla MCP Server")


@mcp.resource("component://schema")
def get_component_list() -> ResourceResult:
    """
    Returns mapping of Tekla component names to config keys.

    Use this to find the config key for a component, then call
    component://schema/{component_key} to get the property schema.
    """
    data = {comp.get("tekla_name"): key for key, comp in get_base_components().items() if comp.get("tekla_name")}
    return ResourceResult(contents=[ResourceContent(content=json.dumps(data), mime_type="application/json")])


@mcp.resource("component://schema/{component_key}")
def get_component_schema(component_key: str) -> ResourceResult:
    """
    Returns the custom_properties schema for a specific component.
    """
    component = get_base_components().get(component_key)
    if component:
        custom_props = component.get("custom_properties", {})
        return ResourceResult(contents=[ResourceContent(content=json.dumps(custom_props), mime_type="application/json")])
    return ResourceResult(contents=[])


@mcp.resource("macro://list")
def get_macro_list() -> ResourceResult:
    """
    Returns a list of available Tekla macros from configured directories.
    """
    return ResourceResult(contents=[ResourceContent(content=json.dumps(get_macros()), mime_type="application/json")])


@mcp.resource("info://connection_status")
def get_connection_status() -> ResourceResult:
    """
    Returns the current Tekla connection status.

    ## RESPONSE
    - connected: boolean
    - model_path: str | null
    - message: str
    """
    from tekla_mcp_server.tekla.model import TeklaModel

    try:
        model = TeklaModel()
        return ResourceResult(
            contents=[
                ResourceContent(
                    content=json.dumps(
                        {
                            "connected": True,
                            "model_path": model.model.GetInfo().ModelPath,
                            "message": "Connected to Tekla model",
                        }
                    ),
                    mime_type="application/json",
                )
            ]
        )
    except ConnectionError as e:
        return ResourceResult(
            contents=[
                ResourceContent(
                    content=json.dumps({"connected": False, "model_path": None, "message": str(e)}),
                    mime_type="application/json",
                )
            ]
        )


# Add all providers to the MCP server
mcp.add_provider(selection_provider)
mcp.add_provider(view_provider)
mcp.add_provider(properties_provider)
mcp.add_provider(operations_provider)
mcp.add_provider(components_provider)


# Run the MCP server locally
if __name__ == "__main__":
    from tekla_mcp_server.embeddings import is_embeddings_enabled

    if is_embeddings_enabled():
        from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser

        logger.info("Pre-loading embeddings at startup...")
        TemplateAttributeParser.preload()
        logger.info("Embeddings ready")

    mcp.add_transform(ResourcesAsTools(mcp))

    mcp.run()
