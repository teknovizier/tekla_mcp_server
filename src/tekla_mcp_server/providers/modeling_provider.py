"""
Modeling tools provider for Tekla MCP server.

Provides tools for placing beams, columns, panels and managing elements.
"""

from typing import Annotated
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
    ElementTypeModel,
    NumberingSeries,
)
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model_object import TeklaBeam, TeklaContourPlate
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


modeling_provider = LocalProvider()


def _resolve_numbering_and_name(
    input_object: BeamInput | ColumnInput | PanelInput | SlabInput,
) -> tuple[NumberingSeries | None, NumberingSeries | None, str | None]:
    """Resolve part/assembly numbering and name from input or defaults."""
    part_number: NumberingSeries | None = getattr(input_object, "part_number", None)
    assembly_number: NumberingSeries | None = getattr(input_object, "assembly_number", None)
    name: str | None = getattr(input_object, "name", None)

    if assembly_number is None or part_number is None:
        numbering = ElementTypeModel.get_default_numbering(input_object.tekla_class)
        if numbering:
            if assembly_number is None:
                assembly_number = numbering.get("assembly_number")
            if part_number is None:
                part_number = numbering.get("part_number")

    if name is None:
        name = ElementTypeModel.get_default_name(input_object.tekla_class)

    return part_number, assembly_number, name


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
        return ToolResult(structured_content={"status": "error", "message": "No beams provided"})

    model = TeklaModel()
    results: list[PlacementResult] = []
    succeeded = 0

    for input_object in beams:
        try:
            start, end = input_object.start_point, input_object.end_point
            part_number, assembly_number, name = _resolve_numbering_and_name(input_object)

            tekla_obj = TeklaBeam.create(
                start_point=start,
                end_point=end,
                profile=input_object.profile,
                material=input_object.material,
                tekla_class=input_object.tekla_class,
                name=name,
                position=input_object.position,
                beam_type=BeamType.BEAM,
                start_point_offset=input_object.start_point_offset,
                end_point_offset=input_object.end_point_offset,
                part_number=part_number,
                assembly_number=assembly_number,
            )
            if tekla_obj is not None:
                succeeded += 1
                results.append(PlacementResult(success=True, guid=tekla_obj.guid))
            else:
                results.append(PlacementResult(success=False, message="Insert() returned false"))
        except Exception as e:
            logger.exception("Failed to insert element")
            results.append(PlacementResult(success=False, message=str(e)))

    model.commit_changes()

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
        return ToolResult(structured_content={"status": "error", "message": "No columns provided"})

    model = TeklaModel()
    results: list[PlacementResult] = []
    succeeded = 0

    for input_object in columns:
        try:
            start = input_object.base_point
            end = PointInput(x=input_object.base_point.x, y=input_object.base_point.y, z=input_object.base_point.z + input_object.height)
            part_number, assembly_number, name = _resolve_numbering_and_name(input_object)

            tekla_obj = TeklaBeam.create(
                start_point=start,
                end_point=end,
                profile=input_object.profile,
                material=input_object.material,
                tekla_class=input_object.tekla_class,
                name=name,
                position=input_object.position,
                beam_type=BeamType.COLUMN,
                start_point_offset=input_object.start_point_offset,
                end_point_offset=input_object.end_point_offset,
                part_number=part_number,
                assembly_number=assembly_number,
            )
            if tekla_obj is not None:
                succeeded += 1
                results.append(PlacementResult(success=True, guid=tekla_obj.guid))
            else:
                results.append(PlacementResult(success=False, message="Insert() returned false"))
        except Exception as e:
            logger.exception("Failed to insert element")
            results.append(PlacementResult(success=False, message=str(e)))

    model.commit_changes()

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
        return ToolResult(structured_content={"status": "error", "message": "No panels provided"})

    model = TeklaModel()
    results: list[PlacementResult] = []
    succeeded = 0

    for input_object in panels:
        try:
            start, end = input_object.start_point, input_object.end_point
            part_number, assembly_number, name = _resolve_numbering_and_name(input_object)

            tekla_obj = TeklaBeam.create(
                start_point=start,
                end_point=end,
                profile=input_object.profile,
                material=input_object.material,
                tekla_class=input_object.tekla_class,
                name=name,
                position=input_object.position,
                beam_type=BeamType.PANEL,
                start_point_offset=input_object.start_point_offset,
                end_point_offset=input_object.end_point_offset,
                part_number=part_number,
                assembly_number=assembly_number,
            )
            if tekla_obj is not None:
                succeeded += 1
                results.append(PlacementResult(success=True, guid=tekla_obj.guid))
            else:
                results.append(PlacementResult(success=False, message="Insert() returned false"))
        except Exception as e:
            logger.exception("Failed to insert element")
            results.append(PlacementResult(success=False, message=str(e)))

    model.commit_changes()

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
        return ToolResult(structured_content={"status": "error", "message": "No slabs provided"})

    model = TeklaModel()
    results: list[PlacementResult] = []
    succeeded = 0

    for input_object in slabs:
        try:
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
            logger.exception("Failed to insert slab")
            results.append(PlacementResult(success=False, message=str(e)))

    model.commit_changes()

    return _to_tool_result(results, len(slabs), succeeded, "slabs")


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
        return ToolResult(structured_content={"status": "error", "message": "No objects selected"})

    deleted = 0
    for obj in selected:
        if obj.Delete():
            deleted += 1

    model.commit_changes()

    return ToolResult(
        structured_content={
            "status": "success" if deleted == count else "warning",
            "total_selected": count,
            "total_deleted": deleted,
            "message": f"Deleted {deleted} of {count} objects",
        }
    )
