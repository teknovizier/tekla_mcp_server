"""
Selection tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.models import (
    ElementTypeModel,
    SelectionModeModel,
    ElementType,
)
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tools.selection import (
    tool_select_elements_by_filter,
    tool_select_elements_by_filter_name,
    tool_select_elements_by_guid,
    tool_select_elements_assemblies_or_main_parts,
)
from tekla_mcp_server.utils import log_mcp_tool_call


selection_provider = LocalProvider()


@selection_provider.tool()
@log_mcp_tool_call
def select_elements_by_filter(
    element_type: str | ElementType | None = None,
    tekla_classes: int | list[int] | None = None,
    standard_string_filters: dict[str, Any] | None = None,
    custom_string_filters: dict[str, Any] | None = None,
    custom_numeric_filters: dict[str, Any] | None = None,
    combine_with: str = "AND",
) -> dict[str, Any]:
    """
    Selects elements in the Tekla model using standard properties,
    custom attributes and numeric ranges.

    ## INPUT
    element_type: Named element type (string).
        Valid values: "Wall", "Steel Beam", "Column", "Beam", etc.
        Use tekla_classes for numeric class filtering.

    tekla_classes: Tekla class number(s) as integer(s).
        Valid values: 1 (Wall), 8 (Sandwich Wall), 100 (Steel Beam), etc.
        Can be a single int or list of ints.

    standard_string_filters: Dict of standard Tekla properties to filter options.
        Valid keys: name, profile, material, finish, phase

    custom_string_filters: Dict of custom attribute names to StringFilterOption.
        Use for string-type template attributes.

    custom_numeric_filters: Dict of custom property names to NumericFilterOption.
        Use for numeric-type template attributes (e.g., WEIGHT).
        Do not use for Tekla built-in properties like "Class" - use element_type instead.

    combine_with: How to combine filter groups - "AND" (default) or "OR".
        - "AND": element matches ALL filter groups
        - "OR": element matches ANY filter group

    StringFilterOption structure:
        Single condition: {"conditions": {"match_type": "Contains", "value": "beam"}}
        Multiple conditions: {"conditions": [
            {"match_type": "Is Equal", "value": "beam1"},
            {"match_type": "Is Equal", "value": "beam2"}
        ], "logic": "OR"}  # or "AND"

    Valid match types for string filters:
        - `Is Equal`: Exact match
        - `Is Not Equal`: Exact mismatch
        - `Contains`: Substring match
        - `Not Contains`: Not contains
        - `Starts With`: Starts with substring
        - `Not Starts With`: Does not start with substring
        - `Ends With`: Ends with substring
        - `Not Ends With`: Does not end with substring

    NumericFilterOption structure:
        Single condition: {"conditions": {"match_type": "Greater Than", "value": 2000}}
        Multiple conditions: {"conditions": [
            {"match_type": "Greater Than", "value": 3000},
            {"match_type": "Smaller Than", "value": 5000}
        ], "logic": "AND"}  # or "OR"

    Valid match types for numeric filters:
        - `Is Equal`: Exact match
        - `Is Not Equal`: Not equal
        - `Smaller Than`: Less than
        - `Smaller Or Equal`: Less than or equal
        - `Greater Than`: Greater than
        - `Greater Or Equal`: Greater than or equal

    ### EXAMPLES
    # NAME = "Wall" OR PHASE = "2"
    {
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Is Equal", "value": "Wall"}},
            "phase": {"conditions": {"match_type": "Is Equal", "value": "2"}}
        },
        "combine_with": "OR"
    }

    # element_type = Wall AND (name = "beam" OR profile = "200*600")
    {
        "element_type": "Wall",
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Is Equal", "value": "beam"}},
            "profile": {"conditions": {"match_type": "Is Equal", "value": "200*600"}}
        },
        "combine_with": "OR"
    }

    # Elements in class 1 (Wall) with name ending in "1601"
    {
        "tekla_classes": 1,
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Ends With", "value": "1601"}}
        }
    }

    # Multiple classes: Sandwich Wall (8) and Wall (1)
    {
        "tekla_classes": [8, 1],
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Contains", "value": "test"}}
        }
    }

    At least one filter must be provided.
    """
    tekla_model = TeklaModel()

    if isinstance(element_type, str):
        element_type = ElementTypeModel(value=element_type).to_enum()
    elif element_type is not None and not isinstance(element_type, ElementType):
        raise ValueError("element_type must be a string (e.g., 'Wall', 'Steel Beam') or ElementType. Use tekla_classes for numeric class filtering.")

    return tool_select_elements_by_filter(
        model=tekla_model,
        element_type=element_type,
        tekla_classes=tekla_classes,
        standard_string_filters=standard_string_filters,
        custom_string_filters=custom_string_filters,
        custom_numeric_filters=custom_numeric_filters,
        combine_with=combine_with,
    )


@selection_provider.tool()
@log_mcp_tool_call
def select_elements_by_filter_name(filter_name: str) -> dict[str, Any]:
    """
    Selects elements applying an existing Tekla filter.

    ## INPUT
    - `filter_name` [Required]: Name of the Tekla filter to apply
    """
    tekla_model = TeklaModel()
    return tool_select_elements_by_filter_name(tekla_model, filter_name)


@selection_provider.tool()
@log_mcp_tool_call
def select_elements_by_guid(guids: list[str]) -> dict[str, Any]:
    """
    Selects elements by their GUID.

    ## INPUT
    - `guids` [Required]: List of GUIDs to select
    """
    tekla_model = TeklaModel()
    return tool_select_elements_by_guid(tekla_model, guids)


@selection_provider.tool()
@log_mcp_tool_call
def select_elements_assemblies_or_main_parts(mode: str) -> dict[str, Any]:
    """
    Selects assemblies or main parts for the selected elements.

    ## INPUT
    - `mode` [Required]: Selection mode

    ## VALID VALUES
    - `mode`: Assembly, Main Part
    """
    selected_objects = TeklaModel().get_selected_objects()
    mode_enum = SelectionModeModel(value=mode).to_enum()
    return tool_select_elements_assemblies_or_main_parts(selected_objects, mode_enum)
