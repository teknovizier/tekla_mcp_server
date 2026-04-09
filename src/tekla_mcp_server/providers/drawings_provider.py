"""
Drawing tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.models import DrawingTypeModel, StringFilterOption
from tekla_mcp_server.tools.drawing import tool_get_drawings, tool_get_drawing_properties
from tekla_mcp_server.utils import log_mcp_tool_call


drawings_provider = LocalProvider()


@drawings_provider.tool()
@log_mcp_tool_call
def get_drawings(
    drawing_type: str | None = None,
    name_filter: dict[str, Any] | StringFilterOption | None = None,
    mark_filter: dict[str, Any] | StringFilterOption | None = None,
    title1_filter: dict[str, Any] | StringFilterOption | None = None,
    title2_filter: dict[str, Any] | StringFilterOption | None = None,
    title3_filter: dict[str, Any] | StringFilterOption | None = None,
) -> dict[str, Any]:
    """
    Get drawings from Tekla model with optional filtering.

    ## INPUT
    - `drawing_type` [Optional]: Filter by drawing type.
        Valid values: GA, Assembly, SinglePart, CastUnit, MultiDrawing, Unknown

    - `name_filter` [Optional]: Filter by drawing name using StringFilterOption.
        Example: {"conditions": {"match_type": "Contains", "value": "floor"}}

    - `mark_filter` [Optional]: Filter by drawing mark using StringFilterOption.
    - `title1_filter` [Optional]: Filter by title1 using StringFilterOption.
    - `title2_filter` [Optional]: Filter by title2 using StringFilterOption.
    - `title3_filter` [Optional]: Filter by title3 using StringFilterOption.

    ## OUTPUT
    Returns a dictionary with:
    - status: "success", "warning", or "error"
    - matched_count: Number of drawings that matched the filter
    - marks: List of drawing marks

    ## EXAMPLES
    # Get all CastUnit drawings
    {"drawing_type": "CastUnit"}

    # Get drawings with "floor" in name
    {
        "name_filter": {
            "conditions": {"match_type": "Contains", "value": "floor"}
        }
    }

    # Get drawings with mark starting with "HCS" (multiple conditions)
    {
        "mark_filter": {
            "conditions": [
                {"match_type": "Starts With", "value": "HCS"},
                {"match_type": "Starts With", "value": "HCS"}
            ],
            "logic": "OR"
        }
    }
    """
    drawing_type_enum = DrawingTypeModel(value=drawing_type).to_enum() if drawing_type else None
    return tool_get_drawings(
        drawing_type=drawing_type_enum,
        name_filter=name_filter,
        mark_filter=mark_filter,
        title1_filter=title1_filter,
        title2_filter=title2_filter,
        title3_filter=title3_filter,
    )


@drawings_provider.tool()
@log_mcp_tool_call
def get_drawing_properties(
    marks: list[str] | None = None,
) -> dict[str, Any]:
    """
    Get properties of drawings by their marks.

    ## INPUT
    - `marks` [Optional]: List of drawing marks to get properties for.
      If not provided, gets properties of currently selected drawings in Tekla.

    ## OUTPUT
    - Table format only; first row = headers, no JSON or extra text.
    - Leftmost "No" column with sequential row numbers starting from 1.

    ### DEFAULT COLUMNS
    - Type, Mark, Name, Title1, Title2, Title3, CreationDate, ModificationDate, IsFrozen, IsLocked, IsReadyForIssue, IsIssued, IsIssuedButModified, IsMasterDrawing, IssuingDate, OutputDate, UpToDateStatus, CommitMessage

    ### GENERAL RULES
    - Each table must have a flat structure.
    - Each row represents one drawing.
    - Each column represents one property.

    ## RETURN KEYS
    - `status`: "success", "warning", or "error"
    - `selected_count`: Number of drawings
    - `drawings`: JSON array of drawing properties

    ## EXAMPLES
    # Get properties of selected drawings
    {}

    # Get properties of specific drawings
    {"marks": ["[HCS-1001 - 1]", "[HCS-1002 - 1]"]}
    """
    return tool_get_drawing_properties(marks=marks)
