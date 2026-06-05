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
from tekla_mcp_server.models import DrawingType, StringFilterOption, ViewScale
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
from tekla_mcp_server.tekla.wrappers.drawing_handler import TeklaDrawingHandler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.loader import (
    Cloud,
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

    Name, mark and title filters are constructed using `StringFilterOption`.
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

    handler = TeklaDrawingHandler()
    filtered_drawings = handler.get_all_drawings()

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
    handler = TeklaDrawingHandler()
    target_drawings = handler.get_drawings_by_marks(marks)

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


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def detect_collisions_between_marks(
    view_keys: Annotated[list[str] | None, Field(description="View keys to check (from `get_drawing_views`). Processes all views when omitted")] = None,
) -> ToolResult:
    """
    Detect collisions between part marks in the active drawing's views and highlight them with revision clouds.

    When view_keys is omitted all views in the active drawing are checked.
    """
    if view_keys is not None and not view_keys:
        raise ValueError("view_keys must not be an empty list. Omit it to process all views.")

    handler = TeklaDrawingHandler()
    drawing = handler.require_active_drawing()

    if view_keys:
        index = handler.index_views_by_key()
        missing = [k for k in view_keys if k not in index]
        if missing:
            raise ValueError(f"View(s) not found: {missing}. Use `get_drawing_views` to list valid keys.")
        views = [index[k] for k in view_keys]
    else:
        views = handler.get_drawing_views()

    view_results: list[dict] = []
    total_collision_pairs = 0
    cloud_failures = 0
    errors: list[dict[str, Any]] = []

    logger.info("Starting collision detection for %d view(s) in drawing '%s'", len(views), drawing.mark)

    for tekla_view in views:
        if tekla_view.is_sheet:
            continue

        view_name = tekla_view.name or tekla_view.view_key
        raw_view = tekla_view.view

        mark_data = []
        for mark_type in (Mark, MarkSet, WeldMark):
            try:
                type_objs = raw_view.GetAllObjects(mark_type)
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

        view_cloud_failures = 0
        for i, j in pairs:
            logger.debug("Drawing cloud for %s <-> %s", type(mark_data[i].mark).__name__, type(mark_data[j].mark).__name__)
            if not draw_collision_cloud(raw_view, mark_data[i], mark_data[j]):
                view_cloud_failures += 1
                cloud_failures += 1

        view_results.append(
            {
                "view_key": tekla_view.view_key,
                "view": view_name,
                "total_marks": len(mark_data),
                "collision_pairs": len(pairs),
                "cloud_failures": view_cloud_failures,
            }
        )

    if cloud_failures:
        errors.append({"error": "cloud_insertion_failed", "count": cloud_failures})

    if total_collision_pairs > 0 and not drawing.commit_changes():
        raise RuntimeError(f"CommitChanges() failed after drawing {total_collision_pairs} collision cloud(s). ")

    logger.info("Collision detection complete: %d total collision pair(s) in drawing '%s'", total_collision_pairs, drawing.mark)
    result: dict[str, Any] = {
        "status": "partial" if errors else "success",
        "drawing_mark": drawing.mark,
        "views_checked": len(views),
        "views_with_collisions": len(view_results),
        "total_collision_pairs": total_collision_pairs,
        "views": view_results,
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
    handler = TeklaDrawingHandler()
    target_drawings = handler.get_drawings_by_marks(marks)

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
            print_result = handler.print_drawing(drawing, print_attrs, str(output_file))

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


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def open_drawing(
    mark: Annotated[str, Field(description="Drawing mark (from `get_drawings`)")],
) -> ToolResult:
    """
    Open a drawing in Tekla's drawing editor.

    Any currently open drawing must be closed first with `close_drawing`.
    """
    handler = TeklaDrawingHandler()

    if handler.get_active_drawing() is not None:
        raise RuntimeError("Another drawing is already open. Close it first with `close_drawing`.")
    if not mark:
        raise ValueError("Drawing mark is required")

    try:
        targets = handler.get_drawings_by_marks([mark])
    except ValueError:
        raise ValueError(f"No drawing found with mark '{mark}'. Use `get_drawings` to find valid marks.")

    target = targets[0]
    if not handler.set_active_drawing(target):
        raise RuntimeError(f"Failed to open drawing '{mark}'.")

    logger.info("Opened drawing %s", mark)
    return ToolResult(
        structured_content={
            "status": "success",
            "drawing_name": target.name,
            "drawing_mark": target.mark,
            "drawing_type": target.drawing_type,
        }
    )


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def close_drawing(
    save: Annotated[bool, Field(description="Save before closing")] = True,
) -> ToolResult:
    """
    Close the active drawing, saving by default.
    """
    handler = TeklaDrawingHandler()

    active = handler.require_active_drawing()

    mark = active.mark
    if not handler.close_active_drawing(save):
        raise RuntimeError(f"Failed to save and close drawing '{mark}'.")

    logger.info("Closed active drawing (saved=%s)", save)
    return ToolResult(structured_content={"status": "success", "drawing_is_saved": save})


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_drawing_views() -> ToolResult:
    """
    List all views in the active drawing with type, scale, position, and size.

    Also returns the sheet size. View origins are measured in mm from the sheet
    bottom-left corner (0, 0), so views fit within (0, 0)-(sheet_width, sheet_height).

    Use `view_key` for all follow-up calls.
    Use `open_drawing` first if no drawing is currently open.
    """
    handler = TeklaDrawingHandler()

    active = handler.require_active_drawing()
    sheet = active.get_sheet()
    if sheet is None:
        raise RuntimeError("Failed to get sheet for active drawing.")

    tekla_views = handler.get_drawing_views(sheet)

    view_list: list[dict[str, Any]] = [v.to_dict() for v in tekla_views]

    return ToolResult(
        structured_content={
            "status": "success",
            "sheet_width": round(sheet.Width, 1),
            "sheet_height": round(sheet.Height, 1),
            "view_count": len(view_list),
            "views": view_list,
        }
    )


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def move_view(
    view_key: Annotated[str, Field(description="View key (from `get_drawing_views`)")],
    dx: Annotated[float, Field(description="Offset in X direction (mm)")],
    dy: Annotated[float, Field(description="Offset in Y direction (mm)")],
) -> ToolResult:
    """
    Move a view by an offset in mm.
    """
    handler = TeklaDrawingHandler()
    drawing = handler.require_active_drawing()
    tekla_view = handler.get_view_by_key(view_key)

    if tekla_view.is_sheet:
        raise RuntimeError("Cannot move the sheet view.")

    ox, oy = tekla_view.origin
    new_x = ox + dx
    new_y = oy + dy
    tekla_view.origin = (new_x, new_y)
    if not tekla_view.modify():
        raise RuntimeError(f"Failed to move view '{view_key}'.")

    if not drawing.commit_changes():
        raise RuntimeError(f"CommitChanges() failed after moving view '{view_key}'.")

    return ToolResult(structured_content={"status": "success", "view_key": view_key, "new_origin_x": round(new_x, 1), "new_origin_y": round(new_y, 1)})


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def set_view_scales(
    view_scales: Annotated[list[ViewScale], Field(description="View key / scale pairs to apply")],
) -> ToolResult:
    """
    Set the scale of one or more drawing views.

    To apply the same scale to several views, repeat the scale value across pairs.
    """
    if not view_scales:
        raise ValueError("view_scales is required")

    handler = TeklaDrawingHandler()
    drawing = handler.require_active_drawing()
    index = handler.index_views_by_key()

    results: list[dict[str, Any]] = []
    succeeded = 0

    for item in view_scales:
        tekla_view = index.get(item.view_key)
        if tekla_view is None:
            results.append({"view_key": item.view_key, "status": "failed", "message": "View not found"})
            continue
        try:
            if tekla_view.set_scale(item.scale):
                succeeded += 1
                results.append({"view_key": item.view_key, "status": "success", "new_scale": item.scale})
            else:
                results.append({"view_key": item.view_key, "status": "failed", "message": "set_scale() returned False"})
        except Exception as e:
            logger.error("Failed to set scale on view %s: %s", item.view_key, e)
            results.append({"view_key": item.view_key, "status": "error", "message": str(e)})

    total = len(view_scales)
    status = "success" if succeeded == total else "partial" if succeeded else "error"
    logger.info("set_view_scales: %d/%d updated", succeeded, total)

    if succeeded > 0 and not drawing.commit_changes():
        raise RuntimeError("CommitChanges() failed after setting view scales.")

    return ToolResult(
        structured_content={
            "status": status,
            "total": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "results": results,
        }
    )


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def delete_view_clouds(
    view_keys: Annotated[list[str] | None, Field(description="View keys to clear (from `get_drawing_views`). Processes all views when omitted")] = None,
) -> ToolResult:
    """
    Delete all clouds from model views in the active drawing.

    When view_keys is omitted, all views are processed.
    Clouds placed outside any model view are not affected.
    """
    if view_keys is not None and not view_keys:
        raise ValueError("view_keys must not be an empty list. Omit it to process all views.")

    handler = TeklaDrawingHandler()
    drawing = handler.require_active_drawing()

    if view_keys is not None:
        index = handler.index_views_by_key()
        missing = [k for k in view_keys if k not in index]
        if missing:
            raise ValueError(f"View(s) not found: {missing}. Use `get_drawing_views` to list valid keys.")
        views = [index[k] for k in view_keys]
    else:
        views = handler.get_drawing_views()

    view_results: list[dict[str, Any]] = []
    total_found = 0
    total_deleted = 0
    total_failed = 0

    for tekla_view in views:
        if tekla_view.is_sheet:
            continue

        all_objects = tekla_view.get_all_objects()
        if all_objects is None:
            logger.warning("get_all_objects() failed for view '%s'", tekla_view.view_key)
            continue

        to_delete = [obj for obj in all_objects if isinstance(obj, Cloud)]
        total_found += len(to_delete)
        if not to_delete:
            continue

        deleted = 0
        failed = 0
        for obj in to_delete:
            try:
                if obj.Delete():
                    deleted += 1
                else:
                    failed += 1
            except Exception as e:
                logger.warning("Cloud.Delete() raised in view '%s': %s", tekla_view.view_key, e)
                failed += 1

        total_deleted += deleted
        total_failed += failed
        view_results.append(
            {
                "view_key": tekla_view.view_key,
                "deleted_count": deleted,
                "failed_count": failed,
            }
        )

    if total_deleted > 0 and not drawing.commit_changes():
        raise RuntimeError(f"CommitChanges() failed after deleting {total_deleted} cloud(s). The drawing editor may not reflect the changes.")

    status = "success" if total_failed == 0 else "partial" if total_deleted else "error"
    logger.info("delete_view_clouds: found=%d deleted=%d failed=%d", total_found, total_deleted, total_failed)
    return ToolResult(
        structured_content={
            "status": status,
            "total_found": total_found,
            "total_deleted": total_deleted,
            "total_failed": total_failed,
            "views": view_results,
        }
    )


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def delete_views(
    view_keys: Annotated[list[str], Field(description="View keys to delete (from `get_drawing_views`)")],
) -> ToolResult:
    """
    Delete one or more views from the active drawing.
    """
    if not view_keys:
        raise ValueError("view_keys is required")

    handler = TeklaDrawingHandler()
    drawing = handler.require_active_drawing()

    # Resolve all views up front in a single scan, then delete from the resolved
    # handles - avoids deleting while iterating the sheet's view enumerator.
    index = handler.index_views_by_key()

    results: list[dict[str, Any]] = []
    succeeded = 0

    for view_key in view_keys:
        tekla_view = index.get(view_key)
        if tekla_view is None:
            results.append({"view_key": view_key, "status": "failed", "message": "View not found"})
            continue
        try:
            if tekla_view.delete():
                succeeded += 1
                results.append({"view_key": view_key, "status": "success"})
            else:
                results.append({"view_key": view_key, "status": "failed", "message": "Delete() returned False"})
        except Exception as e:
            logger.error("Failed to delete view %s: %s", view_key, e)
            results.append({"view_key": view_key, "status": "error", "message": str(e)})

    total = len(view_keys)
    status = "success" if succeeded == total else "partial" if succeeded else "error"
    logger.info("delete_views: %d/%d deleted", succeeded, total)

    if succeeded > 0 and not drawing.commit_changes():
        raise RuntimeError("CommitChanges() failed after deleting views.")

    return ToolResult(
        structured_content={
            "status": status,
            "total": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "results": results,
        }
    )
