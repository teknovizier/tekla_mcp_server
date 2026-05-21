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
from tekla_mcp_server.models import CheckResult
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects, wrap_model_object, TeklaAssembly, TeklaPart, TeklaReinforcement
from tekla_mcp_server.tekla.loader import Operation, Part
from tekla_mcp_server.tekla.utils import iterate_boolean_parts, get_candidates_in_bounding_box, get_all_materials, get_all_rebar_items


operations_provider = LocalProvider()


def _get_tekla_classes(material_key: str) -> set[int]:
    """Get all tekla_classes for a material group from the config."""
    material = get_config().element_types.get(material_key, {})
    return {tekla_class for type_config in material.values() for tekla_class in type_config.get("tekla_classes", [])}


# Class IDs for filtering candidates in orphan-detection tools
EMBEDDED_DETAILS_CLASSES: set[int] = _get_tekla_classes("MATERIAL_EMBEDDED")
REINFORCEMENT_CLASSES: set[int] = _get_tekla_classes("MATERIAL_REINFORCEMENT")


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
        if not isinstance(selected_object, Part):
            logger.debug("convert_cut_parts_to_real_parts: skipping non-part object: %s", selected_object.GetType())
            continue
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
        raise RuntimeError("Tekla is busy running another macro")

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

    def _get_reinforcement_guids(element: TeklaAssembly) -> set[str]:
        """Collect all rebar GUIDs from main part and secondary parts."""
        guids: set[str] = set()

        try:
            reinfs = element.main_part.model_object.GetReinforcements()
        except ValueError:
            reinfs = None

        if reinfs is not None:
            for rebar in wrap_model_objects(reinfs):
                if rebar:
                    guids.add(rebar.guid)

        for sec in element.model_object.GetSecondaries():
            sec_reinfs = sec.GetReinforcements()
            for rebar in wrap_model_objects(sec_reinfs):
                if rebar:
                    guids.add(rebar.guid)

        return guids

    # Check bounding box of a single element for orphaned embeds
    def _check_element_bounding_box_embeds(
        element: TeklaAssembly,
        target_assembly_guids: set[str],
    ) -> tuple[list, list[CheckResult], int]:
        candidates = get_candidates_in_bounding_box(element, tolerance)

        orphaned: list[CheckResult] = []
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
            try:
                main = wrapped_assembly.main_part
            except ValueError:
                continue
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
                    CheckResult(
                        guid=assembly_guid,
                        name=main.name,
                        position=main.position,
                        tekla_class=part_class,
                    )
                )
                orphaned_objects.append(assembly_obj)

        logger.debug("Found %d orphaned embeds for element %s", len(orphaned), element.guid)
        return orphaned_objects, orphaned, evaluated

    # Check bounding box of a single element for orphaned rebars
    def _check_element_bounding_box_rebars(element: TeklaAssembly, element_reinforcement_guids: set[str]) -> tuple[list, list[CheckResult], int]:
        candidates = get_candidates_in_bounding_box(element, tolerance)
        if not candidates:
            return [], [], 0

        orphaned: list[CheckResult] = []
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
                orphaned.append(
                    CheckResult(
                        guid=candidate.guid,
                        name=candidate.name,
                        position=candidate.position,
                        tekla_class=reinforcement_class,
                    )
                )
                orphaned_objects.append(candidate)

        logger.debug("Found %d orphaned rebars for element %s", len(orphaned), element.guid)
        return orphaned_objects, orphaned, evaluated

    # Main loop: process each selected element, find orphans, optionally attach
    orphaned_elements: list[CheckResult] = []
    orphaned_guids: set[str] = set()
    attached_elements: list[CheckResult] = []
    total_evaluated = 0

    for obj in wrap_model_objects(selected_objects):
        if not isinstance(obj, (TeklaPart, TeklaAssembly)):
            continue

        # Get top-level assembly for checking attachment
        parent_assembly = obj.get_top_level_assembly()
        if parent_assembly is None:
            logger.debug("No top-level assembly for %s, skipping", obj.guid)
            continue

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
            if item.guid in orphaned_guids:
                continue

            orphaned_elements.append(item)
            orphaned_guids.add(item.guid)

            if not attach:
                continue

            # Skip self-attachment: don't attach element to itself
            if item.guid == parent_assembly.guid:
                logger.debug("Skipping self-attachment for %s", item.guid)
                continue

            success = False

            try:
                # Different attachment methods for embeds vs rebars
                if mode == "embeds":
                    # Add embed assembly to parent assembly
                    added = parent_assembly.model_object.Add(orphan_obj)

                    if added:
                        success = parent_assembly.model_object.Modify() and orphan_obj.Modify()

                elif mode == "rebars":
                    # Set rebar's Father to main part
                    try:
                        main_part_obj = parent_assembly.main_part.model_object
                    except ValueError:
                        logger.warning("Cannot attach %s: parent assembly %s has no main part", item.guid, parent_assembly.guid)
                        continue
                    orphan_obj.model_object.Father = main_part_obj

                    success = main_part_obj.Modify() and orphan_obj.model_object.Modify()
            except Exception:
                logger.exception("Failed to attach orphaned %s %s to assembly %s", mode[:-1], item.guid, parent_assembly.guid)
                continue

            if not success:
                logger.warning(
                    "Failed to attach orphaned %s %s to assembly %s",
                    mode[:-1],
                    item.guid,
                    parent_assembly.guid,
                )

                continue

            attached_elements.append(item)

            logger.info(
                "Attached orphaned %s %s to assembly %s",
                mode[:-1],
                item.guid,
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

    remaining_orphans = len(orphaned_elements) - len(attached_elements)
    status = "success" if remaining_orphans == 0 else "warning"

    result_content = {
        "status": status,
        "selected_elements": selected_objects.GetSize(),
        f"{prefix}_evaluated": total_evaluated,
        f"orphaned_{prefix}_count": len(orphaned_elements),
    }

    if orphaned_elements:
        if attach:
            result_content[f"attached_{prefix}_count"] = len(attached_elements)
            result_content[f"attached_{prefix}"] = attached_elements
        else:
            result_content[f"orphaned_{prefix}"] = orphaned_elements

    return ToolResult(structured_content=result_content)


@operations_provider.tool(tags={"operations"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def check_for_invalid_objects() -> ToolResult:
    """
    Find invalid objects in selected objects and their bounding boxes.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    tolerance = get_tolerance()

    # All valid material names and reinforcement grades from Tekla catalogs
    valid_materials = {item["name"] for item in get_all_materials()}
    valid_grades = {item["grade"] for item in get_all_rebar_items()}

    invalid_parts: list[CheckResult] = []
    invalid_reinforcements: list[CheckResult] = []
    invalid_assemblies: list[CheckResult] = []
    processed_guids: set[str] = set()
    total_evaluated = 0

    for model_obj in wrap_model_objects(selected_objects):
        if not isinstance(model_obj, (TeklaPart, TeklaAssembly)):
            logger.debug(f"Skipping non-part/assembly object: {type(model_obj).__name__}")
            continue

        # Get top-level assembly for the selected object
        parent_assembly = model_obj.get_top_level_assembly()
        if parent_assembly is None:
            logger.debug("No assembly found for %s, checking object directly", model_obj.guid)
            objects_to_check = [model_obj]
        else:
            # Start with all structural children that belong to the assembly
            children = list(wrap_model_objects(parent_assembly.get_all_children()))

            # Also include nearby objects from the bounding box search
            bbox_candidates = get_candidates_in_bounding_box(
                parent_assembly,
                tolerance,
            )

            objects_to_check = children + bbox_candidates

            logger.debug(
                ("Processing assembly %s: %d children, %d bounding box candidates, %d total objects"),
                parent_assembly.guid,
                len(children),
                len(bbox_candidates),
                len(objects_to_check),
            )

        for obj in objects_to_check:
            guid = obj.guid
            if guid in processed_guids:
                continue
            processed_guids.add(guid)

            # Process parts
            if isinstance(obj, TeklaPart):
                total_evaluated += 1
                issues: list[str] = []

                # Missing profile
                profile = obj.profile
                if not profile:
                    issues.append("missing_profile")

                # Missing or invalid material
                material = obj.material
                if not material:
                    issues.append("missing_material")
                elif material not in valid_materials:
                    issues.append(f"invalid_material: '{material}'")

                # Invalid solid
                solid = obj.model_object.GetSolid()
                if not solid or not solid.IsValid():
                    issues.append("invalid_solid")

                # Zero or negative volume
                try:
                    volume = float(obj.get_report_property("VOLUME"))
                    epsilon = 0.0001
                    if volume <= epsilon:
                        issues.append("zero_volume")
                except Exception as e:
                    logger.warning("Failed to read VOLUME for %s: %s", guid, e)
                    issues.append("volume_unreadable")

                if issues:
                    invalid_parts.append(
                        CheckResult(
                            guid=guid,
                            name=obj.name,
                            position=obj.position,
                            tekla_class=int(obj.tekla_class),
                            issues=issues,
                        )
                    )

            # Process assemblies
            elif isinstance(obj, TeklaAssembly):
                total_evaluated += 1
                assembly_issues: list[str] = []

                # Missing main part
                main_part = obj.model_object.GetMainPart()
                if main_part is None:
                    assembly_issues.append("no_main_part")

                if assembly_issues:
                    invalid_assemblies.append(
                        CheckResult(
                            guid=guid,
                            name=obj.name,
                            position=obj.position,
                            tekla_class=int(main_part.Class) if main_part else None,
                            issues=assembly_issues,
                        )
                    )

            # Process reinforcements
            elif isinstance(obj, TeklaReinforcement):
                total_evaluated += 1
                reinf_issues: list[str] = []

                # Invalid geometry
                if not obj.model_object.IsGeometryValid():
                    reinf_issues.append("invalid_geometry")

                # Invalid solid
                solid = obj.model_object.GetSolid()
                if not solid or not solid.IsValid():
                    reinf_issues.append("invalid_solid")

                # Missing or invalid grade
                grade = obj.model_object.Grade
                if not grade:
                    reinf_issues.append("missing_grade")
                elif grade not in valid_grades:
                    reinf_issues.append(f"invalid_grade: '{grade}'")

                # Missing father (not attached to part/assembly)
                if not obj.model_object.Father:
                    reinf_issues.append("no_father")

                if reinf_issues:
                    invalid_reinforcements.append(
                        CheckResult(
                            guid=guid,
                            name=obj.name,
                            position=obj.position,
                            tekla_class=int(obj.tekla_class),
                            issues=reinf_issues,
                        )
                    )

    logger.info(
        "Evaluated %d objects, found %d invalid parts, %d invalid reinforcements, %d invalid assemblies",
        total_evaluated,
        len(invalid_parts),
        len(invalid_reinforcements),
        len(invalid_assemblies),
    )

    result_content = {
        "status": "success" if not invalid_parts and not invalid_reinforcements and not invalid_assemblies else "warning",
        "selected_count": selected_objects.GetSize(),
        "total_evaluated": total_evaluated,
        "invalid_parts_count": len(invalid_parts),
        "invalid_reinforcements_count": len(invalid_reinforcements),
        "invalid_assemblies_count": len(invalid_assemblies),
    }

    if invalid_parts:
        result_content["invalid_parts"] = invalid_parts

    if invalid_reinforcements:
        result_content["invalid_reinforcements"] = invalid_reinforcements

    if invalid_assemblies:
        result_content["invalid_assemblies"] = invalid_assemblies

    return ToolResult(structured_content=result_content)
