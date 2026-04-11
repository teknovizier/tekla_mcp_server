"""
Placement tools for Tekla model operations.

Provides functions for placing beams, columns, and panels.
"""

from typing import Any, Callable

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    BeamType,
    BeamInput,
    ColumnInput,
    PanelInput,
    PlacementResult,
    BatchPlacementResult,
    PointInput,
    get_default_numbering_for_class,
    get_default_name_for_class,
)
from tekla_mcp_server.tekla.wrappers.beam import TeklaBeam
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.utils import log_function_call


def _place_elements(
    inputs: list[Any],
    element_type: BeamType,
    get_geometry: Callable[[Any], tuple[PointInput, PointInput]],
) -> dict[str, Any]:
    """Helper for placing elements in Tekla model."""
    model = TeklaModel()
    results = []
    succeeded = 0

    for input_obj in inputs:
        try:
            start, end = get_geometry(input_obj)

            part_number = input_obj.part_number
            assembly_number = input_obj.assembly_number
            name = input_obj.name

            if assembly_number is None or part_number is None:
                numbering = get_default_numbering_for_class(input_obj.tekla_class)
                if numbering:
                    if assembly_number is None:
                        assembly_number = numbering.get("assembly_number")
                    if part_number is None:
                        part_number = numbering.get("part_number")

            if name is None:
                name = get_default_name_for_class(input_obj.tekla_class)

            tekla_obj = TeklaBeam.create(
                start=start,
                end=end,
                profile=input_obj.profile,
                material=input_obj.material,
                tekla_class=input_obj.tekla_class,
                name=name,
                position=input_obj.position,
                beam_type=element_type,
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
        success=succeeded == len(inputs),
        total=len(inputs),
        succeeded=succeeded,
        failed=len(inputs) - succeeded,
        results=results,
        message=f"Placed {succeeded} of {len(inputs)} {element_type.value.lower()}s",
    ).model_dump(mode="json")


@log_function_call
def tool_place_beams(beams: list[BeamInput]) -> dict[str, Any]:
    """Place multiple beams in the Tekla model."""
    return _place_elements(beams, BeamType.BEAM, lambda b: (b.start, b.end))


@log_function_call
def tool_place_columns(columns: list[ColumnInput]) -> dict[str, Any]:
    """Place multiple columns (vertical beams) in the Tekla model."""
    return _place_elements(columns, BeamType.COLUMN, lambda c: (c.base, PointInput(x=c.base.x, y=c.base.y, z=c.base.z + c.height)))


@log_function_call
def tool_place_panels(panels: list[PanelInput]) -> dict[str, Any]:
    """Place multiple wall panels in the Tekla model."""
    return _place_elements(panels, BeamType.PANEL, lambda p: (p.start, p.end))


@log_function_call
def tool_delete_selected() -> dict[str, Any]:
    """Delete all currently selected objects in Tekla."""
    model = TeklaModel()
    selected = model.get_selected_objects()
    count = selected.GetSize()

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
