"""
Drawing tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Annotated, Literal, TypeVar

import ezdxf

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.config import (
    get_config_dir,
    get_default_export_settings,
    get_default_print_settings,
    get_export_timeout,
    get_export_output_dir,
    get_mcp_data_dir,
    get_tolerance,
)
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    DWG_FILE_VERSION_MAP,
    FORMAT_TO_FILE_EXTENSION,
    DrawingExportFormat,
    DrawingExportVersion,
    DrawingType,
    StringFilterOption,
    ViewAttributes,
)
from tekla_mcp_server.utils import mcp_handler, resolve_model_relative_dir
from tekla_mcp_server.drawing_export import (
    DWGSETTING_EXTENSION,
    PDF_PRINT_OPTIONS_EXTENSION,
    install_export_settings_content,
    patch_dwgsetting_xml,
    patch_pdf_print_options_xml,
    pdf_print_options_outputs_single_file,
)
from tekla_mcp_server.tekla.filter_builder import to_filter_option
from tekla_mcp_server.tekla.utils import ensure_macro_installed, ensure_export_settings_installed, get_available_attribute_files
from tekla_mcp_server.providers.operations_provider import run_macro
from tekla_mcp_server.tekla.drawing_utils import (
    matches_string_filter,
    map_sheet_size_to_paper_size,
    detect_sheet_grid,
    assign_sheet_number,
    draw_cloud_bbox,
    detect_section_parents,
    compute_section_alignment,
    categorize_drawing_object,
    extract_annotation_content,
    CATEGORY_TYPES,
    DEFAULT_ANNOTATION_CATEGORIES,
)
from tekla_mcp_server.dxf_operations import run_collision_checks, resolve_entities
from tekla_mcp_server.tekla.wrappers.drawing import TeklaDrawing
from tekla_mcp_server.tekla.wrappers.drawing_handler import TeklaDrawingHandler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_object, TeklaAssembly
from tekla_mcp_server.tekla.loader import (
    Cloud,
    DrawingConnection,
    DrawingObject,
    DrawingModelObject,
    ModelObject,
)


drawings_provider = LocalProvider()

_T = TypeVar("_T")

# Internal collision-check setting (config/attributes): remaps drawing objects onto
# custom TEKLA_MCP_* layers the DXF parser depends on, with a TEKLA_MCP_ file prefix.
# Used as-is by check_drawing_collisions, always DXF.
COLLISION_EXPORT_SETTING = "TEKLA_MCP_COLLISION_LAYERS"

# Clean base setting (config/attributes) for the user-facing export_drawings tool:
# standard layers, empty file prefix. Python patches its format/version/output dir
# per call. The export macro selects it by name.
EXPORT_BASE_SETTING = "TEKLA_MCP_EXPORT_BASE"

# Base PDF print setting (config/attributes) for print_drawings. Python patches
# its paper size/orientation/multi-sheet tiling/output dir per drawing. The
# print macro selects it by name.
PDF_BASE_SETTING = "TEKLA_MCP_PDF_BASE"


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
    marks: Annotated[list[str], Field(description="List of drawing marks to get properties for. Leave empty to use the currently selected drawings")] = [],
) -> ToolResult:
    """
    Get properties of drawings by their marks.

    If marks are empty, gets properties of currently selected drawings in Tekla.

    ## OUTPUT
    - Return the result table in Markdown format EXACTLY as provided by the tool.
    - DO NOT reformat, truncate, or modify anything, including spacing, columns, or headers.
    - ALWAYS show the full table. DO NOT remove any rows or columns.
    """
    handler = TeklaDrawingHandler()
    target_drawings = handler.get_drawings_by_marks(marks or None)

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
    marks: Annotated[list[str], Field(description="List of drawing marks to update. Leave empty to update the currently selected drawings")] = [],
    name: Annotated[str | None, Field(description="Drawing name")] = None,
    title1: Annotated[str | None, Field(description="First drawing title")] = None,
    title2: Annotated[str | None, Field(description="Second drawing title")] = None,
    title3: Annotated[str | None, Field(description="Third drawing title")] = None,
    user_properties: Annotated[dict[str, Any], Field(description="Dictionary of user-defined attribute names and values")] = {},
) -> ToolResult:
    """
    Sets properties and user-defined attributes (UDAs) on drawings by their marks.

    If marks are empty, updates the currently selected drawings in Tekla.
    Does not require any drawing to be open.
    """
    handler = TeklaDrawingHandler()
    target_drawings = handler.get_drawings_by_marks(marks or None)
    user_properties_or_none = user_properties or None

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
                user_properties=user_properties_or_none,
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
    marks: Annotated[list[str], Field(description="List of drawing marks to issue or unissue. Leave empty to use the currently selected drawings")] = [],
    action: Annotated[Literal["issue", "unissue"], Field(description="Whether to issue or unissue the drawings")] = "issue",
) -> ToolResult:
    """
    Issue or unissue drawings by their marks.

    If marks are empty, acts on the currently selected drawings in Tekla.
    This is a drawing list level action, it does not require any drawing to be open.
    """
    handler = TeklaDrawingHandler()
    target_drawings = handler.get_drawings_by_marks(marks or None)

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
    marks: Annotated[list[str], Field(description="List of drawing marks to update. Leave empty to use the currently selected drawings")] = [],
) -> ToolResult:
    """
    Update drawings by their marks, refreshing them from the model.

    If marks are empty, acts on the currently selected drawings in Tekla.

    Numbering must be up to date before calling this tool.
    """
    handler = TeklaDrawingHandler()
    target_drawings = handler.get_drawings_by_marks(marks or None)

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


def _wait_for_new_files(directory: Path, pattern: str, before: set[Path], expected_count: int, timeout: float, *, wait_message: str | None = None) -> list[Path]:
    """
    Wait for at least `expected_count` new files matching `pattern` in `directory`.

    Diffs against the `before` snapshot, polling every 2 seconds until either
    `expected_count` new files appear or `timeout` seconds elapse. Tolerates
    `directory` not existing yet (treated as zero matches).

    Args:
        directory: Directory to watch for new files.
        pattern: Glob pattern to match within `directory`, e.g. '*.pdf'.
        before: Snapshot of pre-existing matching files, excluded from the result.
        expected_count: Number of new files to wait for.
        timeout: Max seconds to wait.
        wait_message: If given, logged once if the wait loop actually has to run.

    Returns:
        Sorted list of new file paths found - may have fewer than
        `expected_count` entries if the timeout elapses first.
    """

    def _scan() -> list[Path]:
        return sorted(set(directory.glob(pattern)) - before) if directory.is_dir() else []

    produced = _scan()
    if len(produced) < expected_count:
        if wait_message:
            logger.info(wait_message)
        deadline = time.time() + timeout
        while len(produced) < expected_count and time.time() < deadline:
            time.sleep(2)
            produced = _scan()
    return produced


def _close_print_dialog() -> None:
    """Close the Document Manager print dialog after a print, logging on failure."""
    close_result = run_macro(macro_name="TeklaMCPClosePrintDialog.cs")
    if close_result.structured_content.get("status") != "success":
        logger.warning("Failed to close print dialog after print")


def _run_print_macro(model_path: str, setting_name: str, marks: list[str], poll: Callable[[], _T]) -> _T:
    """
    Run the shared print macro for `marks` using the named print setting.

    Writes `print.tmp` (a `SETTING=<name>` line plus one mark per line) for the
    macro to consume, runs the macro, then calls `poll` to verify the output.
    Closes the print dialog after `poll` returns (closing earlier would cancel
    the print) so the next call doesn't hit an already-open dialog.

    Args:
        model_path: Path to the open Tekla model.
        setting_name: Print setting to select in the Document Manager.
        marks: Drawing marks to search and select.
        poll: Callback run after the macro to verify/collect output. Its return
            value is returned to the caller.

    Returns:
        Whatever `poll` returns.
    """
    ensure_macro_installed("TeklaMCPPrintDrawings.cs", category="modeling")
    ensure_macro_installed("TeklaMCPClosePrintDialog.cs", category="modeling")

    data_dir = get_mcp_data_dir(model_path)
    print_file = data_dir / "print.tmp"
    print_file.write_text(f"SETTING={setting_name}\n" + "\n".join(marks), encoding="utf-8")

    try:
        macro_result = run_macro(macro_name="TeklaMCPPrintDrawings.cs")
        if macro_result.structured_content.get("status") != "success":
            raise RuntimeError("Print macro failed. Ensure the print setting exists in Document Manager.")
        result = poll()
        _close_print_dialog()
        return result
    finally:
        print_file.unlink(missing_ok=True)


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def print_drawings(
    marks: Annotated[list[str], Field(description="List of drawing marks to process. Leave empty to use the currently selected drawings")] = [],
    print_settings: Annotated[str | None, Field(description="Name of a customer '.PdfPrintOptions.xml' print setting. When set, size auto-detection is skipped and the setting is used as-is")] = None,
) -> ToolResult:
    """
    Print drawings to PDF via the Document Manager print macro.

    Two modes: with `print_settings`, the named setting is used as-is. Without
    it, paper size, orientation and multi-sheet tiling (A0-A4, or a clean
    tiling of one) are auto-detected per drawing, and drawings sharing the
    same detected size are batched into a single macro call. Empty `marks`
    uses the current Tekla selection.
    """
    handler = TeklaDrawingHandler()
    if handler.get_active_drawing() is not None:
        raise RuntimeError("A drawing is currently open. Close it first with `close_drawing` before exporting.")

    target_drawings = handler.get_drawings_by_marks(marks or None)

    model_path = TeklaModel().model_path
    raw_dir = get_export_output_dir()
    output_dir = resolve_model_relative_dir(raw_dir, model_path)
    if not Path(output_dir).is_dir():
        raise ValueError(f"Output directory '{output_dir}' does not exist")

    customer_setting = print_settings or get_default_print_settings()
    if customer_setting:
        # Strip .PdfPrintOptions.xml if the user included it, then verify it exists.
        # `get_available_attribute_files` strips only the trailing `.xml`, so its
        # results still carry the `.PdfPrintOptions` suffix - strip that too
        setting_stem = customer_setting.removesuffix(PDF_PRINT_OPTIONS_EXTENSION)
        available = sorted({name.removesuffix(".PdfPrintOptions") for name in get_available_attribute_files(PDF_PRINT_OPTIONS_EXTENSION)})
        if setting_stem not in available:
            raise ValueError(f"Print settings '{customer_setting}' not found. Available settings: {available}")

        expected_marks = [d.mark for d in target_drawings]
        _run_print_macro(model_path, setting_stem, expected_marks, lambda: None)
        return ToolResult(
            structured_content={
                "status": "success",
                "message": f"Print submitted for {len(expected_marks)} drawing(s) using settings '{setting_stem}'. Output location is defined by the settings.",
                "settings": setting_stem,
                "total": len(expected_marks),
                "marks": expected_marks,
            }
        )

    base_xml = (get_config_dir() / "attributes" / f"{PDF_BASE_SETTING}{PDF_PRINT_OPTIONS_EXTENSION}").read_text(encoding="utf-8")
    # OutputToSingleFile is a user-adjustable field on the base setting (see
    # docs/configuration.md), never patched per call - a successful combined
    # print produces one file regardless of how many drawings are in the batch
    single_file_output = pdf_print_options_outputs_single_file(base_xml)

    produced_files: list[Path] = []
    errors: dict[str, str] = {}

    # Group drawings by detected paper size/orientation/multi-sheet signature so
    # drawings sharing the same settings print together in one macro call.
    # Tekla produces exactly one PDF per drawing regardless of tile count - a
    # multi-sheet drawing's tiles become pages within that one file, not
    # separate files. Filenames cannot be reliably attributed back to a
    # specific mark within a batch, so results are reported at the batch
    # level (`files`) plus per-mark failures (`errors`)
    groups: dict[tuple[str, bool, str], list[TeklaDrawing]] = {}
    for drawing in target_drawings:
        sheet_width = drawing.drawing.Layout.SheetSize.Width
        sheet_height = drawing.drawing.Layout.SheetSize.Height

        paper_size = map_sheet_size_to_paper_size(sheet_width, sheet_height)
        is_multi_sheet = False
        if paper_size is None:
            # Single standard size didn't match - check if it's a clean tiling
            # of multiple standard sheets
            grid = detect_sheet_grid(sheet_width, sheet_height)
            if grid is None:
                logger.warning("Format not supported for drawing %s (size: %sx%s mm)", drawing.mark, sheet_width, sheet_height)
                errors[drawing.mark] = f"Format not supported: sheet size {sheet_width}x{sheet_height} mm does not match A0-A4 or a clean tiling of it"
                continue
            paper_size, _cols, _rows = grid
            is_multi_sheet = True

        # Multi-sheet tiles are only ever detected in landscape (see
        # `detect_sheet_grid`). Single sheets keep their actual orientation -
        # forcing Landscape unconditionally would print portrait sheets sideways
        orientation = "Landscape" if is_multi_sheet or sheet_width >= sheet_height else "Portrait"

        groups.setdefault((str(paper_size), is_multi_sheet, orientation), []).append(drawing)

    for (paper_size_str, is_multi_sheet, orientation), group_drawings in groups.items():
        group_marks = [d.mark for d in group_drawings]
        group_size = len(group_marks)
        try:
            # Patch and install the base setting with this group's detected
            # size/orientation/tiling, then let the macro select it by name
            patched = patch_pdf_print_options_xml(
                base_xml,
                paper_size=paper_size_str,
                orientation=orientation,
                multi_sheet=is_multi_sheet,
                multi_sheet_order="LeftToRightTopToBottom",
                output_dir=raw_dir,
            )
            install_export_settings_content(model_path, f"{PDF_BASE_SETTING}{PDF_PRINT_OPTIONS_EXTENSION}", patched)

            before_files = set(Path(output_dir).glob("*.pdf"))
            # A combined file setting always produces one file regardless of
            # batch size. Otherwise it's exactly one file per drawing
            expected_files = 1 if single_file_output else group_size

            def _poll() -> list[Path]:
                return _wait_for_new_files(Path(output_dir), "*.pdf", before_files, expected_files, get_export_timeout())

            logger.info("Printing %d drawing(s) [%s, %s, multi_sheet=%s, single_file=%s] -> %s", group_size, paper_size_str, orientation, is_multi_sheet, single_file_output, output_dir)
            produced = _run_print_macro(model_path, PDF_BASE_SETTING, group_marks, _poll)

            if len(produced) >= expected_files:
                produced_files.extend(produced)
            else:
                message = f"Expected {expected_files} file(s) for {group_size} drawing(s), found {len(produced)} in the output folder."
                logger.warning("Group [%s, %s, multi_sheet=%s]: %s", paper_size_str, orientation, is_multi_sheet, message)
                for mark in group_marks:
                    errors[mark] = message

        except Exception as e:
            logger.error("Failed to print group [%s, %s, multi_sheet=%s]: %s", paper_size_str, orientation, is_multi_sheet, str(e))
            for mark in group_marks:
                errors[mark] = str(e)

    exported_count = len(target_drawings) - len(errors)
    status = "success" if not errors else "partial" if exported_count > 0 else "error"

    result: dict[str, Any] = {
        "status": status,
        "output_folder": raw_dir,
        "total": len(target_drawings),
        "exported": exported_count,
        "files": sorted(p.name for p in produced_files),
        "errors": errors,
    }
    return ToolResult(structured_content=result)


def _close_export_dialog() -> None:
    """Close the Document Manager export dialog after an export, logging on failure."""
    close_result = run_macro(macro_name="TeklaMCPCloseExportDialog.cs")
    if close_result.structured_content.get("status") != "success":
        logger.warning("Failed to close export dialog after export")


def _run_export_macro(model_path: str, setting_name: str, marks: list[str], poll: Callable[[], _T]) -> _T:
    """
    Run the shared export macro for `marks` using the named export setting.

    Writes `export.tmp` (a `SETTING=<name>` line plus one mark per line) for the
    macro to consume, runs the macro, then calls `poll` to verify the output.
    Closes the export dialog after `poll` returns (closing earlier would cancel
    the export).

    Args:
        model_path: Path to the open Tekla model.
        setting_name: Export setting to select in the Document Manager.
        marks: Drawing marks to search and select.
        poll: Callback run after the macro to verify/collect output. Its return
            value is returned to the caller.

    Returns:
        Whatever `poll` returns.
    """
    ensure_macro_installed("TeklaMCPExportDrawings.cs", category="modeling")
    ensure_macro_installed("TeklaMCPCloseExportDialog.cs", category="modeling")

    data_dir = get_mcp_data_dir(model_path)
    export_file = data_dir / "export.tmp"
    export_file.write_text(f"SETTING={setting_name}\n" + "\n".join(marks), encoding="utf-8")

    try:
        macro_result = run_macro(macro_name="TeklaMCPExportDrawings.cs")
        if macro_result.structured_content.get("status") != "success":
            raise RuntimeError("Export macro failed. Ensure the export setting exists in Document Manager.")
        result = poll()
        _close_export_dialog()
        return result
    finally:
        export_file.unlink(missing_ok=True)


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def export_drawings(
    marks: Annotated[list[str], Field(description="Drawing marks to export. Leave empty to use the currently selected drawings")] = [],
    drawing_format: Annotated[DrawingExportFormat, Field(description="Output format: dxf, dwg or dgn")] = DrawingExportFormat.DWG,
    version: Annotated[DrawingExportVersion | None, Field(description="AutoCAD version: 2000, 2004, 2007, 2010 or 2013. Defaults to 2010")] = None,
    export_settings: Annotated[str | None, Field(description="Name of a customer '.dwgsetting' export setting. When set, format/version are ignored and the setting is used as-is")] = None,
) -> ToolResult:
    """
    Export drawings via the Document Manager export macro.

    Two modes: with `export_settings`, the named setting is used as-is. Without
    it, the base setting is patched with `drawing_format` and `version`. Empty
    `marks` uses the current Tekla selection.
    """
    # Coerce to enums so direct calls validate too (raises ValueError on bad values)
    drawing_format = DrawingExportFormat(drawing_format)
    if version is not None:
        version = DrawingExportVersion(version)

    handler = TeklaDrawingHandler()
    if handler.get_active_drawing() is not None:
        raise RuntimeError("A drawing is currently open. Close it first with `close_drawing` before exporting.")

    target_drawings = handler.get_drawings_by_marks(marks or None)
    if not target_drawings:
        raise ValueError("No drawings selected. Select drawings in Document Manager or pass the `marks` parameter.")

    expected_marks = [d.mark for d in target_drawings]
    model_path = TeklaModel().model_path

    customer_setting = export_settings or get_default_export_settings()
    if customer_setting:
        mode = "named"
        setting_name = customer_setting

        # Strip .dwgsetting if the user included it, then verify it exists
        setting_stem = setting_name.removesuffix(DWGSETTING_EXTENSION)
        available = get_available_attribute_files(DWGSETTING_EXTENSION)
        if setting_stem not in available:
            raise ValueError(f"Export settings '{setting_name}' not found. Available settings: {available}")
        output_dir: str | None = None
        ext: str | None = None
        version_label: str | None = None
    else:
        mode = "ongoing"
        setting_name = EXPORT_BASE_SETTING
        ext = FORMAT_TO_FILE_EXTENSION[drawing_format]
        resolved_version = version or DrawingExportVersion.V2010
        file_version = DWG_FILE_VERSION_MAP[resolved_version]
        version_label = resolved_version.value
        raw_dir = get_export_output_dir()
        output_dir = resolve_model_relative_dir(raw_dir, model_path)
        if not Path(output_dir).is_dir():
            raise ValueError(f"Output directory '{output_dir}' does not exist")
        # Patch the bundled base setting with the chosen format/version/output dir,
        # then install it into the model so the macro selects it by name.
        base_xml = (get_config_dir() / "attributes" / f"{EXPORT_BASE_SETTING}{DWGSETTING_EXTENSION}").read_text(encoding="utf-8")
        patched = patch_dwgsetting_xml(base_xml, file_extension=ext, file_version=file_version, output_dir=raw_dir)
        install_export_settings_content(model_path, f"{EXPORT_BASE_SETTING}{DWGSETTING_EXTENSION}", patched)

    logger.info("export_drawings: %s mode, %d drawing(s), setting '%s'", mode, len(expected_marks), setting_name)

    # Snapshot existing files so we count only this run's new outputs - the
    # filename follows Tekla's own XS_DRAWING_PLOT_FILE_NAME_* advanced option
    # template (not configurable from here, see docs/reference.md), so we diff
    # rather than match by mark, and never delete the user's existing files.
    before_files: set[Path] = set()
    if output_dir is not None and ext and Path(output_dir).is_dir():
        before_files = set(Path(output_dir).glob(f"*{ext}"))

    def _poll() -> list[Path]:
        # Named-setting mode: the customer setting owns the output dir and naming,
        # which we cannot predict, so there is nothing to verify.
        if output_dir is None or not ext:
            return []
        out = Path(output_dir)
        if not out.is_dir():
            raise RuntimeError(f"Output directory '{output_dir}' not found after export.")
        expected = len(expected_marks)
        return _wait_for_new_files(out, f"*{ext}", before_files, expected, get_export_timeout(), wait_message=f"Waiting for {expected} export file(s) to appear in {output_dir}...")

    produced = _run_export_macro(model_path, setting_name, expected_marks, _poll)

    if mode == "named":
        result: dict[str, Any] = {
            "status": "success",
            "message": f"Export submitted for {len(expected_marks)} drawing(s) using settings '{setting_name}'. Output location is defined by the settings.",
            "settings": setting_name,
            "total": len(expected_marks),
            "marks": expected_marks,
        }
    else:
        status = "success" if len(produced) >= len(expected_marks) else "partial"
        result = {
            "status": status,
            "format": drawing_format.value,
            "version": version_label,
            "output_folder": raw_dir,
            "total": len(expected_marks),
            "exported": len(produced),
            "files": sorted(p.name for p in produced),
        }
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


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
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
        action = "save and close" if save else "close without saving"
        raise RuntimeError(f"Failed to {action} drawing '{mark}'.")

    logger.info("Closed active drawing (saved=%s)", save)
    return ToolResult(structured_content={"status": "success", "drawing_is_saved": save})


def _resolve_drawing_views(handler: TeklaDrawingHandler, active: TeklaDrawing) -> tuple[list[Any], list[dict[str, Any]], int]:
    """
    Enumerate `active`'s views once: raw Tekla views, their dict form, and sheet count.

    Shared by `get_drawing_views` and `check_drawing_collisions` so both reuse
    one Tekla API enumeration instead of each doing their own.
    """
    # Authoritative source for sheet_count/tiling math below - not guaranteed
    # identical to the sheet view's own width/height in the dict representation
    sheet_width = active.drawing.Layout.SheetSize.Width
    sheet_height = active.drawing.Layout.SheetSize.Height

    tekla_views = handler.get_drawing_views()

    grid = detect_sheet_grid(sheet_width, sheet_height)
    if grid is not None:
        _, cols, rows = grid
        sheet_count = cols * rows
        tile_width = sheet_width / cols
        tile_height = sheet_height / rows
    else:
        sheet_count = 1
        cols, rows = 1, 1
        tile_width, tile_height = sheet_width, sheet_height

    view_list: list[dict[str, Any]] = []
    for v in tekla_views:
        if v.is_sheet:
            view_list.append(v.to_dict())
        else:
            fx, fy = v.frame_origin
            sheet_number = assign_sheet_number(fx, fy, v.width, v.height, tile_width, tile_height, cols, rows)
            view_list.append(v.to_dict(sheet_number=sheet_number))

    return tekla_views, view_list, sheet_count


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_drawing_views() -> ToolResult:
    """
    List all views in the active drawing.
    Returns view type, scale, position, size, and a unique `view_key`.
    Includes the sheet view (`is_sheet=true`).

    Use `view_key` for all follow-up calls.
    Use `open_drawing` first if no drawing is currently open.
    """
    handler = TeklaDrawingHandler()
    active = handler.require_active_drawing()
    _tekla_views, view_list, sheet_count = _resolve_drawing_views(handler, active)

    return ToolResult(
        structured_content={
            "status": "success",
            "sheet_count": sheet_count,
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
    total_count = sum(1 for o in drawing_objects if not isinstance(o, DrawingConnection))
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
        if isinstance(drawing_obj, DrawingConnection):
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
        # Iterate every object so the counts (and therefore has_more) reflect the
        # true total, but only collect up to `limit`. Resolving a mark's target
        # GUID is a model lookup, so only do it for marks we actually return.
        collecting = len(annotations) < limit and (type_filter == "all" or category == type_filter)
        if category == "marks" and collecting and model is None:
            model = TeklaModel()
        annotation = extract_annotation_content(obj, category, model if collecting else None)
        # Marks with no readable content (e.g. empty Mark.Content) are
        # excluded from the count - they carry no useful information
        if category == "marks" and annotation.get("content") is None:
            continue
        counts_by_category[category] = counts_by_category.get(category, 0) + 1
        if collecting:
            annotations.append(annotation)

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
    view_keys: Annotated[list[str], Field(description="Section view keys to align (from `get_drawing_views`). Aligns all section views when empty")] = [],
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
    if view_keys:
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
            "skipped_count": len(skipped),
            "skipped": skipped,
        }
    )


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def set_views_attributes(
    views_attributes: Annotated[list[ViewAttributes], Field(description="Per-view display attribute updates to apply")],
) -> ToolResult:
    """
    Set display attributes (scale, opening symbols, reflected/undeformed/unfolded) on one or more drawing views.

    Each item must set at least one attribute. Unset attributes on an item are left unchanged.

    ## EXAMPLES
    # Set the scale of a view to 1:20:
        {"views_attributes": [{"view_key": "FrontView_42", "scale": 20}]}

    # Show opening and recess symbols on a view:
        {"views_attributes": [{"view_key": "FrontView_42", "show_part_openings_or_recess_symbol": true}]}
    """
    if not views_attributes:
        raise ValueError("views_attributes is required")

    handler = TeklaDrawingHandler()
    drawing = handler.require_active_drawing()
    index = handler.index_views_by_key()

    results: list[dict[str, Any]] = []
    succeeded = 0
    partial = 0
    applied = 0

    for item in views_attributes:
        tekla_view = index.get(item.view_key)
        if tekla_view is None:
            results.append({"view_key": item.view_key, "status": "failed", "message": "View not found"})
            continue
        if tekla_view.is_sheet:
            results.append({"view_key": item.view_key, "status": "failed", "message": "Cannot set attributes on the sheet view"})
            continue
        updated = item.model_dump(exclude={"view_key"}, exclude_none=True)
        try:
            if not tekla_view.set_attributes(**updated):
                results.append({"view_key": item.view_key, "status": "failed", "message": "set_attributes() returned False"})
                continue

            applied += 1
            actual = tekla_view.display_settings
            mismatches = {k: {"requested": v, "actual": actual[k]} for k, v in updated.items() if k in actual and actual[k] != v}
            if mismatches:
                partial += 1
                logger.warning("View '%s': set_attributes applied but Tekla ignored: %s", item.view_key, mismatches)
                results.append({"view_key": item.view_key, "status": "partial", "updated": updated, "warning": f"Tekla did not apply attributes: {mismatches}"})
            else:
                succeeded += 1
                results.append({"view_key": item.view_key, "status": "success", "updated": updated})
        except Exception as e:
            logger.error("Failed to set attributes on view %s: %s", item.view_key, e)
            results.append({"view_key": item.view_key, "status": "error", "message": str(e)})

    total = len(views_attributes)
    status = "success" if succeeded == total else "partial" if succeeded or partial else "error"
    logger.info("set_views_attributes: %d/%d updated, %d partial", succeeded, total, partial)

    if applied > 0 and not drawing.commit_changes():
        raise RuntimeError("CommitChanges() failed after setting view attributes.")

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
def delete_clouds(
    view_keys: Annotated[list[str], Field(description="View keys to clear (from `get_drawing_views`). Processes all views when empty")] = [],
) -> ToolResult:
    """
    Delete all clouds from the active drawing, including the sheet view.
    """
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

    view_results: list[dict[str, Any]] = []
    total_found = 0
    total_deleted = 0
    total_failed = 0

    for tekla_view in views:
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
    logger.info("delete_clouds: found=%d deleted=%d failed=%d", total_found, total_deleted, total_failed)
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


def _export_one_drawing_to_dxf(model_path: str, plotfiles_dir: Path, mark: str) -> Path:
    """
    Export a single drawing to DXF and return its output path.

    Output names cannot be forced to contain the mark - matching by filename is
    not reliable. Instead this exports one mark per macro call and identifies its
    file by snapshotting Plotfiles/ before and after, so the single new file is
    unambiguously this mark's DXF.

    Raises:
        RuntimeError: If zero or more than one new DXF appears within the
            configured timeout (`get_export_timeout`, default 120s).
    """
    before = set(plotfiles_dir.glob("TEKLA_MCP_*.dxf")) if plotfiles_dir.is_dir() else set()
    timeout = get_export_timeout()

    def _poll() -> Path:
        produced = _wait_for_new_files(plotfiles_dir, "TEKLA_MCP_*.dxf", before, 1, timeout, wait_message=f"Waiting for DXF to appear in Plotfiles/ for mark '{mark}'...")
        if not produced:
            raise RuntimeError(f"No DXF appeared in Plotfiles/ after {timeout:g}s for mark '{mark}'. Check the {COLLISION_EXPORT_SETTING} export setting output directory.")
        if len(produced) > 1:
            raise RuntimeError(f"Expected exactly one new DXF for mark '{mark}', found {len(produced)}: {sorted(p.name for p in produced)}")
        return produced[0]

    return _run_export_macro(model_path, COLLISION_EXPORT_SETTING, [mark], _poll)


def _export_drawings_to_dxf(
    model_path: str,
    plotfiles_dir: Path,
    expected_marks: list[str],
) -> dict[str, Path]:
    """
    Export drawings to DXF and return the resulting file paths keyed by mark.

    Exports each mark with its own macro call (see `_export_one_drawing_to_dxf`)
    rather than batching, since output filenames cannot be tied to a mark.

    Args:
        model_path: Path to the open Tekla model.
        plotfiles_dir: The model's Plotfiles/ directory.
        expected_marks: Marks of all drawings being exported.

    Raises:
        RuntimeError: If any mark's export does not produce exactly one new
            DXF within the configured timeout.
    """
    ensure_export_settings_installed(f"{COLLISION_EXPORT_SETTING}{DWGSETTING_EXTENSION}")

    # Remove any stale DXF files from previous exports
    if plotfiles_dir.is_dir():
        for p in plotfiles_dir.glob("TEKLA_MCP_*.dxf"):
            p.unlink()

    return {mark: _export_one_drawing_to_dxf(model_path, plotfiles_dir, mark) for mark in expected_marks}


@drawings_provider.tool(tags={"drawings"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def check_drawing_collisions(
    marks: Annotated[list[str] | None, Field(description="Drawing marks to check. Uses Document Manager selection when omitted.")] = None,
) -> ToolResult:
    """
    Detect mark collisions in selected drawings by exporting to DXF and analysing geometry overlaps.

    Select drawings in the Document Manager first or pass the `marks` parameter.
    Magenta revision clouds are drawn at every found collision.
    """

    handler = TeklaDrawingHandler()

    if handler.get_active_drawing() is not None:
        raise RuntimeError("A drawing is currently open. Close it first with `close_drawing` before running collision checks.")

    model = TeklaModel()
    model_path = model.model_path
    plotfiles_dir = Path(model_path) / "Plotfiles"

    selected = handler.get_drawings_by_marks(marks or None)
    if not selected:
        raise ValueError("No drawings selected in Document Manager.")

    drawing_count = len(selected)
    logger.info("check_drawing_collisions: %d drawing(s) selected", drawing_count)

    expected_marks = [d.mark for d in selected]

    outdated = [d.mark for d in selected if d.up_to_date_status != "DrawingIsUpToDate"]
    if outdated:
        details = {d.mark: d.up_to_date_status for d in selected if d.up_to_date_status != "DrawingIsUpToDate"}
        raise ValueError(f"The following drawing(s) must be updated first: {outdated}. Status: {details}")

    logger.info("Exporting %d drawing(s) to DXF...", drawing_count)
    dxf_paths_by_mark = _export_drawings_to_dxf(model_path, plotfiles_dir, expected_marks)

    all_issues: list = []
    total_clouds_drawn = 0
    total_cloud_failures = 0
    per_drawing_results: list[dict] = []

    # For each selected drawing: open → read its DXF → run collision checks →
    # draw magenta revision clouds in Tekla sheet view → save → close.
    # The whole loop is wrapped in try/finally so the exported DXFs are always
    # cleaned up below, even if a drawing's processing raises something the
    # per-drawing except doesn't catch
    def _fail(mark: str, message: str, log_message: str) -> None:
        """Record a per-drawing error and log it. Caller still needs its own `continue`."""
        per_drawing_results.append({"mark": mark, "status": "error", "message": message})
        logger.warning("check_drawing_collisions: %s", log_message)

    try:
        for i, drawing in enumerate(selected, 1):
            mark = drawing.mark
            logger.info("[%d/%d] Opening '%s'...", i, drawing_count, mark)
            dxf_path = dxf_paths_by_mark.get(mark)
            if dxf_path is None or not dxf_path.exists():
                _fail(mark, f"No matching DXF for mark '{mark}'.", f"no DXF found for drawing '{mark}'")
                continue

            # The drawing's up-to-date status was checked before exporting, but the
            # export itself can take up to 120s - re-check against the model now,
            # right before using its DXF, in case another process modified it meanwhile
            try:
                drawing = handler.get_drawings_by_marks([mark])[0]
            except ValueError:
                _fail(mark, "Drawing no longer found.", f"drawing '{mark}' no longer found")
                continue
            if drawing.up_to_date_status != "DrawingIsUpToDate":
                _fail(mark, f"Drawing became out of date during export (status: {drawing.up_to_date_status}).", f"drawing '{mark}' became out of date during export")
                continue

            if not handler.set_active_drawing(drawing):
                _fail(mark, "Failed to open drawing", f"failed to open drawing '{mark}'")
                continue

            try:
                # Read the DXF, flatten block inserts to sheet coordinates
                doc = ezdxf.readfile(str(dxf_path))
                msp = doc.modelspace()

                # Get Tekla view metadata (frame positions, sheet placement, etc.) once -
                # both the dict views (for the checks below) and the raw views (to find
                # the sheet view object) come from this single Tekla API enumeration
                tekla_views, views, _sheet_count = _resolve_drawing_views(handler, drawing)

                # Flatten all entities from view blocks into world-space sheet coordinates
                entities = resolve_entities(doc, msp)
                logger.info("[%d/%d] Running collision checks for '%s' (%d entities)...", i, drawing_count, mark, len(entities))
                # Run all checks (registered in CHECKS list), merge nearby duplicates
                issues = run_collision_checks(views, entities)

                # Draw revision clouds in Tekla - use the sheet view so that DXF
                # sheet coordinates map directly (no per-view origin transform needed)
                sheet_view = next((v for v in tekla_views if v.is_sheet), None)

                # Draw a magenta revision cloud in the sheet view for every issue bbox.
                # DXF coordinates are in sheet mm - the sheet view's coordinate system
                # is identical, so no transform needed
                cloud_count = 0
                cloud_failures = 0

                for issue in issues:
                    if sheet_view is None:
                        cloud_failures += 1
                        continue
                    if draw_cloud_bbox(sheet_view.view, issue.bbox, margin=issue.margin):
                        cloud_count += 1
                    else:
                        cloud_failures += 1

                if cloud_count > 0 and not drawing.commit_changes():
                    cloud_failures += cloud_count
                    cloud_count = 0

                total_clouds_drawn += cloud_count
                total_cloud_failures += cloud_failures

                per_drawing_results.append(
                    {
                        "mark": mark,
                        "status": "success",
                        "issues": len(issues),
                        "clouds_drawn": cloud_count,
                        "cloud_failures": cloud_failures,
                    }
                )
                all_issues.extend(issues)
                logger.info("check_drawing_collisions: '%s' - %d issue(s), %d cloud(s)", mark, len(issues), cloud_count)
            except Exception as e:
                per_drawing_results.append({"mark": mark, "status": "error", "message": str(e)})
                logger.error("check_drawing_collisions: error processing drawing '%s': %s", mark, e)
            finally:
                handler.close_active_drawing(save=True)
    finally:
        # Clean up all exported DXFs (they were only needed for analysis)
        for p in dxf_paths_by_mark.values():
            try:
                p.unlink()
                logger.debug("Deleted DXF: %s", p)
            except Exception as e:
                logger.warning("Failed to delete DXF '%s': %s", p, e)

    # Group all issues by category for the final report. A merged issue can carry
    # more than one underlying check type (e.g. collides_with_sheet + marks_text_overlap)
    # - it's counted under every one of those types, not under a single composite
    # key, so per-category counts stay accurate even after merging
    issues_by_category: dict[str, list[dict]] = {}
    for issue in all_issues:
        entry = {
            "bbox": [round(c, 1) for c in issue.bbox],
            "views": sorted(issue.views),
            "label": issue.label,
        }
        for cat in issue.types:
            issues_by_category.setdefault(cat, []).append(entry)

    succeeded_count = sum(1 for r in per_drawing_results if r["status"] == "success")
    failed_count = sum(1 for r in per_drawing_results if r["status"] == "error")

    status = "success" if failed_count == 0 else "partial"
    result: dict[str, Any] = {
        "status": status,
        "drawings_selected": drawing_count,
        "drawings_succeeded": succeeded_count,
        "drawings_failed": failed_count,
        "total_issues": len(all_issues),
        "issues_by_category": issues_by_category,
        "clouds_drawn": total_clouds_drawn,
        "cloud_failures": total_cloud_failures,
        "per_drawing": per_drawing_results,
    }

    logger.info("check_drawing_collisions: %d/%d drawings, %d total issues", succeeded_count, drawing_count, len(all_issues))
    return ToolResult(structured_content=result)
