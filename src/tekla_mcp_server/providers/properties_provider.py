"""
Properties tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tools.properties import (
    tool_set_elements_properties,
    tool_get_elements_properties,
    tool_get_elements_cut_parts,
    tool_compare_elements,
)
from tekla_mcp_server.utils import log_mcp_tool_call


properties_provider = LocalProvider()


@properties_provider.tool()
@log_mcp_tool_call
def set_elements_properties(
    name: str | None = None,
    profile: str | None = None,
    material: str | None = None,
    tekla_class: str | None = None,
    finish: str | None = None,
    user_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Sets properties and user-defined attributes (UDAs) on selected Tekla elements (assemblies or parts).

    ## INPUT
    - `name` [Optional]: Part/Assembly name
    - `profile` [Optional]: Profile string (e.g., "3000*200", "HEA200")
    - `material` [Optional]: Material string (e.g., "C25/30", "S355J2")
    - `tekla_class` [Optional]: Tekla class (e.g., "1", "100", etc.)
    - `finish` [Optional]: Finish type
    - `user_properties` [Optional]: Dictionary of user-defined attribute names and values

    ## OUTPUT
    - `status`: "success" if any changes were made, "warning" if no changes
    - `selected_elements`: Total number of selected elements
    - `processed_elements`: Elements that were processed
    - `modified_elements`: Elements that were actually modified
    - `changes_applied`: Breakdown of changes by property type
    """
    selected_objects = TeklaModel().get_selected_objects()
    return tool_set_elements_properties(
        selected_objects,
        name=name,
        profile=profile,
        material=material,
        tekla_class=tekla_class,
        finish=finish,
        user_properties=user_properties,
    )


@properties_provider.tool()
@log_mcp_tool_call
def get_elements_properties(report_props_definitions: list[str] | None = None) -> dict[str, Any]:
    """
    Retrieve key properties for selected Tekla elements (assemblies or parts).

    ## INPUT
    - `report_props_definitions` [Optional]: List of user-friendly property names.

    ### BEHAVIOR
    - Extract properties not in default columns; split multi-property phrases into separate items.
    - Example: ["gross weight", "assembly top and bottom level", "length"] → ["gross weight", "assembly top level", "assembly bottom level", "length"]
    - Only resolved report properties appear in the table; unresolved ones are mentioned after the table.

    ## OUTPUT
    - Table format only; first row = headers, no JSON or extra text.
    - Leftmost "No" column with sequential row numbers starting from 1.
    - All data (including UDAs) MUST be presented in a single unified table.
    - Do NOT create separate tables for user properties or any other data.

    ### DEFAULT COLUMNS
    - Position, GUID
    - Assemblies:
        - Main Part Name*, Profile*, Material*, Finish*, Class*
        - These columns apply ONLY when the element is an assembly.
    - Parts:
        - Name*, Profile*, Material*, Finish*, Class*
        - These columns apply ONLY when the element is an individual part.
    - Properties marked with * are modifiable via set_elements_properties.

    ### USER PROPERTIES (UDAs)
    - UDAs MUST be included as additional columns in the SAME table.
    - Each UDA appears as a separate column using its exact property name.
    - Do NOT group, nest, or separate UDAs outside the main table.
    - If a UDA value is missing for an element, the cell should be empty.

    ### REPORT PROPERTIES
    - Include report properties as additional columns in the SAME table.
    - Use backend-resolved names exactly; append units if provided.
    - Float values should be rounded to 3 decimals.
    - Missing values must be shown as "N/A".
    - Example of property name: ASSEMBLY_TOP_LEVEL, ASSEMBLY_BOTTOM_LEVEL_UNFORMATTED, WEIGHT_GROSS (kg)

    ### GENERAL RULES
    - Maintain a single flat table structure at all times.
    - Each row represents one element.
    - Each column represents one property (default, UDA, or report).

    ## RETURN KEYS
    - `status`: "success", "partial" (if some errors occurred), or "error"
    - `assemblies_list`: JSON array of assembly properties
    - `parts_list`: JSON array of part properties
    - `resolution_errors`: List of errors when resolving property names
    - `extraction_errors`: List of errors when extracting properties from elements
    """
    selected_objects = TeklaModel().get_selected_objects()
    return tool_get_elements_properties(selected_objects, report_props_definitions)


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
