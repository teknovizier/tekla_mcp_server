"""
Module for Tekla Drawing View wrappers.
"""

from typing import Any, overload

from tekla_mcp_server.tekla.loader import SystemType, SystemArray, DrawingView, DrawingObject, SectionMark, BindingFlags, Point
from tekla_mcp_server.init import logger


class TeklaDrawingView:
    """
    A thin wrapper around a Tekla Structures drawing View object.
    """

    def __init__(self, view: DrawingView):
        self._view = view
        self._view_key: str | None = None

    @property
    def view(self) -> DrawingView:
        """Returns the underlying DrawingView instance."""
        return self._view

    @property
    def name(self) -> str | None:
        """Returns the view name, or None if blank."""
        raw = (getattr(self._view, "Name", "") or "").strip()
        return raw or None

    @property
    def view_type(self) -> str:
        """Returns the semantic view type (e.g. 'SectionView', 'FrontView')."""
        try:
            return str(self._view.ViewType)
        except Exception:
            return self._view.GetType().Name

    @property
    def view_key(self) -> str:
        """
        Key: {ViewType}_{Identifier.ID}.

        Unlike Tekla ModelObject types, DrawingView does NOT have a public
        GUID or Identifier property - they are deliberately non-public in the
        Tekla.Structures.Drawing namespace. This uses the same reflection
        workaround as the drawing revision mark.

        The Identifier.ID is NOT stable across Tekla sessions - IDs are reassigned
        when the model is reopened, so the key may change between server runs.

        Falls back to {ViewType}_{origin_x}_{origin_y} if the ID cannot be
        read via reflection. Cached on first access so the key remains stable
        for the lifetime of this wrapper (e.g. does not change after a move).
        """
        if self._view_key is not None:
            return self._view_key
        try:
            pi = self._view.GetType().GetProperty(
                "Identifier",
                BindingFlags.Instance | BindingFlags.NonPublic,
            )
            if pi is not None:
                self._view_key = f"{self.view_type}_{pi.GetValue(self._view, None).ID}"
                return self._view_key
        except Exception:
            pass
        self._view_key = f"{self.view_type}_{round(self._view.Origin.X)}_{round(self._view.Origin.Y)}"
        return self._view_key

    @property
    def scale(self) -> float:
        """Returns the view scale."""
        return self._view.Attributes.Scale

    @property
    def is_sheet(self) -> bool:
        """Returns whether this is the sheet view."""
        return self._view.IsSheet

    @property
    def origin_x(self) -> float:
        """Returns the X origin of the view on the sheet (mm)."""
        return round(self._view.Origin.X, 1)

    @property
    def origin_y(self) -> float:
        """Returns the Y origin of the view on the sheet (mm)."""
        return round(self._view.Origin.Y, 1)

    @property
    def width(self) -> float:
        """Returns the view width (mm)."""
        return round(self._view.Width, 1)

    @property
    def height(self) -> float:
        """Returns the view height (mm)."""
        return round(self._view.Height, 1)

    @property
    def origin(self) -> tuple[float, float]:
        """Returns the (x, y) origin of the view on the sheet (mm)."""
        return (round(self._view.Origin.X, 1), round(self._view.Origin.Y, 1))

    @origin.setter
    def origin(self, xy: tuple[float, float]) -> None:
        """Sets the view origin (x, y) in mm."""
        if not isinstance(xy, tuple) or len(xy) != 2:
            raise ValueError(f"Expected (x, y) tuple, got {xy!r}")
        self._view.Origin = Point(xy[0], xy[1], 0)

    @property
    def frame_origin(self) -> tuple[float, float]:
        """
        Bottom-left corner (x, y) of the visible view frame on the sheet (mm).

        Unlike `origin` (the view's coordinate-system origin, which for
        section and detail views sits at the cut line or detail callout
        inside the source view), this is the corner of the visible view box:
        the view occupies the rectangle `frame_origin` + (`width`, `height`)
        on the sheet.
        """
        aabb = self._view.GetAxisAlignedBoundingBox()
        return (round(aabb.MinPoint.X, 1), round(aabb.MinPoint.Y, 1))

    def modify(self) -> bool:
        """Commits attribute changes to Tekla. Returns True on success."""
        return self._view.Modify()

    def delete(self) -> bool:
        """Deletes the view from the drawing. Returns True on success."""
        return self._view.Delete()

    def set_scale(self, scale: float) -> bool:
        """
        Sets the view scale and commits via Modify().

        Args:
            scale: New scale value (e.g. 20 for 1:20, 50 for 1:50).

        Returns:
            True if Modify() succeeded.
        """
        attrs = self._view.Attributes
        attrs.Scale = scale
        self._view.Attributes = attrs
        return self._view.Modify()

    @overload
    def get_all_objects(self) -> list[DrawingObject] | None: ...

    @overload
    def get_all_objects(self, type_filter: list[type]) -> list[DrawingObject] | None: ...

    def get_all_objects(self, type_filter: list[type] | None = None) -> list[DrawingObject] | None:
        """
        Return all DrawingObject instances in this view as a plain list,
        or None if enumeration fails (e.g. disconnection or corrupted view state).
        Pass a list of types to let Tekla pre-filter via `GetAllObjects(Type[])`.
        """
        if type_filter is not None and not type_filter:
            raise ValueError("type_filter must not be empty")
        try:
            if type_filter is None:
                enum = self._view.GetAllObjects()
            else:
                enum = self._view.GetAllObjects(SystemArray[SystemType](type_filter))
            result: list[Any] = []
            while enum.MoveNext():
                obj = enum.Current
                if obj is not None:
                    result.append(obj)
            return result
        except Exception as e:
            logger.warning("get_all_objects() failed for view '%s': %s", self.view_key, e)
            return None

    def get_section_marks(self) -> list[tuple[str, SectionMark]]:
        """
        Return all SectionMark objects in this view as (mark_name, mark) tuples.

        A SectionMark labels a cut taken in this view; its MarkName matches
        the name of the section view it produced.

        Returns:
            List of (mark_name, mark) tuples. Empty if none found or
            enumeration fails. Marks with a blank MarkName are skipped.
        """
        objs = self.get_all_objects([SectionMark])
        if objs is None:
            return []
        result: list[tuple[str, SectionMark]] = []
        for obj in objs:
            attrs = obj.Attributes
            if attrs is None:
                continue
            name = attrs.MarkName or ""
            if name:
                result.append((name, obj))
        return result

    def to_dict(self) -> dict[str, Any]:
        """Returns a serialisable dict of all view metadata."""
        fx, fy = self.frame_origin
        return {
            "name": self.name,
            "view_key": self.view_key,
            "view_type": self.view_type,
            "scale": self.scale,
            "is_sheet": self.is_sheet,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "frame_origin_x": fx,
            "frame_origin_y": fy,
            "width": self.width,
            "height": self.height,
        }
