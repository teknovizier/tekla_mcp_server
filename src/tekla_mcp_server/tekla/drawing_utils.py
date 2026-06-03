"""
Drawing utility helpers for Tekla MCP server.
"""

from dataclasses import dataclass

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import StringFilterOption, StringMatchType
from tekla_mcp_server.tekla.loader import (
    Cloud,
    DrawingColors,
    DrawingView,
    Mark,
    MarkSet,
    PointList,
    Point,
    DotPrintColor,
    DotPrintOrientationType,
    DotPrintOutputType,
    DotPrintPaperSize,
    DotPrintScalingType,
    LeaderLine,
    WeldMark,
)


@dataclass
class DrawingMarkData:
    """Extracted bounding box, leader line endpoints and object reference for a drawing mark."""

    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1) in drawing coordinates
    line: tuple[tuple[float, float], tuple[float, float]] | None  # Leader line endpoints
    mark: Mark | MarkSet | WeldMark


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


def rects_intersect(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    margin: float = 0.0,
) -> bool:
    """
    Check if two rectangles intersect with margin.

    Args:
        a: Tuple of (x1, y1, x2, y2) defining first rectangle
        b: Tuple of (x1, y1, x2, y2) defining second rectangle
        margin: Optional margin to add to rectangles

    Returns:
        True if rectangles intersect, False otherwise
    """
    return not (a[2] < b[0] - margin or a[0] > b[2] + margin or a[3] < b[1] - margin or a[1] > b[3] + margin)


def lines_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
    margin: float = 0.0,
) -> bool:
    """
    Check if two line segments intersect with margin.

    Args:
        p1: First point of first line segment (x, y)
        p2: Second point of first line segment (x, y)
        p3: First point of second line segment (x, y)
        p4: Second point of second line segment (x, y)
        margin: Optional margin for intersection tolerance

    Returns:
        True if line segments intersect, False otherwise
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4

    epsilon = 0.0001
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < epsilon:
        return False

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if 0 - margin <= t <= 1 + margin and 0 - margin <= u <= 1 + margin:
        return True
    return False


def line_rect_intersect(
    line_p1: tuple[float, float],
    line_p2: tuple[float, float],
    rect: tuple[float, float, float, float],
    margin: float = 0.0,
) -> bool:
    """
    Check if a line segment intersects a rectangle.

    Args:
        line_p1: First point of line segment (x, y)
        line_p2: Second point of line segment (x, y)
        rect: Tuple of (x1, y1, x2, y2) defining rectangle
        margin: Optional margin to add to rectangle

    Returns:
        True if line intersects rectangle, False otherwise
    """
    x1, y1 = line_p1
    x2, y2 = line_p2
    rx1, ry1, rx2, ry2 = rect

    left = min(rx1, rx2) - margin
    right = max(rx1, rx2) + margin
    bottom = min(ry1, ry2) - margin
    top = max(ry1, ry2) + margin

    if left <= x1 <= right and bottom <= y1 <= top:
        return True
    if left <= x2 <= right and bottom <= y2 <= top:
        return True

    if lines_intersect((x1, y1), (x2, y2), (left, bottom), (right, bottom), margin):
        return True
    if lines_intersect((x1, y1), (x2, y2), (right, bottom), (right, top), margin):
        return True
    if lines_intersect((x1, y1), (x2, y2), (right, top), (left, top), margin):
        return True
    if lines_intersect((x1, y1), (x2, y2), (left, top), (left, bottom), margin):
        return True

    return False


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


def draw_collision_cloud(view: DrawingView, data_a: DrawingMarkData, data_b: DrawingMarkData) -> bool:
    """
    Draw one magenta revision cloud that encompasses both marks of a collision pair.

    The cloud is placed around the union of the two marks' bounding boxes with
    a 20 mm margin on all sides (drawing units = mm).

    Args:
        view:   Tekla drawing view in which the cloud is inserted.
        data_a: Collision-data for the first mark.
        data_b: Collision-data for the second mark.

    Returns:
        True if the cloud was inserted successfully, False otherwise.
    """
    bbox_a = data_a.bbox
    bbox_b = data_b.bbox
    combined = (
        min(bbox_a[0], bbox_b[0]),
        min(bbox_a[1], bbox_b[1]),
        max(bbox_a[2], bbox_b[2]),
        max(bbox_a[3], bbox_b[3]),
    )

    x0, y0, x1, y1 = combined
    m = 20.0  # mm: keeps the cloud clear of the mark text

    pts = PointList()
    pts.Add(Point(x0 - m, y0 - m, 0))
    pts.Add(Point(x1 + m, y0 - m, 0))
    pts.Add(Point(x1 + m, y1 + m, 0))
    pts.Add(Point(x0 - m, y1 + m, 0))

    try:
        cloud = Cloud(view, pts)
        cloud.Attributes.Line.Color = DrawingColors.Magenta
        cloud.ArcWidth = 5  # mm per arc bump
        if not cloud.Insert():
            logger.warning("Cloud.Insert() returned False for view '%s'", getattr(view, "Name", ""))
            return False
        return True
    except Exception as e:
        logger.warning("Failed to insert collision cloud in view '%s': %s", getattr(view, "Name", ""), e)
        return False


def get_mark_collision_data(mark: Mark | MarkSet | WeldMark) -> DrawingMarkData | None:
    """
    Extract bounding box and leader-line geometry from a drawing mark object.

    Args:
        mark: Tekla drawing mark to inspect (Mark, MarkSet, or WeldMark).

    Returns:
        DrawingMarkData with bbox in drawing coordinates, leader-line endpoints
        (or None when absent), and the original mark. Returns None if the mark
        has no valid (non-zero-area) bounding box.
    """
    aabb = mark.GetAxisAlignedBoundingBox()
    if not hasattr(aabb, "MinPoint"):
        return None

    min_pt = aabb.MinPoint
    max_pt = aabb.MaxPoint
    x0, y0, x1, y1 = min_pt.X, min_pt.Y, max_pt.X, max_pt.Y
    if x0 == x1 and y0 == y1:
        return None

    ip = mark.InsertionPoint
    if not ip:
        return DrawingMarkData(bbox=(x0, y0, x1, y1), line=None, mark=mark)

    ip_x, ip_y = ip.X, ip.Y

    # WeldMark reports its AABB Y in model coordinates instead of drawing
    # coordinates, making it unusable for collision detection. Reconstruct the
    # Y extent from the insertion point: a weld symbol typically has text both
    # above and below, so ±font_height covers both lines.
    if isinstance(mark, WeldMark):
        try:
            font_h = mark.Attributes.Font.Height
        except Exception:
            font_h = 2.5
        half_h = max(2.0 * font_h, 5.0)
        y0 = ip_y - half_h
        y1 = ip_y + half_h

    leader_start = None
    leader_end = None
    children = mark.GetObjects()
    while children.MoveNext():
        child = children.Current
        if isinstance(child, LeaderLine):
            leader_start = child.StartPoint
            leader_end = child.EndPoint
            break

    line: tuple[tuple[float, float], tuple[float, float]] | None = None
    if leader_start and leader_end:
        line = ((leader_end.X, leader_end.Y), (leader_start.X, leader_start.Y))
    elif leader_start:
        line = ((ip_x, ip_y), (leader_start.X, leader_start.Y))

    return DrawingMarkData(bbox=(x0, y0, x1, y1), line=line, mark=mark)


def get_collision_pairs(data_list: list[DrawingMarkData]) -> list[tuple[int, int]]:
    """
    Return every colliding (i, j) index pair from a list of mark data.

    Three collision types are checked per pair:
        - Bounding-box overlap.
        - Leader-line crossing another leader line.
        - Leader-line crossing another mark's bounding box.

    Args:
        data_list: List of DrawingMarkData as returned by get_mark_collision_data.

    Returns:
        List of (i, j) tuples (i < j) for every colliding pair.

    Note:
        Runtime is O(n²). Views with hundreds of marks will be noticeably slow.
    """
    pairs: list[tuple[int, int]] = []
    n = len(data_list)

    for i in range(n):
        for j in range(i + 1, n):
            di = data_list[i]
            dj = data_list[j]

            if rects_intersect(di.bbox, dj.bbox):
                pairs.append((i, j))
                continue

            if di.line and dj.line and lines_intersect(di.line[0], di.line[1], dj.line[0], dj.line[1]):
                pairs.append((i, j))
                continue

            if di.line and line_rect_intersect(di.line[0], di.line[1], dj.bbox):
                pairs.append((i, j))
                continue

            if dj.line and line_rect_intersect(dj.line[0], dj.line[1], di.bbox):
                pairs.append((i, j))

    return pairs
