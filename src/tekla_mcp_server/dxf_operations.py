"""
DXF operations.

Exports the active drawing to DXF, resolves entities to world space, and runs
geometric collision checks across all annotation categories. Each check is
independent. New checks are added by writing a function and appending it to
CHECKS.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from ezdxf import bbox as dxf_bbox

from tekla_mcp_server.utils import BBox, Segment

# DXF layers that represent non-annotation sheet furniture
SHEET_FURNITURE_LAYERS = {"TEKLA_MCP_DRAWING_FRAME", "TEKLA_MCP_DRAWING_TABLE"}
# DXF layers that carry mark annotations
MARK_LAYERS = {"TEKLA_MCP_MARKS", "TEKLA_MCP_DETAIL_MARKS", "TEKLA_MCP_WELD_MARKS"}


# Empty space between a view's frame rectangle and any real content drawn inside it
FRAME_CONTENT_PADDING = 5.0
# Margin around a collision cloud for visual grouping
CLOUD_MARGIN = 5.0
# Margin around a mark collision cloud
MARK_CLOUD_MARGIN = 20.0
# Max gap between issue bboxes to merge them into one group
MERGE_DISTANCE = 25.0


class WorldEntity:
    """A DXF entity flattened to world coordinates, tagged with metadata."""

    def __init__(
        self,
        layer: str,
        bbox: BBox,
        segments: list[Segment],
        kind: str = "",
        parent: str = "",
        view_key: str = "",
    ):
        self.layer = layer
        self.bbox = bbox
        self.segments = segments
        self.kind = kind
        self.parent = parent
        self.view_key = view_key


@dataclass
class CollisionIssue:
    """A collision issue with accumulated merge state."""

    types: set[str]
    bbox: BBox
    labels: set[str]
    views: set[str]
    view_keys: set[str]
    margin: tuple[float, float]

    @property
    def label(self) -> str:
        """Human-readable label, joining all merged-in labels."""
        return " + ".join(sorted(self.labels))

    @classmethod
    def create(
        cls,
        type_: str,
        view: str,
        bbox: BBox,
        label: str,
        view_keys: list[str],
        margin: tuple[float, float] | None = None,
    ) -> CollisionIssue:
        """
        Create a single-issue instance (pre-merge).

        Args:
            type_: Check type identifier.
            view: View identifier string.
            bbox: Collision bounding box.
            label: Human-readable label.
            view_keys: View keys this issue spans.
            margin: Cloud padding, defaults to (CLOUD_MARGIN, CLOUD_MARGIN).
        """
        m = margin if margin is not None else (CLOUD_MARGIN, CLOUD_MARGIN)
        return cls(
            types={type_},
            bbox=bbox,
            labels={label},
            views={view},
            view_keys=set(view_keys),
            margin=m,
        )

    def merge(self, other: CollisionIssue) -> None:
        """Absorb another issue into this merged group."""
        self.bbox = self.bbox.union(other.bbox)
        self.views.update(other.views)
        self.types.update(other.types)
        self.labels.update(other.labels)
        self.view_keys.update(other.view_keys)
        self.margin = (min(self.margin[0], other.margin[0]), min(self.margin[1], other.margin[1]))


def _view_frame_bbox(v: dict, *, padded: bool = False) -> BBox:
    """Build a view's frame bbox from its dict fields.

    `padded=True` insets by `FRAME_CONTENT_PADDING` - the empty space
    inside a frame edge, so a crossing within it is never a real
    content collision. Use padded for boundary/furniture/content checks,
    unpadded where the frame's true outer extent matters (overlaps, clouds).
    """
    fx, fy = v["frame_origin_x"], v["frame_origin_y"]
    bbox = BBox(fx, fy, fx + v["width"], fy + v["height"])
    return bbox.inset(FRAME_CONTENT_PADDING) if padded else bbox


def entity_in_view(entity: WorldEntity, frame_bbox: BBox) -> bool:
    """Return True if the entity's centroid lies inside the given view frame."""
    return frame_bbox.contains_point(entity.bbox.cx, entity.bbox.cy)


def segment_intersection_point(p1, p2, p3, p4) -> tuple[float, float] | None:
    """Return the intersection point of line segments (p1-p2) and (p3-p4), or None."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    # Parametric line intersection using cross-product denominator
    denom = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(denom) < 1e-12:
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / denom
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return x1 + t * (x2 - x1), y1 + t * (y2 - y1)
    return None


def _segment_intersects_bbox(seg: Segment, bbox: BBox) -> bool:
    """Check if a line segment enters the given axis-aligned bounding box."""
    p1, p2 = seg
    if bbox.contains_point(p1[0], p1[1]):
        return True
    if bbox.contains_point(p2[0], p2[1]):
        return True
    edges: list[Segment] = [
        Segment(bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymin),
        Segment(bbox.xmax, bbox.ymin, bbox.xmax, bbox.ymax),
        Segment(bbox.xmax, bbox.ymax, bbox.xmin, bbox.ymax),
        Segment(bbox.xmin, bbox.ymax, bbox.xmin, bbox.ymin),
    ]
    for edge in edges:
        if segment_intersection_point(p1, p2, edge[0], edge[1]):
            return True
    return False


def collision_bbox(a: WorldEntity, b: WorldEntity) -> BBox | None:
    """
    Return the overlapping bbox between two entities, or None.

    Uses segment-level intersection when both entities have geometry.
    Checks segment-vs-bbox when only one has segments.
    Falls back to bbox-vs-bbox otherwise.
    """
    if not a.bbox.overlaps(b.bbox):
        return None
    inter = a.bbox.intersection(b.bbox)
    if inter is None:
        return None
    if a.segments and b.segments:
        for sa in a.segments:
            for sb in b.segments:
                pt = segment_intersection_point(sa[0], sa[1], sb[0], sb[1])
                if pt:
                    return BBox(pt[0], pt[1], pt[0], pt[1])
        return None
    if a.segments:
        if any(_segment_intersects_bbox(sa, b.bbox) for sa in a.segments):
            return inter
        return None
    if b.segments:
        if any(_segment_intersects_bbox(sb, a.bbox) for sb in b.segments):
            return inter
        return None
    return inter


def resolve_entities(doc, msp) -> list[WorldEntity]:
    """
    Flatten every block-internal entity to world space.

    Iterates over INSERT entities in modelspace, resolves each block
    reference, and transforms its sub-entities through the insert's
    transformation matrix into world coordinates.
    """
    entities: list[WorldEntity] = []
    for insert in msp.query("INSERT"):
        block = doc.blocks.get(insert.dxf.name)
        # 4x4 transformation matrix from block-local to world coordinates
        matrix = insert.matrix44()

        def to_world(x: float, y: float) -> tuple[float, float]:
            p = matrix.transform((x, y, 0))
            return p.x, p.y

        for e in block:
            t = e.dxftype()
            local_points: list[tuple[float, float]] = []
            local_segments: list[Segment] = []
            if t == "LINE":
                p0 = (e.dxf.start[0], e.dxf.start[1])
                p1 = (e.dxf.end[0], e.dxf.end[1])
                local_points = [p0, p1]
                local_segments = [Segment(p0[0], p0[1], p1[0], p1[1])]
            elif t == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in e.get_points("xy")]
                local_points = pts
                # Break polyline into individual edge segments
                local_segments = [Segment(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) for i in range(len(pts) - 1)]
                # Close the loop for closed polylines
                if e.closed and len(pts) > 1:
                    local_segments.append(Segment(pts[-1][0], pts[-1][1], pts[0][0], pts[0][1]))
            elif t == "CIRCLE":
                local_points = [(e.dxf.center[0], e.dxf.center[1])]
            elif t == "ARC":
                local_points = [(e.dxf.center[0], e.dxf.center[1])]
            elif t in ("TEXT", "MTEXT"):
                local_bbox = dxf_bbox.extents([e])
                x0, y0 = local_bbox.extmin[0], local_bbox.extmin[1]
                x1, y1 = local_bbox.extmax[0], local_bbox.extmax[1]
                # Guard against degenerate bbox (e.g. empty string)
                if x1 <= x0 and y1 <= y0:
                    continue
                local_points = [(x0, y0), (x1, y1)]
            else:
                continue

            world_points = [to_world(x, y) for x, y in local_points]
            world_segments = [Segment(*(to_world(*p0)), *(to_world(*p1))) for p0, p1 in local_segments]
            entities.append(
                WorldEntity(
                    e.dxf.layer,
                    BBox.from_points(world_points),
                    world_segments,
                    kind=t,
                    parent=insert.dxf.name,
                )
            )
    return entities


def assign_entity_views(entities: list[WorldEntity], views: list[dict]) -> None:
    """
    Tag each entity with the view_key by parent block suffix, falling back to centroid.
    """
    # Build suffix -> view_key lookup (e.g. '9470' -> 'SectionView_9470')
    suffix_to_view: dict[str, str] = {}
    for v in views:
        if v.get("is_sheet"):
            continue
        suffix = v["view_key"].rsplit("_", 1)[-1]
        suffix_to_view[suffix] = v["view_key"]

    for entity in entities:
        # Primary: parent block suffix
        if " - " in entity.parent:
            parent_suffix = entity.parent.rsplit(" - ", 1)[-1]
            if parent_suffix in suffix_to_view:
                entity.view_key = suffix_to_view[parent_suffix]
                continue
        # Fallback: centroid-in-frame (for entities whose parent name has
        # no recognisable suffix)
        for v in views:
            if v.get("is_sheet"):
                continue
            if _view_frame_bbox(v).contains_point(entity.bbox.cx, entity.bbox.cy):
                entity.view_key = v["view_key"]
                break


def check_out_of_grid_with_content(views: list[dict], entities: list[WorldEntity]) -> list[CollisionIssue]:
    """
    Views entirely outside the sheet grid that still have real content.

    `sheet_number` is None when a view's frame doesn't overlap the tiled
    sheet grid at all (see `assign_sheet_number`). Content placed there
    would otherwise never print and never get flagged by any other check.
    """
    issues: list[CollisionIssue] = []
    for v in views:
        if v.get("is_sheet") or v.get("sheet_number") is not None:
            continue
        frame_bbox = _view_frame_bbox(v)
        content_bbox = _view_frame_bbox(v, padded=True)
        has_content = any(e.layer not in SHEET_FURNITURE_LAYERS and content_bbox.contains_point(e.bbox.cx, e.bbox.cy) for e in entities)
        if has_content:
            issues.append(
                CollisionIssue.create(
                    type_="out_of_grid_with_content",
                    view=v["view_key"],
                    bbox=frame_bbox,
                    label="out_of_grid",
                    view_keys=[v["view_key"]],
                    # frame_bbox is the view's true outer frame - no boundary
                    # crossing to highlight, so no margin should pad it
                    margin=(0.0, 0.0),
                )
            )
    return issues


def _inset_frame_boundary(entities: list[WorldEntity], sheet_w: float, sheet_h: float) -> BBox | None:
    """
    The real, inset print-area boundary from `TEKLA_MCP_DRAWING_FRAME` geometry.

    A drawing frame is an outer border on the paper edge plus an inner,
    inset border (the real print boundary) and short corner/fold ticks.
    Isolates long lines that don't touch the paper edge and whose combined
    bbox spans most of the sheet - this rules out short ticks and small,
    local furniture (e.g. a title-block stamp). Returns None if no such
    geometry exists; callers then fall back to the sheet's nominal size.
    """
    frame_entities = [e for e in entities if e.layer == "TEKLA_MCP_DRAWING_FRAME"]
    if not frame_entities:
        return None
    tol = 1e-3
    long_threshold = 0.1 * min(sheet_w, sheet_h)
    inset_lines = [
        e for e in frame_entities if max(e.bbox.width, e.bbox.height) > long_threshold and e.bbox.xmin > tol and e.bbox.ymin > tol and e.bbox.xmax < sheet_w - tol and e.bbox.ymax < sheet_h - tol
    ]
    if not inset_lines:
        return None
    bx0 = min(e.bbox.xmin for e in inset_lines)
    by0 = min(e.bbox.ymin for e in inset_lines)
    bx1 = max(e.bbox.xmax for e in inset_lines)
    by1 = max(e.bbox.ymax for e in inset_lines)
    if (bx1 - bx0) < 0.5 * sheet_w or (by1 - by0) < 0.5 * sheet_h:
        return None
    return BBox(bx0, by0, bx1, by1)


def _sheet_boundary(views: list[dict], entities: list[WorldEntity]) -> BBox | None:
    """
    The boundary to check views against.

    Uses the real inset `TEKLA_MCP_DRAWING_FRAME` geometry when present (see
    `_inset_frame_boundary`), otherwise falls back to the sheet's nominal
    width/height starting at the origin. Returns None if there's no sheet view.
    """
    sheet = next((v for v in views if v.get("is_sheet")), None)
    if sheet is None:
        return None
    sw, sh = sheet["width"], sheet["height"]
    return _inset_frame_boundary(entities, sw, sh) or BBox(0.0, 0.0, sw, sh)


def _straddling_view_keys(views: list[dict], boundary: BBox) -> set[str]:
    """
    View keys whose (padded) frame partially overlaps the given boundary.

    A straddling view already gets its own cloud from `check_content_out_of_sheet`;
    other boundary/furniture checks should skip these to avoid redundant clouds.
    """
    bx0, by0, bx1, by1 = boundary
    straddling: set[str] = set()
    for v in views:
        if v.get("is_sheet"):
            continue
        fx, fy, fx1, fy1 = _view_frame_bbox(v, padded=True)
        fully_outside = fx1 <= bx0 or fy1 <= by0 or fx >= bx1 or fy >= by1
        fully_inside = fx >= bx0 and fy >= by0 and fx1 <= bx1 and fy1 <= by1
        if not fully_outside and not fully_inside:
            straddling.add(v["view_key"])
    return straddling


def check_collides_with_sheet(views: list[dict], entities: list[WorldEntity]) -> list[CollisionIssue]:
    """
    View frame overlapping the drawing frame or drawing table.

    Reports one issue per view, unioning all frame-furniture overlaps. Skips
    views with no non-furniture content. Straddling views are NOT skipped
    (unlike other boundary checks) - a view can cross the print boundary on
    one side while separately hitting unrelated furniture elsewhere, and
    that's a distinct issue `check_content_out_of_sheet` doesn't catch.
    """
    issues: list[CollisionIssue] = []
    sheet_entities = [e for e in entities if e.layer in SHEET_FURNITURE_LAYERS]
    if not sheet_entities:
        return issues

    for v in views:
        if v.get("is_sheet"):
            continue
        # Skip views with no non-furniture content
        has_content = any(e.view_key == v["view_key"] and e.layer not in SHEET_FURNITURE_LAYERS for e in entities)
        if not has_content:
            continue
        frame_bbox = _view_frame_bbox(v, padded=True)
        # Union all frame-furniture overlap regions into one bbox
        union: BBox | None = None
        for s in sheet_entities:
            overlap = frame_bbox.intersection(s.bbox)
            if overlap is not None:
                union = overlap if union is None else union.union(overlap)
        if union is not None:
            issues.append(
                CollisionIssue.create(
                    type_="collides_with_sheet",
                    view=v["view_key"],
                    bbox=union,
                    label="collides with sheet",
                    view_keys=[v["view_key"]],
                    margin=(CLOUD_MARGIN, CLOUD_MARGIN),
                )
            )
    return issues


def _collide_content_pairs(content_a: list[WorldEntity], content_b: list[WorldEntity], seen_pairs: set[tuple[int, int]]) -> Iterator[tuple[WorldEntity, WorldEntity, BBox]]:
    """
    Yield (entity_a, entity_b, hit_bbox) for colliding, non-mark-vs-mark, not-yet-seen pairs.

    Shared by `check_cross_sheet_collision` and `check_cross_view_same_sheet_collision`,
    which differ only in how they label the resulting issue. `seen_pairs` is owned by
    the caller and shared across the whole scan (not reset per frame pair), so the
    same entity pair reachable through more than one overlapping frame pair is still
    reported once.
    """
    for entity_a in content_a:
        for entity_b in content_b:
            if entity_a is entity_b:
                continue
            if entity_a.layer in MARK_LAYERS and entity_b.layer in MARK_LAYERS:
                continue
            pair_key = (id(entity_a), id(entity_b)) if id(entity_a) < id(entity_b) else (id(entity_b), id(entity_a))
            if pair_key in seen_pairs:
                continue
            hit_bbox = collision_bbox(entity_a, entity_b)
            if hit_bbox:
                seen_pairs.add(pair_key)
                yield entity_a, entity_b, hit_bbox


def check_cross_sheet_collision(views: list[dict], entities: list[WorldEntity]) -> list[CollisionIssue]:
    """
    Content on one sheet colliding with content on another.

    Two views' content can only collide where their frame boxes overlap, so we
    gate on frame-pair overlap (cheap - views are few) and compare only the
    content each view places inside that intersection region. Different-sheet
    frames are tiled apart and rarely overlap, which collapses what was a global
    O(n^2) scan over every tagged entity into a handful of small, local checks.
    """
    issues: list[CollisionIssue] = []
    seen_pairs: set[tuple[int, int]] = set()
    for sheet_a, view_a, sheet_b, view_b, content_a, content_b in _overlapping_view_pairs(views, entities, same_sheet=False):
        for entity_a, entity_b, hit_bbox in _collide_content_pairs(content_a, content_b, seen_pairs):
            issues.append(
                CollisionIssue.create(
                    type_="cross_sheet_collision",
                    view=f"{view_a} (sheet {sheet_a}) x {view_b} (sheet {sheet_b})",
                    bbox=hit_bbox,
                    label=f"sheet {sheet_a} vs sheet {sheet_b}",
                    view_keys=[view_a, view_b],
                )
            )
    return issues


def check_cross_view_same_sheet_collision(views: list[dict], entities: list[WorldEntity]) -> list[CollisionIssue]:
    """
    Two different views on the same sheet whose content crosses.

    One issue per colliding entity pair - not unioned into one per view pair.
    Mark-vs-mark pairs are skipped (handled by dedicated check_marks_* checks).
    """
    issues: list[CollisionIssue] = []
    seen_pairs: set[tuple[int, int]] = set()
    for sheet_a, view_a, _sheet_b, view_b, content_a, content_b in _overlapping_view_pairs(views, entities, same_sheet=True):
        for entity_a, entity_b, hit_bbox in _collide_content_pairs(content_a, content_b, seen_pairs):
            issues.append(
                CollisionIssue.create(
                    type_="cross_view_same_sheet_collision",
                    view=f"{view_a} x {view_b} (sheet {sheet_a})",
                    bbox=hit_bbox,
                    label="view overlap",
                    view_keys=[view_a, view_b],
                )
            )
    return issues


TEXT_KINDS = {"TEXT", "MTEXT"}
LEADER_KINDS = {"LINE", "LWPOLYLINE"}


def _mark_texts(entities: list[WorldEntity]) -> list[WorldEntity]:
    """Mark label entities (text-like) across the drawing."""
    return [e for e in entities if e.layer in MARK_LAYERS and e.kind in TEXT_KINDS]


def _mark_leaders(entities: list[WorldEntity]) -> list[WorldEntity]:
    """Mark leader-line entities across the drawing."""
    return [e for e in entities if e.layer in MARK_LAYERS and e.kind in LEADER_KINDS]


def check_marks_text_overlap(views: list[dict], entities: list[WorldEntity]) -> list[CollisionIssue]:
    """Two mark labels whose bounding boxes overlap."""
    texts = _mark_texts(entities)
    return _collisions(texts, texts, "marks_text_overlap", "text", margin=(MARK_CLOUD_MARGIN, MARK_CLOUD_MARGIN))


def check_marks_leader_overlap(views: list[dict], entities: list[WorldEntity]) -> list[CollisionIssue]:
    """Two mark leader lines that cross each other."""
    leaders = _mark_leaders(entities)
    return _collisions(leaders, leaders, "marks_leader_overlap", "leader", margin=(CLOUD_MARGIN, CLOUD_MARGIN))


def check_marks_text_leader_overlap(views: list[dict], entities: list[WorldEntity]) -> list[CollisionIssue]:
    """A mark's leader passing through a different mark's label text."""
    return _collisions(_mark_texts(entities), _mark_leaders(entities), "marks_text_leader_overlap", "text+leader", margin=(CLOUD_MARGIN, CLOUD_MARGIN))


def _out_of_sheet_issue(view_key: str, bbox: BBox) -> CollisionIssue:
    return CollisionIssue.create(
        type_="content_out_of_sheet",
        view=view_key,
        bbox=bbox,
        label="out of sheet",
        view_keys=[view_key],
        # The boundary-side coordinate of each crossing strip below is
        # already nudged inward by CLOUD_MARGIN, so this bbox is the exact
        # colliding/outside region - apply one more uniform CLOUD_MARGIN here
        # so the final cloud is comfortably bigger than that region and reads
        # clearly as a cloud rather than hugging the content too tightly
        margin=(CLOUD_MARGIN, CLOUD_MARGIN),
    )


def check_content_out_of_sheet(views: list[dict], entities: list[WorldEntity]) -> list[CollisionIssue]:
    """
    Views whose frame extends beyond the sheet's print boundary.

    Skips views fully inside or outside the boundary (the latter is caught
    by the out_of_grid check). Multiple crossed edges merge into one cloud
    per view. Each strip's boundary-side coordinate is nudged inward by
    `CLOUD_MARGIN` so the cloud visibly overlaps the crossing; the frame's
    true outer edges are left exact.
    """
    boundary = _sheet_boundary(views, entities)
    if boundary is None:
        return []
    bx0, by0, bx1, by1 = boundary
    straddling = _straddling_view_keys(views, boundary)

    issues: list[CollisionIssue] = []
    for v in views:
        if v.get("is_sheet") or v["view_key"] not in straddling:
            continue
        fx, fy, fx1, fy1 = _view_frame_bbox(v, padded=True)
        crossing_bbox: BBox | None = None
        if fx1 > bx1:
            crossing_bbox = BBox(bx1 - CLOUD_MARGIN, fy, fx1, fy1)
        if fx < bx0:
            strip = BBox(fx, fy, bx0 + CLOUD_MARGIN, fy1)
            crossing_bbox = strip if crossing_bbox is None else crossing_bbox.union(strip)
        if fy1 > by1:
            strip = BBox(fx, by1 - CLOUD_MARGIN, fx1, fy1)
            crossing_bbox = strip if crossing_bbox is None else crossing_bbox.union(strip)
        if fy < by0:
            strip = BBox(fx, fy, fx1, by0 + CLOUD_MARGIN)
            crossing_bbox = strip if crossing_bbox is None else crossing_bbox.union(strip)
        if crossing_bbox is not None:
            issues.append(_out_of_sheet_issue(v["view_key"], crossing_bbox))
    return issues


# All collision checks registered in order of execution.
# Each function has the signature (views, entities) -> list[CollisionIssue].
# Add new checks by writing a function and appending it here
CHECKS = [
    check_out_of_grid_with_content,
    check_collides_with_sheet,
    check_cross_sheet_collision,
    check_cross_view_same_sheet_collision,
    check_marks_text_overlap,
    check_marks_leader_overlap,
    check_marks_text_leader_overlap,
    check_content_out_of_sheet,
]


def _overlapping_view_pairs(views: list[dict], entities: list[WorldEntity], same_sheet: bool):
    """
    Yield overlapping view-frame pairs (filtered by same/different-sheet),
    with each view's content clipped to the frame intersection.

    Far-apart views are skipped outright (broad-phase prune, avoids O(n^2)
    over every entity). Marks are included in content_a/content_b - callers
    skip mark-vs-mark pairs themselves but still need mark-vs-part crossings.

    Yields (sheet_a, view_a, sheet_b, view_b, content_a, content_b).
    """
    # Collect non-sheet view frames with their sheet number and bbox
    frames = []
    for v in views:
        if v.get("is_sheet"):
            continue
        sheet_number = v.get("sheet_number")
        if sheet_number is None:
            continue
        frames.append((sheet_number, v["view_key"], _view_frame_bbox(v)))

    # Pre-compute entities assigned to each view (excluding sheet furniture).
    # Uses `view_key` from `assign_entity_views` rather than centroid-in-frame, so
    # entities in the overlap zone between two views are only compared from their
    # own view's side - not double-counted into the other view's content.
    # Marks are included here too: the callers skip mark-vs-mark pairs (handled
    # by dedicated check_marks_* checks) but mark-vs-part crossings are real
    content_by_view = {view_key: [e for e in entities if e.layer not in SHEET_FURNITURE_LAYERS and e.view_key == view_key] for _, view_key, _ in frames}

    for i, (sheet_a, view_a, bbox_a) in enumerate(frames):
        for sheet_b, view_b, bbox_b in frames[i + 1 :]:
            # Filter by same/different-sheet and skip non-overlapping frames
            if (sheet_a == sheet_b) != same_sheet or not bbox_a.overlaps(bbox_b):
                continue
            # Compute the intersection region of the two frame bboxes
            inter = bbox_a.intersection(bbox_b)
            if inter is None:
                continue
            # Only compare entities that reach the overlap region
            content_a = [e for e in content_by_view[view_a] if e.bbox.overlaps(inter)]
            content_b = [e for e in content_by_view[view_b] if e.bbox.overlaps(inter)]
            yield sheet_a, view_a, sheet_b, view_b, content_a, content_b


def _entity_view_keys(a: WorldEntity, b: WorldEntity) -> list[str]:
    """Return sorted list of non-empty view keys from two entities."""
    return sorted({k for k in (a.view_key, b.view_key) if k})


def _collisions(items_a: list[WorldEntity], items_b: list[WorldEntity], issue_type: str, label: str, margin: tuple[float, float]) -> list[CollisionIssue]:
    """
    Report collisions between distinct, different-parent entities across two lists.

    Pass the same list twice for an all-pairs scan within one group - `seen_pairs`
    collapses the symmetric (a, b)/(b, a) duplicate. The reported bbox is the
    union of both bboxes, padded by `margin` (text-text needs clearance from
    the label; leader pairs pass margin=(0, 0) since the leader's own bbox
    already spans its length).

    Note:
        Runtime is O(len(items_a) * len(items_b)) - slow for drawings with
        hundreds of marks.
    """
    issues: list[CollisionIssue] = []
    # Track already-reported entity pairs to avoid symmetric duplicates
    seen_pairs = set()
    for a in items_a:
        for b in items_b:
            if a is b or a.parent == b.parent:
                continue
            pair_key = (id(a), id(b)) if id(a) < id(b) else (id(b), id(a))
            if pair_key in seen_pairs:
                continue
            if collision_bbox(a, b):
                seen_pairs.add(pair_key)
                issues.append(
                    CollisionIssue.create(
                        type_=issue_type,
                        view=f"{a.layer} x {b.layer}",
                        bbox=a.bbox.union(b.bbox),
                        label=label,
                        view_keys=_entity_view_keys(a, b),
                        margin=margin,
                    )
                )
    return issues


def merge_issues(issues: list[CollisionIssue]) -> list[CollisionIssue]:
    """
    Group nearby issues with the same or similar location into merged entries.

    Two issues merge if the gap between their bboxes is within `MERGE_DISTANCE`
    (0 if they overlap). Merged entries accumulate sets of types, labels,
    views, and view_keys.

    Note:
        Runtime is O(len(issues) * len(merged)) - slow only if a drawing
        produces thousands of scattered, non-mergeable issues.
    """
    merged: list[CollisionIssue] = []
    for issue in issues:
        match = None
        # Find an existing merged entry close enough to absorb this issue
        for m in merged:
            if m.bbox.gap(issue.bbox) > MERGE_DISTANCE:
                continue
            match = m
            break
        if match:
            match.merge(issue)
        else:
            # Start a new merged group
            merged.append(issue)
    return merged


def run_collision_checks(views: list[dict], entities: list[WorldEntity]) -> list[CollisionIssue]:
    """
    Run all collision checks and return merged issues.

    Args:
        views: Drawing view dicts (from get_drawing_views's structured_content["views"]).
        entities: Flattened world-space entities (from resolve_entities).

    Returns:
        List of merged CollisionIssue instances.

    Note:
        The mark-vs-mark checks and `merge_issues` are quadratic in marks/issues
        (see their own docstrings); view-pair checks are quadratic in views but
        gate on frame overlap first. Slower on drawings with hundreds of marks
        or views.
    """
    assign_entity_views(entities, views)
    raw_issues: list[CollisionIssue] = []
    for check in CHECKS:
        raw_issues.extend(check(views, entities))
    # Sort by bbox area descending so large-span issues (e.g. leaders
    # crossing the whole view) form the initial merge clusters. Smaller
    # issues that sit inside those spans then merge in, avoiding
    # order-dependent splits when a late check adds a wide issue that
    # should have bridged two earlier narrow clusters
    raw_issues.sort(key=lambda i: i.bbox.area, reverse=True)
    return merge_issues(raw_issues)
