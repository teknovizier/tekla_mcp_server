"""
Drawing tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any, Annotated

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import DrawingType, StringFilterOption, StringMatchType
from tekla_mcp_server.utils import mcp_handler, rects_intersect, lines_intersect, line_rect_intersect
from tekla_mcp_server.tekla.wrappers.drawing import wrap_drawings
from tekla_mcp_server.tekla.loader import DrawingHandler, Drawing, Mark, DrawingColors, FrameTypes


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


def _get_mark_collision_data(mark: Mark) -> dict | None:
    """Get mark data for both bbox and line collision detection."""
    result = {"bbox": None, "line": None, "mark": mark}

    # Get bbox using GetAxisAlignedBoundingBox
    bbox = mark.GetAxisAlignedBoundingBox()
    if hasattr(bbox, "MinPoint"):
        min_pt = bbox.MinPoint
        max_pt = bbox.MaxPoint
        result["bbox"] = (min_pt.X, min_pt.Y, max_pt.X, max_pt.Y)

    # Get mark insertion point
    ip = mark.InsertionPoint
    if ip:
        ip_x, ip_y = ip.X, ip.Y
    else:
        return result

    # Try to get LeaderLine from mark's children
    leader_start = None
    leader_end = None

    children = mark.GetObjects()
    while children.MoveNext():
        child = children.Current
        if type(child).__name__ == "LeaderLine":
            leader = child
            leader_start = leader.StartPoint  # Arrow tip
            leader_end = leader.EndPoint  # Point at text edge
            break

    # Set line data
    if leader_start and leader_end:
        result["line"] = ((leader_end.X, leader_end.Y), (leader_start.X, leader_start.Y))
    elif leader_start:
        result["line"] = ((ip_x, ip_y), (leader_start.X, leader_start.Y))
    else:
        result["line"] = None

    return result


def _check_collisions(data_list: list[dict]) -> set[int]:
    """Check both bbox overlap and line intersections."""
    colliding: set[int] = set()
    n = len(data_list)

    for i in range(n):
        for j in range(i + 1, n):
            data_i = data_list[i]
            data_j = data_list[j]
            is_colliding = False

            # Check bbox overlap
            if data_i["bbox"] and data_j["bbox"]:
                if rects_intersect(data_i["bbox"], data_j["bbox"]):
                    is_colliding = True

            # Check line intersection
            if data_i["line"] and data_j["line"]:
                if lines_intersect(data_i["line"][0], data_i["line"][1], data_j["line"][0], data_j["line"][1]):
                    is_colliding = True

            # Check line vs bbox (both directions)
            if data_i["line"] and data_j["bbox"]:
                if line_rect_intersect(data_i["line"][0], data_i["line"][1], data_j["bbox"]):
                    is_colliding = True
            if data_i["bbox"] and data_j["line"]:
                if line_rect_intersect(data_j["line"][0], data_j["line"][1], data_i["bbox"]):
                    is_colliding = True

            if is_colliding:
                colliding.add(i)
                colliding.add(j)

    return colliding


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
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


@drawings_provider.tool(tags={"catalog"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_drawing_properties(
    marks: Annotated[list[str] | None, Field(description="List of drawing marks to get properties for")] = None,
) -> ToolResult:
    """
    Get properties of drawings by their marks.

    If the marks are not provided, gets properties of currently selected drawings in Tekla.

    ## OUTPUT
    - Return the result table in Markdown format EXACTLY as provided by the tool.
    - DO NOT reformat, truncate, or modify anything, including spacing, columns, or headers.
    - ALWAYS show the full table. DO NOT remove any rows or columns.
    """
    drawing_handler = DrawingHandler()

    if not drawing_handler.GetConnectionStatus():
        return ToolResult(
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
            structured_content={"status": "warning", "message": "No drawings found"},
        )

    drawings_data = [{"No": i + 1, **d.to_dict()} for i, d in enumerate(drawings)]

    logger.info("Retrieved properties for %s drawings", len(drawings_data))

    return ToolResult(
        content={"drawings": drawings_data},
        structured_content={
            "status": "success",
            "selected_count": len(drawings_data),
            "drawings": drawings_data,
        },
    )


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def detect_collisions_between_marks(
    marks: Annotated[list[str] | None, Field(description="List of drawing marks to process")] = None,
) -> ToolResult:
    """
    Detect collisions between part marks in drawings.

    If the marks are not provided, processes currently selected drawings in Tekla.
    """
    drawing_handler = DrawingHandler()

    if not drawing_handler.GetConnectionStatus():
        return ToolResult(
            structured_content={"status": "error", "message": "Not connected to Tekla"},
        )

    target_drawings: list[Drawing] = []
    if marks:
        all_drawings_enum = drawing_handler.GetDrawings()
        all_drawings = wrap_drawings(all_drawings_enum)
        target_drawings = [d.drawing for d in all_drawings if d.mark in marks]
    else:
        selector = drawing_handler.GetDrawingSelector()
        selected_enum = selector.GetSelected()
        target_drawings = [d.drawing for d in wrap_drawings(selected_enum)]

    if not target_drawings:
        return ToolResult(
            structured_content={"status": "error", "message": "No drawings found or selected"},
        )

    if drawing_handler.GetActiveDrawing():
        logger.error("detect_drawing_collisions failed: A drawing is currently open")
        return ToolResult(structured_content={"status": "error", "message": "A drawing is currently open. Close it first before running collision detection."})

    all_drawings_results: list[dict] = []
    total_colliding_marks = 0

    for drawing in target_drawings:
        drawing_handler.SetActiveDrawing(drawing)

        view_results: list[dict] = []

        try:
            sheet = drawing.GetSheet()
            views_enum = sheet.GetAllViews()
        except Exception:
            continue

        while views_enum.MoveNext():
            view = views_enum.Current
            view_name = view.Name or ""

            try:
                mark_objects = view.GetAllObjects(Mark)
            except Exception:
                continue

            mark_data = []
            while mark_objects.MoveNext():
                obj = mark_objects.Current
                collision_data = _get_mark_collision_data(obj)
                if collision_data:
                    mark_data.append(collision_data)

            if not mark_data:
                continue

            colliding_indices = _check_collisions(mark_data)

            if not colliding_indices:
                continue

            colliding_count = len(colliding_indices)
            total_colliding_marks += colliding_count

            for i, data in enumerate(mark_data):
                if i in colliding_indices:
                    mark = data["mark"]
                    mark.Attributes.Frame.Color = DrawingColors.Red
                    mark.Attributes.Frame.Type = FrameTypes.Rectangular
                    mark.Modify()

            view_results.append(
                {
                    "view": view_name,
                    "total_marks": len(mark_data),
                    "colliding_marks": colliding_count,
                }
            )

        if view_results:
            all_drawings_results.append(
                {
                    "mark": drawing.Mark,
                    "name": drawing.Name,
                    "views": view_results,
                }
            )
            drawing_handler.SaveActiveDrawing()

    drawing_handler.CloseActiveDrawing()

    logger.info("Collision detection complete: %d total colliding marks", total_colliding_marks)
    return ToolResult(
        structured_content={
            "status": "success",
            "total_drawings": len(target_drawings),
            "drawings_with_collisions": all_drawings_results,
            "total_colliding_marks": total_colliding_marks,
        },
    )
