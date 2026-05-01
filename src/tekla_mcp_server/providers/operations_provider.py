"""
Operations tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Annotated
from pydantic import Field

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult

from tekla_mcp_server.config import get_config, get_tolerance
from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects, TeklaAssembly, TeklaPart
from tekla_mcp_server.tekla.loader import (
    Operation,
    Point,
    ModelObjectSelector,
    ModelObjectVisualization,
    Color,
)
from tekla_mcp_server.tekla.utils import iterate_boolean_parts, collect_children


operations_provider = LocalProvider()


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def cut_elements_with_zero_class_parts(delete_cutting_parts: Annotated[bool, Field(description="Remove cutting parts after cuts are applied")] = False) -> ToolResult:
    """
    Performs boolean cuts on selected model objects using parts in class 0.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    processed_elements = 0
    performed_cuts = 0
    objects_to_select = model.get_objects_by_class(0)
    cutters = list(wrap_model_objects(objects_to_select))
    logger.debug("Processing %d selected objects with %d cutters", selected_objects.GetSize(), len(cutters))
    if cutters:
        for selected_object in wrap_model_objects(selected_objects):
            element_had_cut = False
            for cutter in cutters:
                if selected_object.add_cut(cutter, delete_cutting_parts):
                    performed_cuts += 1
                    element_had_cut = True
            if element_had_cut:
                processed_elements += 1
    if performed_cuts:
        model.commit_changes()
        logger.info("Performed %s cuts on %s elements", performed_cuts, processed_elements)

    if not performed_cuts:
        logger.warning("cut_elements_with_zero_class_parts failed: No cuts performed")

    return ToolResult(
        structured_content={
            "status": "success" if performed_cuts else "warning",
            "selected_elements": selected_objects.GetSize(),
            "processed_elements": processed_elements,
            "performed_cuts": performed_cuts,
        }
    )


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def convert_cut_parts_to_real_parts() -> ToolResult:
    """
    Finds boolean parts and inserts them as real model objects.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    processed_elements = 0
    inserted_booleans = 0
    for selected_object in selected_objects:
        for boolean_part in iterate_boolean_parts(selected_object):
            if boolean_part.OperativePart.Insert():
                inserted_booleans += 1
        processed_elements += 1
    if inserted_booleans > 0:
        model.commit_changes()
        logger.info("Inserted %s boolean parts as real parts", inserted_booleans)

    if not inserted_booleans:
        logger.warning("convert_cut_parts_to_real_parts failed: No boolean parts converted")

    return ToolResult(
        structured_content={
            "status": "success" if inserted_booleans else "warning",
            "selected_elements": selected_objects.GetSize(),
            "processed_elements": processed_elements,
            "converted_booleans": inserted_booleans,
        }
    )


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def run_macro(macro_name: Annotated[str, Field(description="Name of the macro file to run (e.g., 'MyMacro.cs'")]) -> ToolResult:
    """
    Runs a Tekla macro with the specified name.

    ## AVAILABLE MACROS
    Use the `macro://list` resource to get a list of available macros.
    """

    if Operation.IsMacroRunning():
        logger.error("Cannot run macro '%s': Tekla is busy running another macro", macro_name)
        return ToolResult(
            structured_content={
                "status": "error",
                "message": "Tekla is busy running another macro",
            }
        )

    result = Operation.RunMacro(macro_name)

    if not result:
        logger.error("run_macro failed: Macro '%s' returned false", macro_name)
    else:
        logger.info("Ran macro '%s'", macro_name)

    return ToolResult(
        structured_content={
            "status": "success" if result else "error",
            "macro_name": macro_name,
        }
    )


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def check_for_orphaned_embeds() -> ToolResult:
    """
    Check for embedded details not attached to selected elements.
    Returns orphaned details and colors them red.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    _tolerance = get_tolerance()

    # Collect GUIDs of selected elements AND their parent assemblies for matching
    selected_guids: set[str] = set()
    min_point: Point | None = None
    max_point: Point | None = None

    for obj in wrap_model_objects(selected_objects):
        selected_guids.add(obj.guid)

        # If selected object is a Part, also add its parent assembly GUID
        # This allows checking attachment when selecting a part vs assembly
        if isinstance(obj, TeklaPart):
            parent_assembly = obj.model_object.GetAssembly()
            if parent_assembly:
                selected_guids.add(parent_assembly.Identifier.GUID.ToString())

        # Compute horizontal bounding box from selected elements
        aabb = obj.bounding_box
        if aabb:
            if min_point is None:
                min_point = Point(aabb.min_x, aabb.min_y, aabb.min_z)
                max_point = Point(aabb.max_x, aabb.max_y, aabb.max_z)
            else:
                assert min_point is not None and max_point is not None
                min_point.X = min(min_point.X, aabb.min_x)
                min_point.Y = min(min_point.Y, aabb.min_y)
                min_point.Z = min(min_point.Z, aabb.min_z)
                max_point.X = max(max_point.X, aabb.max_x)
                max_point.Y = max(max_point.Y, aabb.max_y)
                max_point.Z = max(max_point.Z, aabb.max_z)

    # No valid bounding box found: selected objects may lack geometry
    if min_point is None or max_point is None:
        logger.warning("Cannot compute bounding box: selected objects may not have valid geometry (selected: %d)", selected_objects.GetSize())
        return ToolResult(
            structured_content={
                "status": "error",
                "message": "Cannot compute bounding box: selected objects may not have valid geometry",
                "selected_elements": selected_objects.GetSize(),
            }
        )

    min_point.X -= _tolerance
    min_point.Y -= _tolerance
    min_point.Z -= _tolerance
    max_point.X += _tolerance
    max_point.Y += _tolerance
    max_point.Z += _tolerance

    selector = ModelObjectSelector()
    candidates = selector.GetObjectsByBoundingBox(min_point, max_point)

    logger.debug("Found %d candidates in bounding box", candidates.GetSize())

    orphaned_elements: list[dict] = []
    orphaned_guids: set[str] = set()
    evaluated_count = 0

    def _get_embedded_classes() -> list[int]:
        """Get all tekla_classes from MATERIAL_EMBEDDED in element_types.json."""
        embedded = get_config().element_types.get("MATERIAL_EMBEDDED", {})
        all_classes: list[int] = []
        for type_config in embedded.values():
            all_classes.extend(type_config.get("tekla_classes", []))
        return all_classes

    EMBEDDED_DETAILS_CLASSES = _get_embedded_classes()

    # Filter candidates to incast detail classes and check attachment
    for candidate in wrap_model_objects(candidates):
        part_class: int | None = None
        part_name: str = ""
        part_position: str = ""

        # Get class from assembly main part or part directly
        if isinstance(candidate, TeklaAssembly):
            main = candidate.main_part
            part_class = int(main.tekla_class)
            part_name = main.name
            part_position = main.position
        elif isinstance(candidate, TeklaPart):
            part_class = int(candidate.tekla_class)
            part_name = candidate.name
            part_position = candidate.position
        else:
            # Skip non-part/assembly objects
            continue

        # Filter to embedded detail classes only
        if part_class not in EMBEDDED_DETAILS_CLASSES:
            continue

        logger.debug("Evaluating embedded detail: %s (class: %d)", part_name, part_class)
        evaluated_count += 1

        # Check if candidate's assembly is attached to selected assembly
        candidate_assembly = candidate.model_object.GetAssembly()
        if not candidate_assembly:
            # Has no assembly at all - definitely orphaned
            orphaned_elements.append(
                {
                    "guid": candidate.guid,
                    "name": part_name,
                    "position": part_position,
                    "class": part_class,
                }
            )
            orphaned_guids.add(candidate.guid)
            continue

        parent = candidate_assembly.GetAssembly()
        if parent:
            parent_guid = parent.Identifier.GUID.ToString()
            # Orphaned if parent assembly is not one of the selected assemblies
            if parent_guid not in selected_guids:
                orphaned_elements.append(
                    {
                        "guid": candidate.guid,
                        "name": part_name,
                        "position": part_position,
                        "class": part_class,
                    }
                )
                orphaned_guids.add(candidate.guid)
        else:
            # Has assembly but no parent assembly - definitely orphaned
            orphaned_elements.append(
                {
                    "guid": candidate.guid,
                    "name": part_name,
                    "position": part_position,
                    "class": part_class,
                }
            )
            orphaned_guids.add(candidate.guid)

    # Color orphaned elements red for visibility
    if orphaned_guids:
        logger.debug("Coloring %d orphaned elements red for visibility", len(orphaned_guids))
        orphaned_objects = model.get_objects_by_guid(list(orphaned_guids))
        tekla_list = collect_children(orphaned_objects)
        color_red = Color(1.0, 0.0, 0.0)
        ModelObjectVisualization.SetTemporaryState(tekla_list, color_red)

    logger.info("Finished check for orphaned embedding details: selected=%d, evaluated=%d, orphaned=%d", selected_objects.GetSize(), evaluated_count, len(orphaned_elements))

    return ToolResult(
        structured_content={
            "status": "success" if not orphaned_elements else "warning",
            "selected_elements": selected_objects.GetSize(),
            "embeds_evaluated": evaluated_count,
            "orphaned_embeds_found": len(orphaned_elements),
            "orphaned_embeds": orphaned_elements,
        }
    )
