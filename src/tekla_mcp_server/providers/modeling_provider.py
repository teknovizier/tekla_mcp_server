"""
Modeling tools provider for Tekla MCP server.

Provides tools for placing beams, columns, panels and managing elements.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    BeamInput,
    ColumnInput,
    PanelInput,
    BeamType,
    PlacementResult,
    BatchPlacementResult,
    PointInput,
    ElementTypeModel,
)
from tekla_mcp_server.utils import log_mcp_tool_call
from tekla_mcp_server.tekla.wrappers.beam import TeklaBeam
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


modeling_provider = LocalProvider()


@modeling_provider.tool()
@log_mcp_tool_call
def place_beams(beams: list[BeamInput] | None = None) -> dict[str, Any]:
    """
    Places multiple beams in the Tekla model.

    ## INPUT
    - `beams` [Required]: List of beam definitions, each containing:
        - `start` [Required]: Start point as {x, y, z}
        - `end` [Required]: End point as {x, y, z}
        - `profile` [Required]: Profile name (e.g., "300*600", "HEA200")
        - `material` [Required]: Material grade (e.g., "C30/37", "S235JR")
        - `tekla_class` [Required]: Tekla class number (e.g., 11, 100)
          Use tekla://filters/view to discover valid classes.
        - `name` [Optional]: Element name
          Only include this field if the user explicitly specifies a name.
        - `position` [Optional]: Position settings with keys:
            - `plane`: "LEFT", "MIDDLE", "RIGHT" (default: "MIDDLE")
            - `plane_offset`: Offset in mm along plane axis
            - `depth`: "FRONT", "MIDDLE", "BEHIND" (default: "MIDDLE")
            - `depth_offset`: Offset in mm along depth axis
            - `rotation`: "FRONT", "TOP", "BACK", "BELOW" (default: "FRONT")
            - `rotation_offset`: Rotation offset in degrees
        - `part_number` [Optional]: Part numbering as {prefix, start_number} (e.g., {"prefix": "SB", "start_number": 1})
        - `assembly_number` [Optional]: Assembly numbering as {prefix, start_number} (e.g., {"prefix": "SBA", "start_number": 1})
          Do not provide these unless explicitly requested by the user.
          If omitted, they will be assigned automatically.

    ## COORDINATES
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
        return {"status": "error", "message": "No beams provided"}

    model = TeklaModel()
    results = []
    succeeded = 0

    for input_obj in beams:
        try:
            start, end = input_obj.start, input_obj.end

            part_number = input_obj.part_number
            assembly_number = input_obj.assembly_number
            name = input_obj.name

            if assembly_number is None or part_number is None:
                numbering = ElementTypeModel.get_default_numbering(input_obj.tekla_class)
                if numbering:
                    if assembly_number is None:
                        assembly_number = numbering.get("assembly_number")
                    if part_number is None:
                        part_number = numbering.get("part_number")

            if name is None:
                name = ElementTypeModel.get_default_name(input_obj.tekla_class)

            tekla_obj = TeklaBeam.create(
                start=start,
                end=end,
                profile=input_obj.profile,
                material=input_obj.material,
                tekla_class=input_obj.tekla_class,
                name=name,
                position=input_obj.position,
                beam_type=BeamType.BEAM,
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

    return BatchPlacementResult(
        success=succeeded == len(beams),
        total=len(beams),
        succeeded=succeeded,
        failed=len(beams) - succeeded,
        results=results,
        message=f"Placed {succeeded} of {len(beams)} beams",
    ).model_dump(mode="json", exclude_none=True)


@modeling_provider.tool()
@log_mcp_tool_call
def place_columns(columns: list[ColumnInput] | None = None) -> dict[str, Any]:
    """
    Places multiple columns (vertical beams) in the Tekla model.

    ## INPUT
    - `columns` [Required]: List of column definitions, each containing:
        - `base` [Required]: Base point as {x, y, z}
        - `height` [Required]: Column height in mm (must be > 0)
        - `profile` [Required]: Profile name (e.g., "300*300", "HEA300")
        - `material` [Required]: Material grade (e.g., "C30/37", "S235JR")
        - `tekla_class` [Required]: Tekla class number (e.g., 10, 101)
          Use tekla://filters/view to discover valid classes.
        - `name` [Optional]: Element name
          Only include this field if the user explicitly specifies a name.
        - `position` [Optional]: Position settings with keys:
            - `plane`: "LEFT", "MIDDLE", "RIGHT" (default: "MIDDLE")
            - `plane_offset`: Offset in mm along plane axis
            - `depth`: "FRONT", "MIDDLE", "BEHIND" (default: "MIDDLE")
            - `depth_offset`: Offset in mm along depth axis
            - `rotation`: "FRONT", "TOP", "BACK", "BOTTOM" (default: "FRONT")
            - `rotation_offset`: Rotation offset in degrees
        - `part_number` [Optional]: Part numbering as {prefix, start_number}
        - `assembly_number` [Optional]: Assembly numbering as {prefix, start_number}
          Do not provide these unless explicitly requested by the user.
          If omitted, they will be assigned automatically.

    ## COORDINATES
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
        return {"status": "error", "message": "No columns provided"}

    model = TeklaModel()
    results = []
    succeeded = 0

    for input_obj in columns:
        try:
            start = input_obj.base
            end = PointInput(x=input_obj.base.x, y=input_obj.base.y, z=input_obj.base.z + input_obj.height)

            part_number = input_obj.part_number
            assembly_number = input_obj.assembly_number
            name = input_obj.name

            if assembly_number is None or part_number is None:
                numbering = ElementTypeModel.get_default_numbering(input_obj.tekla_class)
                if numbering:
                    if assembly_number is None:
                        assembly_number = numbering.get("assembly_number")
                    if part_number is None:
                        part_number = numbering.get("part_number")

            if name is None:
                name = ElementTypeModel.get_default_name(input_obj.tekla_class)

            tekla_obj = TeklaBeam.create(
                start=start,
                end=end,
                profile=input_obj.profile,
                material=input_obj.material,
                tekla_class=input_obj.tekla_class,
                name=name,
                position=input_obj.position,
                beam_type=BeamType.COLUMN,
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

    return BatchPlacementResult(
        success=succeeded == len(columns),
        total=len(columns),
        succeeded=succeeded,
        failed=len(columns) - succeeded,
        results=results,
        message=f"Placed {succeeded} of {len(columns)} columns",
    ).model_dump(mode="json", exclude_none=True)


@modeling_provider.tool()
@log_mcp_tool_call
def place_panels(panels: list[PanelInput] | None = None) -> dict[str, Any]:
    """
    Places multiple wall panels in the Tekla model.

    ## INPUT
    - `panels` [Required]: List of panel definitions, each containing:
        - `start` [Required]: Start point as {x, y, z}
        - `end` [Required]: End point as {x, y, z}
        - `profile` [Required]: Profile name (e.g., "3000*200")
        - `material` [Required]: Material grade (e.g., "C30/37")
        - `tekla_class` [Required]: Tekla class number (e.g., 1)
          Use tekla://filters/view to discover valid classes.
        - `name` [Optional]: Element name
          Only include this field if the user explicitly specifies a name.
        - `position` [Optional]: Position settings with keys:
            - `plane`: "LEFT", "MIDDLE", "RIGHT" (default: "MIDDLE")
            - `plane_offset`: Offset in mm along plane axis
            - `depth`: "FRONT", "MIDDLE", "BEHIND" (default: "MIDDLE")
            - `depth_offset`: Offset in mm along depth axis
            - `rotation`: "FRONT", "TOP", "BACK", "BOTTOM" (default: "FRONT")
            - `rotation_offset`: Rotation offset in degrees
        - `part_number` [Optional]: Part numbering as {prefix, start_number}
        - `assembly_number` [Optional]: Assembly numbering as {prefix, start_number}
          Do not provide these unless explicitly requested by the user.
          If omitted, they will be assigned automatically.

    ## COORDINATES
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
        return {"status": "error", "message": "No panels provided"}

    model = TeklaModel()
    results = []
    succeeded = 0

    for input_obj in panels:
        try:
            start, end = input_obj.start, input_obj.end

            part_number = input_obj.part_number
            assembly_number = input_obj.assembly_number
            name = input_obj.name

            if assembly_number is None or part_number is None:
                numbering = ElementTypeModel.get_default_numbering(input_obj.tekla_class)
                if numbering:
                    if assembly_number is None:
                        assembly_number = numbering.get("assembly_number")
                    if part_number is None:
                        part_number = numbering.get("part_number")

            if name is None:
                name = ElementTypeModel.get_default_name(input_obj.tekla_class)

            tekla_obj = TeklaBeam.create(
                start=start,
                end=end,
                profile=input_obj.profile,
                material=input_obj.material,
                tekla_class=input_obj.tekla_class,
                name=name,
                position=input_obj.position,
                beam_type=BeamType.PANEL,
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

    return BatchPlacementResult(
        success=succeeded == len(panels),
        total=len(panels),
        succeeded=succeeded,
        failed=len(panels) - succeeded,
        results=results,
        message=f"Placed {succeeded} of {len(panels)} panels",
    ).model_dump(mode="json", exclude_none=True)


@modeling_provider.tool()
@log_mcp_tool_call
def delete_selected() -> dict[str, Any]:
    """
    Deletes all currently selected elements in Tekla.

    ## INPUT
    - No additional parameters required.
    """
    model = TeklaModel()
    selected = model.get_selected_objects()
    count = selected.GetSize() if selected else 0

    if count == 0:
        return {"status": "error", "message": "No objects selected"}

    deleted = 0
    for obj in selected:
        if obj.Delete():
            deleted += 1

    model.commit_changes()

    return {
        "status": "success" if deleted == count else "warning",
        "total_selected": count,
        "total_deleted": deleted,
        "message": f"Deleted {deleted} of {count} objects",
    }
