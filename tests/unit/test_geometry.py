"""
Unit tests for the oriented box geometry in geometry.py.
"""

import math

import numpy as np
import pytest

from tekla_mcp_server.geometry import (
    OrientedBox,
    aabb,
    aabb_gap,
    angle_label,
    axis_overlap,
    box_gap,
    box_sample_points,
    orientation,
    polyline_sample_points,
    ranked_axes,
    relation,
    search_extents,
    segment_distances,
    smaller_box,
    sides,
)

X = (1.0, 0.0, 0.0)
Y = (0.0, 1.0, 0.0)


def _box(lo: tuple[float, float, float], hi: tuple[float, float, float], axis_x=X, axis_y=Y, origin=(0.0, 0.0, 0.0)) -> OrientedBox:
    """Build a box from a local extent, axis-aligned by default."""
    return OrientedBox.from_local_extent(origin, axis_x, axis_y, lo, hi)


def _plan_axes(degrees: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Local X and Y axes rotated in plan by the given angle."""
    a = math.radians(degrees)
    return (math.cos(a), math.sin(a), 0.0), (-math.sin(a), math.cos(a), 0.0)


def _extent(lo: tuple[float, float, float], hi: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    """Axis-aligned extent as numpy corners."""
    return np.array(lo, dtype=float), np.array(hi, dtype=float)


class TestOrientedBox:
    def test_from_local_extent_center_and_half(self):
        box = _box((0, -100, 0), (6000, 100, 3000))
        assert box.center == pytest.approx((3000, 0, 1500))
        assert box.half == pytest.approx((3000, 100, 1500))

    def test_from_local_extent_orthogonalizes_y(self):
        box = _box((0, 0, 0), (1, 1, 1), axis_x=(2.0, 0.0, 0.0), axis_y=(1.0, 3.0, 0.0))
        assert box.axes[0] == pytest.approx(X)
        assert box.axes[1] == pytest.approx(Y)
        assert box.axes[2] == pytest.approx((0, 0, 1))

    def test_from_local_extent_with_offset_origin_and_rotation(self):
        x, y = _plan_axes(90)
        box = _box((0, 0, 0), (10, 2, 4), axis_x=x, axis_y=y, origin=(100, 0, 0))
        assert box.center == pytest.approx((99, 5, 2))

    def test_equal_boxes_compare_by_identity(self):
        a = _box((0, 0, 0), (1, 1, 1))
        b = _box((0, 0, 0), (1, 1, 1))
        assert a == a and a != b
        assert len({a, b, a}) == 2

    def test_corners_are_distinct(self):
        corners = _box((0, 0, 0), (1, 2, 3)).corners()
        assert corners.shape == (8, 3)
        assert len(np.unique(corners, axis=0)) == 8

    def test_aabb_of_rotated_box(self):
        x, y = _plan_axes(45)
        lo, hi = aabb([_box((0, -1, 0), (10, 1, 1), axis_x=x, axis_y=y)])
        assert hi[0] - lo[0] == pytest.approx(10 / math.sqrt(2) + 2 / math.sqrt(2))


class TestBoxSamplePoints:
    def test_points_run_along_the_long_axis(self):
        points = box_sample_points(_box((0, 0, 0), (100, 10, 1000)))
        assert points.shape == (5, 3)
        assert points[:, 0] == pytest.approx([50] * 5)
        assert points[:, 1] == pytest.approx([5] * 5)
        assert points[:, 2] == pytest.approx([100, 300, 500, 700, 900])

    def test_rotated_box_points_stay_inside_it(self):
        x, y = _plan_axes(30)
        box = _box((0, -10, -10), (2000, 10, 10), axis_x=x, axis_y=y, origin=(500, 500, 0))
        points = box_sample_points(box)
        assert box.distance_to_points(points) == pytest.approx([0] * 5)
        assert np.linalg.norm(points[-1] - points[0]) == pytest.approx(1600)


class TestPolylineSamplePoints:
    def test_five_points_per_leg_without_the_ends(self):
        points = polyline_sample_points([(0, 0, 0), (100, 0, 0), (100, 0, 50)])
        assert points.shape == (10, 3)
        assert points[:5, 0] == pytest.approx([10, 30, 50, 70, 90])
        assert points[5:, 2] == pytest.approx([5, 15, 25, 35, 45])
        assert not any(np.allclose(p, (100, 0, 0)) for p in points)

    def test_single_point_is_kept(self):
        assert polyline_sample_points([(1, 2, 3)]) == pytest.approx(np.array([[1, 2, 3]]))

    def test_empty_polyline(self):
        assert polyline_sample_points([]).shape == (0, 3)


class TestSegmentDistances:
    @pytest.mark.parametrize(
        "p1, q1, p2, q2, expected",
        [
            ((0, 0, 0), (10, 0, 0), (0, 5, 0), (10, 5, 0), 5.0),  # parallel
            ((0, 0, 0), (10, 0, 0), (5, -5, 3), (5, 5, 3), 3.0),  # skew crossing
            ((0, 0, 0), (10, 0, 0), (13, 4, 0), (20, 4, 0), 5.0),  # end to end
            ((0, 0, 0), (0, 0, 0), (3, 4, 0), (3, 4, 0), 5.0),  # both points
            ((0, 0, 0), (0, 0, 0), (-5, 2, 0), (5, 2, 0), 2.0),  # point to segment
            ((-5, 2, 0), (5, 2, 0), (0, 0, 0), (0, 0, 0), 2.0),  # segment to point
            ((0, 0, 0), (10, 0, 0), (-4, 3, 0), (-4, 9, 0), 5.0),  # beyond the start
        ],
    )
    def test_cases(self, p1, q1, p2, q2, expected):
        assert float(segment_distances(*(np.array(p, dtype=float) for p in (p1, q1, p2, q2)))) == pytest.approx(expected)

    def test_all_pairs_at_once(self):
        starts = np.array([[0, 0, 0], [0, 10, 0]], dtype=float)
        ends = starts + (10, 0, 0)
        result = segment_distances(starts[:, None], ends[:, None], starts[None, :] + (0, 0, 3), ends[None, :] + (0, 0, 3))
        assert result.shape == (2, 2)
        assert result == pytest.approx(np.array([[3.0, math.hypot(10, 3)], [math.hypot(10, 3), 3.0]]))


class TestBoxGap:
    def test_beam_short_of_column(self):
        column = _box((-150, -150, 0), (150, 150, 3000))
        beam = _box((162, -100, 2500), (5000, 100, 2900))
        assert box_gap(column, beam) == pytest.approx((12.0, 0.0))

    def test_corner_to_corner_distance(self):
        a = _box((0, 0, 0), (1, 1, 1))
        b = _box((4, 5, 1), (6, 6, 2))
        assert box_gap(a, b)[0] == pytest.approx(5.0)

    def test_diagonal_beam_uses_its_own_box(self):
        x, y = _plan_axes(45)
        beam = _box((0, -50, -50), (10000 * math.sqrt(2), 50, 50), axis_x=x, axis_y=y)
        cube = _box((6900, 2900, -100), (7100, 3100, 100))
        # The beam's axis-aligned extent contains the cube, its box does not
        assert aabb_gap(aabb([beam]), aabb([cube])) == 0.0
        expected = (6900 - 3100) / math.sqrt(2) - 50
        assert box_gap(beam, cube)[0] == pytest.approx(expected, abs=0.01)

    def test_rotated_edge_to_edge(self):
        x, y = _plan_axes(45)
        a = _box((0, 0, 0), (10, 10, 10))
        # Rotated cube whose nearest edge faces the +X face of `a` at 5 mm
        half_diag = 5 * math.sqrt(2)
        b = _box((-5, -5, 0), (5, 5, 10), axis_x=x, axis_y=y, origin=(15 + half_diag, 5, 0))
        assert box_gap(a, b)[0] == pytest.approx(5.0)

    def test_skew_edges_closest(self):
        x, y = _plan_axes(45)
        a = _box((0, 0, 0), (10, 10, 10))
        # A rotated bar above `a`, crossing over its top edge region without touching
        b = _box((-50, -1, 0), (50, 1, 2), axis_x=x, axis_y=y, origin=(5, 5, 13))
        assert box_gap(a, b)[0] == pytest.approx(3.0)

    def test_penetration(self):
        a = _box((0, 0, 0), (100, 100, 100))
        b = _box((70, 0, 0), (200, 100, 100))
        assert box_gap(a, b) == pytest.approx((0.0, 30.0))

    def test_contained_box_penetration_includes_the_way_out(self):
        # A 20 mm box in the middle of a 100 mm box must move 60 mm to get clear
        a = _box((0, 0, 0), (100, 100, 100))
        b = _box((40, 40, 40), (60, 60, 60))
        assert box_gap(a, b) == pytest.approx((0.0, 60.0))

    def test_embed_near_a_face_penetrates_by_its_depth(self):
        wall = _box((0, 0, 0), (6000, 590, 3000))
        plate = _box((1000, 0, 1000), (1200, 10, 1200))
        assert box_gap(wall, plate) == pytest.approx((0.0, 10.0))

    def test_penetration_is_symmetric(self):
        a = _box((0, 0, 0), (100, 100, 100))
        b = _box((40, 40, 40), (60, 60, 60))
        assert box_gap(a, b) == pytest.approx(box_gap(b, a))

    def test_exact_contact_is_not_separated(self):
        wall = _box((0, -100, 0), (6000, 100, 3000))
        slab = _box((1000, -80, 3000), (2200, 5000, 3265))
        gap, depth = box_gap(wall, slab)
        assert gap == pytest.approx(0.0, abs=1e-9)
        assert depth == pytest.approx(0.0, abs=1e-9)


class TestRelation:
    @pytest.mark.parametrize(
        "gap, penetration, expected",
        [
            (0.0, 0.0, "touching"),  # modelled exactly in contact
            (0.5, 0.0, "touching"),
            (1.0, 0.0, "touching"),
            (0.0, 0.5, "touching"),
            (0.0, 30.0, "boxes_overlap"),
            (20.0, 0.0, "near"),
        ],
    )
    def test_relation(self, gap, penetration, expected):
        assert relation(gap, penetration, 1.0) == expected

    def test_boxes_from_spec(self):
        wall = _box((0, -100, 0), (6000, 100, 3000))
        assert relation(*box_gap(wall, _box((0, 100.5, 0), (10, 200, 10))), 1.0) == "touching"
        assert relation(*box_gap(wall, _box((0, 99.5, 0), (10, 200, 10))), 1.0) == "touching"
        assert relation(*box_gap(wall, _box((0, 70, 0), (10, 200, 10))), 1.0) == "boxes_overlap"
        assert relation(*box_gap(wall, _box((0, 120, 0), (10, 200, 10))), 1.0) == "near"


class TestAabb:
    def test_overlapping_extents(self):
        assert aabb_gap(_extent((0, 0, 0), (10, 10, 10)), _extent((5, 5, 5), (20, 20, 20))) == 0.0

    def test_separated_extents(self):
        assert aabb_gap(_extent((0, 0, 0), (1, 1, 1)), _extent((4, 5, 1), (6, 6, 2))) == pytest.approx(5.0)

    def test_union(self):
        lo, hi = aabb([_box((0, 0, 0), (1, 1, 1)), _box((5, -2, 0), (6, 0, 9))])
        assert lo == pytest.approx((0, -2, 0))
        assert hi == pytest.approx((6, 1, 9))

    def test_grow(self):
        lo, hi = aabb([_box((0, 0, 0), (1, 1, 1))], grow=10)
        assert lo == pytest.approx((-10, -10, -10))
        assert hi == pytest.approx((11, 11, 11))


class TestSides:
    def test_slab_above_wall(self):
        wall = _box((0, -100, 0), (6000, 100, 3000))
        slab = _box((1000, -80, 3000), (2200, 5000, 3265))
        assert sides([wall], [slab], 1.0) == ["above"]

    def test_diagonal_neighbour_has_two_sides(self):
        a = _box((0, 0, 0), (10, 10, 10))
        b = _box((20, 20, 0), (30, 30, 10))
        assert sides([a], [b], 1.0) == ["+X", "+Y"]

    def test_overlapping_extent_has_no_side(self):
        a = _box((0, 0, 0), (10, 10, 10))
        b = _box((5, 5, 5), (15, 15, 15))
        assert sides([a], [b], 1.0) == []

    def test_union_of_source_boxes(self):
        # The second source box reaches past the neighbour in X, so +X no longer holds
        a = _box((0, 0, 0), (10, 10, 10))
        leg = _box((0, 20, 0), (40, 30, 10))
        b = _box((20, 0, 0), (30, 10, 10))
        assert sides([a], [b], 1.0) == ["+X"]
        assert sides([a, leg], [b], 1.0) == []


class TestRankedAxes:
    def test_order_by_extent(self):
        axes, extents = ranked_axes(_box((0, -100, 0), (6000, 100, 3000)))
        assert axes[0] == pytest.approx(X)
        assert axes[2] == pytest.approx(Y)
        assert extents == pytest.approx((6000, 3000, 200))

    def test_equal_extents_keep_coordinate_order(self):
        axes, extents = ranked_axes(_box((0, 0, 0), (10, 10, 10)))
        assert axes == pytest.approx(np.eye(3))
        assert extents == pytest.approx((10, 10, 10))


class TestAxisOverlap:
    def test_bearing_on_wall_rotated_in_plan(self):
        u, v = _plan_axes(30)
        wall = _box((0, -100, 0), (6000, 100, 3000), axis_x=u, axis_y=v)
        slab = _box((1000, -80, 3000), (2200, 5000, 3265), axis_x=u, axis_y=v)
        assert sides([wall], [slab], 1.0) == ["above"]
        overlap = axis_overlap(wall, [wall], [slab])
        assert overlap["thickness"] == pytest.approx(180.0)
        assert overlap["length"] == pytest.approx(1200.0)
        assert overlap["width"] == pytest.approx(0.0, abs=1e-6)

    def test_ties_still_give_three_values(self):
        cube = _box((0, 0, 0), (10, 10, 10))
        assert set(axis_overlap(cube, [cube], [cube])) == {"length", "width", "thickness"}


class TestOrientation:
    def test_parallel_beams(self):
        a = _box((0, -100, 0), (5000, 100, 400))
        b = _box((0, 900, 0), (5000, 1100, 400))
        result = orientation(a, b, 1.0, 1.0)
        assert result["length"] == {"angle_deg": pytest.approx(0.0), "label": "parallel"}

    def test_wall_panel_under_slab(self):
        u, v = _plan_axes(30)
        wall = _box((0, -100, 0), (6000, 100, 3000), axis_x=u, axis_y=v)
        slab = _box((1000, -80, 3000), (2200, 5000, 3265), axis_x=u, axis_y=v)
        result = orientation(wall, slab, 1.0, 1.0)
        assert result["length"]["label"] == "perpendicular"
        assert result["thickness"]["label"] == "perpendicular"

    def test_square_column_has_no_thickness_comparison(self):
        column = _box((-150, -150, 0), (150, 150, 3000))
        slab = _box((-2000, -2000, 3000), (3000, 2000, 3265))
        result = orientation(column, slab, 1.0, 1.0)
        assert result["thickness"] is None
        assert result["length"]["label"] == "perpendicular"

    def test_square_plate_has_no_length_comparison(self):
        plate = _box((0, 0, 0), (2000, 2000, 200))
        beam = _box((0, -100, 0), (5000, 100, 400))
        assert orientation(plate, beam, 1.0, 1.0)["length"] is None

    def test_skew_angle_is_rounded_after_labelling(self):
        x, y = _plan_axes(30.04)
        a = _box((0, -100, 0), (5000, 100, 400))
        b = _box((0, -100, 0), (5000, 100, 400), axis_x=x, axis_y=y)
        result = orientation(a, b, 1.0, 1.0)
        assert result["length"] == {"angle_deg": 30.0, "label": "skew"}

    def test_reversed_axes_still_parallel(self):
        a = _box((0, -100, 0), (5000, 100, 400))
        b = _box((0, -100, 0), (5000, 100, 400), axis_x=(-1.0, 0.0, 0.0), axis_y=(0.0, -1.0, 0.0))
        assert orientation(a, b, 1.0, 1.0)["length"]["label"] == "parallel"

    @pytest.mark.parametrize("angle, expected", [(0.0, "parallel"), (1.0, "parallel"), (45.0, "skew"), (89.0, "perpendicular"), (90.0, "perpendicular")])
    def test_angle_label(self, angle, expected):
        assert angle_label(angle, 1.0) == expected


class TestSearchExtents:
    def test_axis_aligned_box_keeps_one_extent(self):
        box = _box((0, -100, 0), (6000, 100, 3000))
        extents = search_extents(box, 100)
        assert len(extents) == 1
        lo, hi = extents[0]
        assert lo == pytest.approx((-100, -200, -100))
        assert hi == pytest.approx((6100, 200, 3100))

    def test_rotated_beam_is_cut_into_tight_pieces(self):
        x, y = _plan_axes(45)
        beam = _box((0, -40, -40), (10000, 40, 40), axis_x=x, axis_y=y)
        extents = search_extents(beam, 100)
        single_lo, single_hi = aabb([beam], 100)
        single_volume = float(np.prod(single_hi - single_lo))
        assert 1 < len(extents) <= 16
        assert sum(float(np.prod(hi - lo)) for lo, hi in extents) < single_volume / 5

    def test_pieces_cover_everything_within_the_radius(self):
        x, y = _plan_axes(30)
        beam = _box((0, -40, -40), (8000, 40, 40), axis_x=x, axis_y=y)
        grow = 100
        rng = np.random.default_rng(1)
        extents = search_extents(beam, grow)
        # Points on the beam's surface pushed outwards by just under `grow`
        local = rng.uniform(-1, 1, size=(2000, 3)) * beam.half
        axis = rng.integers(0, 3, size=2000)
        local[np.arange(2000), axis] = np.sign(local[np.arange(2000), axis]) * (beam.half[axis] + grow * 0.99)
        points = beam.center + local @ beam.axes
        inside = np.zeros(len(points), dtype=bool)
        for lo, hi in extents:
            inside |= np.all((points >= lo) & (points <= hi), axis=1)
        assert inside.all()


class TestSmallerBox:
    def test_global_box_wins_for_a_part_whose_own_axes_do_not_fit(self):
        # A bent PolyBeam: its own-axis box follows the first segment and is far too large
        x, y = _plan_axes(40)
        own = _box((0, -800, 0), (2500, 800, 2900), axis_x=x, axis_y=y)
        global_box = _box((0, 0, 0), (120, 190, 2900))
        assert smaller_box(own, global_box) is global_box

    def test_own_box_wins_for_a_rotated_straight_member(self):
        x, y = _plan_axes(45)
        own = _box((0, -40, -40), (10000, 40, 40), axis_x=x, axis_y=y)
        lo, hi = aabb([own])
        global_box = _box(tuple(lo), tuple(hi))
        assert smaller_box(own, global_box) is own

    def test_tie_keeps_the_first(self):
        a = _box((0, 0, 0), (10, 10, 10))
        b = _box((0, 0, 0), (10, 10, 10))
        assert smaller_box(a, b) is a
