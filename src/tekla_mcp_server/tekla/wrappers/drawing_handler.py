"""
Module for Tekla DrawingHandler wrapper.
"""

from typing import Any

from tekla_mcp_server.tekla.loader import ContainerView, DrawingHandler, DrawingObject, DrawingView
from tekla_mcp_server.tekla.utils import to_array_list

from tekla_mcp_server.tekla.wrappers.drawing import TeklaDrawing, wrap_drawings
from tekla_mcp_server.tekla.wrappers.view import TeklaDrawingView


class TeklaDrawingHandler:
    """
    A thin wrapper around a Tekla Structures DrawingHandler object.

    NOTE: Not a singleton - creates a fresh DrawingHandler per instance,
    matching the original `get_drawing_handler()` semantics.
    """

    def __init__(self) -> None:
        self._handler = DrawingHandler()
        if not self._handler.GetConnectionStatus():
            raise ConnectionError("Not connected to Tekla")

    @property
    def handler(self) -> DrawingHandler:
        """Returns the underlying DrawingHandler instance."""
        return self._handler

    def get_connection_status(self) -> bool:
        """Check if the connection to Tekla is still active."""
        return self._handler.GetConnectionStatus()

    def get_active_drawing(self) -> TeklaDrawing | None:
        """Return the active drawing, or None if none is open."""
        drawing = self._handler.GetActiveDrawing()
        return TeklaDrawing(drawing) if drawing is not None else None

    def require_active_drawing(self) -> TeklaDrawing:
        """Return the active drawing, or raise RuntimeError if none is open."""
        drawing = self.get_active_drawing()
        if drawing is None:
            raise RuntimeError("No drawing is currently open.")
        return drawing

    def set_active_drawing(self, drawing: TeklaDrawing) -> bool:
        """Open a drawing in the drawing editor. Returns True on success."""
        return self._handler.SetActiveDrawing(drawing.drawing)

    def close_active_drawing(self, save: bool = True) -> bool:
        """Close the active drawing. Returns True on success."""
        return self._handler.CloseActiveDrawing(save)

    def save_active_drawing(self) -> bool:
        """Save the active drawing. Returns True on success."""
        return self._handler.SaveActiveDrawing()

    def issue_drawing(self, drawing: TeklaDrawing) -> bool:
        """Issue the drawing. Returns True on success."""
        return self._handler.IssueDrawing(drawing.drawing)

    def unissue_drawing(self, drawing: TeklaDrawing) -> bool:
        """Unissue the drawing. Returns True on success."""
        return self._handler.UnissueDrawing(drawing.drawing)

    def update_drawing(self, drawing: TeklaDrawing) -> bool:
        """Update the drawing. Returns True on success."""
        return self._handler.UpdateDrawing(drawing.drawing)

    def get_all_drawings(self) -> list[TeklaDrawing]:
        """Return all drawings in the model."""
        return wrap_drawings(self._handler.GetDrawings())

    def get_drawings_by_marks(self, marks: list[str] | None = None) -> list[TeklaDrawing]:
        """Get drawings by marks, or from the current selection if marks is None."""
        if marks is not None:
            if not marks:
                raise ValueError("No drawings found or selected")
            all_drawings = self.get_all_drawings()
            result = [d for d in all_drawings if d.mark in marks]
        else:
            result = wrap_drawings(self._handler.GetDrawingSelector().GetSelected())
        if not result:
            raise ValueError("No drawings found or selected")
        return result

    def get_drawing_views(self, sheet: ContainerView | None = None) -> list[TeklaDrawingView]:
        """
        Return all DrawingView objects from the active drawing's sheet.

        Args:
            sheet: Optional pre-retrieved sheet. Avoids an extra GetSheet() call.

        Returns:
            List of TeklaDrawingView wrappers.

        Raises:
            RuntimeError: If no drawing is open or the sheet cannot be obtained.
        """
        if sheet is None:
            drawing = self._handler.GetActiveDrawing()
            if drawing is None:
                raise RuntimeError("No drawing is currently open.")
            sheet = drawing.GetSheet()
            if sheet is None:
                raise RuntimeError("Failed to get sheet for active drawing.")

        # Sheet view first so callers always get a consistent index[0] for it
        result: list[TeklaDrawingView] = [TeklaDrawingView(sheet)]
        views_enum = sheet.GetViews()
        while views_enum.MoveNext():
            view = views_enum.Current
            if isinstance(view, DrawingView):
                result.append(TeklaDrawingView(view))
        return result

    def index_views_by_key(self) -> dict[str, TeklaDrawingView]:
        """Return {view_key: TeklaDrawingView} for all views in the active drawing."""
        return {v.view_key: v for v in self.get_drawing_views()}

    def get_view_by_key(self, view_key: str) -> TeklaDrawingView:
        """Return the TeklaDrawingView matching view_key, or raise ValueError."""
        view = self.index_views_by_key().get(view_key)
        if view is None:
            raise ValueError(f"No view found with key '{view_key}'. Use `get_drawing_views` to list available keys.")
        return view

    def print_drawing(self, drawing: TeklaDrawing, print_attributes: Any, output_file: str) -> bool:
        """Print a drawing. Returns True on success."""
        return self._handler.PrintDrawing(drawing.drawing, print_attributes, output_file)

    def select_drawing_objects(self, objects: list[DrawingObject]) -> bool:
        """Select the given drawing objects in the active drawing. Returns True on success."""
        return self._handler.GetDrawingObjectSelector().SelectObjects(to_array_list(objects), False)

    def unselect_drawing_objects(self, objects: list[DrawingObject]) -> bool:
        """Unselect the given drawing objects in the active drawing. Returns True on success."""
        return self._handler.GetDrawingObjectSelector().UnselectObjects(to_array_list(objects))
