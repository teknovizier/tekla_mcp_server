"""
Pure geometry helpers: 2D boxes and segments for drawings, 3D oriented boxes for the model.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

EPSILON = 0.0001  # near-zero threshold

# 2D: drawing sheets and views


class BBox(tuple):
    """
    Axis-aligned 2D bounding box.

    Stores (xmin, ymin, xmax, ymax) and provides geometric analysis methods.
    Subclasses tuple so it is JSON-serialisable and supports unpacking.
    """

    def __new__(cls, xmin: float, ymin: float, xmax: float, ymax: float) -> BBox:
        """
        Create a bounding box from its extents.

        Args:
            xmin: Minimum X
            ymin: Minimum Y
            xmax: Maximum X
            ymax: Maximum Y

        Returns:
            New `BBox`
        """
        return tuple.__new__(cls, (xmin, ymin, xmax, ymax))

    @property
    def xmin(self) -> float:
        """Minimum X coordinate."""
        return self[0]

    @property
    def ymin(self) -> float:
        """Minimum Y coordinate."""
        return self[1]

    @property
    def xmax(self) -> float:
        """Maximum X coordinate."""
        return self[2]

    @property
    def ymax(self) -> float:
        """Maximum Y coordinate."""
        return self[3]

    @property
    def width(self) -> float:
        """Width along X axis (xmax - xmin)."""
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        """Height along Y axis (ymax - ymin)."""
        return self.ymax - self.ymin

    @property
    def cx(self) -> float:
        """Center X coordinate."""
        return (self.xmin + self.xmax) / 2

    @property
    def cy(self) -> float:
        """Center Y coordinate."""
        return (self.ymin + self.ymax) / 2

    @property
    def area(self) -> float:
        """Bounding box area."""
        return self.width * self.height

    @staticmethod
    def from_points(points: list[tuple[float, float]]) -> BBox:
        """
        Compute the tight axis-aligned bounding box enclosing all given points.

        Args:
            points: List of (x, y) coordinates.

        Returns:
            BBox covering all points.
        """
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return BBox(min(xs), min(ys), max(xs), max(ys))

    def overlaps(self, other: BBox) -> bool:
        """
        Check whether two axis-aligned rectangles intersect.

        Args:
            other: Another bounding box.

        Returns:
            True if the rectangles overlap.
        """
        return self.xmin < other.xmax and other.xmin < self.xmax and self.ymin < other.ymax and other.ymin < self.ymax

    def contains_point(self, x: float, y: float) -> bool:
        """
        Check if a point is inside this bounding box (inclusive).

        Args:
            x: X coordinate.
            y: Y coordinate.

        Returns:
            True if the point lies within the box.
        """
        return self.xmin <= x <= self.xmax and self.ymin <= y <= self.ymax

    def inset(self, pad: float) -> BBox:
        """
        Shrink the bounding box inward by `pad` on every side.

        Each axis is handled independently: an axis too narrow to absorb the padding
        collapses to its own center, while the other keeps its extent. Collapsing both
        axes together would reduce a long, thin box - a narrow view frame, say - to a
        single point, hiding it from every check that works on the inset frame.

        Args:
            pad: Distance to inset from each edge.

        Returns:
            A new inset BBox.
        """
        if self.width <= 2 * pad:
            x0 = x1 = self.cx
        else:
            x0, x1 = self.xmin + pad, self.xmax - pad
        if self.height <= 2 * pad:
            y0 = y1 = self.cy
        else:
            y0, y1 = self.ymin + pad, self.ymax - pad
        return BBox(x0, y0, x1, y1)

    def intersection(self, other: BBox) -> BBox | None:
        """
        Return the overlapping region of two bounding boxes.

        Args:
            other: Another bounding box.

        Returns:
            The intersection BBox, or None if they do not overlap.
        """
        ox0 = max(self.xmin, other.xmin)
        oy0 = max(self.ymin, other.ymin)
        ox1 = min(self.xmax, other.xmax)
        oy1 = min(self.ymax, other.ymax)
        if ox0 <= ox1 and oy0 <= oy1:
            return BBox(ox0, oy0, ox1, oy1)
        return None

    def union(self, other: BBox) -> BBox:
        """
        Return the minimal BBox that encloses both input boxes.

        Args:
            other: Another bounding box.

        Returns:
            The union BBox.
        """
        return BBox(
            min(self.xmin, other.xmin),
            min(self.ymin, other.ymin),
            max(self.xmax, other.xmax),
            max(self.ymax, other.ymax),
        )

    def gap(self, other: BBox) -> float:
        """
        Euclidean gap between two bounding boxes.

        Args:
            other: Another bounding box.

        Returns:
            Distance between the boxes, 0.0 if they overlap or touch.
        """
        dx = max(other.xmin - self.xmax, self.xmin - other.xmax, 0.0)
        dy = max(other.ymin - self.ymax, self.ymin - other.ymax, 0.0)
        return math.hypot(dx, dy)


class Segment(tuple):
    """
    2D line segment from (x0, y0) to (x1, y1).

    Subclasses tuple so it is JSON-serialisable and supports unpacking.
    """

    def __new__(cls, x0: float, y0: float, x1: float, y1: float) -> Segment:
        """
        Create a segment from its endpoints.

        Args:
            x0: Start X
            y0: Start Y
            x1: End X
            y1: End Y

        Returns:
            New `Segment`
        """
        return tuple.__new__(cls, ((x0, y0), (x1, y1)))


# 3D: oriented boxes for the model, all values in global mm

FloatArray = npt.NDArray[np.float64]
# Axis-aligned extent as (min corner, max corner)
Extent = tuple[FloatArray, FloatArray]

# Side names per global axis, (positive, negative)
SIDE_NAMES: tuple[tuple[str, str], ...] = (("+X", "-X"), ("+Y", "-Y"), ("above", "below"))
SIDE_ORDER = ("above", "below", "+X", "-X", "+Y", "-Y")
AXIS_NAMES = ("length", "width", "thickness")

Relation = Literal["boxes_overlap", "touching", "near"]

# Corner signs, row index bits are (x, y, z)
_CORNER_SIGNS = np.array(list(itertools.product((-1.0, 1.0), repeat=3)))
# An edge joins two corners whose index differs in one bit
_EDGES = np.array([(i, i ^ bit) for i in range(8) for bit in (4, 2, 1) if not i & bit])


@dataclass(frozen=True, eq=False)
class OrientedBox:
    """
    Box with its own orthonormal axes, in global coordinates.

    Attributes:
        center: Box center, shape (3,)
        axes: Unit axes as rows, shape (3, 3)
        half: Half-extents along `axes`, shape (3,)
    """

    center: FloatArray
    axes: FloatArray
    half: FloatArray

    @classmethod
    def from_local_extent(cls, origin: npt.ArrayLike, axis_x: npt.ArrayLike, axis_y: npt.ArrayLike, local_min: npt.ArrayLike, local_max: npt.ArrayLike) -> OrientedBox:
        """
        Build a box from an extent read in a local coordinate system.

        Args:
            origin: Local system origin in global coordinates
            axis_x: Local X axis, any length
            axis_y: Local Y axis, any length, made orthogonal to `axis_x`
            local_min: Extent minimum in local coordinates
            local_max: Extent maximum in local coordinates

        Returns:
            The box in global coordinates
        """
        x = _unit(np.asarray(axis_x, dtype=float))
        y_raw = np.asarray(axis_y, dtype=float)
        y = _unit(y_raw - x * (y_raw @ x))
        axes = np.array([x, y, np.cross(x, y)])
        lo, hi = np.asarray(local_min, dtype=float), np.asarray(local_max, dtype=float)
        return cls(center=np.asarray(origin, dtype=float) + (lo + hi) / 2 @ axes, axes=axes, half=(hi - lo) / 2)

    def corners(self) -> FloatArray:
        """
        Return the 8 corner points.

        Returns:
            Corners, shape (8, 3), row index bits are (x, y, z) sign
        """
        return self.center + (_CORNER_SIGNS * self.half) @ self.axes

    def project(self, axis: FloatArray) -> tuple[float, float]:
        """
        Project the box on a unit axis.

        Args:
            axis: Unit direction

        Returns:
            (min, max) of the projection
        """
        c = float(self.center @ axis)
        r = float(self.half @ np.abs(self.axes @ axis))
        return c - r, c + r

    def distance_to_points(self, points: FloatArray) -> FloatArray:
        """
        Return the distance from each point to the box, 0 inside.

        Args:
            points: Points in global coordinates, shape (n, 3)

        Returns:
            Distances in mm, shape (n,)
        """
        local = (points - self.center) @ self.axes.T
        return np.linalg.norm(np.maximum(np.abs(local) - self.half, 0.0), axis=-1)


def _unit(v: FloatArray) -> FloatArray:
    """
    Scale a vector to length 1.

    Args:
        v: FloatArray to normalize

    Returns:
        Unit vector

    Raises:
        ValueError: If the vector has zero length.
    """
    length = np.linalg.norm(v)
    if length < EPSILON:
        raise ValueError("Cannot normalize a zero-length vector")
    return v / length


def segment_distances(p1: FloatArray, q1: FloatArray, p2: FloatArray, q2: FloatArray) -> FloatArray:
    """
    Return the shortest distances between segments, for any broadcastable shapes (..., 3).

    numpy has no segment-to-segment distance, so this is the closest-point method from
    Ericson, Real-Time Collision Detection, section 5.1.9, done for all pairs at once.

    Args:
        p1: Starts of the first segments
        q1: Ends of the first segments
        p2: Starts of the second segments
        q2: Ends of the second segments

    Returns:
        Distances in mm, the broadcast shape without the last axis
    """
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, b, c = np.sum(d1 * d1, -1), np.sum(d1 * d2, -1), np.sum(d1 * r, -1)
    e, f = np.sum(d2 * d2, -1), np.sum(d2 * r, -1)
    denom = a * e - b * b
    # EPSILON only tells zero from non-zero here. A wrong branch on a near-zero squared length
    # still gives a point on the segment, and the result is clamped
    with np.errstate(divide="ignore", invalid="ignore"):
        # Parallel or point segments take s = 0, any value on the segment is as good
        s = np.where(denom > EPSILON, np.clip((b * f - c * e) / denom, 0.0, 1.0), 0.0)
        t = np.where(e > EPSILON, (b * s + f) / e, 0.0)
        # When t leaves the second segment, clamp it and recompute s
        s = np.where(t < 0.0, np.where(a > EPSILON, np.clip(-c / a, 0.0, 1.0), 0.0), s)
        s = np.where(t > 1.0, np.where(a > EPSILON, np.clip((b - c) / a, 0.0, 1.0), 0.0), s)
        # A point as the second segment fixes t = 0
        s = np.where((e <= EPSILON) & (a > EPSILON), np.clip(-c / a, 0.0, 1.0), s)
    t = np.clip(t, 0.0, 1.0)
    return np.linalg.norm(p1 + d1 * s[..., None] - p2 - d2 * t[..., None], axis=-1)


def _penetration_depth(a: OrientedBox, b: OrientedBox) -> float | None:
    """
    Run the separating-axis test on two boxes.

    The depth is the shortest move along any tested axis that gets the boxes clear of
    each other. For partly overlapping boxes it equals the overlap length. For a box
    inside another it includes the way out, e.g. an embed 290 mm deep in a wall gives
    about 300, not its own 10 mm thickness.

    Args:
        a: First box
        b: Second box

    Returns:
        Shortest move to get clear in mm, or None when the boxes are separated
    """
    crosses = np.cross(a.axes[:, None, :], b.axes[None, :, :]).reshape(9, 3)
    lengths = np.linalg.norm(crosses, axis=1)
    # Near-parallel edges give no new separating direction
    axes = np.vstack([a.axes, b.axes, crosses[lengths > EPSILON] / lengths[lengths > EPSILON, None]])
    a_center, b_center = axes @ a.center, axes @ b.center
    a_radius, b_radius = np.abs(axes @ a.axes.T) @ a.half, np.abs(axes @ b.axes.T) @ b.half
    # Move b past a's far side, or past a's near side, whichever is shorter
    depth = np.minimum(a_center + a_radius - (b_center - b_radius), b_center + b_radius - (a_center - a_radius))
    return None if np.any(depth < 0.0) else float(depth.min())


def _separated_distance(a: OrientedBox, b: OrientedBox) -> float:
    """
    Return the exact distance between two disjoint boxes.

    The closest points of two disjoint convex boxes are a corner and a box, or two edges.

    Args:
        a: First box
        b: Second box

    Returns:
        Distance in mm
    """
    a_corners, b_corners = a.corners(), b.corners()
    corner = min(b.distance_to_points(a_corners).min(), a.distance_to_points(b_corners).min())
    a_edges, b_edges = a_corners[_EDGES], b_corners[_EDGES]
    edge = segment_distances(a_edges[:, None, 0], a_edges[:, None, 1], b_edges[None, :, 0], b_edges[None, :, 1]).min()
    return float(min(corner, edge))


def box_gap(a: OrientedBox, b: OrientedBox) -> tuple[float, float]:
    """
    Return the clear distance and the penetration between two boxes.

    Args:
        a: First box
        b: Second box

    Returns:
        (gap, penetration). One of them is always 0.
    """
    depth = _penetration_depth(a, b)
    if depth is not None:
        return 0.0, depth
    return _separated_distance(a, b), 0.0


def relation(gap: float, penetration: float, tolerance: float) -> Relation:
    """
    Classify contact between two boxes.

    Args:
        gap: Clear distance in mm
        penetration: Penetration depth in mm
        tolerance: Contact tolerance in mm, applied to both gap and penetration

    Returns:
        'boxes_overlap', 'touching' or 'near'
    """
    if penetration > tolerance:
        return "boxes_overlap"
    if gap <= tolerance:
        return "touching"
    return "near"


def aabb(boxes: Sequence[OrientedBox], grow: float = 0.0) -> Extent:
    """
    Return the global axis-aligned extent of one or more boxes.

    Args:
        boxes: At least one box
        grow: Distance in mm added on every side

    Returns:
        (min corner, max corner)
    """
    corners = np.vstack([box.corners() for box in boxes])
    return corners.min(axis=0) - grow, corners.max(axis=0) + grow


def smaller_box(*boxes: OrientedBox) -> OrientedBox:
    """
    Return the box with the smallest volume.

    Callers pass boxes that all enclose the same part, so the smallest one is the
    tightest fit and keeps every gap as close to the real one as boxes allow.

    Args:
        boxes: At least one box

    Returns:
        The smallest box, the first one on a tie
    """
    return min(boxes, key=lambda box: float(np.prod(box.half)))


def search_extents(box: OrientedBox, grow: float, max_pieces: int = 16) -> list[Extent]:
    """
    Cover a box grown by `grow` with axis-aligned extents for a spatial search.

    The extent of a rotated long box is much larger than the box, e.g. a 10 m beam at
    45 degrees in plan spans about 7 x 7 m. Such a box is cut along its length into pieces
    whose extents stay close to it. A box whose extent is at most twice its own volume
    keeps a single extent.

    Args:
        box: Box to cover
        grow: Distance in mm added on every side
        max_pieces: Most pieces one box is cut into

    Returns:
        Extents whose union covers everything within `grow` of the box
    """
    lo, hi = aabb([box], grow)
    if np.prod(hi - lo) <= 2 * np.prod(2 * (box.half + grow)):
        return [(lo, hi)]
    i = int(np.argmax(box.half))
    length = 2 * box.half[i]
    # Pieces about as long as the box is wide, so each piece's extent stays tight
    piece = max(float(np.sort(2 * box.half)[1]), 2 * grow, 1.0)
    count = min(max_pieces, max(1, math.ceil(length / piece)))
    half = box.half.copy()
    half[i] = length / count / 2
    offsets = -box.half[i] + (np.arange(count) + 0.5) * (length / count)
    return [aabb([OrientedBox(center=box.center + box.axes[i] * offset, axes=box.axes, half=half)], grow) for offset in offsets]


def aabb_gap(a: Extent, b: Extent) -> float:
    """
    Return the distance between two axis-aligned extents, 0 when they overlap.

    Args:
        a: (min corner, max corner)
        b: (min corner, max corner)

    Returns:
        Distance in mm
    """
    return float(np.linalg.norm(np.maximum.reduce([b[0] - a[1], a[0] - b[1], np.zeros(3)])))


def _interval(boxes: Sequence[OrientedBox], axis: FloatArray) -> tuple[float, float]:
    """
    Project several boxes on one axis.

    Args:
        boxes: At least one box
        axis: Unit direction

    Returns:
        (min, max) over all boxes
    """
    projections = [box.project(axis) for box in boxes]
    return min(p[0] for p in projections), max(p[1] for p in projections)


def sides(source: Sequence[OrientedBox], neighbour: Sequence[OrientedBox], tolerance: float) -> list[str]:
    """
    List the global sides of the source on which the neighbour lies entirely.

    Args:
        source: Boxes of the source
        neighbour: Boxes of the neighbour
        tolerance: Contact tolerance in mm

    Returns:
        Side names in `SIDE_ORDER`
    """
    (s_min, s_max), (n_min, n_max) = aabb(source), aabb(neighbour)
    found = set()
    for k, (positive, negative) in enumerate(SIDE_NAMES):
        if n_min[k] >= s_max[k] - tolerance:
            found.add(positive)
        if n_max[k] <= s_min[k] + tolerance:
            found.add(negative)
    return [name for name in SIDE_ORDER if name in found]


def ranked_axes(box: OrientedBox) -> tuple[FloatArray, FloatArray]:
    """
    Order box axes by extent as length, width and thickness.

    Equal extents keep coordinate-system order.

    Args:
        box: Oriented box

    Returns:
        (axes as rows, full extents), both ordered length, width, thickness
    """
    order = np.argsort(-box.half, kind="stable")
    return box.axes[order], 2 * box.half[order]


def axis_overlap(axes_box: OrientedBox, source: Sequence[OrientedBox], neighbour: Sequence[OrientedBox]) -> dict[str, float]:
    """
    Measure how far source and neighbour overlap along the source's own axes.

    Args:
        axes_box: Box whose length, width and thickness axes are used
        source: Boxes of the source
        neighbour: Boxes of the neighbour

    Returns:
        Overlap in mm per axis name, 0 when separated
    """
    axes, _ = ranked_axes(axes_box)
    result = {}
    for name, axis in zip(AXIS_NAMES, axes, strict=True):
        s_min, s_max = _interval(source, axis)
        n_min, n_max = _interval(neighbour, axis)
        result[name] = max(min(s_max, n_max) - max(s_min, n_min), 0.0)
    return result


def angle_label(angle: float, angle_tolerance: float) -> str:
    """
    Label an angle between 0 and 90 degrees.

    Args:
        angle: Angle in degrees
        angle_tolerance: Tolerance in degrees

    Returns:
        'parallel', 'perpendicular' or 'skew'
    """
    if angle <= angle_tolerance:
        return "parallel"
    if angle >= 90.0 - angle_tolerance:
        return "perpendicular"
    return "skew"


def orientation(a: OrientedBox, b: OrientedBox, tolerance: float, angle_tolerance: float) -> dict[str, dict[str, float | str] | None]:
    """
    Compare the length axes and the thickness axes of two boxes.

    An axis is undefined when its extent is within `tolerance` of the next one, e.g. the
    thickness of a square column. The label is decided before the angle is rounded.

    Args:
        a: First box
        b: Second box
        tolerance: Extent tie tolerance in mm
        angle_tolerance: Label tolerance in degrees

    Returns:
        Per axis name ('length', 'thickness'), the angle rounded to 0.1 and its label, or None when either axis is undefined
    """
    (a_axes, a_ext), (b_axes, b_ext) = ranked_axes(a), ranked_axes(b)
    result: dict[str, dict[str, float | str] | None] = {}
    # Length is defined when it beats the width, thickness when the width beats it
    for name, index, (longer, shorter) in (("length", 0, (0, 1)), ("thickness", 2, (1, 2))):
        if a_ext[longer] - a_ext[shorter] <= tolerance or b_ext[longer] - b_ext[shorter] <= tolerance:
            result[name] = None
            continue
        # Axes have no direction, so the absolute cosine folds the angle into 0..90
        angle = float(np.degrees(np.arccos(min(abs(float(a_axes[index] @ b_axes[index])), 1.0))))
        result[name] = {"angle_deg": round(angle, 1), "label": angle_label(angle, angle_tolerance)}
    return result
