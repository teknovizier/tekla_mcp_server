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
    align_entities_to_sheet,
    sheet_alignment_offset,
    check_collides_with_sheet,
    check_content_out_of_sheet,
    check_cross_sheet_collision,
    check_cross_view_same_sheet_collision,
    check_marks_leader_overlap,
    check_out_of_grid_with_content,
    collect_attach_targets,
    dimension_point_is_attached,
    merge_issues,
    on_any_horizontal_edge,
    on_any_vertical_edge,
    point_is_attached,
    resolve_entities,
    shortened_axis_to_sheet,
    shortening_gaps_from_boxes,
    view_local_to_sheet,
)
from tekla_mcp_server.utils import BBox, Segment

import ezdxf


def _pairwise_collisions(items, issue_type, label, margin=(0.0, 0.0)):
    """Same-list scan: helper called with one group passed twice."""
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
    # bbox is the union of both bboxes, not the crossing point -
    # the cloud must clear both marks' geometry
    assert issues[0].bbox == BBox(0.0, 0.0, 1.0, 1.0)


def test_pairwise_skips_same_parent():
    a = _crossing("same")
    b = _anti_crossing("same")
    assert _pairwise_collisions([a, b], "t", "lbl") == []


def test_pairwise_skips_non_colliding():
    assert _pairwise_collisions([_crossing("p1"), _far("p2")], "t", "lbl") == []


def test_pairwise_each_unordered_pair_once():
    # Three crossing entities, distinct parents -> C(3,2) = 3 issues
    items = [_crossing("p1"), _anti_crossing("p2"), _vertical("p3")]
    issues = _pairwise_collisions(items, "t", "lbl")
    assert len(issues) == 3


def test_pairwise_reports_union_of_both_bboxes_with_given_margin():
    # Cloud wraps both bboxes (their union), not just the crossing sliver.
    # Margin is whatever the caller passes
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
    # `a is b` skips the self-pair, leaving one real hit
    issues = _cross_collisions([shared, other], [shared, other], "t", "lbl")
    assert len(issues) == 1


def test_cross_dedups_symmetric_pair():
    a = _crossing("p1")
    b = _anti_crossing("p2")
    # Same pair reachable as (a,b) and (b,a) - reported once
    issues = _cross_collisions([a, b], [b, a], "t", "lbl")
    assert len(issues) == 1


# _entity_view_keys
def test_entity_view_keys_drops_empty_and_sorts():
    a = _crossing("p1", view_key="V2")
    b = _anti_crossing("p2", view_key="")
    assert _entity_view_keys(a, b) == ["V2"]


# cross-view checks
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
# overlap in x=[95,100]. EA centroid in A only, EB in B only,
# both bboxes reach into the sliver and overlap
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
    # Both views on sheet 1 -> cross-sheet finds nothing
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
    # Marks are checked by dedicated check_marks_* checks.
    # Including them here would create a redundant "views overlap" cloud
    # on top of the precise mark-vs-mark one
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


def test_inset_collapses_only_the_axis_that_is_too_thin():
    # A long, thin box must keep its long axis. Collapsing both would reduce a
    # narrow view frame to a point and hide it from every inset-frame check.
    inset = BBox(0.0, 0.0, 1000.0, 5.0).inset(5.0)
    assert inset.width == 990.0
    assert inset.height == 0.0
    assert (inset.cy, inset.ymin, inset.ymax) == (2.5, 2.5, 2.5)

    # Thin on X instead
    inset = BBox(0.0, 0.0, 5.0, 1000.0).inset(5.0)
    assert inset.width == 0.0
    assert inset.height == 990.0


def test_inset_unchanged_for_boxes_wider_than_the_padding():
    # Normal frames must be untouched by the per-axis handling
    assert BBox(0.0, 0.0, 1000.0, 500.0).inset(5.0) == BBox(5.0, 5.0, 995.0, 495.0)


def test_resolve_entities_skips_text_degenerate_on_either_axis():
    # ezdxf reports an infinite bbox for empty text but a ZERO-WIDTH, real-height
    # bbox for whitespace-only text. The latter used to survive as a sliver that
    # collides with anything crossing its vertical line.
    doc = ezdxf.new()
    block = doc.blocks.new(name="View - 100")
    block.add_text("A1", height=2.5, dxfattribs={"layer": "TEKLA_MCP_MARKS"})
    block.add_text("   ", height=2.5, dxfattribs={"layer": "TEKLA_MCP_MARKS"})
    block.add_text("", height=2.5, dxfattribs={"layer": "TEKLA_MCP_MARKS"})
    block.add_mtext("", dxfattribs={"layer": "TEKLA_MCP_MARKS"})
    msp = doc.modelspace()
    msp.add_blockref("View - 100", (0.0, 0.0))

    entities = resolve_entities(doc, msp)

    assert len(entities) == 1, "only the text with a real two-dimensional bbox should survive"
    assert entities[0].bbox.width > 0.0
    assert entities[0].bbox.height > 0.0


# check_content_out_of_sheet
def _sheet(w=100.0, h=100.0):
    return {"is_sheet": True, "view_key": "SHEET", "width": w, "height": h}


def test_content_out_of_sheet_clouds_right_edge_crossing():
    # View frame straddles the sheet's right edge (x=50 to x=150, sheet 100).
    # Cloud is a strip from the boundary to the frame's outer edge, full frame
    # height. The boundary side (x=100) is nudged inward by CLOUD_MARGIN (5.0)
    # so the cloud visibly overlaps the crossing; outer edges stay exact.
    # Frame is inset by FRAME_CONTENT_PADDING (5.0) before the strip is computed
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
    # Frame crosses right (x=80-120, sheet 100) and bottom (y=80-120, sheet 100)
    # edge - yields ONE issue covering both strips, not two separate ones
    sheet = _sheet(100.0, 100.0)
    view = _view("A", 1, 80.0, 80.0, w=40.0, h=40.0)
    issues = check_content_out_of_sheet([sheet, view], [])
    assert len(issues) == 1
    assert issues[0].bbox == BBox(85.0, 85.0, 115.0, 115.0)


def _double_border_frame(sheet_w, sheet_h, inset=20.0, parent="frame"):
    """Realistic frame geometry: outer border on paper edges, inner inset border,
    plus short corner/fold ticks - mirrors a Tekla DXF export."""
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
    # Real inner border is inset 20mm from the sheet's 200x100 edges,
    # so its right edge is at x=180. A view x=170-190, y=30-50 crosses
    # that real boundary but NOT the nominal paper edge (200)
    sheet = _sheet(200.0, 100.0)
    frame = _double_border_frame(200.0, 100.0, inset=20.0)
    view = _view("A", 1, 170.0, 30.0, w=20.0, h=20.0)
    issues = check_content_out_of_sheet([sheet, view], frame)
    assert len(issues) == 1
    assert issues[0].bbox == BBox(175.0, 35.0, 185.0, 45.0)


def test_content_out_of_sheet_ignores_small_furniture_not_spanning_sheet():
    # Small furniture (e.g. title-block stamp) on DRAWING_FRAME layer
    # does not span most of the sheet, so it's not mistaken for the
    # print boundary - nominal sheet size is used instead
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
    # A 0-margin issue must not get re-inflated by a neighbor's margin
    zero_margin_issue = CollisionIssue.create("out_of_grid_with_content", "A", BBox(0.0, 0.0, 10.0, 10.0), "out_of_grid", ["A"], margin=(0.0, 0.0))
    default_margin_issue = CollisionIssue.create("collides_with_sheet", "A", BBox(1.0, 1.0, 9.0, 9.0), "collides with sheet", ["A"])
    merged = merge_issues([zero_margin_issue, default_margin_issue])
    assert len(merged) == 1
    assert merged[0].margin == (0.0, 0.0)


def test_merge_issues_takes_elementwise_min_of_axis_margins():
    # Per-axis margin merging: (X, 0) + (0, Y) -> (0, 0), not just min tuple
    x_only_issue = CollisionIssue.create("content_out_of_sheet", "A", BBox(0.0, 0.0, 10.0, 10.0), "out of sheet", ["A"], margin=(CLOUD_MARGIN, 0.0))
    y_only_issue = CollisionIssue.create("content_out_of_sheet", "A", BBox(1.0, 1.0, 9.0, 9.0), "out of sheet", ["A"], margin=(0.0, CLOUD_MARGIN))
    merged = merge_issues([x_only_issue, y_only_issue])
    assert len(merged) == 1
    assert merged[0].margin == (0.0, 0.0)


def test_merge_issues_merges_overlapping_wide_duplicates():
    # Near-duplicate hits against the same line must merge into one cloud
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


def _part_seg(x0, y0, x1, y1, layer="TEKLA_MCP_PARTS"):
    """A part-edge entity with one segment, for attach-target tests."""
    return WorldEntity(layer=layer, bbox=BBox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), segments=[((x0, y0), (x1, y1))], parent="p")


def _circle(cx, cy, layer="TEKLA_MCP_BOLTS"):
    """A circle entity (no segments) - its bbox centre is the target point."""
    return WorldEntity(layer=layer, bbox=BBox(cx, cy, cx, cy), segments=[], kind="CIRCLE", parent="b")


def test_view_local_to_sheet_applies_origin_and_scale():
    # 1:20 view at sheet origin (267, 1556.5); local point (-80, -11035)
    sx, sy = view_local_to_sheet(-80.0, -11035.0, 267.0, 1556.5, 20.0)
    assert round(sx, 2) == 263.0
    assert round(sy, 2) == 1004.75


def test_collect_attach_targets_lines_and_centers():
    entities = [
        _part_seg(0.0, 0.0, 10.0, 0.0),
        _circle(5.0, 5.0, layer="TEKLA_MCP_BOLTS"),
        _part_seg(0.0, 0.0, 0.0, 20.0, layer="TEKLA_MCP_GRIDS"),
    ]
    targets = collect_attach_targets(entities)
    # Part edge and grid both become line targets
    assert len(targets.lines) == 2
    assert (5.0, 5.0) in targets.centers


def test_point_is_attached_only_at_corners_not_midpoint_or_mid_span():
    # Horizontal edge (0,0)-(10,0): corners at the ends
    targets = collect_attach_targets([_part_seg(0.0, 0.0, 10.0, 0.0)])
    assert point_is_attached(0.0, 0.0, targets, tol=0.5)  # corner
    # Midpoints and mid-span points are NOT direction-agnostic anchors -
    # a fragment midpoint sits where a dangling point sits
    # (perpendicular edges are covered by the directional rule instead)
    assert not point_is_attached(5.0, 0.0, targets, tol=0.5)
    assert not point_is_attached(3.0, 0.0, targets, tol=0.5)
    # Off the edge entirely
    assert not point_is_attached(5.0, 5.0, targets, tol=0.5)


def test_on_any_edge_matches_only_its_orientation():
    targets = collect_attach_targets(
        [
            _part_seg(0.0, 0.0, 10.0, 0.0),  # horizontal
            _part_seg(0.0, 0.0, 0.0, 10.0),  # vertical
        ]
    )
    # Mid-span on the horizontal edge: a horizontal-edge match, not a vertical one
    assert on_any_horizontal_edge(3.0, 0.0, targets, tol=0.5)
    assert not on_any_vertical_edge(3.0, 0.0, targets, tol=0.5)
    # Mid-span on the vertical edge: the mirror image
    assert on_any_vertical_edge(0.0, 3.0, targets, tol=0.5)
    assert not on_any_horizontal_edge(0.0, 3.0, targets, tol=0.5)


def test_dimension_point_is_attached_is_directional():
    targets = collect_attach_targets(
        [
            _part_seg(0.0, 0.0, 10.0, 0.0),  # horizontal edge at y=0
            _part_seg(0.0, 0.0, 0.0, 10.0),  # vertical edge at x=0
        ]
    )
    # A vertical dimension attaches anywhere along a HORIZONTAL edge...
    assert dimension_point_is_attached(3.0, 0.0, targets, tol=0.5, dim_is_vertical=True)
    # ...but mid-span on a PARALLEL edge is dangling (like a deleted object)
    assert not dimension_point_is_attached(0.0, 3.0, targets, tol=0.5, dim_is_vertical=True)
    # A horizontal dimension is the mirror image
    assert dimension_point_is_attached(0.0, 3.0, targets, tol=0.5, dim_is_vertical=False)
    assert not dimension_point_is_attached(3.0, 0.0, targets, tol=0.5, dim_is_vertical=False)
    # A point in empty space is unattached whichever way the dimension runs
    assert not dimension_point_is_attached(5.0, 5.0, targets, tol=0.5, dim_is_vertical=True)
    assert not dimension_point_is_attached(5.0, 5.0, targets, tol=0.5, dim_is_vertical=False)


def test_dimension_point_is_attached_corner_and_center_regardless_of_direction():
    targets = collect_attach_targets(
        [
            _part_seg(0.0, 0.0, 10.0, 0.0),
            _circle(20.0, 20.0, layer="TEKLA_MCP_BOLTS"),
        ]
    )
    # A corner is accepted whichever way the dimension runs
    assert dimension_point_is_attached(0.0, 0.0, targets, tol=0.5, dim_is_vertical=True)
    assert dimension_point_is_attached(0.0, 0.0, targets, tol=0.5, dim_is_vertical=False)
    # A bolt/hole centre likewise
    assert dimension_point_is_attached(20.0, 20.0, targets, tol=0.5, dim_is_vertical=True)
    # A point off all geometry is unattached in either direction


def test_dimension_point_attaches_to_reference_line():
    # A vertical reference line anchors a horizontal dim anywhere along it
    # (perpendicular rule), and either dim at its corners
    targets = collect_attach_targets([_part_seg(0.0, 0.0, 0.0, 100.0, layer="TEKLA_MCP_REFERENCE_LINES")])
    assert dimension_point_is_attached(1.0, 50.0, targets, tol=2.0, dim_is_vertical=False)
    assert dimension_point_is_attached(0.0, 0.0, targets, tol=2.0, dim_is_vertical=True)
    assert not dimension_point_is_attached(10.0, 50.0, targets, tol=2.0, dim_is_vertical=False)


def test_point_is_attached_to_bolt_or_hole_center():
    targets = collect_attach_targets([_circle(5.0, 5.0, layer="TEKLA_MCP_BOLTS")])
    assert point_is_attached(5.0, 6.0, targets, tol=2.0)
    assert not point_is_attached(5.0, 10.0, targets, tol=2.0)


def test_dimension_point_attaches_to_rebar_hidden_and_catchall_geometry():
    # Rebar, hidden edges and catch-all layer are all valid dim anchors
    for layer in ("TEKLA_MCP_REINFORCEMENT", "TEKLA_MCP_HIDDEN_LINES", "TEKLA_MCP_ALL"):
        targets = collect_attach_targets([_part_seg(5.0, 0.0, 5.0, 10.0, layer=layer)])
        assert dimension_point_is_attached(5.0, 3.0, targets, tol=0.1, dim_is_vertical=False), layer


def test_annotation_layers_are_not_attach_targets():
    # Dimension witness lines and mark leaders must never vouch for a point
    for layer in ("TEKLA_MCP_DIMENSIONS", "TEKLA_MCP_MARKS", "TEKLA_MCP_DRAWING_TABLE"):
        targets = collect_attach_targets([_part_seg(5.0, 0.0, 5.0, 10.0, layer=layer)])
        assert not dimension_point_is_attached(5.0, 3.0, targets, tol=0.1, dim_is_vertical=False), layer


def test_dimension_point_attaches_to_bolt_axis_line():
    # Bolts drawn as axis lines: horizontal dim attaches mid-span on the
    # vertical axis; cross centre attaches regardless of direction
    targets = collect_attach_targets(
        [
            _part_seg(105.34, 198.18, 105.34, 204.18, layer="TEKLA_MCP_BOLTS"),  # vertical hole axis
            _part_seg(103.54, 201.18, 107.14, 201.18, layer="TEKLA_MCP_BOLTS"),  # horizontal cross arm
        ]
    )
    assert dimension_point_is_attached(105.31, 202.2, targets, tol=0.1, dim_is_vertical=False)
    # Mid-span on the parallel axis line does not satisfy a vertical dimension
    assert not dimension_point_is_attached(105.31, 202.2, targets, tol=0.1, dim_is_vertical=True)
    # The cross centre (midpoint of both arms) attaches in either direction
    assert dimension_point_is_attached(105.34, 201.18, targets, tol=0.1, dim_is_vertical=True)


def test_circle_and_arc_center_is_target_on_any_geometry_layer():
    # Holes and pipes in section are drawn as circle/arc segments.
    # Centre = axis anchor. Rule stays broad since arcs can land on
    # any geometry layer (see collect_attach_targets known-limitation note)
    for kind in ("CIRCLE", "ARC"):
        for layer in ("TEKLA_MCP_HIDDEN_LINES", "TEKLA_MCP_SECTION_EDGES"):
            e = WorldEntity(layer=layer, bbox=BBox(7.0, 8.0, 7.0, 8.0), segments=[], kind=kind, parent="h")
            assert dimension_point_is_attached(7.0, 8.0, collect_attach_targets([e]), tol=0.1, dim_is_vertical=True), (kind, layer)


def test_small_rebar_hatch_center_is_target_but_large_fill_is_not():
    # Small hatch dots = bar cross-sections (centre = bar axis).
    # Large hatches = surface fills, never targets
    dot = WorldEntity(layer="TEKLA_MCP_REINFORCEMENT", bbox=BBox(10.0, 10.0, 10.6, 10.6), segments=[], kind="HATCH", parent="r")
    fill = WorldEntity(layer="TEKLA_MCP_REINFORCEMENT", bbox=BBox(50.0, 50.0, 150.0, 150.0), segments=[], kind="HATCH", parent="r")
    targets = collect_attach_targets([dot, fill])
    assert dimension_point_is_attached(10.3, 10.3, targets, tol=0.1, dim_is_vertical=False)
    assert not dimension_point_is_attached(100.0, 100.0, targets, tol=0.1, dim_is_vertical=False)


def test_graphical_objects_layer_is_never_a_target():
    # Revision clouds export to TEKLA_MCP_GRAPHICAL_OBJECTS.
    # If it were a target, a clouded point would rescue itself on re-run
    cloud_edge = _part_seg(215.1, 1813.2, 235.1, 1813.2, layer="TEKLA_MCP_GRAPHICAL_OBJECTS")
    targets = collect_attach_targets([cloud_edge])
    assert not dimension_point_is_attached(225.1, 1813.2, targets, tol=0.5, dim_is_vertical=True)


def test_capped_face_midpoint_is_target_pipe_end_cap():
    # Pipe end cap: short cap line with perpendicular wall lines at each
    # corner. Cap midpoint = pipe axis anchor, works in either direction
    targets = collect_attach_targets(
        [
            _part_seg(195.79, 1135.12, 199.66, 1135.12, layer="TEKLA_MCP_HIDDEN_LINES"),  # cap
            _part_seg(195.79, 1101.79, 195.79, 1135.12, layer="TEKLA_MCP_ALL"),  # wall
            _part_seg(199.66, 1101.79, 199.66, 1135.12, layer="TEKLA_MCP_ALL"),  # wall
        ]
    )
    assert dimension_point_is_attached(197.68, 1135.13, targets, tol=0.5, dim_is_vertical=False)
    assert dimension_point_is_attached(197.725, 1135.12, targets, tol=0.5, dim_is_vertical=True)


def test_uncapped_fragment_midpoint_is_not_a_target():
    # A line split into fragments: collinear neighbours do not cap,
    # so the fragment midpoint (where a dangling point sits) is NOT an anchor
    targets = collect_attach_targets(
        [
            _part_seg(289.04, 1896.48, 292.04, 1896.48, layer="TEKLA_MCP_ALL"),  # fragment
            _part_seg(292.04, 1896.48, 300.71, 1896.48, layer="TEKLA_MCP_ALL"),  # collinear continuation
            _part_seg(289.04, 1896.48, 300.71, 1896.48, layer="TEKLA_MCP_SECTION_EDGES"),  # overlapping full line
        ]
    )
    assert not dimension_point_is_attached(290.57, 1896.50, targets, tol=0.5, dim_is_vertical=False)


def test_long_capped_face_midpoint_is_a_target():
    # Any corner-bounded face offers its midpoint as an anchor.
    # Only split fragments (bare split points) are excluded
    targets = collect_attach_targets(
        [
            _part_seg(0.0, 0.0, 100.0, 0.0),  # long bottom face
            _part_seg(0.0, 0.0, 0.0, 50.0),  # side
            _part_seg(100.0, 0.0, 100.0, 50.0),  # side
        ]
    )
    assert dimension_point_is_attached(50.0, 0.0, targets, tol=0.5, dim_is_vertical=False)
    # Away from the midpoint, mid-span on the parallel face still dangles
    assert not dimension_point_is_attached(30.0, 0.0, targets, tol=0.5, dim_is_vertical=False)


def test_perpendicular_capped_fragment_midpoint_is_a_target_known_limitation():
    # DOCUMENTED LIMITATION: a fragment with perpendicular edges at its
    # split points looks like a real face, so its midpoint is an anchor.
    # A dangling point there would be masked. Bare split points are excluded
    targets = collect_attach_targets(
        [
            _part_seg(289.04, 1896.48, 292.04, 1896.48),  # fragment
            _part_seg(289.04, 1896.48, 289.04, 1900.0),  # perpendicular edge at split
            _part_seg(292.04, 1896.48, 292.04, 1900.0),  # perpendicular edge at split
        ]
    )
    assert dimension_point_is_attached(290.54, 1896.48, targets, tol=0.5, dim_is_vertical=False)


def test_degenerate_segment_does_not_crash_target_collection():
    # A zero-length segment must not raise in the cap-midpoint pass (its
    # direction is undefined). Its point still attaches as an ordinary
    # segment-endpoint corner - that is `point_is_attached`, not midpoint logic
    degenerate = _part_seg(5.0, 5.0, 5.0, 5.0)
    wall = _part_seg(5.0, 5.0, 5.0, 10.0)
    targets = collect_attach_targets([degenerate, wall])
    assert dimension_point_is_attached(5.0, 5.0, targets, tol=0.5, dim_is_vertical=True)
    assert not dimension_point_is_attached(6.5, 5.0, targets, tol=0.5, dim_is_vertical=True)


def test_noise_sliver_does_not_cap_a_bare_split_point():
    # Sub-0.1mm export-noise slivers at a split point must not fake a cap -
    # segments shorter than one grid cell are ignored
    targets = collect_attach_targets(
        [
            _part_seg(289.04, 1896.48, 292.04, 1896.48),  # fragment
            _part_seg(292.04, 1896.48, 300.71, 1896.48),  # collinear continuation
            _part_seg(289.04, 1896.48, 289.06, 1896.53),  # noise sliver, ~0.05mm, angled
            _part_seg(292.04, 1896.48, 292.06, 1896.53),  # noise sliver, ~0.05mm, angled
        ]
    )
    assert not dimension_point_is_attached(290.54, 1896.48, targets, tol=0.4, dim_is_vertical=False)


# sheet alignment
def _frame_line(x0, y0, x1, y1):
    return WorldEntity(layer="TEKLA_MCP_DRAWING_FRAME", bbox=BBox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), segments=[Segment(x0, y0, x1, y1)], kind="LINE", parent="f")


def test_sheet_alignment_offset_from_frame_min_corner():
    # A translated export: frame outer border corner at (-392.5, -1351.0)
    entities = [
        _frame_line(-392.5, -1351.0, 201.5, -1351.0),
        _frame_line(-392.5, -1351.0, -392.5, 749.0),
        _part_seg(0.0, 0.0, 10.0, 0.0),
    ]
    assert sheet_alignment_offset(entities) == (-392.5, -1351.0)


def test_sheet_alignment_offset_without_frame_is_zero():
    assert sheet_alignment_offset([_part_seg(5.0, 5.0, 10.0, 5.0)]) == (0.0, 0.0)


def test_align_entities_to_sheet_translates_geometry():
    frame = _frame_line(-100.0, -50.0, 494.0, -50.0)
    part = _part_seg(-90.0, -40.0, -80.0, -40.0)
    align_entities_to_sheet([frame, part])
    assert part.bbox == BBox(10.0, 10.0, 20.0, 10.0)
    assert part.segments == [Segment(10.0, 10.0, 20.0, 10.0)]


def test_align_entities_to_sheet_noop_when_aligned():
    frame = _frame_line(0.0, 0.0, 594.0, 0.0)
    part = _part_seg(10.0, 10.0, 20.0, 10.0)
    align_entities_to_sheet([frame, part])
    assert part.bbox == BBox(10.0, 10.0, 20.0, 10.0)


def test_targets_are_sheet_space_only_after_alignment():
    # collect_attach_targets MUST run on aligned entities. Without alignment
    # the part edge at world (-90, -40) misses the sheet point (10, 10).
    # After alignment the target moves to sheet coordinates and attaches.
    def fresh_entities():
        return [_frame_line(-100.0, -50.0, 494.0, -50.0), _part_seg(-90.0, -40.0, -80.0, -40.0)]

    # Skipping alignment: target at world (-90, -40) -> sheet point misses
    unaligned = collect_attach_targets(fresh_entities())
    assert not dimension_point_is_attached(10.0, 10.0, unaligned, tol=0.5, dim_is_vertical=True)

    # Aligning first: target at sheet (10, 10) -> point attaches
    entities = fresh_entities()
    align_entities_to_sheet(entities)
    aligned = collect_attach_targets(entities)
    assert dimension_point_is_attached(10.0, 10.0, aligned, tol=0.5, dim_is_vertical=True)


# shortening helpers
def test_shortening_gaps_from_boxes_empty_and_single_box():
    assert shortening_gaps_from_boxes([]) == ([], [])
    assert shortening_gaps_from_boxes([(0.0, 0.0, 100.0, 50.0)]) == ([], [])


def test_shortening_gaps_from_boxes_x_gap():
    # Two visible regions along X with full-height boxes: one X gap, no Y gap
    boxes = [(-165.5, -85.2, 854.1, 191.4), (3438.9, -85.2, 4470.5, 191.4)]
    x_gaps, y_gaps = shortening_gaps_from_boxes(boxes)
    assert x_gaps == [(854.1, 3438.9)]
    assert y_gaps == []


def test_shortening_gaps_from_boxes_sorts_and_merges_overlapping():
    # Boxes given out of order, with the two left ones overlapping in X -
    # they merge into one visible interval, leaving a single gap
    boxes = [(500.0, 0.0, 900.0, 10.0), (0.0, 0.0, 600.0, 10.0), (2000.0, 0.0, 3000.0, 10.0)]
    x_gaps, _ = shortening_gaps_from_boxes(boxes)
    assert x_gaps == [(900.0, 2000.0)]


def test_shortened_axis_to_sheet_no_gaps_matches_plain_transform():
    assert shortened_axis_to_sheet(79.1, 97.4, 10.0, [], 0.0) == view_local_to_sheet(79.1, 0.0, 97.4, 0.0, 10.0)[0]


def test_shortened_axis_to_sheet_point_before_gap_is_unshifted():
    gaps = [(854.1, 3438.9)]
    assert round(shortened_axis_to_sheet(44.1, 97.4, 10.0, gaps, 1.0), 2) == 101.81


def test_shortened_axis_to_sheet_point_after_gap_collapses_gap_and_adds_seam_offset():
    # Real NB-4008 numbers: local 4248.9 with a 2584.8 mm gap at 1:10 plus the
    # 1.0 mm seam offset lands at the DXF-verified 264.81, not off-sheet 522.29
    gaps = [(854.1, 3438.9)]
    assert round(shortened_axis_to_sheet(4248.9, 97.4, 10.0, gaps, 1.0), 2) == 264.81


def test_shortened_axis_to_sheet_point_inside_gap_collapses_to_seam():
    gaps = [(854.1, 3438.9)]
    seam = shortened_axis_to_sheet(854.1, 97.4, 10.0, gaps, 1.0)
    assert shortened_axis_to_sheet(2000.0, 97.4, 10.0, gaps, 1.0) == seam


def test_shortened_axis_to_sheet_accumulates_multiple_gaps():
    # Two gaps of 100 each at 1:10 with 1.0 mm seam offset: a point past both
    # is pulled back 20 mm on the sheet and pushed out 2 seam offsets
    gaps = [(100.0, 200.0), (300.0, 400.0)]
    assert shortened_axis_to_sheet(500.0, 0.0, 10.0, gaps, 1.0) == (500.0 - 200.0) / 10.0 + 2.0
