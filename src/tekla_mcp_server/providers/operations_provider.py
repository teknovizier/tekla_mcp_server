"""
Operations tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tools.operations import (
    tool_cut_elements_with_zero_class_parts,
    tool_convert_cut_parts_to_real_parts,
    tool_run_macro,
)
from tekla_mcp_server.utils import log_mcp_tool_call


operations_provider = LocalProvider()


@operations_provider.tool()
@log_mcp_tool_call
def cut_elements_with_zero_class_parts(delete_cutting_parts: bool = False) -> dict[str, Any]:
    """
    Performs boolean cuts on selected model objects using parts in class 0.

    ## INPUT
    - `delete_cutting_parts` [Optional]: If True, removes cutting parts after cuts are applied (default: False)
    """
    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    return tool_cut_elements_with_zero_class_parts(tekla_model, selected_objects, delete_cutting_parts)


@operations_provider.tool()
@log_mcp_tool_call
def convert_cut_parts_to_real_parts() -> dict[str, Any]:
    """
    Finds boolean parts and inserts them as real model objects.

    ## INPUT
    - No additional parameters required.
    """
    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    return tool_convert_cut_parts_to_real_parts(tekla_model, selected_objects)


@operations_provider.tool()
@log_mcp_tool_call
def run_macro(macro_name: str) -> dict[str, Any]:
    """
    Runs a Tekla macro with the specified name.

    ## INPUT
    - `macro_name` [Required]: Name of the macro file to run (e.g., "MyMacro.cs")

    ## AVAILABLE MACROS
    Use the `macro://list` resource to get a list of available macros.

    ## OUTPUT
    Returns status indicating whether the macro ran successfully.
    """
    return tool_run_macro(macro_name)
