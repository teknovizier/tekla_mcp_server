"""
Drawing tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from pathlib import Path
from typing import Any, Annotated, Literal

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.config import get_advanced_option_directories
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import DrawingType, StringFilterOption
from tekla_mcp_server.utils import mcp_handler, sanitize_filename, resolve_model_relative_dir
from tekla_mcp_server.tekla.filter_builder import to_filter_option
from tekla_mcp_server.tekla.drawing_utils import (
    matches_string_filter,
    map_sheet_size_to_paper_size,
    get_mark_collision_data,
    get_collision_pairs,
    draw_collision_cloud,
    OUTPUT_TYPE_MAP,
    COLOR_MODE_MAP,
    ORIENTATION_MAP,
    SCALING_METHOD_MAP,
)
from tekla_mcp_server.tekla.wrappers.drawing import get_drawing_handler, get_all_drawings, get_drawings_by_marks
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.loader import (
    Mark,
    MarkSet,
    WeldMark,
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

    drawing_handler = get_drawing_handler()
    filtered_drawings = get_all_drawings(drawing_handler)

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


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
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
    drawing_handler = get_drawing_handler()
    target_drawings = get_drawings_by_marks(drawing_handler, marks)

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
    drawing_handler = get_drawing_handler()
    target_drawings = get_drawings_by_marks(drawing_handler, marks)

    if drawing_handler.GetActiveDrawing():
        raise RuntimeError("A drawing is currently open. Close it first before running collision detection.")

    all_drawings_results: list[dict] = []
    total_collision_pairs = 0
    errors: list[dict[str, Any]] = []

    logger.info("Starting collision detection for %d drawing(s)", len(target_drawings))

    try:
        for drawing in target_drawings:
            logger.info("Processing drawing %s / %s", drawing.mark, drawing.name)
            drawing_handler.SetActiveDrawing(drawing.drawing)
            view_results: list[dict] = []
            drawing_cloud_failures = 0

            try:
                sheet = drawing.drawing.GetSheet()
                views_enum = sheet.GetAllViews()
            except Exception:
                logger.warning("Failed to open sheet for drawing %s, skipping", drawing.mark)
                errors.append({"drawing": drawing.mark, "error": "sheet_open_failed"})
                continue

            while views_enum.MoveNext():
                view = views_enum.Current
                view_name = getattr(view, "Name", "") or ""

                mark_data = []
                for mark_type in (Mark, MarkSet, WeldMark):
                    try:
                        type_objs = view.GetAllObjects(mark_type)
                    except Exception as e:
                        logger.warning("Failed to get %s objects from view '%s': %s", mark_type.__name__, view_name, e)
                        continue
                    while type_objs.MoveNext():
                        collision_data = get_mark_collision_data(type_objs.Current)
                        if collision_data is not None:
                            mark_data.append(collision_data)

                logger.debug("View '%s': %d marks collected", view_name, len(mark_data))

                if not mark_data:
                    continue

                pairs = get_collision_pairs(mark_data)
                if not pairs:
                    logger.debug("View '%s': no collisions", view_name)
                    continue

                logger.info("View '%s': %d collision pair(s) found", view_name, len(pairs))
                total_collision_pairs += len(pairs)

                for i, j in pairs:
                    logger.debug(
                        "Drawing cloud for %s <-> %s",
                        type(mark_data[i].mark).__name__,
                        type(mark_data[j].mark).__name__,
                    )
                    if not draw_collision_cloud(view, mark_data[i], mark_data[j]):
                        drawing_cloud_failures += 1

                view_results.append({"view": view_name, "total_marks": len(mark_data), "collision_pairs": len(pairs)})

            if drawing_cloud_failures:
                errors.append({"drawing": drawing.mark, "error": "cloud_insertion_failed", "count": drawing_cloud_failures})

            if view_results:
                all_drawings_results.append(
                    {
                        "mark": drawing.mark,
                        "name": drawing.name,
                        "views": view_results,
                    }
                )
                logger.info("Saving drawing %s", drawing.mark)
                if not drawing_handler.SaveActiveDrawing():
                    logger.warning("SaveActiveDrawing() returned False for drawing %s", drawing.mark)
                    errors.append({"drawing": drawing.mark, "error": "save_failed"})
    finally:
        drawing_handler.CloseActiveDrawing()

    logger.info("Collision detection complete: %d total collision pair(s) across %d drawing(s)", total_collision_pairs, len(target_drawings))
    result: dict = {
        "status": "partial" if errors else "success",
        "total_drawings": len(target_drawings),
        "drawings_with_collisions": all_drawings_results,
        "total_collision_pairs": total_collision_pairs,
    }
    if errors:
        result["errors"] = errors
    return ToolResult(structured_content=result)


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
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
    drawing_handler = get_drawing_handler()
    target_drawings = get_drawings_by_marks(drawing_handler, marks)

    provided_output_folder = output_folder
    if not output_folder:
        plot_dirs = get_advanced_option_directories("XS_DRAWING_PLOT_FILE_DIRECTORY")
        if not plot_dirs:
            raise ValueError("No output directory is set: XS_DRAWING_PLOT_FILE_DIRECTORY is not configured")
        output_folder = str(Path(plot_dirs[0]).resolve())
    else:
        # A relative folder is resolved against the model folder, consistent with
        # create_report and how relative advanced-option paths are interpreted.
        output_folder = resolve_model_relative_dir(output_folder, TeklaModel().model_path)
        if not Path(output_folder).is_dir():
            raise ValueError(f"Output directory '{output_folder}' does not exist")

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

            logger.info("Printing drawing %s -> %s", drawing.mark, output_file)
            print_result = drawing_handler.PrintDrawing(drawing.drawing, print_attrs, str(output_file))

            if not print_result:
                logger.warning("PrintDrawing returned False for drawing %s (target: %s)", drawing.mark, output_file)
                results.append({"mark": drawing.mark, "status": "failed", "message": "PrintDrawing returned False"})
            elif not Path(output_file).exists():
                # Tekla reports success even when it only queued the job. If the PDF is not
                # on disk, the print engine could not write the file - most often because the
                # MCP client launched this server without the permissions/environment Tekla's
                # PDF print engine needs).
                message = (
                    "Tekla reported the print succeeded but no file was created. "
                    "The print engine could not write the output - check your MCP client settings: "
                    "the server may be launched without sufficient permissions or environment."
                )
                logger.warning("Drawing %s: %s", drawing.mark, message)
                results.append({"mark": drawing.mark, "status": "failed", "message": message})
            else:
                success_count += 1
                logger.info("Printed drawing %s successfully: %s", drawing.mark, output_file)
                results.append({"mark": drawing.mark, "status": "success", "file_name": output_filename_with_ext})

        except Exception as e:
            logger.error("Failed to print drawing %s: %s", drawing.mark, str(e))
            results.append({"mark": drawing.mark, "status": "error", "message": str(e)})

    status = "success" if success_count == len(target_drawings) else "partial" if success_count > 0 else "error"

    result: dict[str, Any] = {
        "status": status,
        "total": len(target_drawings),
        "succeeded": success_count,
        "failed": len(target_drawings) - success_count,
        "results": results,
    }
    if provided_output_folder:
        result["output_folder"] = provided_output_folder
    return ToolResult(structured_content=result)
