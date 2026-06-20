"""
Drawing utility helpers for Tekla MCP server.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tekla_mcp_server.tekla.wrappers.model import TeklaModel

from tekla_mcp_server.config import get_tolerance
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import StringFilterOption, StringMatchType
from tekla_mcp_server.tekla.loader import (
    Cloud,
    DrawingColors,
    DrawingView,
    Mark,
    MarkBase,
    MarkSet,
    SectionMark,
    SectionMarkBase,
    CurvedSectionMark,
    WeldMark,
    DetailMark,
    LevelMark,
    DimensionBase,
    DimensionSetBase,
    StraightDimension,
    StraightDimensionSet,
    AngleDimension,
    RadiusDimension,
    CurvedDimensionOrthogonal,
    CurvedDimensionRadial,
    CurvedDimensionSetOrthogonal,
    CurvedDimensionSetRadial,
    DrawingText,
    GraphicObject,
    Arc,
    Line,
    Polyline,
    Circle,
    Polygon,
    Rectangle,
    PointList,
    Point,
    DotPrintColor,
    DotPrintOrientationType,
    DotPrintOutputType,
    DotPrintPaperSize,
    DotPrintScalingType,
    LeaderLine,
)
from tekla_mcp_server.tekla.wrappers import TeklaDrawingView
from tekla_mcp_server.tekla.wrappers.view import SheetPlacement


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


# Categories returned by default in get_view_annotations (type_filter="all").
DEFAULT_ANNOTATION_CATEGORIES = frozenset({"dimensions", "marks", "text"})

# Concrete Tekla.Structures.Drawing types per category, used as the type filter
# for `view.get_all_objects([...])`. MUST be concrete types only - abstract bases
# (MarkBase, DimensionBase, GraphicObject) throw "Cannot create an instance of
# abstract class" when passed to Tekla's TypeMapper.
# `categorize_drawing_object` still classifies by the abstract bases via isinstance.
CATEGORY_TYPES: dict[str, tuple[type, ...]] = {
    "marks": (Mark, MarkSet, WeldMark, DetailMark, LevelMark, SectionMark, CurvedSectionMark),
    "dimensions": (
        StraightDimension,
        StraightDimensionSet,
        AngleDimension,
        RadiusDimension,
        CurvedDimensionOrthogonal,
        CurvedDimensionRadial,
        CurvedDimensionSetOrthogonal,
        CurvedDimensionSetRadial,
    ),
    "text": (DrawingText,),
    "graphics": (Arc, Line, Polyline, Circle, Polygon, Rectangle, Cloud),
}


def categorize_drawing_object(obj: Any) -> str:
    """
    Classify a drawing object into dimensions/marks/text/graphics/other.

    Matched by isinstance against Tekla.Structures.Drawing base classes.
    Use type_filter="graphics" in get_view_annotations to enumerate graphical
    objects (clouds, lines, shapes) which are excluded from the default.

    LeaderLine falls into 'other', which is excluded from every type_filter value.

    Returns:
        One of: 'dimensions', 'marks', 'text', 'graphics', 'other'.
    """
    if isinstance(obj, (MarkBase, WeldMark, DetailMark, LevelMark, SectionMarkBase)):
        return "marks"
    if isinstance(obj, (DimensionBase, DimensionSetBase)):
        return "dimensions"
    if isinstance(obj, DrawingText):
        return "text"
    if isinstance(obj, GraphicObject):
        return "graphics"
    return "other"


def extract_annotation_content(obj: Any, category: str, model: "TeklaModel | None" = None) -> dict[str, Any]:
    """
    Best-effort textual content of a single annotation (no geometry).

    Lightweight: reads only the rendered string/value, never coordinates. The
    property names below are NOT yet verified against the installed
    Tekla.Structures.Drawing assembly - confirm each in a live model and adjust.
    Anything that cannot be read comes back as None rather than raising, so one
    odd object never fails the whole view read.

    Args:
        obj: The annotation object.
        category: Its category from `categorize_drawing_object`.
        model: Model used to resolve a mark's target to a GUID. Required to
            populate `target_guid` for marks; when None it comes back as None.

    Returns:
        dict with at least 'type' and 'category'; plus 'content' (marks/text)
        or 'value' (dimensions) when readable. Marks also carry 'target_guid'.
    """
    info: dict[str, Any] = {"type": type(obj).__name__, "category": category}
    try:
        if category == "marks":
            # Section/detail marks expose `.Attributes.MarkName`; a plain Mark's
            # string is assembled from `.Attributes.Content` (both handled in the
            # helper). WeldMark/LevelMark have neither and return "N/A" for now.
            info["content"] = _extract_mark_text(obj)
            # GUID of the part the mark points at - the join key a coverage audit
            # diffs against the view's parts (from `get_view_objects`).
            info["target_guid"] = _extract_mark_target(obj, model) if model is not None else None
        elif category == "text":
            # Confirmed live: Text.TextString holds the note string.
            info["content"] = getattr(obj, "TextString", None) or None
        elif category == "dimensions":
            # Confirmed live: StraightDimension(Set) and AngleDimension all expose
            # `.Distance` (float). `.Value` is a ContainerElement, not a number.
            # Report the magnitude - a linear dimension is shown unsigned. For an
            # AngleDimension this is the dimension-line distance, not the angle.
            dist = getattr(obj, "Distance", None)
            info["value"] = round(abs(float(dist)), 1) if dist is not None else None
    except Exception as e:
        logger.debug("extract_annotation_content failed for %s: %s", type(obj).__name__, e)
    return info


def _extract_mark_text(mark: Any) -> str | None:
    """
    Extract a mark's rendered string across mark subtypes.

    - Section/detail marks name their target via `Attributes.MarkName`.
    - A plain Mark/MarkSet has no flat text property, its `Attributes.Content`
    is an ordered element collection:
        * PropertyElement / UserDefinedElement / TextElement carry a `.Value`
        string (e.g. 'EPS-383', '4500*140', '-T')
        * SpaceElement renders a space, NewLineElement a line break
        * SymbolElement and other graphic-only elements carry no text (skipped)

    WeldMark and LevelMark expose neither. WeldMarkAttributes has no text/value
    field at all, LevelMark has no flat text property either. Both return the
    literal "N/A" for now.

    Args:
        mark: A mark object.

    Returns:
        The mark string, "N/A" for WeldMark/LevelMark, or None if it renders no
        text or cannot be read.
    """
    if isinstance(mark, (WeldMark, LevelMark)):
        return "N/A"

    try:
        attrs = mark.Attributes
    except Exception as e:
        logger.debug("Mark.Attributes unavailable for %s: %s", type(mark).__name__, e)
        return None
    if attrs is None:
        return None

    # Section/detail marks: the name of the view/detail they reference.
    mark_name = getattr(attrs, "MarkName", None)
    if mark_name:
        return mark_name

    content = getattr(attrs, "Content", None)
    if content is None:
        return None

    try:
        text = render_content_elements(content).strip()
    except Exception as e:
        logger.debug("Failed to iterate Mark content for %s: %s", type(mark).__name__, e)
        return None

    return text or None


def render_content_elements(content: Any) -> str:
    """
    Render a Tekla annotation-content element collection into its displayed text.

    Args:
        content: A `ContainerElement` (or any iterable of its element types).

    Returns:
        The rendered text. Raises on iteration failure - callers decide the fallback.
    """
    parts: list[str] = []
    for element in content:
        element_type = type(element).__name__
        if element_type == "SpaceElement":
            parts.append(" ")
        elif element_type == "NewLineElement":
            parts.append("\n")
        else:
            value = getattr(element, "Value", None)
            if value is not None:
                parts.append(str(value))
    return "".join(parts)


def _extract_mark_target(mark: Any, model: "TeklaModel") -> str | None:
    """
    GUID of the model object a mark points at.

    A drawing mark associates to its model object via `GetRelatedObjects()`,
    which yields drawing-side objects: the mark's own LeaderLine (no model
    identifier, skipped) plus the related model object.

    The drawing-side GUID is always zero, so the integer
    ModelIdentifier.ID is resolved to a model object via
    TeklaModel.get_object_by_id() (which can take an integer), and that
    object's own (non-zero) GUID is returned.

    Args:
        mark: A Tekla.Structures.Drawing mark object.
        model: Model used to resolve the integer ID to a GUID.

    Returns:
        The target object's GUID string, or None when the mark points at no
        resolvable model object (e.g. WeldMark) or the call fails.
    """
    try:
        related = mark.GetRelatedObjects()
    except Exception as e:
        logger.debug("GetRelatedObjects() failed for %s: %s", type(mark).__name__, e)
        return None
    if related is None:
        return None

    try:
        while related.MoveNext():
            obj = related.Current
            identifier = getattr(obj, "ModelIdentifier", None)
            if identifier is None:
                continue
            raw_id = getattr(identifier, "ID", None)
            if raw_id is None:
                continue
            obj_id = int(raw_id)
            if obj_id == 0:
                continue
            model_obj = model.get_object_by_id(obj_id)
            if model_obj is None:
                continue
            return model_obj.Identifier.GUID.ToString()
    except Exception as e:
        logger.debug("Failed to resolve mark target for %s: %s", type(mark).__name__, e)
    return None


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


# ISO paper sizes (width, height) in millimetres, both orientations.
_PAPER_SIZES: dict[tuple[int, int], DotPrintPaperSize] = {
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

# Landscape (width, height) dimensions per paper size, used for tiling
# detection. Multi-sheet tiling is only checked against the landscape
# orientation of each size - this resolves the otherwise unavoidable
# ambiguity from ISO sizes nesting by powers of two (e.g. a 420x1188mm sheet
# tiles cleanly as A2 portrait 1x2, A3 landscape 1x4, or A4 portrait 2x4,
# assuming landscape tiles picks A3 1x4).
_CANONICAL_PAPER_SIZES_LANDSCAPE: dict[tuple[int, int], DotPrintPaperSize] = {
    (1189, 841): DotPrintPaperSize.A0,
    (841, 594): DotPrintPaperSize.A1,
    (594, 420): DotPrintPaperSize.A2,
    (420, 297): DotPrintPaperSize.A3,
    (297, 210): DotPrintPaperSize.A4,
}


def map_sheet_size_to_paper_size(sheet_width: float, sheet_height: float, tolerance: float | None = None) -> DotPrintPaperSize | None:
    """
    Map Tekla sheet dimensions to a DotPrintPaperSize enum value.

    Supports ISO A0-A4 in both landscape and portrait orientations.

    Args:
        sheet_width: Sheet width in millimetres.
        sheet_height: Sheet height in millimetres.
        tolerance: Maximum deviation in millimetres for a match. Defaults to
            the `tolerances.drawings.sheet_size` config value.

    Returns:
        Matching DotPrintPaperSize, or None if no standard size matches.
    """
    if tolerance is None:
        tolerance = get_tolerance("sheet_size", 1.0, group="drawings")
    for (paper_w, paper_h), paper_size in _PAPER_SIZES.items():
        if abs(sheet_width - paper_w) <= tolerance and abs(sheet_height - paper_h) <= tolerance:
            return paper_size
    return None


def detect_sheet_grid(sheet_width: float, sheet_height: float, tolerance: float | None = None) -> tuple[DotPrintPaperSize, int, int] | None:
    """
    Detect whether sheet dimensions are a clean tiling of multiple standard sheets.

    Some drawings combine multiple physical sheets into a single Tekla
    sheet (ContainerView). This checks whether `sheet_width` x `sheet_height`
    is an integer-multiple tiling of a standard ISO paper size in landscape
    orientation, within tolerance. Landscape is assumed as the tile
    orientation (see `_CANONICAL_PAPER_SIZES_LANDSCAPE`).

    Only landscape-oriented tiling is checked. Sheets tiled in portrait
    orientation (e.g. 2x2 A4 portrait = 210x594mm) are not detected and
    are reported as single-page. This avoids the inherent ambiguity when
    landscape and portrait tilings overlap for the same sheet dimensions.

    Args:
        sheet_width: Sheet width in millimetres.
        sheet_height: Sheet height in millimetres.
        tolerance: Maximum deviation in millimetres for a tiling match.
            Defaults to the `tolerances.drawings.sheet_size` config value.

    Returns:
        `(paper_size, cols, rows)` for the largest standard paper size that
        tiles cleanly with `cols * rows >= 2`, or None if the dimensions match a
        single standard sheet or no clean tiling is found.
    """
    if tolerance is None:
        tolerance = get_tolerance("sheet_size", 1.0, group="drawings")
    if map_sheet_size_to_paper_size(sheet_width, sheet_height, tolerance) is not None:
        return None

    for (paper_w, paper_h), paper_size in _CANONICAL_PAPER_SIZES_LANDSCAPE.items():
        cols = round(sheet_width / paper_w)
        rows = round(sheet_height / paper_h)
        if cols < 1 or rows < 1 or cols * rows < 2:
            continue
        if abs(sheet_width - cols * paper_w) <= tolerance and abs(sheet_height - rows * paper_h) <= tolerance:
            return paper_size, cols, rows
    return None


def assign_sheet_number(
    frame_origin_x: float,
    frame_origin_y: float,
    frame_width: float,
    frame_height: float,
    tile_width: float,
    tile_height: float,
    cols: int,
    rows: int,
    tolerance: float | None = None,
) -> tuple[int | None, SheetPlacement]:
    """
    Map a view's visible frame to a 1-based sheet number in a tiled sheet grid.

    Sheets are numbered row-major starting from the top-left tile (highest Y,
    lowest X) as sheet 1, proceeding right then down.

    The assignment is based on overlap area: the view's frame rectangle
    (`frame_origin` + `frame_width`/`frame_height`) is intersected with every
    tile in the grid, and the view is assigned to the tile with the largest
    overlap area. This handles views that straddle a sheet boundary - e.g. a
    view whose origin sits on sheet 4 but whose bulk lies on sheet 3 is
    assigned to sheet 3.

    Args:
        frame_origin_x: X coordinate of the view's frame origin (mm).
        frame_origin_y: Y coordinate of the view's frame origin (mm).
        frame_width: Width of the view's visible frame (mm).
        frame_height: Height of the view's visible frame (mm).
        tile_width: Width of a single sheet tile (mm).
        tile_height: Height of a single sheet tile (mm).
        cols: Number of tile columns.
        rows: Number of tile rows.
        tolerance: Margin in millimetres allowed outside the grid bounds.
            Defaults to the `tolerances.drawings.sheet_size` config value.

    Returns:
        Tuple of (sheet_number, sheet_placement):
        - sheet_number: 1-based sheet number of the tile with the largest
          overlap, or None if `sheet_placement` is `out_of_grid`.
        - sheet_placement: `fits` if the frame overlaps exactly one tile and
          stays within the grid bounds, `spans_multiple_sheets` if it
          overlaps more than one tile, `overflows_sheet` if it extends past
          the overall grid bounds (would be clipped when printed),
          `spans_and_overflows` if both apply, or `out_of_grid` if the frame
          does not overlap the tiled grid at all within `tolerance`.
    """
    if tolerance is None:
        tolerance = get_tolerance("sheet_size", 1.0, group="drawings")
    grid_width = cols * tile_width
    grid_height = rows * tile_height
    frame_x_max = frame_origin_x + frame_width
    frame_y_max = frame_origin_y + frame_height
    if frame_x_max < -tolerance or frame_origin_x > grid_width + tolerance or frame_y_max < -tolerance or frame_origin_y > grid_height + tolerance:
        return None, "out_of_grid"

    best_sheet_number: int | None = None
    best_overlap = 0.0
    overlapping_tiles = 0
    for row_from_bottom in range(rows):
        tile_y_min = row_from_bottom * tile_height
        tile_y_max = tile_y_min + tile_height
        overlap_y = min(frame_y_max, tile_y_max) - max(frame_origin_y, tile_y_min)
        if overlap_y <= 0:
            continue
        for col in range(cols):
            tile_x_min = col * tile_width
            tile_x_max = tile_x_min + tile_width
            overlap_x = min(frame_x_max, tile_x_max) - max(frame_origin_x, tile_x_min)
            if overlap_x <= 0:
                continue
            overlapping_tiles += 1
            overlap = overlap_x * overlap_y
            if overlap > best_overlap:
                best_overlap = overlap
                row_from_top = (rows - 1) - row_from_bottom
                best_sheet_number = row_from_top * cols + col + 1
    if best_sheet_number is None:
        return None, "out_of_grid"

    spans = overlapping_tiles > 1
    overflows = frame_origin_x < -tolerance or frame_x_max > grid_width + tolerance or frame_origin_y < -tolerance or frame_y_max > grid_height + tolerance
    if spans and overflows:
        placement: SheetPlacement = "spans_and_overflows"
    elif spans:
        placement = "spans_multiple_sheets"
    elif overflows:
        placement = "overflows_sheet"
    else:
        placement = "fits"
    return best_sheet_number, placement


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


def detect_section_parents(views: list[TeklaDrawingView]) -> dict[str, tuple[str, SectionMark]]:
    """
    Map each section view to the view it was cut from and the mark itself.

    A section view's parent is the view holding a SectionMark whose MarkName
    equals the section view's own name. Only section views with a matching
    mark are included, everything else (front, detail, 3D views, or sections
    whose mark is missing) is omitted.

    Args:
        views: List of TeklaDrawingView wrappers.

    Returns:
        Dict of section_view_key -> (parent_view_key, section_mark). The mark
        is carried through so callers (e.g. `compute_section_alignment`) need
        not re-enumerate the parent's drawing objects to recover it.
    """
    # mark_name -> (view_key, mark) pairs for views holding a mark of that name
    mark_owners: dict[str, list[tuple[str, SectionMark]]] = {}
    for v in views:
        for name, mark in v.get_section_marks():
            mark_owners.setdefault(name, []).append((v.view_key, mark))

    parents: dict[str, tuple[str, SectionMark]] = {}
    for v in views:
        if v.view_type != "SectionView" or not v.name:
            continue
        candidates = [(owner_key, mark) for owner_key, mark in mark_owners.get(v.name, []) if owner_key != v.view_key]
        if not candidates:
            continue
        if len(candidates) > 1:
            logger.warning(
                "Section view '%s' (name '%s') matches section marks in %d views %s; using the first (%s)",
                v.view_key,
                v.name,
                len(candidates),
                [owner_key for owner_key, _ in candidates],
                candidates[0][0],
            )
        parents[v.view_key] = candidates[0]
    return parents


def compute_section_alignment(child_view: TeklaDrawingView, parent_view: TeklaDrawingView, mark: SectionMark) -> tuple[str, float] | None:
    """
    Compute the projection-alignment offset for a section view.

    A horizontal cut aligns X, a vertical cut aligns Y. Alignment shifts
    the section view's origin on the cut axis so the cut midpoint projects
    to the same sheet position in both views.

    Args:
        child_view: TeklaDrawingView for the section view.
        parent_view: TeklaDrawingView for the view it was taken from.
        mark: The SectionMark in `parent_view` that produced `child_view`, as
            returned alongside the parent key by `detect_section_parents`.

    Returns:
        (axis, delta): the cut axis ("x" or "y") and the offset to add to
        the child view's origin on that axis. None if the mark has no
        endpoint geometry.
    """
    lp = getattr(mark, "LeftPoint", None)
    rp = getattr(mark, "RightPoint", None)
    if lp is None or rp is None:
        return None

    if abs(lp.X - rp.X) > abs(lp.Y - rp.Y):
        # Horizontal cut: the views project along X
        mid = (lp.X + rp.X) / 2.0
        target = parent_view.origin_x + mid / parent_view.scale
        current = child_view.origin_x + mid / child_view.scale
        return ("x", target - current)
    else:
        # Vertical cut: the views project along Y
        mid = (lp.Y + rp.Y) / 2.0
        target = parent_view.origin_y + mid / parent_view.scale
        current = child_view.origin_y + mid / child_view.scale
        return ("y", target - current)
