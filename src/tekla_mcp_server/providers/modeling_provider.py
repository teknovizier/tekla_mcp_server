"""
Modeling tools provider for Tekla MCP server.

Provides tools for placing beams, columns, panels and managing elements.
"""

import math
from typing import Annotated, Any, Callable, TypeVar
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
from tekla_mcp_server.tekla.wrappers.model_object import (
    TeklaModelObject,
    TeklaAssembly,
    TeklaBoltGroup,
    TeklaBooleanPart,
    TeklaPart,
    TeklaBeam,
    TeklaContourPlate,
    TeklaReinforcement,
    TeklaWeld,
    wrap_model_objects,
)
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.loader import Grid, Connection, Operation, Phase, Point, Seam, Vector, ViewHandler
from tekla_mcp_server.tekla.utils import get_active_views


modeling_provider = LocalProvider()

T = TypeVar("T", BeamInput, ColumnInput, PanelInput)

# A grid coordinate in mm. NaN or infinity cannot be written into the grid string
GridCoordinate = Annotated[float, Field(allow_inf_nan=False)]


def _collect_parts(obj: TeklaModelObject) -> list[TeklaModelObject]:
    """
    Return the child Part objects to move/copy for *obj*.

    For an assembly this is the main part, secondaries, single-part-component parts
    and real sub-assembly parts. Parts created by a Seam or Connection - components
    that span two or more parts - are skipped: such a component is associative to all
    its host parts and moves its created parts (e.g. pipes) along when those parts
    move, so displacing them explicitly as well would put them in the wrong place.

    Any other object, such as a part, rebar or bolt group, is returned as it is.

    Args:
        obj: Part, assembly or other model object

    Returns:
        Objects to move or copy
    """
    if not isinstance(obj, TeklaAssembly):
        return [obj]

    parts: list[TeklaModelObject] = []
    for part in obj.get_all_parts():
        # Skip Seam/Connection parts - the component moves them with its host parts.
        if not isinstance(part.model_object.GetFatherComponent(), (Seam, Connection)):
            parts.append(part)
    return parts


def _carrier_ids(obj: TeklaModelObject) -> set[int]:
    """
    Return the IDs of the parts that carry *obj* along when one of them is moved or copied.

    A rebar or cut follows its father part and a weld its secondary part.
    A bolt group follows only when it bolts a single part. A bolt group joining several
    parts stays in place when they are moved one by one, so it has no carrier.

    Args:
        obj: Selected model object

    Returns:
        Part IDs, empty for parts, assemblies and objects that no part carries
    """
    raw = obj.model_object
    if isinstance(obj, (TeklaReinforcement, TeklaBooleanPart)):
        carriers = [raw.Father]
    elif isinstance(obj, TeklaWeld):
        carriers = [raw.SecondaryObject]
    elif isinstance(obj, TeklaBoltGroup):
        bolted = _bolted_ids(raw)
        return bolted if len(bolted) == 1 else set()
    else:
        return set()
    return {c.Identifier.ID for c in carriers if c is not None}


def _bolted_ids(bolt: Any) -> set[int]:
    """
    Return the IDs of all parts a bolt group bolts.

    Args:
        bolt: Tekla `BoltGroup`

    Returns:
        Part IDs
    """
    return {p.Identifier.ID for p in (bolt.PartToBoltTo, bolt.PartToBeBolted, *bolt.OtherPartsToBolt) if p is not None}


def _joint_bolts(parts: list[TeklaModelObject], moved_ids: set[int], handled_ids: set[int]) -> list[Any]:
    """
    Return the bolt groups joining several moved parts that were not moved yet.

    Moving the parts one by one leaves a bolt group that joins them in place, unlike a copy,
    which brings it along. Such a bolt group must therefore be moved itself.

    Args:
        parts: Objects that were moved
        moved_ids: IDs of the parts that were moved
        handled_ids: IDs of the objects already moved or carried, extended with the returned bolt groups

    Returns:
        Tekla `BoltGroup` objects to move
    """
    bolts: list[Any] = []
    for part in parts:
        if not isinstance(part, TeklaPart) or part.id not in moved_ids:
            continue
        enumerator = part.model_object.GetBolts()
        while enumerator.MoveNext():
            bolt = enumerator.Current
            bolted = _bolted_ids(bolt)
            if bolt.Identifier.ID not in handled_ids and len(bolted) > 1 and bolted <= moved_ids:
                handled_ids.add(bolt.Identifier.ID)
                bolts.append(bolt)
    return bolts


def _resolve_numbering_and_name(
    input_object: BeamInput | ColumnInput | PanelInput | SlabInput,
) -> tuple[NumberingSeries | None, NumberingSeries | None, str | None]:
    """
    Resolve part/assembly numbering and name from input or defaults.

    Args:
        input_object: Element input

    Returns:
        Tuple of (part number, assembly number, name)
    """
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
    """
    Place a single beam-type element and return success flag and result.

    Args:
        input_object: Element input
        input_to_points: Maps input to start and end points
        beam_type: Tekla beam type

    Returns:
        Tuple of (success, placement result)
    """
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


def _redraw_active_views() -> bool:
    """
    Redraw the active model views.

    Changes made without a successful commit are in the model but stay hidden until a view is redrawn.

    Returns:
        True if at least one view was redrawn
    """
    redrawn = 0
    try:
        for view in get_active_views():
            if ViewHandler.RedrawView(view):
                redrawn += 1
    except Exception:
        logger.exception("Redrawing the active views failed")
    return redrawn > 0


def _commit_failure_note(commit_success: bool, action_description: str) -> str:
    """
    Show the changes after a failed commit and describe it for the result message.

    Inserted, moved, copied and deleted objects are already changed in the model when the commit
    runs, and a failed commit does not undo them. It only leaves the views showing the old state.
    So the views are redrawn and the per-element results stay as they are. Claiming the changes
    failed would invite a retry that duplicates them.

    Args:
        commit_success: Commit outcome
        action_description: Action text for the log

    Returns:
        Text to append to the message, empty when the commit succeeded
    """
    if commit_success:
        return ""
    logger.error("commit_changes() failed after %s", action_description)
    if _redraw_active_views():
        return ", but commit_changes() failed. The changes are in the model and the view was redrawn to show them, so check them before retrying"
    return ", but commit_changes() failed. The changes are in the model but are not shown until the view is redrawn, so check the model before retrying"


def _to_tool_result(
    results: list[PlacementResult],
    total: int,
    succeeded: int,
    item_type: str,
    commit_success: bool,
) -> ToolResult:
    """
    Convert batch placement results to ToolResult.

    Args:
        results: Placement results
        total: Total element count
        succeeded: Success count
        item_type: Element type for the message
        commit_success: Commit outcome

    Returns:
        Batch placement tool result
    """
    return ToolResult(
        structured_content=BatchPlacementResult(
            success=commit_success and succeeded == total and total > 0,
            total=total,
            succeeded=succeeded,
            failed=total - succeeded,
            results=results,
            message=f"Placed {succeeded} of {total} {item_type}{_commit_failure_note(commit_success, f'placing {succeeded} {item_type}')}",
        ).model_dump(mode="json", exclude_none=True)
    )


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def place_beams(beams: Annotated[list[BeamInput], Field(description="List of beam definitions")] = []) -> ToolResult:
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
        {"start_point": {"x": 0, "y": 0, "z": 0}, "end_point": {"x": 5000, "y": 0, "z": 0}, "profile": "300*600", "material": "C30/37", "tekla_class": 11},
        {"start_point": {"x": 5000, "y": 0, "z": 0}, "end_point": {"x": 10000, "y": 0, "z": 0}, "profile": "300*600", "material": "C30/37", "tekla_class": 11}
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

    commit_success = model.commit_changes()
    logger.info("Placed %d of %d beams", succeeded, len(beams))
    return _to_tool_result(results, len(beams), succeeded, "beams", commit_success)


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def place_columns(columns: Annotated[list[ColumnInput], Field(description="List of column definitions")] = []) -> ToolResult:
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
        {"base_point": {"x": 0, "y": 0, "z": 0}, "height": 3000, "profile": "400*400", "material": "C30/37", "tekla_class": 10},
        {"base_point": {"x": 5000, "y": 0, "z": 0}, "height": 3000, "profile": "400*400", "material": "C30/37", "tekla_class": 10}
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

    commit_success = model.commit_changes()
    logger.info("Placed %d of %d columns", succeeded, len(columns))
    return _to_tool_result(results, len(columns), succeeded, "columns", commit_success)


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def place_panels(panels: Annotated[list[PanelInput], Field(description="List of wall panels definitions")] = []) -> ToolResult:
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
        {"start_point": {"x": 0, "y": 0, "z": 0}, "end_point": {"x": 3000, "y": 0, "z": 0}, "profile": "3000*200", "material": "C30/37", "tekla_class": 1}
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

    commit_success = model.commit_changes()
    logger.info("Placed %d of %d panels", succeeded, len(panels))
    return _to_tool_result(results, len(panels), succeeded, "panels", commit_success)


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def place_slabs(slabs: Annotated[list[SlabInput], Field(description="List of slab definitions")] = []) -> ToolResult:
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

    commit_success = model.commit_changes()
    logger.info("Placed %d of %d slabs", succeeded, len(slabs))
    return _to_tool_result(results, len(slabs), succeeded, "slabs", commit_success)


def _move_or_copy_elements(dx: float, dy: float, dz: float, copy: bool) -> ToolResult:
    """
    Move or copy the selected elements by a displacement.

    Args:
        dx: X displacement
        dy: Y displacement
        dz: Z displacement
        copy: Copy instead of move

    Returns:
        Batch placement tool result

    Raises:
        ValueError: If all displacements are zero
    """
    action = "Copied" if copy else "Moved"
    verb = "copying" if copy else "moving"
    op = "copy" if copy else "move"
    if dx == 0.0 and dy == 0.0 and dz == 0.0:
        logger.error("%s_elements failed: all displacements are zero", op)
        raise ValueError("At least one displacement (dx, dy, dz) must be non-zero")

    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    move_vec = Vector(dx, dy, dz)
    results: list[PlacementResult] = []
    succeeded = 0
    # A part reached through several selected objects (e.g. a part selected together with
    # its assembly) must be moved or copied only once, otherwise it is displaced twice
    handled_ids: set[int] = set()
    objects = [item for obj in wrap_model_objects(selected_objects) for item in _collect_parts(obj)]
    # A rebar, cut, weld or bolt group whose carrier part is moved too goes along with it,
    # so moving it as well would displace it twice. Collected first, as a child may come before its father
    part_ids = {item.id for item in objects if isinstance(item, TeklaPart)}
    carried = 0
    moved_ids: set[int] = set()

    for part in objects:
        if part.id in handled_ids:
            continue
        handled_ids.add(part.id)
        if _carrier_ids(part) & part_ids:
            carried += 1
            continue
        try:
            if copy:
                Operation.CopyObject(part.model_object, move_vec)
            else:
                Operation.MoveObject(part.model_object, move_vec)
            succeeded += 1
            moved_ids.add(part.id)
            results.append(PlacementResult(success=True, guid=part.guid))
        except Exception as e:
            logger.exception("Failed to %s part %s: %s", op, part.guid, str(e))
            results.append(PlacementResult(success=False, message=str(e)))

    if not copy:
        for bolt in _joint_bolts(objects, moved_ids, handled_ids):
            guid = bolt.Identifier.GUID.ToString()
            try:
                Operation.MoveObject(bolt, move_vec)
                carried += 1
            except Exception as e:
                logger.exception("Failed to move bolt group %s joining moved parts: %s", guid, str(e))
                results.append(PlacementResult(success=False, guid=guid, message=f"Bolt group joining moved parts was not moved: {e}"))

    total = len(results)
    commit_success = model.commit_changes()
    logger.info("%s %d of %d elements, %d carried along by their parts (dx=%.0f dy=%.0f dz=%.0f)", action, succeeded, total, carried, dx, dy, dz)
    carried_note = f", {carried} more went along with their parts" if carried else ""
    return ToolResult(
        structured_content=BatchPlacementResult(
            success=commit_success and succeeded == total and total > 0,
            total=total,
            succeeded=succeeded,
            failed=total - succeeded,
            results=results,
            message=f"{action} {succeeded} of {total} elements{carried_note}{_commit_failure_note(commit_success, f'{verb} {succeeded} elements')}",
        ).model_dump(mode="json", exclude_none=True)
    )


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def move_elements(
    dx: Annotated[float, Field(allow_inf_nan=False, description="Displacement in X direction (mm)")] = 0.0,
    dy: Annotated[float, Field(allow_inf_nan=False, description="Displacement in Y direction (mm)")] = 0.0,
    dz: Annotated[float, Field(allow_inf_nan=False, description="Displacement in Z direction (mm)")] = 0.0,
) -> ToolResult:
    """
    Moves all selected elements by a displacement offset relative to their current positions.

    A rebar, cut, weld or bolt group selected together with the part that carries it is moved
    once, along with that part. A bolt group joining moved parts is moved with them even when
    it is not selected.

    ## COORDINATE SYSTEM
    X, Y = horizontal plane, Z = vertical (height, mm). Z+ is up.
    dx, dy, dz are relative offsets - not absolute coordinates.

    ## EXAMPLES
    # Move selected elements 1000 mm in X
    move_elements(dx=1000)
    """
    return _move_or_copy_elements(dx, dy, dz, copy=False)


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def copy_elements(
    dx: Annotated[float, Field(allow_inf_nan=False, description="Displacement in X direction (mm)")] = 0.0,
    dy: Annotated[float, Field(allow_inf_nan=False, description="Displacement in Y direction (mm)")] = 0.0,
    dz: Annotated[float, Field(allow_inf_nan=False, description="Displacement in Z direction (mm)")] = 0.0,
) -> ToolResult:
    """
    Copies all selected elements by a displacement offset relative to their current positions.

    A rebar, cut, weld or bolt group selected together with the part that carries it is copied
    once, along with that part.

    ## COORDINATE SYSTEM
    X, Y = horizontal plane, Z = vertical (height, mm). Z+ is up.
    dx, dy, dz are relative offsets - not absolute coordinates.

    ## EXAMPLES
    # Copy selected elements 500 mm diagonally
    copy_elements(dx=500, dy=500)
    """
    return _move_or_copy_elements(dx, dy, dz, copy=True)


def _check_grid_axis(axis: str, coordinates: list[float], labels: list[str]) -> None:
    """
    Check the coordinates and labels of one grid axis.

    The coordinates may come in any order, Tekla places each line at its own coordinate.

    Args:
        axis: Axis name for the error message
        coordinates: Absolute coordinates
        labels: Line labels, empty for Tekla's default labels

    Raises:
        ValueError: If there are fewer than two coordinates, a repeated coordinate, a label count that
            does not match, or a label with whitespace
    """
    if len(coordinates) < 2:
        raise ValueError(f"At least two {axis} coordinates required")
    if not all(math.isfinite(c) for c in coordinates):
        raise ValueError(f"{axis} coordinates must be finite numbers, got {coordinates}")
    repeated = sorted({c for c in coordinates if coordinates.count(c) > 1})
    if repeated:
        raise ValueError(f"{axis} coordinates {repeated} are given more than once")
    if labels and len(labels) != len(coordinates):
        raise ValueError(f"{len(labels)} {axis} labels given for {len(coordinates)} {axis} coordinates, give one label per coordinate")
    # Tekla stores the labels as one space separated string, so a space would split a label in two
    spaced = [label for label in labels if not label.strip() or any(c.isspace() for c in label)]
    if spaced:
        raise ValueError(f"{axis} labels {spaced} are empty or contain whitespace, which would shift every later label")


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def place_grid(
    x: Annotated[list[GridCoordinate], Field(description="Absolute X axis coordinates (mm), e.g. [0, 5000, 10000]. At least two, each once")],
    y: Annotated[list[GridCoordinate], Field(description="Absolute Y axis coordinates (mm). At least two, each once")],
    z: Annotated[list[GridCoordinate], Field(description="Absolute Z levels (mm), e.g. [0, 3000]. At least two, each once, Tekla does not show a grid with fewer")],
    x_labels: Annotated[list[str], Field(description="Labels for X axis lines, one per coordinate in the same order, without spaces")] = [],
    y_labels: Annotated[list[str], Field(description="Labels for Y axis lines, one per coordinate in the same order, without spaces")] = [],
    z_labels: Annotated[list[str], Field(description="Labels for Z levels, one per coordinate in the same order, without spaces")] = [],
    origin: Annotated[PointInput | None, Field(description="Grid origin point (mm). Defaults to (0, 0, 0)")] = None,
    name: Annotated[str | None, Field(description="Grid name")] = None,
) -> ToolResult:
    """
    Places a rectangular grid in the Tekla model.

    ## COORDINATE SYSTEM
    X, Y = horizontal plane, Z = vertical (height, mm). Z+ is up.

    ## EXAMPLES
    # Simple 3 x 2 grid, 5 m spacing, one 3 m storey
    place_grid(x=[0, 5000, 10000], y=[0, 5000], z=[0, 3000])

    # Named grid with labels and storeys
    place_grid(
        x=[0, 6000, 12000], y=[0, 4000],
        z=[0, 3000, 6000],
        x_labels=["A", "B", "C"], y_labels=["1", "2"],
        z_labels=["+0.000", "+3.000", "+6.000"],
        name="MAIN_GRID",
    )
    """
    for axis, coordinates, labels in (("X", x, x_labels), ("Y", y, y_labels), ("Z", z, z_labels)):
        _check_grid_axis(axis, coordinates, labels)

    grid = Grid()
    if name:
        grid.Name = name
    grid.CoordinateX = format_coordinate_string(x)
    grid.CoordinateY = format_coordinate_string(y)
    grid.CoordinateZ = format_coordinate_string(z)
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
    logger.info("Placed grid guid=%s (x=%d, y=%d, z=%d lines)", guid, len(x), len(y), len(z))
    return ToolResult(structured_content={"status": "success", "guid": guid, "name": grid.Name})


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def delete_elements() -> ToolResult:
    """
    Deletes all currently selected objects, including cut parts, cut planes and fittings.
    """
    model = TeklaModel()
    objects = list(model.get_selected_objects())
    count = len(objects)

    deleted = 0
    failed_count = 0
    for obj in objects:
        # An attached object listed after its father part is already gone with it, which still counts as deleted
        if obj.Delete() or model.model.SelectModelObject(obj.Identifier) is None:
            deleted += 1
        else:
            failed_count += 1
            logger.warning("Failed to delete %s (%s)", type(obj).__name__, obj.Identifier.GUID)

    commit_success: bool | None = None
    if deleted:
        commit_success = model.commit_changes()

    if not deleted:
        status = "error"
        message = f"None of the {count} objects could be deleted"
    elif not commit_success:
        status = "error"
        message = f"Deleted {deleted} of {count} objects{_commit_failure_note(False, f'deleting {deleted} objects')}"
    elif failed_count:
        status = "partial"
        message = f"Deleted {deleted} of {count} objects"
    else:
        status = "success"
        message = f"Deleted {deleted} of {count} objects"

    logger.info("Deleted %d of %d objects (commit: %s)", deleted, count, commit_success)
    result: dict[str, Any] = {
        "status": status,
        "total_selected": count,
        "total_deleted": deleted,
        "failed_count": failed_count,
        "message": message,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@modeling_provider.tool(tags={"modeling"}, annotations={"readOnlyHint": False, "destructiveHint": False})
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
