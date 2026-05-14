"""
Operations tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Annotated, Literal
from pydantic import Field

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult

from tekla_mcp_server.config import get_config, get_tolerance
from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects, TeklaAssembly, TeklaPart, TeklaReinforcement
from tekla_mcp_server.tekla.loader import Operation, Point, ModelObjectSelector
from tekla_mcp_server.tekla.utils import iterate_boolean_parts


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
def check_for_orphans(mode: Annotated[Literal["embeds", "rebars"], Field(description="Check mode: embeds or rebars")]) -> ToolResult:
    """
    Check for embedded details or reinforcement bars not attached to selected elements.
    Returns orphaned objects.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    tolerance = get_tolerance()

    def _get_tekla_classes(material_key: str) -> set[int]:
        """Get all tekla_classes for a material group."""
        material = get_config().element_types.get(material_key, {})

        return {
            tekla_class
            for type_config in material.values()
            for tekla_class in type_config.get("tekla_classes", [])
        }

    EMBEDDED_DETAILS_CLASSES = _get_tekla_classes("MATERIAL_EMBEDDED")
    REINFORCEMENT_CLASSES = _get_tekla_classes("MATERIAL_REINFORCEMENT")

    def _build_orphaned_dict(guid: str, name: str, position: str, tekla_class: int) -> dict:
        return {"guid": guid, "name": name, "position": position, "class": tekla_class}

    def _get_reinforcement_guids(element: TeklaAssembly) -> set[str]:
        guids: set[str] = set()

        reinfs = element.main_part.model_object.GetReinforcements()
        for rebar in wrap_model_objects(reinfs):
            if rebar:
                guids.add(rebar.guid)

        for sec in element.model_object.GetSecondaries():
            sec_reinfs = sec.GetReinforcements()
            for rebar in wrap_model_objects(sec_reinfs):
                if rebar:
                    guids.add(rebar.guid)

        return guids

    def _get_candidates_in_bounding_box(element: TeklaAssembly) -> list:
        aabb = element.bounding_box
        if not aabb:
            return []
        min_point = Point(aabb.min_x - tolerance, aabb.min_y - tolerance, aabb.min_z - tolerance)
        max_point = Point(aabb.max_x + tolerance, aabb.max_y + tolerance, aabb.max_z + tolerance)
        selector = ModelObjectSelector()
        return wrap_model_objects(selector.GetObjectsByBoundingBox(min_point, max_point))

    # Check bounding box of a single element for orphaned embeds
    def _check_element_bounding_box_embeds(element: TeklaAssembly, target_assembly_guids: set[str]) -> tuple[list[dict], int]:
        candidates = _get_candidates_in_bounding_box(element)
        if not candidates:
            return [], 0

        orphaned: list[dict] = []
        evaluated = 0

        # Filter candidates to incast detail classes and check attachment
        for candidate in candidates:
            part_class: int | None = None
            part_name: str = ""
            part_position: str = ""

            # Get class from assembly main part or part directly
            if isinstance(candidate, TeklaAssembly):
                main = candidate.main_part
                if not main:
                    continue
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

            evaluated += 1
            logger.debug("Evaluating embedded detail: %s (class: %d)", part_name, part_class)

            # Check if candidate's assembly is attached to target assembly
            candidate_assembly = candidate.model_object.GetAssembly()
            if not candidate_assembly:
                orphaned.append(_build_orphaned_dict(candidate.guid, part_name, part_position, part_class))
                continue

            parent = candidate_assembly.GetAssembly()
            if parent:
                parent_guid = parent.Identifier.GUID.ToString()
                if parent_guid not in target_assembly_guids:
                    orphaned.append(_build_orphaned_dict(candidate.guid, part_name, part_position, part_class))
            else:
                orphaned.append(_build_orphaned_dict(candidate.guid, part_name, part_position, part_class))

        return orphaned, evaluated

    # Check bounding box of a single element for orphaned rebars
    def _check_element_bounding_box_rebars(element: TeklaAssembly, element_reinforcement_guids: set[str]) -> tuple[list[dict], int]:
        candidates = _get_candidates_in_bounding_box(element)
        if not candidates:
            return [], 0

        orphaned: list[dict] = []
        evaluated = 0

        # Filter candidates to reinforcement classes and check attachment
        for candidate in candidates:
            # Get reinforcement class directly
            if not isinstance(candidate, TeklaReinforcement):
                # Skip non-reinforcement objects
                continue

            reinforcement_class = int(candidate.tekla_class)
            if reinforcement_class not in REINFORCEMENT_CLASSES:
                # Filter to reinforcement classes only
                continue

            evaluated += 1

            # Check if reinforcement is attached to element
            if candidate.guid not in element_reinforcement_guids:
                orphaned.append(_build_orphaned_dict(candidate.guid, candidate.name, candidate.position, reinforcement_class))

        return orphaned, evaluated

    # Process each selected element individually
    orphaned_elements: list[dict] = []
    orphaned_guids: set[str] = set()
    total_evaluated = 0

    for obj in wrap_model_objects(selected_objects):
        if not isinstance(obj, (TeklaPart, TeklaAssembly)):
            continue
        #
        parent_assembly = obj.get_top_level_assembly()
        if mode == "embeds":
            target_guids = {parent_assembly.guid}
            orphaned, evaluated = _check_element_bounding_box_embeds(parent_assembly, target_guids)
        else:
            reinforcement_guids = _get_reinforcement_guids(parent_assembly)
            orphaned, evaluated = _check_element_bounding_box_rebars(parent_assembly, reinforcement_guids)

        for item in orphaned:
            if item["guid"] not in orphaned_guids:
                orphaned_elements.append(item)
                orphaned_guids.add(item["guid"])

        total_evaluated += evaluated

    # No valid bounding box found: selected objects may lack geometry
    if total_evaluated == 0:
        logger.warning("No %s found: selected objects may not have valid geometry or no %s present (selected: %d)", mode, mode, selected_objects.GetSize())

    logger.info("Finished check for orphaned %s: selected=%d, evaluated=%d, orphaned=%d", mode, selected_objects.GetSize(), total_evaluated, len(orphaned_elements))

    prefix = "embeds" if mode == "embeds" else "rebar_objects"

    return ToolResult(
        structured_content={
            "status": "success" if not orphaned_elements else "warning",
            "selected_elements": selected_objects.GetSize(),
            f"{prefix}_evaluated": total_evaluated,
            f"orphaned_{prefix}_found": len(orphaned_elements),
            f"orphaned_{prefix}": orphaned_elements,
        }
    )
