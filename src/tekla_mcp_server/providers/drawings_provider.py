"""
Drawing tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Annotated, Literal

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.config import get_advanced_option_directories, get_tolerance
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
    detect_section_parents,
    compute_section_alignment,
    categorize_drawing_object,
    extract_annotation_content,
    CATEGORY_TYPES,
    DEFAULT_ANNOTATION_CATEGORIES,
    OUTPUT_TYPE_MAP,
    COLOR_MODE_MAP,
    ORIENTATION_MAP,
    SCALING_METHOD_MAP,
)
from tekla_mcp_server.tekla.wrappers.drawing_handler import TeklaDrawingHandler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_object, TeklaAssembly
from tekla_mcp_server.tekla.loader import (
    Cloud,
    Connection,
    DrawingObject,
    Mark,
    MarkSet,
    WeldMark,
    DrawingModelObject,
    DPMPrinterAttributes,
    DotPrintToMultipleSheet,
    ModelObject,
)


drawings_provider = LocalProvider()


def _describe_model_object(guid: str, model_obj: ModelObject) -> dict[str, Any]:
    """
    Build a lightweight record for a model object shown in a view (no geometry).

    Resolves name/profile/material/class via the model-object wrappers where the
    type is supported (parts, assemblies, reinforcement). Unsupported types
    (e.g. bolts) fall back to the raw object's name so nothing is dropped.
    """
    # Use .NET type name (Beam, Column, etc.) as element_type identifier
    entry: dict[str, Any] = {"guid": guid, "element_type": type(model_obj).__name__}
    wrapped = wrap_model_object(model_obj)
    if wrapped is None:
        entry["name"] = getattr(model_obj, "Name", None) or None
        return entry
    for attr in ("name", "position", "profile", "material", "tekla_class"):
        try:
            value = getattr(wrapped, attr)
        except AttributeError:
            continue
        if value is not None:
            entry[attr] = value
    return entry


@dataclass
class EmbeddedDetailPart:
    """
    A single member part of an embedded detail: its GUID and element type.
    """

    guid: str
    element_type: str


@dataclass
class EmbeddedDetail:
    """
    An embedded detail subassembly shown in a view.
    """

    guid: str
    name: str | None
    position: str | None
    element_type: str = "EmbeddedDetail"
    parts: list[EmbeddedDetailPart] = field(default_factory=list)


def _describe_embedded_detail(guid: str, assembly: TeklaAssembly) -> EmbeddedDetail:
    """Build an `EmbeddedDetail` record from an embedded detail subassembly."""
    return EmbeddedDetail(guid=guid, name=assembly.name or None, position=assembly.position or None)


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
def get_drawings_properties(
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

    drawings_data = [d.to_dict() for d in target_drawings]
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
def set_drawings_properties(
    marks: Annotated[list[str] | None, Field(description="List of drawing marks to update")] = None,
    name: Annotated[str | None, Field(description="Drawing name")] = None,
    title1: Annotated[str | None, Field(description="First drawing title")] = None,
    title2: Annotated[str | None, Field(description="Second drawing title")] = None,
    title3: Annotated[str | None, Field(description="Third drawing title")] = None,
    user_properties: Annotated[dict[str, Any] | None, Field(description="Dictionary of user-defined attribute names and values")] = None,
) -> ToolResult:
    """
    Sets properties and user-defined attributes (UDAs) on drawings by their marks.

    If marks are not provided, updates the currently selected drawings in Tekla.
    Does not require any drawing to be open.
    """
    handler = TeklaDrawingHandler()
    target_drawings = handler.get_drawings_by_marks(marks)

    total_changes: dict[str, int] = {
        "name": 0,
        "title1": 0,
        "title2": 0,
        "title3": 0,
        "udas": 0,
    }
    modified_count = 0
    property_errors: list[dict] = []

    for drawing in target_drawings:
        try:
            changes = drawing.set_properties(
                name=name,
                title1=title1,
                title2=title2,
                title3=title3,
                user_properties=user_properties,
            )
            elem_errors: list[dict] = changes.pop("errors", [])
            for key, value in changes.items():
                if key in total_changes:
                    total_changes[key] += value
            if any(v > 0 for v in changes.values()):
                modified_count += 1
                if not drawing.modify():
                    elem_errors.append({"property": "modify", "reason": "Modify() returned False"})
                elif not drawing.commit_changes():
                    elem_errors.append({"property": "commit", "reason": "CommitChanges() returned False"})
            if elem_errors:
                logger.warning("Property errors on drawing %s: %s", drawing.mark, elem_errors)
                property_errors.append({"mark": drawing.mark, "errors": elem_errors})
        except Exception:
            logger.exception("Failed to set properties on drawing %s", drawing.mark)

    if modified_count > 0 and property_errors:
        status = "partial"
        message = f"Modified {modified_count} drawing(s) with some errors"
    elif modified_count > 0:
        status = "success"
        message = f"Successfully modified {modified_count} drawing(s)"
    else:
        status = "warning"
        message = "No drawings were modified"

    logger.info("Set drawing properties result: %s — %s", status, message)
    result: dict[str, Any] = {
        "status": status,
        "message": message,
        "selected_count": len(target_drawings),
        "modified_count": modified_count,
        "changes_applied": total_changes,
        "property_errors": property_errors,
    }
    return ToolResult(structured_content=result)


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def set_drawings_issue_state(
    marks: Annotated[list[str] | None, Field(description="List of drawing marks to issue or unissue")] = None,
    action: Annotated[Literal["issue", "unissue"], Field(description="Whether to issue or unissue the drawings")] = "issue",
) -> ToolResult:
    """
    Issue or unissue drawings by their marks.

    If marks are not provided, acts on the currently selected drawings in Tekla.
    This is a drawing list level action, it does not require any drawing to be open.
    """
    handler = TeklaDrawingHandler()
    target_drawings = handler.get_drawings_by_marks(marks)

    if action == "issue":
        action_fn = handler.issue_drawing
    elif action == "unissue":
        action_fn = handler.unissue_drawing
    else:
        raise ValueError(f"Invalid action '{action}'. Must be 'issue' or 'unissue'.")

    # IssueDrawing/UnissueDrawing act directly on the drawing list, unlike SetUserProperty -
    # no Modify()/CommitChanges() is needed or applicable here.
    modified_count = 0
    errors: list[dict[str, Any]] = []

    for drawing in target_drawings:
        try:
            if action_fn(drawing):
                modified_count += 1
            else:
                errors.append({"mark": drawing.mark, "error": f"{action.capitalize()}Drawing returned False"})
        except Exception as e:
            logger.exception("Failed to %s drawing %s", action, drawing.mark)
            errors.append({"mark": drawing.mark, "error": str(e)})

    if modified_count > 0 and errors:
        status = "partial"
        message = f"{action.capitalize()}d {modified_count} drawing(s) with some errors"
    elif modified_count > 0:
        status = "success"
        message = f"Successfully {action}d {modified_count} drawing(s)"
    else:
        status = "warning"
        message = f"No drawings were {action}d"

    logger.info("Issue drawings result: %s — %s", status, message)
    result: dict[str, Any] = {
        "status": status,
        "message": message,
        "selected_count": len(target_drawings),
        "modified_count": modified_count,
        "errors": errors,
    }
    return ToolResult(structured_content=result)


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def update_drawings(
    marks: Annotated[list[str] | None, Field(description="List of drawing marks to update")] = None,
) -> ToolResult:
    """
    Update drawings by their marks, refreshing them from the model.

    If marks are not provided, acts on the currently selected drawings in Tekla.

    Numbering must be up to date before calling this tool.
    """
    handler = TeklaDrawingHandler()
    target_drawings = handler.get_drawings_by_marks(marks)

    # UpdateDrawing acts directly on the drawing list, unlike SetUserProperty -
    # no Modify()/CommitChanges() is needed or applicable here.
    modified_count = 0
    skipped_count = 0
    errors: list[dict[str, Any]] = []

    for drawing in target_drawings:
        try:
            if drawing.up_to_date_status == "DrawingIsUpToDate":
                skipped_count += 1
            elif handler.update_drawing(drawing):
                modified_count += 1
            else:
                errors.append({"mark": drawing.mark, "error": "UpdateDrawing returned False - the drawing may be active, locked, or numbering may be out of date"})
        except Exception as e:
            logger.exception("Failed to update drawing %s", drawing.mark)
            errors.append({"mark": drawing.mark, "error": str(e)})

    if modified_count > 0 and errors:
        status = "partial"
        message = f"Updated {modified_count} drawing(s) with some errors"
    elif modified_count > 0:
        status = "success"
        message = f"Successfully updated {modified_count} drawing(s)"
        if skipped_count > 0:
            message += f", {skipped_count} already up to date"
    elif errors:
        status = "warning"
        message = "No drawings were updated"
    else:
        status = "success"
        message = f"All {skipped_count} drawing(s) were already up to date"

    logger.info("Update drawings result: %s — %s", status, message)
    result: dict[str, Any] = {
        "status": status,
        "message": message,
        "selected_count": len(target_drawings),
        "modified_count": modified_count,
        "skipped_count": skipped_count,
        "errors": errors,
    }
    return ToolResult(structured_content=result)


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
        # Sheet view aggregates marks from all child views - skip to avoid duplicate detection
        if tekla_view.is_sheet:
            continue

        view_name = tekla_view.name or tekla_view.view_key

        all_mark_objs = tekla_view.get_all_objects([Mark, MarkSet, WeldMark])
        if all_mark_objs is None:
            logger.warning("Failed to enumerate mark objects in view '%s'", view_name)
            continue

        mark_data = []
        for obj in all_mark_objs:
            try:
                cd = get_mark_collision_data(obj)
                if cd is not None:
                    mark_data.append(cd)
            except Exception as e:
                logger.warning("get_mark_collision_data failed for object in view '%s': %s", view_name, e)

        logger.debug("View '%s': %d marks collected", view_name, len(mark_data))

        if not mark_data:
            continue

        pairs = get_collision_pairs(mark_data)
        if not pairs:
            logger.debug("View '%s': no collisions", view_name)
            continue

        logger.info("View '%s': %d collision pair(s) found", view_name, len(pairs))
        total_collision_pairs += len(pairs)

        raw_view = tekla_view.view
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


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
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


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
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

    Also returns the sheet view (is_sheet=true) which holds title-block
    annotations but no model objects. View origins are measured in mm from
    the sheet bottom-left corner (0, 0).

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


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_view_objects(
    view_key: Annotated[str, Field(description="View key (from `get_drawing_views`)")],
    limit: Annotated[int, Field(description="Max objects in the list", ge=1)] = 200,
) -> ToolResult:
    """
    List the model objects (parts, rebars, etc.) shown in a drawing view.

    Returns model objects only, NOT annotations (use `get_view_annotations` instead).
    Embedded detail subassemblies are reported once rather than as separate parts.
    """
    handler = TeklaDrawingHandler()
    handler.require_active_drawing()
    view = handler.get_view_by_key(view_key)
    model = TeklaModel()

    # Sheet view aggregates model objects from all child views - it has none of its own
    if view.is_sheet:
        drawing_objects: list[DrawingObject] = []
    else:
        drawing_objects = view.get_all_objects([DrawingModelObject])
        if drawing_objects is None:
            raise RuntimeError(f"Failed to enumerate model objects in view '{view_key}'. The view state may be corrupted or the connection lost.")

    # Exclude Connection objects from total_count
    total_count = sum(1 for o in drawing_objects if not isinstance(o, Connection))
    objects: list[dict[str, Any] | EmbeddedDetail] = []
    embedded_details: dict[str, EmbeddedDetail] = {}
    unresolved_count = 0
    returned_count = 0
    has_more = False
    seen_guids: set[str] = set()
    # The same model object can be referenced by multiple drawing objects (e.g. a
    # part and its weld marks), so cache lookups to avoid repeat SelectModelObject calls
    model_objects_by_id: dict[int, ModelObject | None] = {}

    for drawing_obj in drawing_objects:
        if returned_count >= limit:
            has_more = True
            break
        # Tekla components shown in a drawing view are internal
        # connection geometry, not structural parts. Skip them
        if isinstance(drawing_obj, Connection):
            continue
        identifier = getattr(drawing_obj, "ModelIdentifier", None)
        if identifier is None:
            unresolved_count += 1
            continue
        # The drawing-side ModelIdentifier carries a zero GUID, only its
        # integer ID maps to the model object
        object_id = int(identifier.ID)
        if object_id not in model_objects_by_id:
            model_objects_by_id[object_id] = model.get_object_by_id(object_id)
        model_obj = model_objects_by_id[object_id]
        if model_obj is None:
            unresolved_count += 1
            continue

        # Promote a part belonging to an embedded-detail subassembly to the
        # subassembly itself, deduplicating its other parts but counting them
        try:
            parent_assembly = model_obj.GetAssembly()
        except Exception as e:
            logger.debug("GetAssembly() failed for model object id %s: %s", identifier.ID, e)
            parent_assembly = None
        if parent_assembly is not None:
            wrapped_assembly = wrap_model_object(parent_assembly)
            if isinstance(wrapped_assembly, TeklaAssembly):
                try:
                    if wrapped_assembly.is_embedded_detail():
                        guid = parent_assembly.Identifier.GUID.ToString()
                        detail = embedded_details.get(guid)
                        if detail is None:
                            detail = _describe_embedded_detail(guid, wrapped_assembly)
                            embedded_details[guid] = detail
                            objects.append(detail)
                        part_guid = model_obj.Identifier.GUID.ToString()
                        # Track individual parts so the client gets a part_count breakdown
                        if part_guid not in {p.guid for p in detail.parts}:
                            detail.parts.append(EmbeddedDetailPart(guid=part_guid, element_type=type(model_obj).__name__))
                            returned_count += 1
                        continue
                except ValueError:
                    pass

        guid = model_obj.Identifier.GUID.ToString()
        if guid in seen_guids:
            continue
        seen_guids.add(guid)
        try:
            objects.append(_describe_model_object(guid, model_obj))
            returned_count += 1
        except Exception as e:
            logger.debug("Failed to describe model object %s in view '%s': %s", guid, view_key, e)
            unresolved_count += 1

    logger.info("get_view_objects: view '%s' has %d model object(s), %d returned, %d unresolved", view_key, total_count, returned_count, unresolved_count)
    return ToolResult(
        structured_content={
            "status": "success",
            "view_key": view_key,
            "total_count": total_count,
            "returned_count": returned_count,
            "unresolved_count": unresolved_count,
            "objects": [{**asdict(o), "part_count": len(o.parts)} if isinstance(o, EmbeddedDetail) else o for o in objects],
            "limit": limit,
            "has_more": has_more,
        }
    )


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_view_annotations(
    view_key: Annotated[str, Field(description="View key (from `get_drawing_views`)")],
    type_filter: Annotated[
        Literal["all", "dimensions", "marks", "text", "graphics"],
        Field(description="Restrict to one annotation category. Counts then cover only that category instead of every annotation."),
    ] = "all",
    limit: Annotated[int, Field(description="Max annotations in the list", ge=1)] = 200,
) -> ToolResult:
    """
    Read the annotations (marks, dimensions, text) shown in a drawing view.

    Each annotation reports its content but no geometry/coordinates.
    """
    handler = TeklaDrawingHandler()
    handler.require_active_drawing()
    view = handler.get_view_by_key(view_key)

    type_filter_types = list(CATEGORY_TYPES[type_filter]) if type_filter != "all" else None
    all_objects = view.get_all_objects(type_filter_types)
    if all_objects is None:
        raise RuntimeError(f"Failed to enumerate objects in view '{view_key}'. The view state may be corrupted or the connection lost.")

    counts_by_category: dict[str, int] = {}
    annotations: list[dict[str, Any]] = []
    # Lazy: TeklaModel() is only needed for marks (target_guid resolution),
    # not for text/dimensions/graphics
    model: TeklaModel | None = None

    for obj in all_objects:
        category = categorize_drawing_object(obj)
        # Sheet view aggregates marks/dimensions from all child views - only show
        # text/graphics that belong to the sheet itself, regardless of type_filter
        if view.is_sheet and category not in ("text", "graphics"):
            continue
        if type_filter == "all" and category not in DEFAULT_ANNOTATION_CATEGORIES:
            continue
        if category == "marks" and model is None:
            model = TeklaModel()
        annotation = extract_annotation_content(obj, category, model)
        # Marks with no readable content (e.g. empty Mark.Content) are
        # excluded from the count - they carry no useful information
        if category == "marks" and annotation.get("content") is None:
            continue
        counts_by_category[category] = counts_by_category.get(category, 0) + 1
        if type_filter != "all" and category != type_filter:
            continue
        annotations.append(annotation)
        if len(annotations) >= limit:
            break

    total_count = sum(counts_by_category.values())
    available = total_count if type_filter == "all" else counts_by_category.get(type_filter, 0)
    has_more = len(annotations) < available

    logger.info("get_view_annotations: view '%s' has %d annotation(s), %d returned", view_key, total_count, len(annotations))
    return ToolResult(
        structured_content={
            "status": "success",
            "view_key": view_key,
            "type_filter": type_filter,
            "total_count": total_count,
            "counts_by_category": counts_by_category,
            "returned_count": len(annotations),
            "annotations": annotations,
            "limit": limit,
            "has_more": has_more,
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
def align_section_views(
    view_keys: Annotated[list[str] | None, Field(description="Section view keys to align (from `get_drawing_views`). Aligns all section views when omitted")] = None,
    overlap_tolerance: Annotated[
        float,
        Field(description="Overlap in mm, on the non-aligned axis, above which a section is treated as intentionally placed outside its projection lane and left as-is"),
    ] = 5.0,
) -> ToolResult:
    """
    Align section views in projection with the view they were cut from.

    A horizontal cut aligns X, a vertical cut aligns Y.  The parent is the
    view holding a section mark whose name matches the section view's name.

    A section is only aligned if it sits in its projection lane: beside the
    parent for a vertical cut, above/below it for a horizontal cut. `overlap_tolerance`
    sets how much non-aligned-axis overlap is tolerated before a section counts as
    out-of-lane.
    """
    if view_keys is not None and not view_keys:
        raise ValueError("view_keys must not be an empty list. Omit it to align all section views.")

    handler = TeklaDrawingHandler()
    drawing = handler.require_active_drawing()

    tekla_views = [v for v in handler.get_drawing_views() if not v.is_sheet]
    by_key = {v.view_key: v for v in tekla_views}

    # Parent lookup must see every view: a section's parent may be outside view_keys.
    parents = detect_section_parents(tekla_views)

    # Views already within this many mm of their projection are left untouched
    snap_tolerance = get_tolerance("snap_tolerance", group="drawings", default=0.1)

    target_set: set[str] | None = None
    moves: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if view_keys is not None:
        missing = [k for k in view_keys if k not in by_key]
        if missing:
            raise ValueError(f"View(s) not found: {missing}. Use `get_drawing_views` to list valid keys.")
        target_set = set(view_keys)
        for key in view_keys:
            if by_key[key].view_type != "SectionView":
                skipped.append({"view_key": key, "view_name": by_key[key].name, "reason": "not a section view, cannot align"})

    for v in tekla_views:
        if v.view_type != "SectionView":
            continue
        if target_set is not None and v.view_key not in target_set:
            continue
        entry = parents.get(v.view_key)
        if entry is None:
            skipped.append({"view_key": v.view_key, "view_name": v.name, "reason": "no matching section mark found"})
            continue
        parent_key, mark = entry
        parent_view = by_key[parent_key]
        alignment = compute_section_alignment(v, parent_view, mark)
        if alignment is None:
            skipped.append({"view_key": v.view_key, "view_name": v.name, "reason": "section mark has no endpoint geometry (LeftPoint/RightPoint)"})
            continue
        axis, delta = alignment
        if abs(delta) < snap_tolerance:
            continue  # already aligned

        # Placement classifier, not a collision check. If the section overlaps the
        # parent on the axis that does not change during alignment, it was likely
        # placed outside its normal lane on purpose. Aligning it would move it across
        # the parent, so we leave it where it is
        v_fx, v_fy = v.frame_origin
        p_fx, p_fy = parent_view.frame_origin
        if axis == "y":
            v_x_end = v_fx + v.width
            p_x_end = p_fx + parent_view.width
            overlap = min(v_x_end, p_x_end) - max(v_fx, p_fx)
            if overlap > overlap_tolerance:
                skipped.append(
                    {"view_key": v.view_key, "view_name": v.name, "reason": f"left as-is: placed outside the projection lane (X-overlap with parent {overlap:.1f} mm > {overlap_tolerance} mm)"}
                )
                continue
        else:
            v_y_end = v_fy + v.height
            p_y_end = p_fy + parent_view.height
            overlap = min(v_y_end, p_y_end) - max(v_fy, p_fy)
            if overlap > overlap_tolerance:
                skipped.append(
                    {"view_key": v.view_key, "view_name": v.name, "reason": f"left as-is: placed outside the projection lane (Y-overlap with parent {overlap:.1f} mm > {overlap_tolerance} mm)"}
                )
                continue

        ox, oy = v.origin
        v.origin = (ox + delta, oy) if axis == "x" else (ox, oy + delta)
        if not v.modify():
            raise RuntimeError(f"Failed to align view '{v.view_key}'.")
        moves.append(
            {
                "view_key": v.view_key,
                "view_name": v.name,
                "parent_view_key": parent_key,
                "axis": axis,
                "delta": round(delta, 1),
            }
        )

    if moves and not drawing.commit_changes():
        raise RuntimeError("CommitChanges() failed after aligning section views.")

    logger.info("align_section_views: aligned %d section view(s), skipped %d", len(moves), len(skipped))
    return ToolResult(
        structured_content={
            "status": "success" if moves else "warning",
            "aligned_count": len(moves),
            "moves": moves,
            "skipped": skipped,
        }
    )


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
        if tekla_view.is_sheet:
            results.append({"view_key": item.view_key, "status": "failed", "message": "Cannot set scale on the sheet view"})
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

    The sheet view aggregates clouds from all child views, so it is
    skipped to avoid double-deletion. Only model-view clouds are affected.
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
        to_delete = tekla_view.get_all_objects([Cloud])
        if to_delete is None:
            continue

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
