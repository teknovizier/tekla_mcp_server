"""
Module for Tekla Drawing wrappers.
"""

from typing import Any

from tekla_mcp_server.tekla.loader import Drawing, DrawingEnumerator, DrawingHandler


class TeklaDrawing:
    """
    A thin wrapper class around the Tekla Structures Drawing object.
    """

    def __init__(self, drawing: Drawing):
        self._drawing = drawing

    @property
    def drawing(self) -> Drawing:
        """
        Returns the underlying Drawing instance.
        """
        return self._drawing

    @property
    def name(self) -> str:
        """
        Returns the name of the drawing.
        """
        return self.drawing.Name

    @property
    def mark(self) -> str:
        """
        Returns the mark of the drawing.
        """
        return self.drawing.Mark

    @property
    def drawing_type(self) -> str:
        """
        Returns the type of the drawing.
        """
        try:
            return self.drawing.DrawingTypeStr
        except AttributeError:
            return self.drawing.GetType().Name.replace("Drawing", "")

    @property
    def is_frozen(self) -> bool:
        """
        Returns whether the drawing is frozen.
        """
        return self.drawing.IsFrozen

    @property
    def is_locked(self) -> bool:
        """
        Returns whether the drawing is locked.
        """
        return self.drawing.IsLocked

    @property
    def is_issued(self) -> bool:
        """
        Returns whether the drawing is issued.
        """
        return self.drawing.IsIssued

    @property
    def is_issued_but_modified(self) -> bool:
        """
        Returns whether the drawing is issued but modified.
        """
        return self.drawing.IsIssuedButModified

    @property
    def is_ready_for_issue(self) -> bool:
        """
        Returns whether the drawing is ready for issue.
        """
        return self.drawing.IsReadyForIssue

    @property
    def is_master_drawing(self) -> bool:
        """
        Returns whether the drawing is a master drawing.
        """
        try:
            return self.drawing.IsMasterDrawing
        except AttributeError:
            return False

    @property
    def title1(self) -> str:
        """
        Returns the first drawing title.
        """
        return self.drawing.Title1

    @property
    def title2(self) -> str:
        """
        Returns the second drawing title.
        """
        return self.drawing.Title2

    @property
    def title3(self) -> str:
        """
        Returns the third drawing title.
        """
        return self.drawing.Title3

    @property
    def creation_date(self) -> Any:
        """
        Returns the drawing creation date.
        """
        return self.drawing.CreationDate

    @property
    def modification_date(self) -> Any:
        """
        Returns the drawing modification date.
        """
        return self.drawing.ModificationDate

    @property
    def issuing_date(self) -> Any:
        """
        Returns the drawing issuing date.
        """
        return self.drawing.IssuingDate

    @property
    def output_date(self) -> Any:
        """
        Returns the drawing output date.
        """
        return self.drawing.OutputDate

    @property
    def up_to_date_status(self) -> str:
        """
        Returns the drawing up to date status.
        """
        try:
            return str(self.drawing.UpToDateStatus)
        except AttributeError:
            return ""

    @property
    def commit_message(self) -> str:
        """
        Returns the commit message.
        """
        return self.drawing.CommitMessage

    def _format_date(self, dt: Any) -> str | None:
        """
        Format date, returning None if it's a zero date.
        """
        if dt is None:
            return None
        if hasattr(dt, "Year") and dt.Year == 1:
            return None
        return str(dt)

    def to_dict(self) -> dict[str, Any]:
        """
        Converts the drawing to a dictionary.
        """
        return {
            "drawing_type": self.drawing_type,
            "mark": self.mark,
            "name": self.name,
            "title1": self.title1,
            "title2": self.title2,
            "title3": self.title3,
            "modification_date": self._format_date(self.modification_date),
            "creation_date": self._format_date(self.creation_date),
            "is_frozen": self.is_frozen,
            "is_locked": self.is_locked,
            "is_ready_for_issue": self.is_ready_for_issue,
            "is_issued": self.is_issued,
            "is_issued_but_modified": self.is_issued_but_modified,
            "is_master_drawing": self.is_master_drawing,
            "issuing_date": self._format_date(self.issuing_date),
            "output_date": self._format_date(self.output_date),
            "up_to_date_status": self.up_to_date_status,
            "commit_message": self.commit_message,
        }


def wrap_drawings(drawings: DrawingEnumerator) -> list[TeklaDrawing]:
    """
    Wraps a DrawingEnumerator in a list of TeklaDrawing wrappers.

    Args:
        drawings: The DrawingEnumerator

    Returns:
        List of TeklaDrawing wrappers
    """
    result: list[TeklaDrawing] = []
    while drawings.MoveNext():
        result.append(TeklaDrawing(drawings.Current))
    return result


def get_drawings_by_marks(marks: list[str] | None = None) -> list[TeklaDrawing]:
    """
    Get drawings by marks or from selection.

    Args:
        marks: Optional list of drawing marks to filter by.
               If None, returns selected drawings.

    Returns:
        List of TeklaDrawing wrappers. Empty list if not connected or no drawings found.
    """
    drawing_handler = DrawingHandler()
    if not drawing_handler.GetConnectionStatus():
        return []

    if marks:
        all_drawings = wrap_drawings(drawing_handler.GetDrawings())
        return [d for d in all_drawings if d.mark in marks]
    else:
        return wrap_drawings(drawing_handler.GetDrawingSelector().GetSelected())
