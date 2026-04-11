"""
MCP Server for Tekla

This server facilitates interaction with Tekla Structures, allowing users to
speed-up modeling processes.
"""

from fastmcp import FastMCP
from fastmcp.server.transforms import ResourcesAsTools

from tekla_mcp_server.init import logger
from tekla_mcp_server.providers import (
    resources_provider,
    selection_provider,
    view_provider,
    properties_provider,
    operations_provider,
    components_provider,
    drawings_provider,
    modeling_provider,
)


mcp = FastMCP("Tekla MCP Server")


# Add all providers to the MCP server
mcp.add_provider(resources_provider)

mcp.add_provider(selection_provider)
mcp.add_provider(view_provider)
mcp.add_provider(properties_provider)
mcp.add_provider(operations_provider)
mcp.add_provider(components_provider)
mcp.add_provider(drawings_provider)
mcp.add_provider(modeling_provider)


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
