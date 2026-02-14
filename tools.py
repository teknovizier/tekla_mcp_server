"""
Module for tools used for Tekla model operations.
"""

from typing import Any
from collections import defaultdict, Counter
from collections.abc import Callable
import re

from init import logger
from models import (
    ELEMENT_TYPE_MAPPING,
    SelectionMode,
    UDASetMode,
    StringMatchType,
    ElementType,
    ElementLabel,
    BaseComponent,
    LiftingAnchorsComponent,
    ElementTypeModel,
    ElementProperties,
    ComponentType,
)

from tekla_loader import (
    ArrayList,
    TeklaStructuresDatabaseTypeEnum,
    AABB,
    Point,
    ModelObject,
    ModelObjectEnumerator,
    Beam,
    BooleanPart,
    Position,
    Solid,
    TransformationPlane,
    Operation,
    Color,
    GraphicsDrawer,
    ViewHandler,
    BinaryFilterOperatorType,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    NumericOperatorType,
    NumericConstantFilterExpression,
    StringConstantFilterExpression,
    BinaryFilterExpression,
    PartFilterExpressions,
    ObjectFilterExpressions,
    TemplateFilterExpressions,
)

from tekla_utils import (
    STRING_MATCH_TYPE_MAPPING,
    TeklaModel,
    TeklaModelObject,
    TemplateAttributeParser,
    wrap_model_objects,
    get_wall_pairs,
    ensure_transformation_plane,
    insert_component,
    insert_detail,
    insert_seam,  # noqa: F401
)

from utils import serialize_to_json, log_function_call


# Helper functions
@log_function_call
def manage_components_on_selected_objects(callback: Callable[..., int], component: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """
    Applies a component operation to selected objects in the Tekla model using a specified callback function.
    """

    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    if component.component_type in [ComponentType.DETAIL, ComponentType.COMPONENT]:
        return process_detail_or_component(selected_objects, callback, tekla_model, component, *args, **kwargs)
    elif component.component_type in [ComponentType.SEAM, ComponentType.CONNECTION]:
        return process_seam_or_connection(selected_objects, callback, tekla_model, component, *args, **kwargs)
    logger.warning("Unsupported component type: %s", component.component_type)
    return {"status": "error", "message": f"Unsupported component type: {component.component_type}"}


@log_function_call
def add_filter(
    filter_collection: BinaryFilterExpressionCollection,
    filter_expression: Any,
    value: str | int,
    match_type: StringMatchType | NumericOperatorType = None,
    operator: BinaryFilterOperatorType = BinaryFilterOperatorType.BOOLEAN_AND,
) -> None:
    """
    Adds a filter expression to the filter collection.

    For string filters: provide match_type as StringMatchType
    For numeric filters: provide match_type as NumericOperatorType (defaults to IS_EQUAL if None)
    """
    if isinstance(value, str):
        # String filter - use provided match_type or default to IS_EQUAL
        if match_type is None:
            match_type = StringMatchType.IS_EQUAL
        op = STRING_MATCH_TYPE_MAPPING.get(match_type)
        expr = BinaryFilterExpression(filter_expression, op, StringConstantFilterExpression(value))
    else:
        # Numeric filter - use provided match_type or default to IS_EQUAL
        if match_type is None:
            match_type = NumericOperatorType.IS_EQUAL
        expr = BinaryFilterExpression(filter_expression, match_type, NumericConstantFilterExpression(value))

    filter_collection.Add(BinaryFilterExpressionItem(expr, operator))


@log_function_call
def process_detail_or_component(selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: TeklaModel, component: Any, *args: Any, **kwargs: Any) -> dict:
    """
    Processes a list of selected objects, applying a callback to each object that is an instance of Beam.
    Used for components that require only one primary object.
    """
    processed_elements = 0
    processed_components = 0
    for selected_object in selected_objects:
        if isinstance(selected_object, Beam):
            success = callback(model, component, selected_object, *args, **kwargs)
            if success:
                processed_components += success
            processed_elements += 1
    model.commit_changes()
    logger.info("Processed %s elements, %s components", processed_elements, processed_components)
    return {
        "status": "success" if processed_components else "error",
        "total_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "processed_components": processed_components,
    }


@log_function_call
def process_seam_or_connection(selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: TeklaModel, component: Any, *args: Any, **kwargs: Any) -> dict:
    """
    Processes seams or connections between selected objects in the model.
    This function is intended for use with components that require two objects, such as wall joints.
    It validates the number of selected objects, ensuring that exactly two are selected.
    """
    total_selected = selected_objects.GetSize()
    if total_selected == 0:
        raise ValueError("No elements selected. Please select two elements.")
    if total_selected == 1:
        raise ValueError("Only one element selected. Please select two elements.")
    if total_selected > 2:
        raise ValueError("More than two elements selected.")

    processed_elements = 0
    processed_components = 0

    wall_pairs = get_wall_pairs(selected_objects)
    for pair in wall_pairs:
        success = callback(model, component, pair[1], pair[0], *args, **kwargs)
        if success:
            processed_components += success
    model.commit_changes()
    logger.info("Processed %s elements, %s components", processed_elements, processed_components)
    return {
        "status": "success" if processed_components else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "inserted_components": processed_components,
    }


# Tools functions
@ensure_transformation_plane
@log_function_call
def tool_put_components(model: TeklaModel, component: BaseComponent, selected_object: ModelObject) -> int:
    """
    Inserts a component to the specified object in the Tekla model.
    Handles specialized components like lifting anchors with intelligent behavior.
    """

    # Check if this is a lifting anchor component
    is_lifting_anchor = isinstance(component, LiftingAnchorsComponent)

    # Handle lifting anchor specific logic
    if is_lifting_anchor:
        # Get element type by class
        material, element_type = ElementTypeModel.get_element_type_by_class(selected_object.Class)
        if material != "Concrete":
            raise ValueError(f"Unsupported material type: {material}. Only concrete elements are supported.")

        assembly = TeklaModelObject(selected_object.GetAssembly())
        solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
        length = abs(solid.MaximumPoint.X - solid.MinimumPoint.X)
        width = abs(solid.MaximumPoint.Z - solid.MinimumPoint.Z)

        # Get cast unit total weight
        # Assume the total element weight is increased by 5% to account for the weight of subassemblies and rebars
        total_weight = float(assembly.get_report_property("WEIGHT", float)) * 1.05

        logger.debug("Assuming total weight: %s kg", total_weight)

        # Calculate the necessary number of anchors and get their type
        number_of_anchors, valid_anchors = LiftingAnchorsComponent.get_required_anchors(element_type, total_weight, component.safety_margin if hasattr(component, "safety_margin") else 5)

        # Get the first anchor's attributes
        first_anchor_key = next(iter(valid_anchors))
        first_anchor_attributes = valid_anchors[first_anchor_key]["attributes"]
        logger.info("Number of anchors required: %s. Selected anchor type: %s", number_of_anchors, first_anchor_key)

        # Get initial COG X-coordinate
        local_plane = TransformationPlane(selected_object.GetCoordinateSystem())
        local_cog = local_plane.TransformationMatrixToLocal.Transform(assembly.cog)

        min_edge_distance = valid_anchors[first_anchor_key]["min_edge_distance"]

        # Calculate the placement of lifting anchors
        distance_from_start, distance_from_end, double_anchor_spacing = LiftingAnchorsComponent.calculate_anchor_placement(min_edge_distance, length, local_cog.X, number_of_anchors)
        logger.info("Anchor placement calculated: start=%s, end=%s, spacing=%s", distance_from_start, distance_from_end, double_anchor_spacing)

        attributes = {
            "DistanceFrom": 1,
            "DistFromPartStart": distance_from_start,
            "DistFromPartFinish": distance_from_end,
            "custom": 1,
            "custom_name": first_anchor_key,
            "AnchorRecess": 2,
            "RecessWidth": width + 100.0,
            "CustomCRotation": 1,
            "up_direction": 1,
            **first_anchor_attributes,
        }
        component.set_attributes(attributes)

    # Insert the component
    if component.number == -1:
        counter = int(insert_detail(selected_object, component, selected_object.GetCoordinateSystem().Origin))
        logger.debug("Inserted %s custom detail components", counter)
    else:
        counter = int(insert_component(selected_object, component))
        logger.debug("Inserted %s components", counter)

    # Handle additional logic for lifting anchors
    if is_lifting_anchor:
        # Handle additional anchors for 4-anchor configuration
        if number_of_anchors == 4:
            updated_attributes = {
                "DistFromPartStart": distance_from_start + double_anchor_spacing,
                "DistFromPartFinish": distance_from_end + double_anchor_spacing,
            }
            component.update_attributes(updated_attributes)
            counter += int(insert_component(selected_object, component))
            logger.debug("Inserted additional anchors for 4-anchor configuration. Total number of anchor components: %s", counter)

        # Add recesses where necessary
        def create_boolean_cut(x_position: float, y_position: float, cut_height: float, depth_offset: float, cut_length: float) -> bool:
            """
            Creates a boolean cut and applies it to the selected element.
            """
            logger.debug("Creating boolean cut at X=%s, Y=%s, height=%s, length=%s", x_position, y_position, cut_height, cut_length)
            # Define start and end points for the boolean cut
            solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
            cut_start = Point(x_position, y_position, solid.MinimumPoint.Z - 25.0)
            cut_end = Point(x_position, y_position, solid.MaximumPoint.Z + 25.0)

            # Create the boolean cutting part as a rectangular beam
            cutting_part = Beam()
            cutting_part.Class = "0"
            cutting_part.Material.MaterialString = "ZERO WEIGHT"
            cutting_part.Name = "LIFTING_ANCHOR_RECESS"  # Name for identification
            cutting_part.Profile.ProfileString = f"{cut_length}*{cut_height}"

            # Set positioning attributes
            cutting_part.StartPoint = cut_start
            cutting_part.EndPoint = cut_end
            cutting_part.Position.Depth = Position.DepthEnum.MIDDLE
            cutting_part.Position.Plane = Position.PlaneEnum.LEFT
            cutting_part.Position.DepthOffset = depth_offset

            # Insert the boolean part into the model
            if cutting_part.Insert():
                target_object = TeklaModelObject(selected_object)
                cutter_object = TeklaModelObject(cutting_part)
                return target_object.add_cut(cutter_object, True)
            logger.warning("Failed to insert boolean cut part")
            return False

        # Iterate through all boolean parts within the element, identify the recesses for lifting anchors, and create additional cuts where needed
        boolean_part_enum = selected_object.GetBooleans()
        while boolean_part_enum.MoveNext():
            boolean_part = boolean_part_enum.Current
            if isinstance(boolean_part, BooleanPart):
                operative_part = boolean_part.OperativePart

                # Rely on these properties for proper identification:
                # - The type is BOOLEAN_CUT
                # - The Tekla class is 0
                # - The name is empty
                # - The profile starts with "PRMD"
                if (
                    boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT
                    and operative_part.Class == "0"
                    and operative_part.Name == ""
                    and operative_part.Profile.ProfileString.startswith("PRMD")
                ):
                    # Create the boolean part only if the recess is positioned below the highest Y coordinate of the element solid
                    solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
                    DEFAULT_OFFSET = 0.0  # Assume zero offset, should probably be offset = 25.0 if local_cog.X < operative_part.StartPoint.X else -25.0
                    DEFAULT_CUT_LENGTH = 300.0
                    MIN_LEDGE_HEIGHT = 100.0
                    ledge_height = solid.MaximumPoint.Y - operative_part.StartPoint.Y
                    if ledge_height > MIN_LEDGE_HEIGHT:
                        create_boolean_cut(operative_part.StartPoint.X, operative_part.StartPoint.Y, ledge_height, DEFAULT_OFFSET, DEFAULT_CUT_LENGTH)
                    elif ledge_height:
                        match = re.search(r"PRMD(\d+)", operative_part.Profile.ProfileString)
                        if match:
                            cut_length = float(match.group(1)) + 0.99  # Add 0.99 mm to avoid Tekla bug
                            create_boolean_cut(operative_part.StartPoint.X, operative_part.StartPoint.Y, ledge_height, DEFAULT_OFFSET, cut_length)
        logger.info("Total lifting anchor components inserted: %s", counter)

    return counter


@log_function_call
def tool_remove_components(model: TeklaModel, component: BaseComponent, *selected_objects: ModelObject) -> int:
    """
    Removes components with the specified number and name from the specified object in the Tekla model.
    Handles special cleanup for intelligent components like lifting anchors.
    """
    if not selected_objects:
        raise ValueError("No elements selected. Please select at least one element.")

    counter = 0

    # Special handling for lifting anchors - remove recess cuts first
    is_lifting_anchor = isinstance(component, LiftingAnchorsComponent)
    if is_lifting_anchor:
        for selected_object in selected_objects:
            boolean_part_enum = selected_object.GetBooleans()
            while boolean_part_enum.MoveNext():
                boolean_part = boolean_part_enum.Current
                if isinstance(boolean_part, BooleanPart):
                    operative_part = boolean_part.OperativePart
                    if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT and operative_part.Name == "LIFTING_ANCHOR_RECESS":
                        if boolean_part.Delete():
                            counter += 1
        logger.debug("Total lifting anchor recess boolean cuts removed: %s", counter)

    # Remove components
    for comp in selected_objects[0].GetComponents():  # Process only the first object
        if comp.Number == component.number and comp.Name == component.name:
            if comp.Delete():
                counter += 1
    logger.info("Total components removed: %s", counter)
    return counter


@log_function_call
def tool_select_elements_by_filter(
    model: TeklaModel,
    element_type: int | list[int] | ElementType | None = None,
    name: str | None = None,
    name_match_type: StringMatchType = StringMatchType.IS_EQUAL,
    profile: str | None = None,
    profile_match_type: StringMatchType = StringMatchType.IS_EQUAL,
    material: str | None = None,
    material_match_type: StringMatchType = StringMatchType.IS_EQUAL,
    finish: str | None = None,
    finish_match_type: StringMatchType = StringMatchType.IS_EQUAL,
    phase: str | None = None,
    phase_match_type: StringMatchType = StringMatchType.IS_EQUAL,
) -> dict:
    """
    Selects elements in the Tekla model based on type, class, name, profile, material, finish and phase filters.
    """
    if not element_type and not name and not profile and not phase and not material and not finish:
        raise ValueError("At least one argument (element type, Tekla class, name, profile, material, finish or phase) must be provided.")

    filter_collection = BinaryFilterExpressionCollection()

    # Filter on parts
    add_filter(filter_collection, ObjectFilterExpressions.Type(), TeklaStructuresDatabaseTypeEnum.PART)

    # Filter on element types = Tekla classes
    if element_type:
        tekla_classes = []
        if isinstance(element_type, int):
            element_type = [element_type]
        if isinstance(element_type, list):
            tekla_classes = element_type
        elif isinstance(element_type, ElementType):
            tekla_classes = []
            for material_types in ELEMENT_TYPE_MAPPING.values():
                if element_type.name in material_types:
                    tekla_classes.extend(material_types[element_type.name])
        else:
            raise ValueError("Invalid input. Please enter a Tekla class number or element type.")

        filter_collection_class = BinaryFilterExpressionCollection()
        for tekla_class in tekla_classes:
            add_filter(filter_collection_class, PartFilterExpressions.Class(), tekla_class, operator=BinaryFilterOperatorType.BOOLEAN_OR)
        filter_collection.Add(BinaryFilterExpressionItem(filter_collection_class))
        logger.debug("Filtering by Tekla classes: %s", tekla_classes)

    # Filter on name
    if name:
        add_filter(filter_collection, PartFilterExpressions.Name(), name, name_match_type)
        logger.debug("Filtering by name: %s with match type: %s", name, name_match_type)

    # Filter on profile
    if profile:
        add_filter(filter_collection, PartFilterExpressions.Profile(), profile, profile_match_type)
        logger.debug("Filtering by profile: %s with match type: %s", profile, profile_match_type)

    # Filter on material
    if material:
        add_filter(filter_collection, PartFilterExpressions.Material(), material, material_match_type)
        logger.debug("Filtering by material: %s with match type: %s", material, material_match_type)

    # Filter on finish
    if finish:
        add_filter(filter_collection, PartFilterExpressions.Finish(), finish, finish_match_type)
        logger.debug("Filtering by finish: %s with match type: %s", finish, finish_match_type)

    # Filter on phase
    if phase:
        assembly_phase = TemplateFilterExpressions.CustomString("ASSEMBLY.PHASE")
        add_filter(filter_collection, assembly_phase, phase, phase_match_type)
        logger.debug("Filtering by phase: %s with match type: %s", phase, phase_match_type)

    objects_to_select = model.get_objects_by_filter(filter_collection)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by filter", objects_to_select.GetSize())
    return {
        "status": "success" if objects_to_select.GetSize() else "error",
        "selected_elements": objects_to_select.GetSize(),
    }


@log_function_call
def tool_select_elements_by_filter_name(model: TeklaModel, filter_name: str) -> dict:
    """
    Selects elements in the Tekla model based on the existing filter.
    """
    objects_to_select = model.get_objects_by_filter(filter_name)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by named filter", objects_to_select.GetSize())
    return {
        "status": "success" if objects_to_select.GetSize() else "error",
        "selected_elements": objects_to_select.GetSize(),
    }


@log_function_call
def tool_select_elements_by_guid(model: TeklaModel, guids: list[str]) -> dict:
    """
    Selects elements in the Tekla model by their GUID.
    """

    objects_to_select = model.get_objects_by_guid(guids)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by GUID", objects_to_select.Count)
    return {
        "status": "success" if objects_to_select.Count else "error",
        "selected_elements": objects_to_select.Count,
    }


@log_function_call
def tool_select_elements_assemblies_or_main_parts(selected_objects: ModelObjectEnumerator, mode: SelectionMode) -> dict:
    """
    Returns assemblies or main parts for the given selected objects.
    """
    processed_elements = 0
    selected_object_types = ""

    # Process filtered parts
    filtered_parts = ArrayList()
    for selected_object in wrap_model_objects(selected_objects):
        try:
            assembly = selected_object.get_top_level_assembly()
        except TypeError:
            logger.warning("Failed to get top level assembly for the element %s", selected_object.guid)
            continue
        if mode == SelectionMode.ASSEMBLY:
            filtered_parts.Add(assembly.model_object)
            selected_object_types = "selected_assemblies"
        elif mode == SelectionMode.MAIN_PART:
            filtered_parts.Add(assembly.main_part.model_object)
            selected_object_types = "selected_main_parts"
        processed_elements += 1

    TeklaModel.select_objects(filtered_parts)
    logger.info("Selected %s elements as '%s'", filtered_parts.Count, mode.value)
    return {
        "status": "success" if filtered_parts.Count else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        selected_object_types: filtered_parts.Count,
    }


@log_function_call
def tool_draw_elements_labels(selected_objects: ModelObjectEnumerator, label: ElementLabel, custom_label: str | None = None) -> dict:
    """
    Draws labels for the given Tekla model objects using the GraphicsDrawer.
    """
    drawer = GraphicsDrawer()
    processed_elements = 0
    drawn_labels = 0
    for selected_object in wrap_model_objects(selected_objects):
        if label == ElementLabel.CUSTOM:
            if not custom_label:
                raise ValueError("Custom label parameter has to be set.")
            custom_property = TemplateAttributeParser.parse(custom_label)
            value = selected_object.get_report_property(custom_property.name, custom_property.data_type)
            unit = f" {custom_property.unit}" if custom_property.unit else ""
            text = f"{custom_label} = {value}{unit}"
        else:
            labels = {
                ElementLabel.POSITION: selected_object.position,
                ElementLabel.GUID: selected_object.guid,
                ElementLabel.NAME: selected_object.name,
                ElementLabel.PROFILE: selected_object.profile,
                ElementLabel.MATERIAL: selected_object.material,
                ElementLabel.FINISH: selected_object.finish,
                ElementLabel.WEIGHT: f"{selected_object.weight[0]:.1f} kg",  # Ignore reinforcement weight
                ElementLabel.CLASS: selected_object.tekla_class,
            }
            text = labels.get(label, ElementLabel.NAME)
        if drawer.DrawText(selected_object.cog, text, Color(0.0, 0.0, 0.0)):
            drawn_labels += 1
        processed_elements += 1
    logger.info("Drawn '%s' labels on %s elements", label.value, drawn_labels)
    return {
        "status": "success" if drawn_labels else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "drawn_labels": drawn_labels,
    }


@log_function_call
def tool_zoom_to_selection(selected_objects: ModelObjectEnumerator) -> dict:
    """
    Zooms the Tekla view to the provided model objects.
    """
    processed_elements = 0

    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")

    for selected_object in selected_objects:
        solid = selected_object.GetSolid()
        if solid is None:
            continue

        # Get the bounding box corners
        sp = solid.MinimumPoint
        ep = solid.MaximumPoint

        # Update overall min/max
        min_x = min(min_x, sp.X)
        min_y = min(min_y, sp.Y)
        min_z = min(min_z, sp.Z)
        max_x = max(max_x, ep.X)
        max_y = max(max_y, ep.Y)
        max_z = max(max_z, ep.Z)

        processed_elements += 1

    # Create final AABB for all objects
    min_point = Point(min_x, min_y, min_z)
    max_point = Point(max_x, max_y, max_z)
    bbox = AABB(min_point, max_point)
    result = ViewHandler.ZoomToBoundingBox(bbox)
    logger.info("Zoomed to bounding box: %s", bbox)
    return {
        "status": "success" if result else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
    }


@log_function_call
def tool_show_only_selected(selected_objects: ModelObjectEnumerator) -> dict:
    """
    Updates the Tekla view to show only the currently selected model objects.
    """
    Operation.ShowOnlySelected(Operation.UnselectedModeEnum.Hidden)
    logger.info("Hidden all the elements except the selected ones")
    return {
        "status": "success",
        "selected_elements": selected_objects.GetSize(),
    }


@log_function_call
def tool_cut_elements_with_zero_class_parts(model: TeklaModel, selected_objects: ModelObjectEnumerator, delete_cutting_parts: bool = False, tekla_class: int = 0) -> dict:
    """
    Applies boolean cuts to selected elements in the Tekla model using parts of a specified class as cutting objects.
    """

    processed_elements = 0
    performed_cuts = 0
    objects_to_select = model.get_objects_by_class(tekla_class)
    cutters = list(wrap_model_objects(objects_to_select))  # Keep same instances
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
    # fmt: off
    return {
        "status": "success" if performed_cuts else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "performed_cuts": performed_cuts
    }
    # fmt: on


@log_function_call
def tool_convert_cut_parts_to_real_parts(model: TeklaModel, selected_objects: ModelObjectEnumerator) -> dict:
    """
    Inserts operative parts from boolean parts as real model objects.
    """
    processed_elements = 0
    inserted_booleans = 0
    for selected_object in selected_objects:
        boolean_part_enum = selected_object.GetBooleans()
        while boolean_part_enum.MoveNext():
            boolean_part = boolean_part_enum.Current
            if isinstance(boolean_part, BooleanPart):
                operative_part = boolean_part.OperativePart
                if operative_part.Insert():
                    inserted_booleans += 1
        processed_elements += 1
    if inserted_booleans > 0:
        model.commit_changes()
    logger.info("Inserted %s boolean parts as real parts", inserted_booleans)
    return {
        "status": "success" if inserted_booleans else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "converted_booleans": inserted_booleans,
    }


@log_function_call
def tool_set_elements_udas(selected_objects: ModelObjectEnumerator, udas: dict[str, Any], mode: UDASetMode) -> dict:
    """
    Applies UDAs to a collection of Tekla model objects.
    """
    processed_elements = 0
    updated_attributes = 0
    skipped_attributes = 0
    for selected_object in wrap_model_objects(selected_objects):
        for key, value in udas.items():
            try:
                _ = selected_object.get_user_property(key, type(value))
                uda_exists = True
            except AttributeError:
                uda_exists = False

            if mode == UDASetMode.KEEP and uda_exists:
                skipped_attributes += 1
                continue
            else:
                if selected_object.set_user_property(key, value):
                    updated_attributes += 1
        processed_elements += 1
    logger.info("Updated %s UDAs in %s element, skipped %s", updated_attributes, processed_elements, skipped_attributes)
    return {
        "status": "success" if updated_attributes else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "skipped_attributes": skipped_attributes,
        "updated_attributes": updated_attributes,
    }


@log_function_call
def tool_get_all_elements_udas(selected_objects: ModelObjectEnumerator) -> dict:
    """
    Retrieves GUID, position, and all UDAs for a collection of model objects.
    """
    processed_elements = 0
    assemblies: list[dict] = []
    parts: list[dict] = []

    def extract_metadata(selected_object: TeklaModelObject) -> dict:
        return {"guid": selected_object.guid, "position": selected_object.position, "udas": selected_object.get_all_user_properties()}

    for selected_object in wrap_model_objects(selected_objects):
        metadata = extract_metadata(selected_object)
        if selected_object.is_assembly:
            assemblies.append(metadata)
        elif selected_object.is_part:
            parts.append(metadata)
        processed_elements += 1
    logger.info("Retrieved UDAs for %s elements", processed_elements)
    return {
        "status": "success" if assemblies or parts else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "assemblies": assemblies,
        "parts": parts,
    }


@log_function_call
def tool_get_elements_properties(selected_objects: ModelObjectEnumerator, custom_props_definitions: list[str]) -> dict:
    """
    Extracts and serializes key element properties from a collection of model objects.
    """
    processed_elements = 0
    assemblies: list[ElementProperties] = []
    parts: list[ElementProperties] = []
    custom_props_errors: dict[str, dict[str, str]] = defaultdict(dict)

    def get_single_element_properties(selected_object: TeklaModelObject) -> ElementProperties:
        weight, _ = selected_object.weight
        custom_properties = []
        if custom_props_definitions:
            for custom_prop_definition in custom_props_definitions:
                try:
                    custom_property = TemplateAttributeParser.parse(custom_prop_definition)
                    custom_property.value = selected_object.get_report_property(custom_property.name, custom_property.data_type)
                    custom_properties.append(custom_property)
                except Exception as e:
                    custom_props_errors[selected_object.guid][custom_prop_definition] = str(e)
                    logger.warning("Error extracting custom property '%s' for the object %s: %s", custom_prop_definition, selected_object.guid, e)

        return ElementProperties(
            position=selected_object.position,
            guid=selected_object.guid,
            name=selected_object.name,
            profile=selected_object.profile,
            material=selected_object.material,
            finish=selected_object.finish,
            tekla_class=selected_object.tekla_class,
            weight=weight,
            custom_properties=custom_properties,
        )

    for selected_object in wrap_model_objects(selected_objects):
        metadata = get_single_element_properties(selected_object).model_copy(deep=True)
        if selected_object.is_assembly:
            assemblies.append(metadata)
        elif selected_object.is_part:
            parts.append(metadata)
        processed_elements += 1

    serialized_assemblies = serialize_to_json([a.model_dump() for a in assemblies])
    serialized_parts = serialize_to_json([a.model_dump() for a in parts])

    logger.info("Retrieved properties for %s elements", processed_elements)
    return {
        "status": "success" if assemblies or parts else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "assemblies_list": serialized_assemblies,
        "parts_list": serialized_parts,
        "custom_properties_errors": custom_props_errors,
    }


@log_function_call
def tool_get_elements_cut_parts(selected_objects: ModelObjectEnumerator) -> dict:
    """
    Extracts cut parts from selected elements and groups them by profile.
    """
    processed_elements = 0
    cut_parts_by_profile: Counter[str] = Counter()

    for selected_object in selected_objects:
        boolean_part_enum = selected_object.GetBooleans()
        while boolean_part_enum.MoveNext():
            boolean_part = boolean_part_enum.Current
            if isinstance(boolean_part, BooleanPart):
                operative_part = boolean_part.OperativePart
                if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT:
                    profile = operative_part.Profile.ProfileString
                    cut_parts_by_profile[profile] += 1
        processed_elements += 1

    sorted_profiles = sorted(cut_parts_by_profile.items(), key=lambda x: x[0])

    cut_parts_list = [{"profile": profile, "count": count} for profile, count in sorted_profiles]
    serialized_cut_parts = serialize_to_json(cut_parts_list)

    total_cut_parts = sum(cut_parts_by_profile.values())
    logger.info("Found %s cut parts across %s profiles in %s elements", total_cut_parts, len(sorted_profiles), processed_elements)
    return {
        "status": "success" if cut_parts_list else "warning",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "total_cut_parts": total_cut_parts,
        "cut_parts_list": serialized_cut_parts,
    }
