"""
Drawing utility helpers for Tekla MCP server.
"""

from pathlib import Path

from tekla_mcp_server.models import StringFilterOption, StringMatchType
from tekla_mcp_server.utils import line_rect_intersect, lines_intersect, rects_intersect
from tekla_mcp_server.tekla.loader import (
    DotPrintColor,
    DotPrintOrientationType,
    DotPrintOutputType,
    DotPrintPaperSize,
    DotPrintScalingType,
    LeaderLine,
    Mark,
    TeklaStructuresSettings,
)
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


OUTPUT_TYPE_MAP: dict[str, DotPrintOutputType] = {
    "PDF": DotPrintOutputType.PDF,
    "Printer": DotPrintOutputType.Printer,
    "Plot": DotPrintOutputType.Plot,
    "Image": DotPrintOutputType.Image,
}

COLOR_MODE_MAP: dict[str, DotPrintColor] = {
    "BlackAndWhite": DotPrintColor.BlackAndWhite,
    "Color": DotPrintColor.Color,
}

ORIENTATION_MAP: dict[str, DotPrintOrientationType] = {
    "Landscape": DotPrintOrientationType.Landscape,
    "Portrait": DotPrintOrientationType.Portrait,
}

SCALING_METHOD_MAP: dict[str, DotPrintScalingType] = {
    "Auto": DotPrintScalingType.Auto,
    "Scale": DotPrintScalingType.Scale,
}


def get_default_plot_output_folder() -> Path | None:
    """
    Return the default plot output folder from Tekla advanced settings.

    Reads XS_DRAWING_PLOT_FILE_DIRECTORY. Relative paths are resolved
    against the current model directory.

    Returns:
        Absolute Path to the configured output folder, or None if the
        setting is empty.
    """
    model = TeklaModel()
    model_path = model.model.GetInfo().ModelPath
    _, plot_dir = TeklaStructuresSettings.GetAdvancedOption("XS_DRAWING_PLOT_FILE_DIRECTORY", str())

    if not plot_dir:
        return None

    if Path(plot_dir).is_absolute():
        return Path(plot_dir).resolve()
    return (Path(model_path) / plot_dir).absolute()


def matches_string_filter(value: str, filter_option: StringFilterOption | None) -> bool:
    """
    Check whether a string satisfies all conditions in a StringFilterOption.

    Comparisons are case-insensitive except for IS_EQUAL and IS_NOT_EQUAL.
    Conditions are combined with the filter's logic operator (AND/OR).

    Args:
        value: The string to test.
        filter_option: Filter to evaluate. Returns True when None or empty.

    Returns:
        True if value passes all (AND) or any (OR) of the conditions.
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

    return any(results) if logic == "OR" else all(results)


def map_sheet_size_to_paper_size(sheet_width: float, sheet_height: float) -> DotPrintPaperSize | None:
    """
    Map Tekla sheet dimensions to a DotPrintPaperSize enum value.

    Supports ISO A0-A4 in both landscape and portrait orientations.
    Dimensions are rounded to the nearest millimetre before lookup.

    Args:
        sheet_width: Sheet width in millimetres.
        sheet_height: Sheet height in millimetres.

    Returns:
        Matching DotPrintPaperSize, or None if no standard size matches.
    """
    paper_sizes = {
        (210, 297): DotPrintPaperSize.A4,
        (297, 210): DotPrintPaperSize.A4,
        (297, 420): DotPrintPaperSize.A3,
        (420, 297): DotPrintPaperSize.A3,
        (420, 594): DotPrintPaperSize.A2,
        (594, 420): DotPrintPaperSize.A2,
        (594, 841): DotPrintPaperSize.A1,
        (841, 594): DotPrintPaperSize.A1,
        (841, 1189): DotPrintPaperSize.A0,
        (1189, 841): DotPrintPaperSize.A0,
    }
    return paper_sizes.get((round(sheet_width), round(sheet_height)))


def get_mark_collision_data(mark: Mark) -> dict:
    """
    Extract bounding box and leader-line geometry from a drawing Mark.

    Retrieves the axis-aligned bounding box and, when present, the leader
    line endpoints from the mark's child objects. The result is used as
    input for check_collisions.

    Args:
        mark: Tekla drawing Mark object to inspect.

    Returns:
        Dict with keys:
            bbox: (x0, y0, x1, y1) tuple, or None if unavailable.
            line: ((x0, y0), (x1, y1)) tuple, or None if unavailable.
            mark: The original Mark object.
    """
    result: dict = {"bbox": None, "line": None, "mark": mark}

    bbox = mark.GetAxisAlignedBoundingBox()
    if hasattr(bbox, "MinPoint"):
        min_pt = bbox.MinPoint
        max_pt = bbox.MaxPoint
        result["bbox"] = (min_pt.X, min_pt.Y, max_pt.X, max_pt.Y)

    ip = mark.InsertionPoint
    if not ip:
        return result
    ip_x, ip_y = ip.X, ip.Y

    leader_start = None
    leader_end = None
    children = mark.GetObjects()
    while children.MoveNext():
        child = children.Current
        if isinstance(child, LeaderLine):
            leader_start = child.StartPoint
            leader_end = child.EndPoint
            break

    if leader_start and leader_end:
        result["line"] = ((leader_end.X, leader_end.Y), (leader_start.X, leader_start.Y))
    elif leader_start:
        result["line"] = ((ip_x, ip_y), (leader_start.X, leader_start.Y))

    return result


def check_collisions(data_list: list[dict]) -> set[int]:
    """
    Find indices of marks that collide with at least one other mark.

    Three collision types are checked for each pair:
        - Bounding-box overlap.
        - Leader-line crossing another leader line.
        - Leader-line crossing another mark's bounding box.

    Args:
        data_list: List of dicts as returned by get_mark_collision_data.

    Returns:
        Set of indices (into data_list) of every mark involved in a collision.
    """
    colliding: set[int] = set()
    n = len(data_list)

    for i in range(n):
        for j in range(i + 1, n):
            data_i = data_list[i]
            data_j = data_list[j]
            is_colliding = False

            if data_i["bbox"] and data_j["bbox"] and rects_intersect(data_i["bbox"], data_j["bbox"]):
                is_colliding = True

            if not is_colliding and data_i["line"] and data_j["line"]:
                if lines_intersect(data_i["line"][0], data_i["line"][1], data_j["line"][0], data_j["line"][1]):
                    is_colliding = True

            if not is_colliding and data_i["line"] and data_j["bbox"]:
                if line_rect_intersect(data_i["line"][0], data_i["line"][1], data_j["bbox"]):
                    is_colliding = True

            if not is_colliding and data_i["bbox"] and data_j["line"]:
                if line_rect_intersect(data_j["line"][0], data_j["line"][1], data_i["bbox"]):
                    is_colliding = True

            if is_colliding:
                colliding.add(i)
                colliding.add(j)

    return colliding
