"""
Drawing tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from pathlib import Path
from typing import Any, Annotated, Literal

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import DrawingType, StringFilterOption
from tekla_mcp_server.utils import mcp_handler, sanitize_filename
from tekla_mcp_server.tekla.filter_builder import to_filter_option
from tekla_mcp_server.tekla.drawing_utils import (
    get_default_plot_output_folder,
    matches_string_filter,
    map_sheet_size_to_paper_size,
    get_mark_collision_data,
    check_collisions,
    OUTPUT_TYPE_MAP,
    COLOR_MODE_MAP,
    ORIENTATION_MAP,
    SCALING_METHOD_MAP,
)
from tekla_mcp_server.tekla.wrappers.drawing import wrap_drawings, get_drawings_by_marks
from tekla_mcp_server.tekla.loader import (
    DrawingHandler,
    Mark,
    DrawingColors,
    DPMPrinterAttributes,
    DotPrintToMultipleSheet,
)


drawings_provider = LocalProvider()


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_drawings(
    drawing_type: Annotated[DrawingType | None, Field(description="Filter by drawing type: G=GA, A=Assembly, W=SinglePart, C=CastUnit, M=Multidrawing")] = None,
    name_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by drawing name")] = None,
    mark_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by drawing mark")] = None,
    title1_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by Title 1")] = None,
    title2_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by Title 2")] = None,
    title3_filter: Annotated[dict[str, Any] | StringFilterOption | None, Field(description="Filter by Title 3")] = None,
) -> ToolResult:
    """
    Get drawings from Tekla model with optional filtering.

    Name, mark and title filters are constructed using StringFilterOption.
    Example: {"conditions": {"match_type": "Contains", "value": "floor"}}

    ## EXAMPLES
    # Get all CastUnit drawings
    {"drawing_type": "C"}

    # Get drawings with "floor" in name
    {
        "name_filter": {
            "conditions": {"match_type": "Contains", "value": "floor"}
        }
    }

    # Get drawings with mark starting with "HCS" (multiple conditions)
    {
        "mark_filter": {
            "conditions": [
                {"match_type": "Starts With", "value": "HCS"},
                {"match_type": "Starts With", "value": "HCS"}
            ],
            "logic": "OR"
        }
    }
    """
    name_filter = to_filter_option(name_filter, StringFilterOption)
    mark_filter = to_filter_option(mark_filter, StringFilterOption)
    title1_filter = to_filter_option(title1_filter, StringFilterOption)
    title2_filter = to_filter_option(title2_filter, StringFilterOption)
    title3_filter = to_filter_option(title3_filter, StringFilterOption)

    drawing_handler = DrawingHandler()

    if not drawing_handler.GetConnectionStatus():
        raise ConnectionError("Not connected to Tekla")

    all_drawings = wrap_drawings(drawing_handler.GetDrawings())
    filtered_drawings = all_drawings

    if drawing_type is not None:
        drawing_type = DrawingType(drawing_type)  # raises ValueError for invalid values
        filtered_drawings = [d for d in filtered_drawings if d.drawing_type == drawing_type]
    if name_filter:
        filtered_drawings = [d for d in filtered_drawings if matches_string_filter(d.name, name_filter)]
    if mark_filter:
        filtered_drawings = [d for d in filtered_drawings if matches_string_filter(d.mark, mark_filter)]
    if title1_filter:
        filtered_drawings = [d for d in filtered_drawings if matches_string_filter(d.title1, title1_filter)]
    if title2_filter:
        filtered_drawings = [d for d in filtered_drawings if matches_string_filter(d.title2, title2_filter)]
    if title3_filter:
        filtered_drawings = [d for d in filtered_drawings if matches_string_filter(d.title3, title3_filter)]

    marks = [d.mark for d in filtered_drawings]
    logger.info("Found %s drawings matching filters", len(marks))

    return ToolResult(
        structured_content={
            "status": "success",
            "matched_count": len(marks),
            "marks": marks,
        }
    )


@drawings_provider.tool(tags={"catalog"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_drawing_properties(
    marks: Annotated[list[str] | None, Field(description="List of drawing marks to get properties for")] = None,
) -> ToolResult:
    """
    Get properties of drawings by their marks.

    If marks are not provided, gets properties of currently selected drawings in Tekla.

    ## OUTPUT
    - Return the result table in Markdown format EXACTLY as provided by the tool.
    - DO NOT reformat, truncate, or modify anything, including spacing, columns, or headers.
    - ALWAYS show the full table. DO NOT remove any rows or columns.
    """
    drawing_handler = DrawingHandler()

    if not drawing_handler.GetConnectionStatus():
        raise ConnectionError("Not connected to Tekla")

    target_drawings = get_drawings_by_marks(marks)

    if not target_drawings:
        return ToolResult(
            structured_content={"status": "warning", "message": "No drawings found"},
        )

    drawings_data = [{"No": i + 1, **d.to_dict()} for i, d in enumerate(target_drawings)]
    logger.info("Retrieved properties for %s drawings", len(drawings_data))

    return ToolResult(
        content={"drawings": drawings_data},
        structured_content={
            "status": "success",
            "selected_count": len(drawings_data),
            "drawings": drawings_data,
        },
    )


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def detect_collisions_between_marks(
    marks: Annotated[list[str] | None, Field(description="List of drawing marks to process")] = None,
) -> ToolResult:
    """
    Detect collisions between part marks in drawings.

    If the marks are not provided, processes currently selected drawings in Tekla.
    """
    drawing_handler = DrawingHandler()

    if not drawing_handler.GetConnectionStatus():
        raise ConnectionError("Not connected to Tekla")

    target_drawings = get_drawings_by_marks(marks)

    if not target_drawings:
        raise ValueError("No drawings found or selected")

    if drawing_handler.GetActiveDrawing():
        raise RuntimeError("A drawing is currently open. Close it first before running collision detection.")

    all_drawings_results: list[dict] = []
    total_colliding_marks = 0

    try:
        for drawing in target_drawings:
            drawing_handler.SetActiveDrawing(drawing.drawing)
            view_results: list[dict] = []

            try:
                sheet = drawing.drawing.GetSheet()
                views_enum = sheet.GetAllViews()
            except Exception:
                logger.debug("Failed to open sheet for drawing, skipping")
                continue

            while views_enum.MoveNext():
                view = views_enum.Current
                view_name = view.Name or ""

                try:
                    mark_objects = view.GetAllObjects(Mark)
                except Exception:
                    logger.debug("Failed to get marks for view %s, skipping", view_name)
                    continue

                mark_data = []
                while mark_objects.MoveNext():
                    collision_data = get_mark_collision_data(mark_objects.Current)
                    if collision_data:
                        mark_data.append(collision_data)

                if not mark_data:
                    continue

                colliding_indices = check_collisions(mark_data)
                if not colliding_indices:
                    continue

                colliding_count = len(colliding_indices)
                total_colliding_marks += colliding_count

                for i, data in enumerate(mark_data):
                    if i in colliding_indices:
                        data["mark"].Attributes.Frame.Color = DrawingColors.Red
                        data["mark"].Modify()

                view_results.append(
                    {
                        "view": view_name,
                        "total_marks": len(mark_data),
                        "colliding_marks": colliding_count,
                    }
                )

            if view_results:
                all_drawings_results.append(
                    {
                        "mark": drawing.mark,
                        "name": drawing.name,
                        "views": view_results,
                    }
                )
                drawing_handler.SaveActiveDrawing()
    finally:
        drawing_handler.CloseActiveDrawing()

    logger.info("Collision detection complete: %d total colliding marks", total_colliding_marks)
    return ToolResult(
        structured_content={
            "status": "success",
            "total_drawings": len(target_drawings),
            "drawings_with_collisions": all_drawings_results,
            "total_colliding_marks": total_colliding_marks,
        },
    )


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def print_drawings(
    marks: Annotated[list[str] | None, Field(description="List of drawing marks to process")] = None,
    output_filename: Annotated[Literal["name", "mark", "title1", "title2", "title3"] | None, Field(description="Output filename")] = None,
    output_folder: Annotated[str | None, Field(description="Output folder path for PDF output")] = None,
    printer_attributes: Annotated[
        dict[str, Any] | None,
        Field(description="Optional overrides for printing behavior. Used to customize default print settings."),
    ] = None,
) -> ToolResult:
    """
    Print drawings by their marks.

    If marks are not provided, prints currently selected drawings in Tekla.
    """
    drawing_handler = DrawingHandler()

    if not drawing_handler.GetConnectionStatus():
        raise ConnectionError("Not connected to Tekla")

    target_drawings = get_drawings_by_marks(marks)

    if not target_drawings:
        raise ValueError("No drawings found or selected")

    if not output_folder:
        output_folder_path = get_default_plot_output_folder()
        if not output_folder_path:
            raise ValueError("No output directory is set")
        output_folder = str(output_folder_path)

    default_attrs = {
        "printer_name": "PDF-XChange 3.0",
        "output_filename": output_filename,
        "output_type": "PDF",
        "color_mode": "BlackAndWhite",
        "orientation": "Landscape",
        "copies": 1,
        "scale_factor": 1.0,
        "open_when_finished": False,
        "scaling_method": "Auto",
    }
    attrs = {**default_attrs, **(printer_attributes or {})}

    results: list[dict] = []
    success_count = 0

    for drawing in target_drawings:
        try:
            sheet_width = drawing.drawing.Layout.SheetSize.Width
            sheet_height = drawing.drawing.Layout.SheetSize.Height

            paper_size = map_sheet_size_to_paper_size(sheet_width, sheet_height)
            if paper_size is None:
                logger.warning("Format not supported for drawing %s (size: %sx%s mm)", drawing.mark, sheet_width, sheet_height)
                results.append({"mark": drawing.mark, "status": "failed", "message": f"Format not supported: sheet size {sheet_width}x{sheet_height} mm does not match A0-A4"})
                continue

            print_attrs = DPMPrinterAttributes()
            print_attrs.PrinterName = attrs["printer_name"]
            print_attrs.OutputType = OUTPUT_TYPE_MAP.get(attrs["output_type"], OUTPUT_TYPE_MAP["PDF"])
            print_attrs.ColorMode = COLOR_MODE_MAP.get(attrs["color_mode"], COLOR_MODE_MAP["BlackAndWhite"])
            print_attrs.Orientation = ORIENTATION_MAP.get(attrs["orientation"], ORIENTATION_MAP["Landscape"])
            print_attrs.PaperSize = paper_size
            print_attrs.NumberOfCopies = attrs["copies"]
            print_attrs.ScaleFactor = attrs["scale_factor"]
            print_attrs.ScalingMethod = SCALING_METHOD_MAP.get(attrs["scaling_method"], SCALING_METHOD_MAP["Auto"])
            print_attrs.PrintToMultipleSheet = DotPrintToMultipleSheet.Off

            file_attr = attrs["output_filename"]
            raw_name = getattr(drawing, file_attr) if isinstance(file_attr, str) and hasattr(drawing, file_attr) else drawing.mark
            safe_name = sanitize_filename(str(raw_name))
            if safe_name is None:
                logger.warning("Drawing %s has no valid filename after sanitization", drawing.mark)
                results.append({"mark": drawing.mark, "status": "failed", "message": "No valid filename after sanitization"})
                continue
            print_attrs.OutputFileName = safe_name

            output_filename_with_ext = safe_name + ".pdf"
            output_file = Path(output_folder) / output_filename_with_ext
            print_attrs.OpenFileWhenFinished = attrs["open_when_finished"]

            result = drawing_handler.PrintDrawing(drawing.drawing, print_attrs, str(output_file))

            if result:
                success_count += 1
                results.append({"mark": drawing.mark, "status": "success", "file_name": output_filename_with_ext})
            else:
                results.append({"mark": drawing.mark, "status": "failed", "message": "PrintDrawing returned False"})

        except Exception as e:
            logger.error("Failed to print drawing %s: %s", drawing.mark, str(e))
            results.append({"mark": drawing.mark, "status": "error", "message": str(e)})

    status = "success" if success_count == len(target_drawings) else "partial" if success_count > 0 else "error"

    return ToolResult(
        structured_content={
            "status": status,
            "total": len(target_drawings),
            "succeeded": success_count,
            "failed": len(target_drawings) - success_count,
            "output_folder": str(output_folder),
            "results": results,
        },
    )
