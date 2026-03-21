"""
Info tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.tools.info import tool_check_tekla_connection
from tekla_mcp_server.utils import log_mcp_tool_call


info_provider = LocalProvider()


@info_provider.tool()
@log_mcp_tool_call
def check_tekla_connection():
    """
    Check Tekla connection status.

    ## INPUT
    - No additional parameters required.

    ## OUTPUT
    - Returns connection status with fields:
      - connected: boolean
      - model_path: str | null
      - message: str
    """
    return tool_check_tekla_connection()
