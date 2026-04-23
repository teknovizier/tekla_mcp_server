"""
Providers package for Tekla MCP server.

Uses LocalProvider to organize tools into modular components.
"""

from tekla_mcp_server.providers.resources_provider import resources_provider
from tekla_mcp_server.providers.selection_provider import selection_provider
from tekla_mcp_server.providers.view_provider import view_provider
from tekla_mcp_server.providers.properties_provider import properties_provider
from tekla_mcp_server.providers.operations_provider import operations_provider
from tekla_mcp_server.providers.components_provider import components_provider
from tekla_mcp_server.providers.drawings_provider import drawings_provider
from tekla_mcp_server.providers.modeling_provider import modeling_provider
from tekla_mcp_server.providers.ifc_provider import ifc_provider

__all__ = [
    "resources_provider",
    "selection_provider",
    "view_provider",
    "properties_provider",
    "operations_provider",
    "components_provider",
    "drawings_provider",
    "modeling_provider",
    "ifc_provider",
]
