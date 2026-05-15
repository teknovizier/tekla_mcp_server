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
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects, wrap_model_object, TeklaAssembly, TeklaPart, TeklaReinforcement
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


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def check_for_orphans(
    mode: Annotated[Literal["embeds", "rebars"], Field(description="Check mode: embeds or rebars")],
    attach: Annotated[bool, Field(description="If true, attach orphaned elements to their parent assembly")] = False,
) -> ToolResult:
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

        return {tekla_class for type_config in material.values() for tekla_class in type_config.get("tekla_classes", [])}

    # Load class IDs from config for filtering candidates
    EMBEDDED_DETAILS_CLASSES = _get_tekla_classes("MATERIAL_EMBEDDED")
    REINFORCEMENT_CLASSES = _get_tekla_classes("MATERIAL_REINFORCEMENT")

    def _build_orphaned_dict(guid: str, name: str, position: str, tekla_class: int) -> dict:
        """Build orphaned object result data."""
        return {"guid": guid, "name": name, "position": position, "class": tekla_class}

    def _get_reinforcement_guids(element: TeklaAssembly) -> set[str]:
        """Collect all rebar GUIDs from main part and secondary parts."""
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
        """Find objects within element's bounding box (expanded by tolerance)."""
        aabb = element.bounding_box
        if not aabb:
            return []
        # Expand box by tolerance to catch objects near boundaries
        min_point = Point(aabb.min_x - tolerance, aabb.min_y - tolerance, aabb.min_z - tolerance)
        max_point = Point(aabb.max_x + tolerance, aabb.max_y + tolerance, aabb.max_z + tolerance)
        selector = ModelObjectSelector()
        candidates = list(wrap_model_objects(selector.GetObjectsByBoundingBox(min_point, max_point)))
        logger.debug("Bounding box search for %s: found %d candidates", element.guid, len(candidates))
        return candidates

    # Check bounding box of a single element for orphaned embeds
    def _check_element_bounding_box_embeds(
        element: TeklaAssembly,
        target_assembly_guids: set[str],
    ) -> tuple[list, list[dict], int]:
        candidates = _get_candidates_in_bounding_box(element)

        orphaned: list[dict] = []
        orphaned_objects: list = []
        processed_guids: set[str] = set()
        evaluated = 0

        for candidate in candidates:
            # Get assembly from candidate (or part's assembly)
            assembly_obj = None
            wrapped_assembly = None

            if isinstance(candidate, TeklaAssembly):
                wrapped_assembly = candidate
                assembly_obj = candidate.model_object
            elif isinstance(candidate, TeklaPart):
                assembly_obj = candidate.model_object.GetAssembly()
                if assembly_obj:
                    wrapped_assembly = wrap_model_object(assembly_obj)

            if not assembly_obj or not wrapped_assembly:
                continue

            # Skip already processed assemblies
            assembly_guid = wrapped_assembly.guid
            if assembly_guid in processed_guids:
                continue

            # Get main part class
            main = wrapped_assembly.main_part
            if not main:
                continue

            part_class = int(main.tekla_class)
            if part_class not in EMBEDDED_DETAILS_CLASSES:
                # Filter to embeds classes only
                continue

            evaluated += 1
            processed_guids.add(assembly_guid)

            # Check if attached to target assembly (orphan if parent differs)
            parent = assembly_obj.GetAssembly()
            parent_guid = parent.Identifier.GUID.ToString() if parent else None

            if parent_guid not in target_assembly_guids:
                orphaned.append(
                    _build_orphaned_dict(
                        assembly_guid,
                        main.name,
                        main.position,
                        part_class,
                    )
                )
                orphaned_objects.append(assembly_obj)

        logger.debug("Found %d orphaned embeds for element %s", len(orphaned), element.guid)
        return orphaned_objects, orphaned, evaluated

    # Check bounding box of a single element for orphaned rebars
    def _check_element_bounding_box_rebars(element: TeklaAssembly, element_reinforcement_guids: set[str]) -> tuple[list, list[dict], int]:
        candidates = _get_candidates_in_bounding_box(element)
        if not candidates:
            return [], [], 0

        orphaned: list[dict] = []
        orphaned_objects: list = []
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

            # Orphan if rebar's GUID is not in element's reinforcement set (not attached)
            if candidate.guid not in element_reinforcement_guids:
                orphaned.append(_build_orphaned_dict(candidate.guid, candidate.name, candidate.position, reinforcement_class))
                orphaned_objects.append(candidate)

        logger.debug("Found %d orphaned rebars for element %s", len(orphaned), element.guid)
        return orphaned_objects, orphaned, evaluated

    # Main loop: process each selected element, find orphans, optionally attach
    orphaned_elements: list[dict] = []
    orphaned_guids: set[str] = set()
    attached_elements: list[dict] = []
    total_evaluated = 0

    for obj in wrap_model_objects(selected_objects):
        if not isinstance(obj, (TeklaPart, TeklaAssembly)):
            continue

        # Get top-level assembly for checking attachment
        parent_assembly = obj.get_top_level_assembly()

        # Run mode-specific orphan detection
        if mode == "embeds":
            # Check if candidates have different parent (orphan)
            orphaned_objects, orphaned, evaluated = _check_element_bounding_box_embeds(
                parent_assembly,
                {parent_assembly.guid},
            )

        elif mode == "rebars":
            # Check if rebars are in element's reinforcement set (orphan if not found)
            orphaned_objects, orphaned, evaluated = _check_element_bounding_box_rebars(
                parent_assembly,
                _get_reinforcement_guids(parent_assembly),
            )

        total_evaluated += evaluated

        # Deduplicate: same orphan may be found near multiple selected elements
        for item, orphan_obj in zip(orphaned, orphaned_objects):
            if item["guid"] in orphaned_guids:
                continue

            orphaned_elements.append(item)
            orphaned_guids.add(item["guid"])

            if not attach:
                continue

            # Skip self-attachment: don't attach element to itself
            if item["guid"] == parent_assembly.guid:
                logger.debug("Skipping self-attachment for %s", item["guid"])
                continue

            success = False

            # Different attachment methods for embeds vs rebars
            if mode == "embeds":
                # Add embed assembly to parent assembly
                added = parent_assembly.model_object.Add(orphan_obj)

                if added:
                    success = parent_assembly.model_object.Modify() and orphan_obj.Modify()

            elif mode == "rebars":
                # Set rebar's Father to main part
                orphan_obj.model_object.Father = parent_assembly.main_part.model_object

                success = parent_assembly.main_part.model_object.Modify() and orphan_obj.model_object.Modify()

            if not success:
                logger.warning(
                    "Failed to attach orphaned %s %s to assembly %s",
                    mode[:-1],
                    item["guid"],
                    parent_assembly.guid,
                )

                continue

            attached_elements.append(item)

            logger.info(
                "Attached orphaned %s %s to assembly %s",
                mode[:-1],
                item["guid"],
                parent_assembly.guid,
            )

    # Commit all attached orphans in single transaction
    if attach and attached_elements:
        model.commit_changes()

    # Warn if no candidates evaluated (no geometry or wrong object types selected)
    if total_evaluated == 0:
        logger.warning("No %s found: selected objects may not have valid geometry or no %s present (selected: %d)", mode, mode, selected_objects.GetSize())

    logger.info(
        "Finished check for orphaned %s: selected=%d, evaluated=%d, orphaned=%d, attached=%d", mode, selected_objects.GetSize(), total_evaluated, len(orphaned_elements), len(attached_elements)
    )

    prefix = "embeds" if mode == "embeds" else "rebar_objects"

    result_content = {
        "status": "success" if not orphaned_elements else "warning",
        "selected_elements": selected_objects.GetSize(),
        f"{prefix}_evaluated": total_evaluated,
        f"orphaned_{prefix}_count": len(orphaned_elements),
    }

    if attach:
        result_content[f"attached_{prefix}_count"] = len(attached_elements)
        result_content[f"attached_{prefix}"] = attached_elements
    else:
        result_content[f"orphaned_{prefix}"] = orphaned_elements

    return ToolResult(structured_content=result_content)
