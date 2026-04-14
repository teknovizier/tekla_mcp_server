"""
Drawing tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any, Annotated
from pydantic import Field

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from tabulate import tabulate  # type: ignore

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import DrawingType, StringFilterOption, StringMatchType
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


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@log_mcp_tool_call
def get_drawings(
    drawing_type: Annotated[DrawingType | None, Field(description="Filter by drawing type")] = None,
    name_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by drawing name")] = None,
    mark_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by drawing mark")] = None,
    title1_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by Title 1")] = None,
    title2_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by Title 2")] = None,
    title3_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by Title 3")] = None,
) -> ToolResult:
    """
    Get drawings from Tekla model with optional filtering.

    Name, mark and title filters are constructed using StringFilterOption.
    Example: {"conditions": {"match_type": "Contains", "value": "floor"}}

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

    try:
        drawing_handler = DrawingHandler()

        if not drawing_handler.GetConnectionStatus():
            return ToolResult(
                structured_content={
                    "status": "error",
                    "message": "Not connected to Tekla",
                }
            )

        drawings_enum = drawing_handler.GetDrawings()

        all_drawings = wrap_drawings(drawings_enum)

        filtered_drawings = all_drawings

        if drawing_type:
            filtered_drawings = [d for d in filtered_drawings if d.drawing_type == drawing_type]

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

        return ToolResult(
            structured_content={
                "status": "success",
                "matched_count": len(marks),
                "marks": marks,
            }
        )

    except Exception:
        logger.exception("Failed to get drawings")
        return ToolResult(
            structured_content={
                "status": "error",
                "message": "Failed to get drawings",
            }
        )


@drawings_provider.tool(tags={"catalog"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@log_mcp_tool_call
def get_drawing_properties(
    marks: Annotated[list[str] | None, Field(description="List of drawing marks to get properties for")] = None,
) -> ToolResult:
    """
    Get properties of drawings by their marks.

    If the marks are not provided, gets properties of currently selected drawings in Tekla.

    ## EXAMPLES
    # Get properties of selected drawings
    {}

    # Get properties of specific drawings
    {"marks": ["[HCS-1001 - 1]", "[HCS-1002 - 1]"]}

    ## OUTPUT
    - Return the result table EXACTLY as provided by the tool.
    - DO NOT reformat, summarize, or explain.
    - DO NOT modify spacing, columns, or headers.
    """

    def _build_table(items: list[dict[str, Any]]) -> str:
        if not items:
            return ""
        headers = [h.replace("_", " ").title() for h in items[0].keys()]
        data = [[i + 1] + list(d.values()) for i, d in enumerate(items)]
        return tabulate(data, headers=headers, tablefmt="github")

    try:
        drawing_handler = DrawingHandler()

        if not drawing_handler.GetConnectionStatus():
            return ToolResult(
                content="Not connected to Tekla",
                structured_content={"status": "error", "message": "Not connected to Tekla"},
            )

        if marks is None or marks == []:
            selector = drawing_handler.GetDrawingSelector()
            selected_drawings_enum = selector.GetSelected()

            drawings = wrap_drawings(selected_drawings_enum)
        else:
            drawings_enum = drawing_handler.GetDrawings()
            all_drawings = wrap_drawings(drawings_enum)

            drawings = [d for d in all_drawings if d.mark in marks]

        if not drawings:
            return ToolResult(
                content="No drawings found",
                structured_content={"status": "warning", "message": "No drawings found"},
            )

        drawings_data = [d.to_dict() for d in drawings]

        drawings_table = _build_table(drawings_data)
        content = f"## Drawings\n{drawings_table}\n"

        logger.info("Retrieved properties for %s drawings", len(drawings_data))

        return ToolResult(
            content=content,
            structured_content={
                "status": "success",
                "selected_count": len(drawings_data),
                "drawings": drawings_data,
            },
        )

    except Exception:
        logger.exception("Failed to get drawing properties")
        return ToolResult(
            content="Failed to get drawing properties",
            structured_content={"status": "error", "message": "Failed to get drawing properties"},
        )
