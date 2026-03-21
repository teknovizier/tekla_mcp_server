"""
Properties tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.models import UDASetModeModel
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tools.properties import (
    tool_set_elements_udas,
    tool_get_elements_udas,
    tool_get_elements_properties,
    tool_get_elements_cut_parts,
    tool_compare_elements,
)
from tekla_mcp_server.utils import log_mcp_tool_call


properties_provider = LocalProvider()


@properties_provider.tool()
@log_mcp_tool_call
def set_elements_udas(udas: dict[str, Any], mode: str) -> dict[str, Any]:
    """
    Sets user-defined attributes (UDAs) on selected elements.

    ## INPUT
    - `udas` [Required]: Dictionary of attribute names and values to set
    - `mode` [Required]: How to handle existing values

    ## VALID VALUES
    - `mode`: Keep Existing Values, Overwrite Existing Values
    """
    selected_objects = TeklaModel().get_selected_objects()
    mode_enum = UDASetModeModel(value=mode).to_enum()
    return tool_set_elements_udas(selected_objects, udas, mode_enum)


@properties_provider.tool()
@log_mcp_tool_call
def get_elements_udas() -> dict[str, Any]:
    """
    Retrieve all user-defined attributes (UDAs) for selected Tekla elements (assemblies or parts).

    ## INPUT
    - No additional parameters required.

    ## BEHAVIOR
    - Extract all available UDAs for each selected element.
    - Each element is represented as one row in the output table.
    - Only UDAs that exist for at least one selected element should appear as columns.

    ## OUTPUT
    - Table format only; first row = headers, no JSON or extra text.
    - Leftmost "No" column with sequential row numbers starting from 1.

    ### DEFAULT COLUMNS
    - Position
    - GUID

    ### UDA COLUMNS
    - Each UDA appears as a separate column using its exact property name.
    - If a UDA value is missing for an element, the cell should be empty.
    """
    selected_objects = TeklaModel().get_selected_objects()
    return tool_get_elements_udas(selected_objects)


@properties_provider.tool()
@log_mcp_tool_call
def get_elements_properties(custom_props_definitions: list[str] | None = None) -> dict[str, Any]:
    """
    Retrieve key properties for selected Tekla elements (assemblies or parts).

    ## INPUT
    - `custom_props_definitions` [Optional]: List of user-friendly property names.

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


@properties_provider.tool()
@log_mcp_tool_call
def get_elements_cut_parts() -> dict[str, Any]:
    """
    Find all cut parts in the selected Tekla elements and return a summary grouped by profile.

    ## INPUT
    - No additional parameters required.

    ## OUTPUT
    - Table format only; first row = headers, no JSON or extra text.
    - Leftmost "No" column with sequential row numbers starting from 1.

    ### TABLE COLUMNS
    - Profile
    - Count

    ### SUMMARY
    - Show the total number of cut parts found across all profiles.
    - Show the total number of processed elements.
    """
    selected_objects = TeklaModel().get_selected_objects()
    return tool_get_elements_cut_parts(selected_objects)


@properties_provider.tool()
@log_mcp_tool_call
def compare_elements(ignore_numbering: bool = False) -> dict[str, Any]:
    """
    Compares two selected Tekla parts or assemblies and returns a human-readable summary of changes.

    ## INPUT
    - `ignore_numbering` [Optional]: If True, skips numbering check (default: False)

    ## RESPONSE FIELDS
    - `identical`: Boolean - True if elements are identical, False otherwise
    - `differences`: Only present when `identical=False`. Machine-readable diff format
    - `differences_summary`: Only present when `identical=False`. Human-readable list of differences
    - `part_a_raw`: Full snapshot of Part A (with guid/id) - use only when you need identifiers
    - `part_b_raw`: Full snapshot of Part B (with guid/id) - use only when you need identifiers

    ## INSTRUCTIONS
    1. Check `identical` field first
    2. If `identical=False`, use `differences_summary` for human-readable report
    3. Use `differences` for programmatic analysis if needed
    4. Use `part_a_raw`/`part_b_raw` only when you need guid/id identifiers

    ## WHAT TO IGNORE
    - `id` and `guid` fields - they are ALWAYS different (not actual differences)
    - Order of items in lists (cutparts, reinforcements, welds) - pre-sorted for comparison

    ## OUTPUT
    A human-readable summary listing only the actual differences between the two selected parts or assemblies.
    """
    selected_objects = TeklaModel().get_selected_objects()
    return tool_compare_elements(selected_objects, ignore_numbering)
