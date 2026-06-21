"""
Drawing utility helpers for Tekla MCP server.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tekla_mcp_server.tekla.wrappers.model import TeklaModel

from tekla_mcp_server.config import get_tolerance
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import StringFilterOption, StringMatchType
from tekla_mcp_server.utils import BBox
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
)
from tekla_mcp_server.tekla.wrappers import TeklaDrawingView


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
            populate `target_guid` for marks. When None it comes back as None.

    Returns:
        dict with at least 'type' and 'category', plus 'content' (marks/text)
        or 'value' (dimensions) when readable. Marks also carry 'target_guid'.
    """
    info: dict[str, Any] = {"type": type(obj).__name__, "category": category}
    try:
        if category == "marks":
            # Section/detail marks expose `.Attributes.MarkName`. A plain Mark's
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
) -> int | None:
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
        The 1-based sheet number of the tile with the largest overlap, or None
        if the frame does not overlap the tiled grid at all within `tolerance`.
    """
    if tolerance is None:
        tolerance = get_tolerance("sheet_size", 1.0, group="drawings")
    grid_width = cols * tile_width
    grid_height = rows * tile_height
    frame_x_max = frame_origin_x + frame_width
    frame_y_max = frame_origin_y + frame_height
    if frame_x_max < -tolerance or frame_origin_x > grid_width + tolerance or frame_y_max < -tolerance or frame_origin_y > grid_height + tolerance:
        return None

    best_sheet_number: int | None = None
    best_overlap = 0.0
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
            overlap = overlap_x * overlap_y
            if overlap > best_overlap:
                best_overlap = overlap
                row_from_top = (rows - 1) - row_from_bottom
                best_sheet_number = row_from_top * cols + col + 1
    return best_sheet_number


def draw_cloud_bbox(view: DrawingView, bbox: BBox, margin: tuple[float, float], color: Any = DrawingColors.Magenta) -> bool:
    """
    Draw a revision cloud around a bounding box in the given drawing view.

    Args:
        view: Tekla drawing view in which to insert.
        bbox: Bounding box in drawing coordinates.
        margin: (margin_x, margin_y) extra space around the bbox (mm) - margin_x
            pads the left/right sides, margin_y pads the top/bottom sides. Pass
            (0.0, 0.0) for a bbox that should be drawn exactly as given (e.g. one
            with its own per-side padding already baked in).
        color: Cloud line color.

    Returns:
        True if inserted successfully.
    """
    x0, y0, x1, y1 = bbox
    margin_x, margin_y = margin
    pts = PointList()
    pts.Add(Point(x0 - margin_x, y0 - margin_y, 0))
    pts.Add(Point(x1 + margin_x, y0 - margin_y, 0))
    pts.Add(Point(x1 + margin_x, y1 + margin_y, 0))
    pts.Add(Point(x0 - margin_x, y1 + margin_y, 0))
    try:
        cloud = Cloud(view, pts)
        cloud.Attributes.Line.Color = color
        cloud.ArcWidth = 5
        if not cloud.Insert():
            logger.warning("draw_cloud_bbox: Cloud.Insert() returned False")
            return False
        return True
    except Exception as e:
        logger.warning("draw_cloud_bbox: failed to insert cloud: %s", e)
        return False


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
