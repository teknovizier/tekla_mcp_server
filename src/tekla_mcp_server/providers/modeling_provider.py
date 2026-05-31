"""
Modeling tools provider for Tekla MCP server.

Provides tools for placing beams, columns, panels and managing elements.
"""

from typing import Annotated, Callable, TypeVar
from pydantic import Field

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    BeamInput,
    ColumnInput,
    PanelInput,
    SlabInput,
    BeamType,
    PlacementResult,
    BatchPlacementResult,
    PointInput,
    ElementTypes,
    NumberingSeries,
)
from tekla_mcp_server.utils import format_coordinate_string, mcp_handler
from tekla_mcp_server.tekla.wrappers.model_object import TeklaModelObject, TeklaAssembly, TeklaPart, TeklaBeam, TeklaContourPlate, wrap_model_objects, wrap_model_object
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.loader import Grid, Operation, Phase, Point, Vector


modeling_provider = LocalProvider()

T = TypeVar("T", BeamInput, ColumnInput, PanelInput)


def _collect_parts(obj: TeklaModelObject) -> list[TeklaPart]:
    """Return all child Part objects reachable from *obj*."""
    if isinstance(obj, TeklaAssembly):
        return [wrapped for raw in obj.get_all_children(include_all=False) if (wrapped := wrap_model_object(raw)) is not None and isinstance(wrapped, TeklaPart)]

    return [obj]


def _resolve_numbering_and_name(
    input_object: BeamInput | ColumnInput | PanelInput | SlabInput,
) -> tuple[NumberingSeries | None, NumberingSeries | None, str | None]:
    """Resolve part/assembly numbering and name from input or defaults."""
    part_number: NumberingSeries | None = getattr(input_object, "part_number", None)
    assembly_number: NumberingSeries | None = getattr(input_object, "assembly_number", None)
    name: str | None = getattr(input_object, "name", None)

    if assembly_number is None or part_number is None:
        numbering = ElementTypes.get_default_numbering(input_object.tekla_class)
        if numbering:
            if assembly_number is None:
                assembly_number = numbering.get("assembly_number")
            if part_number is None:
                part_number = numbering.get("part_number")

    if name is None:
        name = ElementTypes.get_default_name(input_object.tekla_class)

    return part_number, assembly_number, name


def _place_beam_element(
    input_object: T,
    input_to_points: Callable[[T], tuple[PointInput, PointInput]],
    beam_type: BeamType,
) -> tuple[bool, PlacementResult]:
    """Place a single beam-type element and return success flag and result."""
    start, end = input_to_points(input_object)
    part_number, assembly_number, name = _resolve_numbering_and_name(input_object)

    tekla_obj = TeklaBeam.create(
        start_point=start,
        end_point=end,
        profile=input_object.profile,
        material=input_object.material,
        tekla_class=input_object.tekla_class,
        name=name,
        position=input_object.position,
        beam_type=beam_type,
        start_point_offset=input_object.start_point_offset,
        end_point_offset=input_object.end_point_offset,
        part_number=part_number,
        assembly_number=assembly_number,
    )
    if tekla_obj is not None:
        return True, PlacementResult(success=True, guid=tekla_obj.guid)
    return False, PlacementResult(success=False, message="Insert() returned false")


def _commit_or_fail(
    results: list[PlacementResult],
    succeeded: int,
    commit_success: bool,
    item_type: str,
) -> tuple[list[PlacementResult], int]:
    """Replace all results with failure records when commit fails; return updated results and succeeded count."""
    if not commit_success:
        logger.error("commit_changes() failed after placing %d %s", succeeded, item_type)
        results = [PlacementResult(success=False, message="Commit failed: changes not persisted") for _ in results]
        succeeded = 0
    return results, succeeded


def _to_tool_result(
    results: list[PlacementResult],
    total: int,
    succeeded: int,
    item_type: str,
) -> ToolResult:
    """Convert batch placement results to ToolResult."""
    return ToolResult(
        structured_content=BatchPlacementResult(
            success=succeeded == total,
            total=total,
            succeeded=succeeded,
            failed=total - succeeded,
            results=results,
            message=f"Placed {succeeded} of {total} {item_type}",
        ).model_dump(mode="json", exclude_none=True)
    )


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def place_beams(beams: Annotated[list[BeamInput] | None, Field(description="List of beam definitions")] = None) -> ToolResult:
    """
    Places multiple beams in the Tekla model.

    ## INSTRUCTIONS
    - Use `tekla://element_types` to discover default Tekla classes.
    - Do NOT provide optional fields (`name`, `position`, `part_number`, `assembly_number`) unless explicitly specified by the user.

    ## COORDINATE SYSTEM
    X, Y = horizontal plane, Z = vertical (height, mm). Z+ is up.

    ## EXAMPLES
    ```json
    {
      "beams": [
        {"start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 5000, "y": 0, "z": 0}, "profile": "300*600", "material": "C30/37", "tekla_class": 11},
        {"start": {"x": 5000, "y": 0, "z": 0}, "end": {"x": 10000, "y": 0, "z": 0}, "profile": "300*600", "material": "C30/37", "tekla_class": 11}
      ]
    }
    ```
    """
    if not beams:
        logger.error("place_beams failed: No beams provided")
        raise ValueError("No beams provided")

    model = TeklaModel()
    results: list[PlacementResult] = []
    succeeded = 0

    for i, input_object in enumerate(beams):
        try:
            logger.debug("Placing beam %d/%d: profile=%s, material=%s, class=%d", i + 1, len(beams), input_object.profile, input_object.material, input_object.tekla_class)
            success, result = _place_beam_element(
                input_object,
                lambda b: (b.start_point, b.end_point),
                BeamType.BEAM,
            )
            if success:
                succeeded += 1
            results.append(result)
        except Exception as e:
            logger.exception("Failed to insert element: %s", str(e))
            results.append(PlacementResult(success=False, message=str(e)))

    results, succeeded = _commit_or_fail(results, succeeded, model.commit_changes(), "beams")
    logger.info("Placed %d of %d beams", succeeded, len(beams))
    return _to_tool_result(results, len(beams), succeeded, "beams")


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def place_columns(columns: Annotated[list[ColumnInput] | None, Field(description="List of column definitions")] = None) -> ToolResult:
    """
    Places multiple columns in the Tekla model.

    ## INSTRUCTIONS
    - Use `tekla://element_types` to discover default Tekla classes.
    - Do NOT provide optional fields (`name`, `position`, `part_number`, `assembly_number`) unless explicitly specified by the user.

    ## COORDINATE SYSTEM
    X, Y = horizontal plane, Z = vertical (height, mm). Z+ is up.

    ## EXAMPLES
    ```json
    {
      "columns": [
        {"base": {"x": 0, "y": 0, "z": 0}, "height": 3000, "profile": "400*400", "material": "C30/37", "tekla_class": 10},
        {"base": {"x": 5000, "y": 0, "z": 0}, "height": 3000, "profile": "400*400", "material": "C30/37", "tekla_class": 10}
      ]
    }
    ```
    """
    if not columns:
        logger.error("place_columns failed: No columns provided")
        raise ValueError("No columns provided")

    model = TeklaModel()
    results: list[PlacementResult] = []
    succeeded = 0

    for i, input_object in enumerate(columns):
        try:
            logger.debug(
                "Placing column %d/%d: profile=%s, material=%s, class=%d, height=%.0f", i + 1, len(columns), input_object.profile, input_object.material, input_object.tekla_class, input_object.height
            )
            success, result = _place_beam_element(
                input_object,
                lambda c: (c.base_point, PointInput(x=c.base_point.x, y=c.base_point.y, z=c.base_point.z + c.height)),
                BeamType.COLUMN,
            )
            if success:
                succeeded += 1
            results.append(result)
        except Exception as e:
            logger.exception("Failed to insert element: %s", str(e))
            results.append(PlacementResult(success=False, message=str(e)))

    results, succeeded = _commit_or_fail(results, succeeded, model.commit_changes(), "columns")
    logger.info("Placed %d of %d columns", succeeded, len(columns))
    return _to_tool_result(results, len(columns), succeeded, "columns")


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def place_panels(panels: Annotated[list[PanelInput] | None, Field(description="List of wall panels definitions")] = None) -> ToolResult:
    """
    Places multiple wall panels in the Tekla model.

    ## INSTRUCTIONS
    - Use `tekla://element_types` to discover default Tekla classes.
    - Do NOT provide optional fields (`name`, `position`, `part_number`, `assembly_number`) unless explicitly specified by the user.

    ## COORDINATE SYSTEM
    X, Y = horizontal plane, Z = vertical (height, mm). Z+ is up.

    ## EXAMPLES
    ```json
    {
      "panels": [
        {"start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 3000, "y": 0, "z": 0}, "profile": "3000*200", "material": "C30/37", "tekla_class": 1}
      ]
    }
    ```
    """
    if not panels:
        logger.error("place_panels failed: No panels provided")
        raise ValueError("No panels provided")

    model = TeklaModel()
    results: list[PlacementResult] = []
    succeeded = 0

    for i, input_object in enumerate(panels):
        try:
            logger.debug("Placing panel %d/%d: profile=%s, material=%s, class=%d", i + 1, len(panels), input_object.profile, input_object.material, input_object.tekla_class)
            success, result = _place_beam_element(
                input_object,
                lambda p: (p.start_point, p.end_point),
                BeamType.PANEL,
            )
            if success:
                succeeded += 1
            results.append(result)
        except Exception as e:
            logger.exception("Failed to insert element: %s", str(e))
            results.append(PlacementResult(success=False, message=str(e)))

    results, succeeded = _commit_or_fail(results, succeeded, model.commit_changes(), "panels")
    logger.info("Placed %d of %d panels", succeeded, len(panels))
    return _to_tool_result(results, len(panels), succeeded, "panels")


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def place_slabs(slabs: Annotated[list[SlabInput] | None, Field(description="List of slab definitions")] = None) -> ToolResult:
    """
    Places multiple slabs in the Tekla model.

    ## INSTRUCTIONS
    - Use `tekla://element_types` to discover default Tekla classes.
    - Do NOT provide optional fields (`name`, `position`, `part_number`, `assembly_number`) unless explicitly specified by the user.
    - Slabs require at least 3 points to define a contour.

    ## COORDINATE SYSTEM
    X, Y = horizontal plane, Z = vertical (height, mm). Z+ is up.

    ## EXAMPLES
    ```json
    {
      "slabs": [
        {"points": [{"x": 0, "y": 0, "z": 0}, {"x": 5000, "y": 0, "z": 0}, {"x": 5000, "y": 4000, "z": 0}, {"x": 0, "y": 4000, "z": 0}], "profile": "200", "material": "C30/37", "tekla_class": 4}
      ]
    }
    ```
    """
    if not slabs:
        logger.error("place_slabs failed: No slabs provided")
        raise ValueError("No slabs provided")

    model = TeklaModel()
    results: list[PlacementResult] = []
    succeeded = 0

    for i, input_object in enumerate(slabs):
        try:
            logger.debug(
                "Placing slab %d/%d: profile=%s, material=%s, class=%d, points=%d", i + 1, len(slabs), input_object.profile, input_object.material, input_object.tekla_class, len(input_object.points)
            )
            if len(input_object.points) < 3:
                results.append(PlacementResult(success=False, message="Slab requires at least 3 points"))
                continue

            part_number, assembly_number, name = _resolve_numbering_and_name(input_object)

            tekla_obj = TeklaContourPlate.create(
                points=input_object.points,
                profile=input_object.profile,
                material=input_object.material,
                tekla_class=input_object.tekla_class,
                name=name,
                position=input_object.position,
                part_number=part_number,
                assembly_number=assembly_number,
            )
            if tekla_obj is not None:
                succeeded += 1
                results.append(PlacementResult(success=True, guid=tekla_obj.guid))
            else:
                results.append(PlacementResult(success=False, message="Insert() returned false"))
        except Exception as e:
            logger.exception("Failed to insert slab: %s", str(e))
            results.append(PlacementResult(success=False, message=str(e)))

    results, succeeded = _commit_or_fail(results, succeeded, model.commit_changes(), "slabs")
    logger.info("Placed %d of %d slabs", succeeded, len(slabs))
    return _to_tool_result(results, len(slabs), succeeded, "slabs")


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def move_elements(
    dx: Annotated[float, Field(description="Displacement in X direction (mm)")] = 0.0,
    dy: Annotated[float, Field(description="Displacement in Y direction (mm)")] = 0.0,
    dz: Annotated[float, Field(description="Displacement in Z direction (mm)")] = 0.0,
    copy: Annotated[bool, Field(description="When True, creates a copy at the new position and keeps the original in place")] = False,
) -> ToolResult:
    """
    Moves or copies all selected elements by the given displacement vector.

    ## COORDINATE SYSTEM
    X, Y = horizontal plane, Z = vertical (height, mm). Z+ is up.

    ## EXAMPLES
    # Move selected elements 1000 mm in X
    move_elements(dx=1000)

    # Copy selected elements 500 mm diagonally, keeping originals
    move_elements(dx=500, dy=500, copy=True)
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    if selected_objects.GetSize() == 0:
        logger.error("move_elements failed: No elements selected")
        raise ValueError("No objects selected")

    move_vec = Vector(dx, dy, dz)
    results: list[PlacementResult] = []
    succeeded = 0
    failed = 0

    for obj in wrap_model_objects(selected_objects):
        for part in _collect_parts(obj):
            try:
                if copy:
                    Operation.CopyObject(part.model_object, move_vec)
                else:
                    Operation.MoveObject(part.model_object, move_vec)
                succeeded += 1
                results.append(PlacementResult(success=True, guid=part.guid))
            except Exception as e:
                logger.exception("Failed to %s part %s: %s", "copy" if copy else "move", part.guid, str(e))
                results.append(PlacementResult(success=False, message=str(e)))
                failed += 1

    total = succeeded + failed
    commit_success = model.commit_changes()
    if not commit_success:
        logger.error("commit_changes() failed after moving/copying %d elements", succeeded)
        results = [PlacementResult(success=False, message="Commit failed: changes not persisted") for _ in results]
        succeeded = 0
        failed = total

    action = "Copied" if copy else "Moved"
    logger.info("%s %d of %d elements (dx=%.0f dy=%.0f dz=%.0f)", action, succeeded, total, dx, dy, dz)
    return ToolResult(
        structured_content=BatchPlacementResult(
            success=failed == 0 and total > 0 and commit_success,
            total=total,
            succeeded=succeeded,
            failed=total - succeeded,
            results=results,
            message=f"{action} {succeeded} of {total} elements" if commit_success else f"Commit failed: {action} reverted",
        ).model_dump(mode="json", exclude_none=True)
    )


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def place_grid(
    x: Annotated[list[float], Field(description="Absolute X axis coordinates (mm), e.g. [0, 5000, 10000]")],
    y: Annotated[list[float], Field(description="Absolute Y axis coordinates (mm)")],
    z: Annotated[list[float] | None, Field(description="Absolute Z axis coordinates (storey heights, mm)")] = None,
    x_labels: Annotated[list[str] | None, Field(description="Labels for X axis lines")] = None,
    y_labels: Annotated[list[str] | None, Field(description="Labels for Y axis lines")] = None,
    z_labels: Annotated[list[str] | None, Field(description="Labels for Z axis lines")] = None,
    origin: Annotated[PointInput | None, Field(description="Grid origin point (mm). Defaults to (0, 0, 0)")] = None,
    name: Annotated[str | None, Field(description="Grid name")] = None,
) -> ToolResult:
    """
    Places a rectangular grid in the Tekla model.

    ## COORDINATE SYSTEM
    X, Y = horizontal plane, Z = vertical (height, mm). Z+ is up.

    ## EXAMPLES
    # Simple 3 x 2 grid, 5 m spacing
    place_grid(x=[0, 5000, 10000], y=[0, 5000])

    # Named grid with labels and storeys
    place_grid(
        x=[0, 6000, 12000], y=[0, 4000],
        z=[0, 3000, 6000],
        x_labels=["A", "B", "C"], y_labels=["1", "2"],
        z_labels=["+0.000", "+3.000", "+6.000"],
        name="MAIN_GRID",
    )
    """
    if len(x) < 2:
        raise ValueError("At least two X coordinates required")
    if len(y) < 2:
        raise ValueError("At least two Y coordinates required")

    resolved_z = z or []

    grid = Grid()
    if name:
        grid.Name = name
    grid.CoordinateX = format_coordinate_string(x)
    grid.CoordinateY = format_coordinate_string(y)
    grid.CoordinateZ = format_coordinate_string(resolved_z) if resolved_z else ""
    if x_labels:
        grid.LabelX = " ".join(x_labels)
    if y_labels:
        grid.LabelY = " ".join(y_labels)
    if z_labels:
        grid.LabelZ = " ".join(z_labels)

    if origin:
        grid.Origin = Point(origin.x, origin.y, origin.z)

    model = TeklaModel()
    if not grid.Insert():
        raise RuntimeError("Grid.Insert() returned false")

    commit_success = model.commit_changes()
    if not commit_success:
        logger.error("commit_changes() failed after inserting grid")
        raise RuntimeError("Grid insertion failed: commit_changes() returned false")
    guid = grid.Identifier.GUID.ToString()
    logger.info("Placed grid guid=%s (x=%d, y=%d, z=%d lines)", guid, len(x), len(y), len(resolved_z))
    return ToolResult(structured_content={"status": "success", "guid": guid, "name": grid.Name})



@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def delete_selected() -> ToolResult:
    """
    Deletes all currently selected elements in Tekla.
    """
    model = TeklaModel()
    selected = model.get_selected_objects()
    count = selected.GetSize() if selected else 0

    if count == 0:
        logger.error("delete_selected failed: No objects selected")
        raise ValueError("No objects selected")

    deleted = 0
    for obj in selected:
        if obj.Delete():
            deleted += 1

    commit_success = model.commit_changes()
    if not commit_success:
        logger.error("commit_changes() failed after deleting %d objects", deleted)
        deleted = 0
        status = "error"
        message = "Delete failed: commit_changes() returned false"
    elif deleted == count:
        status = "success"
        message = f"Deleted {deleted} of {count} objects"
    else:
        status = "warning"
        message = f"Deleted {deleted} of {count} objects"

    logger.info("Deleted %d of %d objects (commit: %s)", deleted, count, commit_success)
    return ToolResult(
        structured_content={
            "status": status,
            "total_selected": count,
            "total_deleted": deleted,
            "commit_success": commit_success,
            "message": message,
        }
    )


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def create_phase(
    phase_number: Annotated[int, Field(description="Phase number to create (must not already exist in the model)", ge=1)],
    name: Annotated[str | None, Field(description="Optional phase name")] = None,
) -> ToolResult:
    """
    Creates a new phase in the Tekla model.
    """
    model = TeklaModel()
    existing_numbers = {p.PhaseNumber for p in model.get_phases()}
    if phase_number in existing_numbers:
        raise ValueError(f"Phase {phase_number} already exists")

    phase = Phase(phase_number)
    if name is not None:
        phase.PhaseName = name
    if not phase.Insert():
        raise RuntimeError(f"Phase.Insert() returned false for phase {phase_number}")

    commit_success = model.commit_changes()
    if not commit_success:
        logger.error("commit_changes() failed after creating phase %d", phase_number)
        raise RuntimeError("Phase creation failed: commit_changes() returned false")

    logger.info("Created phase %d (name=%s)", phase_number, name)
    return ToolResult(
        structured_content={
            "status": "success",
            "phase_number": phase_number,
            "phase_name": name or "",
        }
    )
