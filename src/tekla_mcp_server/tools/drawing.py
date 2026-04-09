"""
Drawing tools for Tekla model operations.
"""

from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import DrawingType, StringFilterOption, StringMatchType
from tekla_mcp_server.tekla.drawing import wrap_drawings
from tekla_mcp_server.tekla.loader import DrawingHandler
from tekla_mcp_server.utils import log_function_call


def _parse_filter(filter_option: Any) -> StringFilterOption | None:
    """
    Parse filter option from dict to StringFilterOption.
    """
    if isinstance(filter_option, dict):
        return StringFilterOption.model_validate(filter_option)
    return filter_option


def _matches_string_filter(value: str, filter_option: Any) -> bool:
    """
    Check if a value matches a StringFilterOption.
    """
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


@log_function_call
def tool_get_drawings(
    drawing_type: DrawingType | None = None,
    name_filter: dict[str, Any] | StringFilterOption | None = None,
    mark_filter: dict[str, Any] | StringFilterOption | None = None,
    title1_filter: dict[str, Any] | StringFilterOption | None = None,
    title2_filter: dict[str, Any] | StringFilterOption | None = None,
    title3_filter: dict[str, Any] | StringFilterOption | None = None,
) -> dict[str, Any]:
    """
    Get drawings from Tekla model with optional filtering.

    Args:
        drawing_type: Filter by drawing type (GA, Assembly, SinglePart, CastUnit, MultiDrawing, Unknown)
        name_filter: Filter by drawing name using StringFilterOption
        mark_filter: Filter by drawing mark using StringFilterOption
        title1_filter: Filter by title1 using StringFilterOption
        title2_filter: Filter by title2 using StringFilterOption
        title3_filter: Filter by title3 using StringFilterOption

    Returns:
        Dictionary with list of drawing marks
    """
    # Parse dict filters to StringFilterOption
    name_filter = _parse_filter(name_filter)
    mark_filter = _parse_filter(mark_filter)
    title1_filter = _parse_filter(title1_filter)
    title2_filter = _parse_filter(title2_filter)
    title3_filter = _parse_filter(title3_filter)

    normalized_type = drawing_type.value if drawing_type else None

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


@log_function_call
def tool_get_drawing_properties(
    marks: list[str] | None = None,
) -> dict[str, Any]:
    """
    Get properties of drawings by their marks.

    Args:
        marks: Optional list of drawing marks. If not provided,
               gets properties of currently selected drawings in Tekla.

    Returns:
        Dictionary with drawing properties
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
