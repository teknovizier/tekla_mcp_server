"""
Drawing tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import DrawingTypeModel, StringFilterOption, StringMatchType
from tekla_mcp_server.utils import log_mcp_tool_call
from tekla_mcp_server.tekla.wrappers.drawing import wrap_drawings
from tekla_mcp_server.tekla.loader import DrawingHandler


drawings_provider = LocalProvider()


def _parse_filter(filter_option: Any) -> StringFilterOption | None:
    if isinstance(filter_option, dict):
        return StringFilterOption.model_validate(filter_option)
    return filter_option


def _matches_string_filter(value: str, filter_option: Any) -> bool:
    if not filter_option:
        return True

    conditions = filter_option.conditions
    if not isinstance(conditions, list):
        conditions = [conditions]

    logic = filter_option.logic or "AND"
    results = []

    for cond in conditions:
        match_type = StringMatchType(cond.match_type)
        filter_value = cond.value

        if match_type == StringMatchType.IS_EQUAL:
            matches = value == filter_value
        elif match_type == StringMatchType.IS_NOT_EQUAL:
            matches = value != filter_value
        elif match_type == StringMatchType.CONTAINS:
            matches = filter_value.lower() in value.lower()
        elif match_type == StringMatchType.NOT_CONTAINS:
            matches = filter_value.lower() not in value.lower()
        elif match_type == StringMatchType.STARTS_WITH:
            matches = value.lower().startswith(filter_value.lower())
        elif match_type == StringMatchType.NOT_STARTS_WITH:
            matches = not value.lower().startswith(filter_value.lower())
        elif match_type == StringMatchType.ENDS_WITH:
            matches = value.lower().endswith(filter_value.lower())
        elif match_type == StringMatchType.NOT_ENDS_WITH:
            matches = not value.lower().endswith(filter_value.lower())
        else:
            matches = False

        results.append(matches)

    if logic == "OR":
        return any(results)
    return all(results)


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
    name_filter = _parse_filter(name_filter)
    mark_filter = _parse_filter(mark_filter)
    title1_filter = _parse_filter(title1_filter)
    title2_filter = _parse_filter(title2_filter)
    title3_filter = _parse_filter(title3_filter)

    normalized_type = DrawingTypeModel(value=drawing_type).to_enum().value if drawing_type else None

    try:
        drawing_handler = DrawingHandler()

        if not drawing_handler.GetConnectionStatus():
            return {
                "status": "error",
                "message": "Not connected to Tekla",
            }

        drawings_enum = drawing_handler.GetDrawings()

        all_drawings = wrap_drawings(drawings_enum)

        filtered_drawings = all_drawings

        if normalized_type:
            filtered_drawings = [d for d in filtered_drawings if d.drawing_type == normalized_type]

        if name_filter:
            filtered_drawings = [d for d in filtered_drawings if _matches_string_filter(d.name, name_filter)]

        if mark_filter:
            filtered_drawings = [d for d in filtered_drawings if _matches_string_filter(d.mark, mark_filter)]

        if title1_filter:
            filtered_drawings = [d for d in filtered_drawings if _matches_string_filter(d.title1, title1_filter)]

        if title2_filter:
            filtered_drawings = [d for d in filtered_drawings if _matches_string_filter(d.title2, title2_filter)]

        if title3_filter:
            filtered_drawings = [d for d in filtered_drawings if _matches_string_filter(d.title3, title3_filter)]

        marks = [d.mark for d in filtered_drawings]

        logger.info("Found %s drawings matching filters", len(marks))

        return {
            "status": "success",
            "matched_count": len(marks),
            "marks": marks,
        }

    except Exception:
        logger.exception("Failed to get drawings")
        return {
            "status": "error",
            "message": "Failed to get drawings",
        }


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
    try:
        drawing_handler = DrawingHandler()

        if not drawing_handler.GetConnectionStatus():
            return {
                "status": "error",
                "message": "Not connected to Tekla",
            }

        if marks is None or marks == []:
            selector = drawing_handler.GetDrawingSelector()
            selected_drawings_enum = selector.GetSelected()

            drawings = wrap_drawings(selected_drawings_enum)
        else:
            drawings_enum = drawing_handler.GetDrawings()
            all_drawings = wrap_drawings(drawings_enum)

            drawings = [d for d in all_drawings if d.mark in marks]

        if not drawings:
            return {
                "status": "warning",
                "message": "No drawings found",
                "selected_count": 0,
                "drawings": [],
            }

        drawings_data = [d.to_dict() for d in drawings]

        logger.info("Retrieved properties for %s drawings", len(drawings_data))

        return {
            "status": "success",
            "selected_count": len(drawings_data),
            "drawings": drawings_data,
        }

    except Exception:
        logger.exception("Failed to get drawing properties")
        return {
            "status": "error",
            "message": "Failed to get drawing properties",
        }
