"""
MCP Server for Tekla

This server facilitates interaction with Tekla Structures, allowing users to
speed-up modeling processes.
"""

from fastmcp import FastMCP
from fastmcp.server.transforms import ResourcesAsTools, Transform

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import load_dlls, logger
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


class ReadOnlyToolFilter(Transform):
    """Shows only tools marked as read-only to the LLM.

    A tool with no annotations (or readOnlyHint unset) is hidden, so a
    tool that someone forgets to annotate never silently leaks into read-only mode.
    """

    async def list_tools(self, tools):
        return [t for t in tools if t.annotations and t.annotations.readOnlyHint]


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
    if not load_dlls():
        logger.error("Not all Tekla DLLs were loaded. The server may not function correctly.")

    from tekla_mcp_server.embeddings import is_embeddings_enabled, check_embeddings_ready

    if not is_embeddings_enabled():
        logger.info("Embeddings are disabled")
    else:
        try:
            if check_embeddings_ready():
                from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser

                logger.info("Pre-loading embeddings at startup...")
                TemplateAttributeParser.preload()
                logger.info("Embeddings ready")
        except (ImportError, ValueError) as e:
            logger.warning("Embeddings validation failed: %s. Continuing without embeddings", e)

    if get_config().read_only:
        mcp.add_transform(ReadOnlyToolFilter())
        logger.info("Read-only mode: only read-only tools shown")

    disabled = get_config().excluded_tags
    if disabled:
        mcp.disable(tags=disabled)
        logger.info("Disabled tools with tags: %s", disabled)

    mcp.add_transform(ResourcesAsTools(mcp))

    mcp.run()
