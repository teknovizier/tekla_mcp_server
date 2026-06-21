"""
Unit tests for dxf_operations pairwise-collision helpers.
"""

from tekla_mcp_server.dxf_operations import (
    CLOUD_MARGIN,
    FRAME_CONTENT_PADDING,
    MARK_CLOUD_MARGIN,
    CollisionIssue,
    WorldEntity,
    _collisions,
    _entity_view_keys,
    _view_frame_bbox,
    check_collides_with_sheet,
    check_content_out_of_sheet,
    check_cross_sheet_collision,
    check_cross_view_same_sheet_collision,
    check_marks_leader_overlap,
    check_out_of_grid_with_content,
    merge_issues,
)
from tekla_mcp_server.utils import BBox


def _pairwise_collisions(items, issue_type, label, margin=(0.0, 0.0)):
    """Same-list scan: the unified helper called with one group passed twice."""
    return _collisions(items, items, issue_type, label, margin)


def _cross_collisions(items_a, items_b, issue_type, label, margin=(0.0, 0.0)):
    return _collisions(items_a, items_b, issue_type, label, margin)


def _crossing(parent: str, layer: str = "L", view_key: str = "") -> WorldEntity:
    """An entity whose single segment is the diagonal of the unit square at origin."""
    return WorldEntity(
        layer=layer,
        bbox=BBox(0.0, 0.0, 1.0, 1.0),
        segments=[((0.0, 0.0), (1.0, 1.0))],
        parent=parent,
        view_key=view_key,
    )


def _anti_crossing(parent: str, layer: str = "L", view_key: str = "") -> WorldEntity:
    """An entity whose segment is the opposite diagonal - crosses `_crossing` at (0.5, 0.5)."""
    return WorldEntity(
        layer=layer,
        bbox=BBox(0.0, 0.0, 1.0, 1.0),
        segments=[((0.0, 1.0), (1.0, 0.0))],
        parent=parent,
        view_key=view_key,
    )


def _vertical(parent: str, layer: str = "L", view_key: str = "") -> WorldEntity:
    """A vertical segment through x=0.5 - crosses both diagonals at (0.5, 0.5)."""
    return WorldEntity(
        layer=layer,
        bbox=BBox(0.5, 0.0, 0.5, 1.0),
        segments=[((0.5, 0.0), (0.5, 1.0))],
        parent=parent,
        view_key=view_key,
    )


def _far(parent: str) -> WorldEntity:
    """An entity far from the origin - never collides with the unit-square entities."""
    return WorldEntity(
        layer="L",
        bbox=BBox(100.0, 100.0, 101.0, 101.0),
        segments=[((100.0, 100.0), (101.0, 101.0))],
        parent=parent,
    )


# _pairwise_collisions
def test_pairwise_reports_crossing_distinct_parents():
    a = _crossing("p1")
    b = _anti_crossing("p2")
    issues = _pairwise_collisions([a, b], "t", "lbl")
    assert len(issues) == 1
    assert issues[0].types == {"t"}
    assert issues[0].label == "lbl"
    # bbox is the union of both entities' full bboxes, not the crossing point -
    # the cloud must clear both marks' geometry entirely
    assert issues[0].bbox == BBox(0.0, 0.0, 1.0, 1.0)


def test_pairwise_skips_same_parent():
    a = _crossing("same")
    b = _anti_crossing("same")
    assert _pairwise_collisions([a, b], "t", "lbl") == []


def test_pairwise_skips_non_colliding():
    assert _pairwise_collisions([_crossing("p1"), _far("p2")], "t", "lbl") == []


def test_pairwise_each_unordered_pair_once():
    # Three mutually crossing entities (all meet at (0.5, 0.5)), distinct parents
    # -> C(3,2) = 3 issues, each unordered pair reported exactly once
    items = [_crossing("p1"), _anti_crossing("p2"), _vertical("p3")]
    issues = _pairwise_collisions(items, "t", "lbl")
    assert len(issues) == 3


def test_pairwise_reports_union_of_both_bboxes_with_given_margin():
    # The cloud must wrap both entities' bboxes entirely (their union), not
    # just the crossing sliver where they meet - margin is whatever the
    # caller passes (text-text checks pass MARK_CLOUD_MARGIN, leader-involving
    # checks pass (0, 0); see check_marks_*)
    a = WorldEntity(layer="L", bbox=BBox(-5.0, -5.0, 2.0, 2.0), segments=[((0.0, 0.0), (1.0, 1.0))], parent="p1")
    b = WorldEntity(layer="L", bbox=BBox(-2.0, -2.0, 8.0, 8.0), segments=[((0.0, 1.0), (1.0, 0.0))], parent="p2")
    issues = _pairwise_collisions([a, b], "t", "lbl", margin=(MARK_CLOUD_MARGIN, MARK_CLOUD_MARGIN))
    assert len(issues) == 1
    assert issues[0].bbox == BBox(-5.0, -5.0, 8.0, 8.0)
    assert issues[0].margin == (MARK_CLOUD_MARGIN, MARK_CLOUD_MARGIN)


def test_marks_leader_overlap_sizes_cloud_from_leader_bboxes_with_default_margin():
    leader_a = WorldEntity(layer="TEKLA_MCP_MARKS", bbox=BBox(0.0, 0.0, 100.0, 1.0), segments=[((0.0, 0.5), (100.0, 0.5))], kind="LINE", parent="mark_a")
    leader_b = WorldEntity(layer="TEKLA_MCP_MARKS", bbox=BBox(0.0, 0.0, 1.0, 100.0), segments=[((0.5, 0.0), (0.5, 100.0))], kind="LINE", parent="mark_b")
    issues = check_marks_leader_overlap([], [leader_a, leader_b])
    assert len(issues) == 1
    assert issues[0].bbox == BBox(0.0, 0.0, 100.0, 100.0)
    assert issues[0].margin == (CLOUD_MARGIN, CLOUD_MARGIN)


def test_pairwise_view_keys_union_sorted():
    a = _crossing("p1", view_key="V2")
    b = _anti_crossing("p2", view_key="V1")
    issues = _pairwise_collisions([a, b], "t", "lbl")
    assert sorted(issues[0].view_keys) == ["V1", "V2"]


# _cross_collisions
def test_cross_reports_crossing_distinct_parents():
    issues = _cross_collisions([_crossing("p1")], [_anti_crossing("p2")], "t", "lbl")
    assert len(issues) == 1
    assert issues[0].bbox == BBox(0.0, 0.0, 1.0, 1.0)


def test_cross_skips_same_parent():
    a = _crossing("same")
    b = _anti_crossing("same")
    assert _cross_collisions([a], [b], "t", "lbl") == []


def test_cross_skips_identical_entity_in_both_lists():
    shared = _crossing("p1")
    other = _anti_crossing("p2")
    # shared appears in both lists; `a is b` must skip the self-pair, leaving one real hit
    issues = _cross_collisions([shared, other], [shared, other], "t", "lbl")
    assert len(issues) == 1


def test_cross_dedups_symmetric_pair():
    a = _crossing("p1")
    b = _anti_crossing("p2")
    # Same pair reachable as (a,b) and (b,a) across the lists - must be reported once
    issues = _cross_collisions([a, b], [b, a], "t", "lbl")
    assert len(issues) == 1


# --- _entity_view_keys -----------------------------------------------------


def test_entity_view_keys_drops_empty_and_sorts():
    a = _crossing("p1", view_key="V2")
    b = _anti_crossing("p2", view_key="")
    assert _entity_view_keys(a, b) == ["V2"]


# --- cross-view checks (frame-overlap gating + intersection clip) -----------


def _view(view_key, sheet_number, x0, y0, w=100.0, h=100.0):
    return {
        "is_sheet": False,
        "view_key": view_key,
        "sheet_number": sheet_number,
        "frame_origin_x": x0,
        "frame_origin_y": y0,
        "width": w,
        "height": h,
    }


def _box(bbox, parent="p", layer="TEKLA_MCP_PARTS"):
    """A non-furniture content entity with no segments - collides by bbox overlap."""
    return WorldEntity(layer=layer, bbox=bbox, segments=[], parent=parent)


# Frame A [0,100]x[0,100] (sheet 1) and frame B [95,195]x[0,100] (sheet 2)
# overlap in the thin sliver x in [95,100]. EA's centroid is in A only, EB's in
# B only, but both bboxes reach into the sliver and overlap each other there
def _straddling_views_and_content(sheet_a, sheet_b):
    view_a = _view("A", sheet_a, 0.0, 0.0)
    view_b = _view("B", sheet_b, 95.0, 0.0)
    # centroid x=91.5 -> view A only (frame A x=0-100, frame B x=95-195)
    ea = _box(BBox(85.0, 45.0, 98.0, 55.0), parent="pa")
    ea.view_key = "A"
    # centroid x=103 -> view B only
    eb = _box(BBox(96.0, 45.0, 110.0, 55.0), parent="pb")
    eb.view_key = "B"
    return [view_a, view_b], [ea, eb]


def test_cross_sheet_reports_overlapping_frames_with_colliding_content():
    views, entities = _straddling_views_and_content(sheet_a=1, sheet_b=2)
    issues = check_cross_sheet_collision(views, entities)
    assert len(issues) == 1
    assert issues[0].types == {"cross_sheet_collision"}
    assert sorted(issues[0].view_keys) == ["A", "B"]


def test_cross_sheet_ignores_same_sheet():
    # Same geometry but both views on sheet 1 -> cross-sheet must find nothing
    views, entities = _straddling_views_and_content(sheet_a=1, sheet_b=1)
    assert check_cross_sheet_collision(views, entities) == []


def test_cross_sheet_ignores_non_overlapping_frames():
    # Frames far apart -> no frame overlap -> no comparison
    views = [_view("A", 1, 0.0, 0.0), _view("B", 2, 300.0, 0.0)]
    ea = _box(BBox(40.0, 40.0, 60.0, 60.0), parent="pa")
    ea.view_key = "A"
    eb = _box(BBox(340.0, 40.0, 360.0, 60.0), parent="pb")
    eb.view_key = "B"
    assert check_cross_sheet_collision(views, [ea, eb]) == []


def test_cross_sheet_skips_views_without_sheet_number():
    views, entities = _straddling_views_and_content(sheet_a=None, sheet_b=2)
    assert check_cross_sheet_collision(views, entities) == []


def test_cross_view_same_sheet_reports_one_issue_per_overlapping_pair():
    # Same straddling geometry, both on sheet 1 -> one same-sheet issue for the pair
    views, entities = _straddling_views_and_content(sheet_a=1, sheet_b=1)
    issues = check_cross_view_same_sheet_collision(views, entities)
    assert len(issues) == 1
    assert issues[0].types == {"cross_view_same_sheet_collision"}
    assert sorted(issues[0].view_keys) == ["A", "B"]


def test_cross_view_same_sheet_ignores_different_sheets():
    views, entities = _straddling_views_and_content(sheet_a=1, sheet_b=2)
    assert check_cross_view_same_sheet_collision(views, entities) == []


def test_cross_view_same_sheet_emits_separate_issues_per_colliding_pair():
    """Three scattered entity pairs in the overlap zone -> 3 issues, not one union."""
    view_a = _view("A", 1, 0.0, 0.0)
    view_b = _view("B", 1, 60.0, 0.0)
    # ea entities: centroid x < 60 -> view A only
    ea1 = _box(BBox(30.0, 10.0, 66.0, 20.0), parent="pa1")
    ea1.view_key = "A"
    eb1 = _box(BBox(64.0, 10.0, 120.0, 20.0), parent="pb1")
    eb1.view_key = "B"
    ea2 = _box(BBox(30.0, 50.0, 66.0, 60.0), parent="pa2")
    ea2.view_key = "A"
    eb2 = _box(BBox(64.0, 50.0, 120.0, 60.0), parent="pb2")
    eb2.view_key = "B"
    ea3 = _box(BBox(30.0, 90.0, 66.0, 100.0), parent="pa3")
    ea3.view_key = "A"
    eb3 = _box(BBox(64.0, 90.0, 120.0, 100.0), parent="pb3")
    eb3.view_key = "B"
    issues = check_cross_view_same_sheet_collision([view_a, view_b], [ea1, eb1, ea2, eb2, ea3, eb3])
    assert len(issues) == 3


def test_cross_view_same_sheet_excludes_marks():
    # Marks are already checked precisely (and sized/margined appropriately)
    # by the dedicated check_marks_* checks, which compare marks sheet-wide
    # regardless of view - including them here too would let the same
    # mark-vs-mark crossing also surface as a coarser, redundant "views
    # overlap" cloud
    view_a = _view("A", 1, 0.0, 0.0)
    view_b = _view("B", 1, 95.0, 0.0)
    mark_a = _box(BBox(85.0, 45.0, 98.0, 55.0), parent="pa", layer="TEKLA_MCP_MARKS")
    mark_a.view_key = "A"
    mark_b = _box(BBox(96.0, 45.0, 110.0, 55.0), parent="pb", layer="TEKLA_MCP_MARKS")
    mark_b.view_key = "B"
    assert check_cross_view_same_sheet_collision([view_a, view_b], [mark_a, mark_b]) == []


# check_out_of_grid_with_content
def test_out_of_grid_reports_view_with_content():
    view = _view("A", None, 0.0, 0.0)
    entities = [_box(BBox(10.0, 10.0, 20.0, 20.0), parent="p")]
    issues = check_out_of_grid_with_content([view], entities)
    assert len(issues) == 1
    assert issues[0].types == {"out_of_grid_with_content"}
    assert sorted(issues[0].view_keys) == ["A"]
    # The bbox is the view's true outer frame - no margin should pad it
    assert issues[0].margin == (0.0, 0.0)


def test_out_of_grid_ignores_view_without_content():
    view = _view("A", None, 0.0, 0.0)
    assert check_out_of_grid_with_content([view], []) == []


def test_out_of_grid_ignores_view_with_sheet_number():
    view = _view("A", 1, 0.0, 0.0)
    entities = [_box(BBox(10.0, 10.0, 20.0, 20.0), parent="p")]
    assert check_out_of_grid_with_content([view], entities) == []


def test_out_of_grid_ignores_content_within_frame_padding():
    # Real content sits at least FRAME_CONTENT_PADDING clear
    # of a view's frame edge, so an entity whose centroid falls inside that
    # margin must not count as "content present"
    view = _view("A", None, 0.0, 0.0)
    near_edge = _box(BBox(1.0, 1.0, 2.0, 2.0), parent="p")
    assert check_out_of_grid_with_content([view], [near_edge]) == []


def test_out_of_grid_reports_content_just_past_frame_padding():
    view = _view("A", None, 0.0, 0.0)
    just_inside = _box(BBox(FRAME_CONTENT_PADDING + 1.0, FRAME_CONTENT_PADDING + 1.0, FRAME_CONTENT_PADDING + 2.0, FRAME_CONTENT_PADDING + 2.0), parent="p")
    assert len(check_out_of_grid_with_content([view], [just_inside])) == 1


# _view_frame_bbox
def test_view_frame_bbox_unpadded_matches_true_frame_extent():
    view = _view("A", None, 10.0, 20.0, w=100.0, h=50.0)
    assert _view_frame_bbox(view) == BBox(10.0, 20.0, 110.0, 70.0)


def test_view_frame_bbox_padded_insets_by_frame_content_padding():
    view = _view("A", None, 10.0, 20.0, w=100.0, h=50.0)
    pad = FRAME_CONTENT_PADDING
    assert _view_frame_bbox(view, padded=True) == BBox(10.0 + pad, 20.0 + pad, 110.0 - pad, 70.0 - pad)


# check_content_out_of_sheet
def _sheet(w=100.0, h=100.0):
    return {"is_sheet": True, "view_key": "SHEET", "width": w, "height": h}


def test_content_out_of_sheet_clouds_right_edge_crossing():
    # View frame straddles the sheet's right edge (sheet is 100x100): the
    # frame runs from x=50 to x=150, so it crosses x=100. The cloud must be a
    # strip from the boundary out to the frame's outer edge, spanning the
    # frame's full height - not sized to whatever content happens to be there.
    # The boundary side (x=100) is nudged inward by CLOUD_MARGIN (5.0) so the
    # cloud visibly overlaps the crossing; the outer/top/bottom sides, being
    # the frame's true edges, stay exact - no margin baked in there. The frame
    # is also inset by FRAME_CONTENT_PADDING (5.0) on every side before the
    # crossing strip is computed, since real content is guaranteed that much
    # clear of the frame edge
    sheet = _sheet(100.0, 100.0)
    view = _view("A", 1, 50.0, 0.0, w=100.0, h=50.0)
    issues = check_content_out_of_sheet([sheet, view], [])
    assert len(issues) == 1
    assert issues[0].bbox == BBox(95.0, 5.0, 145.0, 45.0)
    # Boundary-side margin is already baked into the bbox above; an extra
    # uniform CLOUD_MARGIN is still applied at draw time so the cloud reads
    # clearly bigger than the exact colliding region
    assert issues[0].margin == (CLOUD_MARGIN, CLOUD_MARGIN)


def test_content_out_of_sheet_clouds_left_edge_crossing():
    sheet = _sheet(100.0, 100.0)
    view = _view("A", 1, -20.0, 0.0, w=50.0, h=50.0)
    issues = check_content_out_of_sheet([sheet, view], [])
    assert len(issues) == 1
    assert issues[0].bbox == BBox(-15.0, 5.0, 5.0, 45.0)


def test_content_out_of_sheet_unions_multiple_edge_crossings_into_one_cloud():
    # Frame crosses both the right edge (x: 80-120 vs sheet width 100) and the
    # bottom edge (y: 80-120 vs sheet height 100) - must yield ONE issue whose
    # bbox covers both crossing strips, not two separate issues. Each strip's
    # own margin-nudged boundary side (95 and 95 respectively) is less extreme
    # than the other strip's true outer edge (80), so the union is unaffected
    sheet = _sheet(100.0, 100.0)
    view = _view("A", 1, 80.0, 80.0, w=40.0, h=40.0)
    issues = check_content_out_of_sheet([sheet, view], [])
    assert len(issues) == 1
    assert issues[0].bbox == BBox(85.0, 85.0, 115.0, 115.0)


def _double_border_frame(sheet_w, sheet_h, inset=20.0, parent="frame"):
    """Realistic TEKLA_MCP_DRAWING_FRAME geometry: an outer border touching the
    sheet's paper edges exactly, plus an inner border inset from it, plus a
    handful of short corner/fold registration ticks - mirrors the real
    pattern found in an actual Tekla DXF export."""
    ix0, iy0, ix1, iy1 = inset, inset, sheet_w - inset, sheet_h - inset
    entities = [
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(0.0, 0.0, sheet_w, 0.0), segments=[], parent=parent),
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(sheet_w, 0.0, sheet_w, sheet_h), segments=[], parent=parent),
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(0.0, sheet_h, sheet_w, sheet_h), segments=[], parent=parent),
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(0.0, 0.0, 0.0, sheet_h), segments=[], parent=parent),
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(ix0, iy0, ix1, iy0), segments=[], parent=parent),
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(ix1, iy0, ix1, iy1), segments=[], parent=parent),
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(ix0, iy1, ix1, iy1), segments=[], parent=parent),
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(ix0, iy0, ix0, iy1), segments=[], parent=parent),
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(sheet_w / 2 - 0.5, 0.0, sheet_w / 2 + 0.5, inset / 2), segments=[], parent=parent),
        WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(0.0, sheet_h / 2 - 0.5, inset / 2, sheet_h / 2 + 0.5), segments=[], parent=parent),
    ]
    return entities


def test_content_out_of_sheet_uses_real_inset_frame_boundary():
    # The real TEKLA_MCP_DRAWING_FRAME inner border is inset 20mm from the
    # sheet's nominal 200x100 paper edges, so its right edge is at x=180. A
    # view from x=170 to x=190, y=30 to y=50 (clear of the top/bottom inset
    # edges at y=20/80) crosses that real boundary but NOT the nominal paper
    # edge (200) - it would be "fully inside" and never flagged if the check
    # still used the nominal sheet size
    sheet = _sheet(200.0, 100.0)
    frame = _double_border_frame(200.0, 100.0, inset=20.0)
    view = _view("A", 1, 170.0, 30.0, w=20.0, h=20.0)
    issues = check_content_out_of_sheet([sheet, view], frame)
    assert len(issues) == 1
    assert issues[0].bbox == BBox(175.0, 35.0, 185.0, 45.0)


def test_content_out_of_sheet_ignores_small_furniture_not_spanning_sheet():
    # A small, local piece of furniture on the TEKLA_MCP_DRAWING_FRAME layer
    # (e.g. a title-block stamp) must not be mistaken for the real print
    # boundary just because it's "long and doesn't touch the paper edge" -
    # it doesn't span most of the sheet, so the nominal sheet size is used
    # instead, and this view (fully inside the 100x100 sheet) is not flagged
    sheet = _sheet(100.0, 100.0)
    small_furniture = WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(40.0, 10.0, 41.0, 90.0), segments=[], parent="f")
    view = _view("A", 1, 0.0, 0.0, w=100.0, h=100.0)
    assert check_content_out_of_sheet([sheet, view], [small_furniture]) == []


# merge_issues margin passthrough
def test_merge_issues_preserves_margin_for_single_issue():
    issue = CollisionIssue.create("out_of_grid_with_content", "A", BBox(0.0, 0.0, 10.0, 10.0), "out_of_grid", ["A"], margin=(0.0, 0.0))
    merged = merge_issues([issue])
    assert len(merged) == 1
    assert merged[0].margin == (0.0, 0.0)


def test_merge_issues_defaults_margin_when_unspecified():
    issue = CollisionIssue.create("collides_with_sheet", "A", BBox(0.0, 0.0, 10.0, 10.0), "collides with sheet", ["A"])
    merged = merge_issues([issue])
    assert merged[0].margin == (CLOUD_MARGIN, CLOUD_MARGIN)


def test_merge_issues_keeps_zero_margin_when_merged_with_default_margin_issue():
    # A 0-margin issue (exact, pre-padded bbox) merged with a default-margin
    # neighbor must not end up re-inflated by the neighbor's margin, on either axis
    zero_margin_issue = CollisionIssue.create("out_of_grid_with_content", "A", BBox(0.0, 0.0, 10.0, 10.0), "out_of_grid", ["A"], margin=(0.0, 0.0))
    default_margin_issue = CollisionIssue.create("collides_with_sheet", "A", BBox(1.0, 1.0, 9.0, 9.0), "collides with sheet", ["A"])
    merged = merge_issues([zero_margin_issue, default_margin_issue])
    assert len(merged) == 1
    assert merged[0].margin == (0.0, 0.0)


def test_merge_issues_takes_elementwise_min_of_axis_margins():
    # One issue wants no X margin but full Y margin, the other wants no Y
    # margin but full X margin - the merged result must keep both axes at
    # their minimum (0.0) independently, not just the smaller of the two tuples
    x_only_issue = CollisionIssue.create("content_out_of_sheet", "A", BBox(0.0, 0.0, 10.0, 10.0), "out of sheet", ["A"], margin=(CLOUD_MARGIN, 0.0))
    y_only_issue = CollisionIssue.create("content_out_of_sheet", "A", BBox(1.0, 1.0, 9.0, 9.0), "out of sheet", ["A"], margin=(0.0, CLOUD_MARGIN))
    merged = merge_issues([x_only_issue, y_only_issue])
    assert len(merged) == 1
    assert merged[0].margin == (0.0, 0.0)


def test_merge_issues_merges_overlapping_wide_duplicates():
    # Two near-duplicate hits against the same furniture line (e.g. two
    # different parts grazing it a fraction of a mm apart) must still merge
    # into one cloud even when each individual bbox is already wide
    a = CollisionIssue.create("collides_with_sheet", "A", BBox(271.4, 1248.1, 321.4, 1248.1), "collides with sheet", ["A"])
    b = CollisionIssue.create("collides_with_sheet", "A", BBox(271.4, 1248.3, 321.4, 1248.3), "collides with sheet", ["A"])
    merged = merge_issues([a, b])
    assert len(merged) == 1
    assert merged[0].bbox == BBox(271.4, 1248.1, 321.4, 1248.3)


def test_merge_issues_merges_small_cloud_fully_inside_a_wide_one():
    wide = CollisionIssue.create("collides_with_sheet", "A", BBox(206.8, 1218.9, 359.3, 1250.1), "collides with sheet", ["A"])
    contained = CollisionIssue.create("collides_with_sheet", "A", BBox(209.9, 1224.7, 234.0, 1239.0), "collides with sheet", ["A"])
    merged = merge_issues([wide, contained])
    assert len(merged) == 1
    assert merged[0].bbox == wide.bbox


def test_collides_with_sheet_still_reports_view_straddling_sheet_boundary():
    sheet = _sheet(100.0, 100.0)
    view = _view("A", 1, 50.0, 0.0, w=100.0, h=50.0)
    furniture = WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(95.0, 0.0, 105.0, 50.0), segments=[], parent="f", view_key="A")
    content = WorldEntity(layer="L", bbox=BBox(90.0, 10.0, 110.0, 20.0), segments=[], parent="c", view_key="A")
    issues = check_collides_with_sheet([sheet, view], [furniture, content])
    assert len(issues) == 1
    assert issues[0].bbox == BBox(95.0, 5.0, 105.0, 45.0)


def test_collides_with_sheet_reports_view_fully_inside():
    sheet = _sheet(100.0, 100.0)
    view = _view("A", 1, 0.0, 0.0, w=100.0, h=100.0)
    furniture = WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(40.0, 40.0, 60.0, 60.0), segments=[], parent="f", view_key="A")
    content = WorldEntity(layer="L", bbox=BBox(45.0, 45.0, 55.0, 55.0), segments=[], parent="c", view_key="A")
    issues = check_collides_with_sheet([sheet, view], [furniture, content])
    assert len(issues) == 1
    assert issues[0].types == {"collides_with_sheet"}


def test_collides_with_sheet_reports_overlap_with_vertical_frame_border():
    sheet = _sheet(100.0, 100.0)
    view = _view("A", 1, 0.0, 0.0, w=100.0, h=100.0)
    furniture = WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(50.0, 10.0, 51.0, 90.0), segments=[], parent="f", view_key="A")
    content = WorldEntity(layer="L", bbox=BBox(45.0, 40.0, 55.0, 60.0), segments=[], parent="c", view_key="A")
    issues = check_collides_with_sheet([sheet, view], [furniture, content])
    assert len(issues) == 1
    assert issues[0].bbox == BBox(50.0, 10.0, 51.0, 90.0)
    assert issues[0].margin == (CLOUD_MARGIN, CLOUD_MARGIN)


def test_collides_with_sheet_reports_overlap_with_horizontal_frame_border():
    sheet = _sheet(100.0, 100.0)
    view = _view("A", 1, 0.0, 0.0, w=100.0, h=100.0)
    furniture = WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(10.0, 50.0, 90.0, 51.0), segments=[], parent="f", view_key="A")
    content = WorldEntity(layer="L", bbox=BBox(40.0, 45.0, 60.0, 55.0), segments=[], parent="c", view_key="A")
    issues = check_collides_with_sheet([sheet, view], [furniture, content])
    assert len(issues) == 1
    assert issues[0].bbox == BBox(10.0, 50.0, 90.0, 51.0)
    assert issues[0].margin == (CLOUD_MARGIN, CLOUD_MARGIN)


def test_content_out_of_sheet_ignores_view_fully_inside():
    sheet = _sheet(100.0, 100.0)
    view = _view("A", 1, 0.0, 0.0, w=100.0, h=100.0)
    assert check_content_out_of_sheet([sheet, view], []) == []


def test_content_out_of_sheet_ignores_view_fully_outside():
    # Caught by check_out_of_grid_with_content instead
    sheet = _sheet(100.0, 100.0)
    view = _view("A", None, 200.0, 0.0, w=50.0, h=50.0)
    assert check_content_out_of_sheet([sheet, view], []) == []
