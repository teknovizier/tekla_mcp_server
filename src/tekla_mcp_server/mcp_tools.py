"""
Module for tools used for Tekla model operations.
"""

import re
from collections import defaultdict, Counter
from collections.abc import Callable
from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    BaseComponent,
    ComponentType,
    ElementLabel,
    ElementProperties,
    ElementType,
    ElementTypeModel,
    LiftingAnchorsComponent,
    NumericMatchType,
    ReportProperty,
    SelectionMode,
    StandardStringFilterKey,
    StringFilterOption,
    StringMatchType,
    NumericFilterOption,
    UDASetMode,
    get_element_type_mapping,
)
from tekla_mcp_server.tekla.loader import (
    ArrayList,
    AABB,
    BinaryFilterExpression,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    BinaryFilterOperatorType,
    Beam,
    BooleanPart,
    Color,
    GraphicsDrawer,
    List,
    ModelObject,
    ModelObjectEnumerator,
    ModelObjectVisualization,
    NumericConstantFilterExpression,
    NumericOperatorType,
    ObjectFilterExpressions,
    Operation,
    PartFilterExpressions,
    Point,
    Position,
    Solid,
    StringConstantFilterExpression,
    TeklaStructuresDatabaseTypeEnum,
    TemplateFilterExpressions,
    TemporaryTransparency,
    TransformationPlane,
    ViewHandler,
)
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tekla.model_object import (
    TeklaAssembly,
    TeklaModelObject,
    TeklaPart,
    wrap_model_object,
    wrap_model_objects,
)
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.utils import (
    NUMERIC_MATCH_TYPE_MAPPING,
    STRING_MATCH_TYPE_MAPPING,
    ensure_transformation_plane,
    get_wall_pairs,
    insert_component,
    insert_detail,
    insert_seam,  # noqa: F401
)

from tekla_mcp_server.utils import serialize_to_json, log_function_call


# Helper functions
def validate_exactly_two_selected(count: int) -> None:
    """
    Validate that exactly two elements are selected.

    Args:
        count: Number of selected elements

    Raises:
        ValueError: If the count is not equal to 2.
    """
    if count == 0:
        raise ValueError("No elements selected. Please select two elements.")
    if count == 1:
        raise ValueError("Only one element selected. Please select two elements.")
    if count > 2:
        raise ValueError(f"More than two elements selected. Expected 2, got {count}.")


def add_filter(
    filter_collection: BinaryFilterExpressionCollection,
    filter_expression: Any,
    value: str | int | float,
    match_type: StringMatchType | NumericMatchType | NumericOperatorType | None = None,
    operator: BinaryFilterOperatorType = BinaryFilterOperatorType.BOOLEAN_AND,
) -> None:
    """
    Adds a filter expression to the filter collection.

    For string filters: provide match_type as StringMatchType enum
    For numeric filters: provide match_type as NumericMatchType or NumericOperatorType enum
    For Tekla enum types (like TeklaStructuresDatabaseTypeEnum): uses default IS_EQUAL

    Args:
        filter_collection: The filter collection to add to
        filter_expression: The filter expression to add
        value: The value to filter by
        match_type: Enum for match type (StringMatchType, NumericMatchType, or NumericOperatorType)
        operator: Boolean operator to combine with previous filter (default BOOLEAN_AND)
    """
    # Handle Tekla enum types (e.g., TeklaStructuresDatabaseTypeEnum)
    if not isinstance(value, (str, int, float)):
        expr = BinaryFilterExpression(filter_expression, NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(value))
        filter_collection.Add(BinaryFilterExpressionItem(expr, operator))
        return

    # Determine if this is a string or numeric filter based on match_type
    is_string_filter = False
    if match_type is not None:
        if isinstance(match_type, StringMatchType):
            is_string_filter = True
        elif isinstance(match_type, NumericMatchType):
            is_string_filter = False

    # Convert numeric strings to numbers ONLY for numeric filters
    if isinstance(value, str) and not is_string_filter:
        try:
            if value.replace(".", "").replace("-", "").isdigit():
                value = float(value) if "." in value else int(value)
        except ValueError:
            pass  # Keep as string if conversion fails

    if isinstance(value, str):
        # String filter - require match_type to be provided as StringMatchType enum
        if match_type is None:
            match_type = StringMatchType.IS_EQUAL
        op = STRING_MATCH_TYPE_MAPPING.get(match_type)
        expr = BinaryFilterExpression(filter_expression, op, StringConstantFilterExpression(value))
    elif isinstance(value, (int, float)):
        # Numeric filter - require match_type to be provided as NumericMatchType or NumericOperatorType enum
        if match_type is None:
            match_type = NumericOperatorType.IS_EQUAL
        # If already NumericOperatorType (from Tekla), use directly
        if isinstance(match_type, NumericOperatorType):
            op = match_type
        else:
            op = NUMERIC_MATCH_TYPE_MAPPING.get(match_type)
        expr = BinaryFilterExpression(filter_expression, op, NumericConstantFilterExpression(value))
    else:
        raise ValueError(f"Unsupported value type: {type(value)}")

    filter_collection.Add(BinaryFilterExpressionItem(expr, operator))


@log_function_call
def manage_components_on_selected_objects(callback: Callable[..., int], component: Any, custom_properties_errors: list | None = None, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """
    Applies a component operation to selected objects in the Tekla model using a specified callback function.

    Args:
        callback: Callback function to apply to each object
        component: Component to apply
        custom_properties_errors: List to collect custom property errors
        *args: Additional positional arguments for callback
        **kwargs: Additional keyword arguments for callback
    """

    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    if component.component_type in [ComponentType.DETAIL, ComponentType.COMPONENT]:
        return process_detail_or_component(selected_objects, callback, tekla_model, component, custom_properties_errors, *args, **kwargs)
    elif component.component_type in [ComponentType.SEAM, ComponentType.CONNECTION]:
        return process_seam_or_connection(selected_objects, callback, tekla_model, component, custom_properties_errors, *args, **kwargs)
    logger.warning("Unsupported component type: %s", component.component_type)
    return {"status": "error", "message": f"Unsupported component type: {component.component_type}"}


@log_function_call
def process_detail_or_component(
    selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: TeklaModel, component: Any, custom_properties_errors: list | None = None, *args: Any, **kwargs: Any
) -> dict[str, Any]:
    """
    Processes a list of selected objects, applying a callback to each object that is an instance of Beam.
    Used for components that require only one primary object.

    Args:
        selected_objects: Enumerator of selected model objects
        callback: Callback function to apply to each object
        model: Tekla model instance
        component: Component to apply
        custom_properties_errors: List to collect custom property errors
        *args: Additional positional arguments for callback
        **kwargs: Additional keyword arguments for callback
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
    errors = custom_properties_errors or []
    status = "success" if processed_components else "error"
    if errors:
        status = "warning"
    return {
        "status": status,
        "total_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "processed_components": processed_components,
        "custom_properties_errors": errors,
    }


@log_function_call
def process_seam_or_connection(
    selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: TeklaModel, component: Any, custom_properties_errors: list | None = None, *args: Any, **kwargs: Any
) -> dict[str, Any]:
    """
    Processes seams or connections between selected objects in the model.
    This function is intended for use with components that require two objects, such as wall joints.
    It validates the number of selected objects, ensuring that exactly two are selected.

    Args:
        selected_objects: Enumerator of selected model objects
        callback: Callback function to apply to each object
        model: Tekla model instance
        component: Component to apply
        custom_properties_errors: List to collect custom property errors
        *args: Additional positional arguments for callback
        **kwargs: Additional keyword arguments for callback
    """
    validate_exactly_two_selected(selected_objects.GetSize())

    processed_elements = 0
    processed_components = 0

    wall_pairs = get_wall_pairs(selected_objects)
    for pair in wall_pairs:
        success = callback(model, component, pair[1], pair[0], *args, **kwargs)
        if success:
            processed_components += success
    model.commit_changes()
    logger.info("Processed %s elements, %s components", processed_elements, processed_components)
    errors = custom_properties_errors or []
    status = "success" if processed_components else "error"
    if errors:
        status = "warning"
    return {
        "status": status,
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "inserted_components": processed_components,
        "custom_properties_errors": errors,
    }


# Tools functions
@ensure_transformation_plane
@log_function_call
def tool_put_components(model: TeklaModel, component: BaseComponent, selected_object: ModelObject) -> int:
    """
    Inserts a component to the specified object in the Tekla model.
    Handles specialized components like lifting anchors with intelligent behavior.

    Args:
        model: Tekla model instance
        component: Component to insert
        selected_object: Target object for the component
    """
    weight_factor = 1.05  # 5% to account for the weight of subassemblies and rebars
    safety_margin = 5  # 5% safety margin
    recess_width_offset = 100.0  # Recess offset

    is_lifting_anchor = isinstance(component, LiftingAnchorsComponent)

    # Handle lifting anchor specific logic
    if is_lifting_anchor:
        # Get element type by class
        material, element_type = ElementTypeModel.get_element_type_by_class(selected_object.Class)
        if material != "Concrete":
            raise ValueError(f"Unsupported material type: {material}. Only concrete elements are supported.")

        assembly = wrap_model_object(selected_object.GetAssembly())
        solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
        length = abs(solid.MaximumPoint.X - solid.MinimumPoint.X)
        width = abs(solid.MaximumPoint.Z - solid.MinimumPoint.Z)

        # Get cast unit total weight
        total_weight = float(assembly.get_report_property("WEIGHT")) * weight_factor

        logger.debug("Assuming total weight: %s kg", total_weight)

        # Calculate the necessary number of anchors and get their type
        safety_margin = getattr(component, "safety_margin", safety_margin)
        number_of_anchors, valid_anchors = LiftingAnchorsComponent.get_required_anchors(element_type, total_weight, safety_margin)

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

        properties = {
            "DistanceFrom": 1,
            "DistFromPartStart": distance_from_start,
            "DistFromPartFinish": distance_from_end,
            "custom": 1,
            "custom_name": first_anchor_key,
            "AnchorRecess": 2,
            "RecessWidth": width + recess_width_offset,
            "CustomCRotation": 1,
            "up_direction": 1,
            **first_anchor_attributes,
        }
        component.set_properties(properties)

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
            updated_properties = {
                "DistFromPartStart": distance_from_start + double_anchor_spacing,
                "DistFromPartFinish": distance_from_end + double_anchor_spacing,
            }
            component.update_properties(updated_properties)
            counter += int(insert_component(selected_object, component))
            logger.debug("Inserted additional anchors for 4-anchor configuration. Total number of anchor components: %s", counter)

        _process_lifting_anchor_recesses(selected_object, local_cog)
        logger.info("Total lifting anchor components inserted: %s", counter)

    return counter


def _process_lifting_anchor_recesses(selected_object: ModelObject, local_cog: Any) -> None:
    """
    Iterates through all boolean parts within the element, identifies the recesses for lifting anchors,
    and creates additional cuts where needed.
    """
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
            if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT and operative_part.Class == "0" and operative_part.Name == "" and operative_part.Profile.ProfileString.startswith("PRMD"):
                # Create the boolean part only if the recess is positioned below the highest Y coordinate of the element solid
                solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
                default_offset = 0.0  # Assume zero offset, should probably be offset = 25.0 if local_cog.X < operative_part.StartPoint.X else -25.0
                default_cut_length = 300.0
                min_ledge_height = 100.0
                magic_offset = 0.99  # Add 0.99 mm to avoid Tekla bug
                ledge_height = solid.MaximumPoint.Y - operative_part.StartPoint.Y
                if ledge_height > min_ledge_height:
                    _create_boolean_cut(selected_object, operative_part.StartPoint.X, operative_part.StartPoint.Y, ledge_height, default_offset, default_cut_length)
                elif ledge_height:
                    match = re.search(r"PRMD(\d+)", operative_part.Profile.ProfileString)
                    if match:
                        cut_length = float(match.group(1)) + magic_offset
                        _create_boolean_cut(selected_object, operative_part.StartPoint.X, operative_part.StartPoint.Y, ledge_height, default_offset, cut_length)


def _create_boolean_cut(selected_object: ModelObject, x_position: float, y_position: float, cut_height: float, depth_offset: float, cut_length: float) -> bool:
    """
    Creates a boolean cut and applies it to the selected element.
    """
    z_offset = 25.0
    logger.debug("Creating boolean cut at X=%s, Y=%s, height=%s, length=%s", x_position, y_position, cut_height, cut_length)
    solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
    cut_start = Point(x_position, y_position, solid.MinimumPoint.Z - z_offset)
    cut_end = Point(x_position, y_position, solid.MaximumPoint.Z + z_offset)

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
        target_object = wrap_model_object(selected_object)
        cutter_object = wrap_model_object(cutting_part)
        return target_object.add_cut(cutter_object, True)
    logger.warning("Failed to insert boolean cut part")
    return False


@log_function_call
def tool_remove_components(model: TeklaModel, component: BaseComponent, *selected_objects: ModelObject) -> int:
    """
    Removes components with the specified number and name from the specified object in the Tekla model.
    Handles special cleanup for intelligent components like lifting anchors.

    Args:
        model: Tekla model instance
        component: Component to remove
        *selected_objects: Objects to remove component from
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
    element_type: ElementType | None = None,
    tekla_classes: int | list[int] | None = None,
    standard_string_filters: dict[str, StringFilterOption] | None = None,
    custom_string_filters: dict[str, StringFilterOption] | None = None,
    custom_numeric_filters: dict[str, NumericFilterOption] | None = None,
    combine_with: str = "AND",
) -> dict[str, Any]:
    """
    Select elements using standard Tekla properties, custom attributes, and numeric ranges.

    Args:
        model: TeklaModel instance
        element_type: Named element type (ElementType enum)
        tekla_classes: Tekla class number(s) - int or list of ints (e.g., 1, 8, 100)
        standard_string_filters: Dict of standard property names to StringFilterOption.
            Valid keys: name, profile, material, finish, phase
        custom_string_filters: Dict of custom string property names to StringFilterOption
        custom_numeric_filters: Dict of custom numeric property names to NumericFilterOption
        combine_with: How to combine filter groups - "AND" or "OR", default "AND"
    """
    if combine_with not in {"AND", "OR"}:
        raise ValueError(f"Invalid combine_with '{combine_with}'. Must be 'AND' or 'OR'.")

    if not any(
        [
            element_type,
            tekla_classes,
            standard_string_filters,
            custom_string_filters,
            custom_numeric_filters,
        ]
    ):
        raise ValueError("At least one filter must be provided.")

    valid_standard_keys = {k.value for k in StandardStringFilterKey}
    if standard_string_filters:
        for key in standard_string_filters:
            if key not in valid_standard_keys:
                raise ValueError(f"Invalid standard_string_filters key '{key}'. Must be one of: {valid_standard_keys}")

    filter_collection = BinaryFilterExpressionCollection()

    filter_collection.Add(
        BinaryFilterExpressionItem(
            BinaryFilterExpression(
                ObjectFilterExpressions.Type(),
                NumericOperatorType.IS_EQUAL,
                NumericConstantFilterExpression(TeklaStructuresDatabaseTypeEnum.PART),
            )
        )
    )

    filter_groups: list[BinaryFilterExpressionCollection] = []

    def build_filter_group(
        expression,
        filter_option: StringFilterOption | NumericFilterOption,
        is_numeric: bool = False,
    ) -> BinaryFilterExpressionCollection:
        sub = BinaryFilterExpressionCollection()
        conditions = filter_option.conditions
        logic = filter_option.logic
        if not isinstance(conditions, list):
            conditions = [conditions]
        operator = BinaryFilterOperatorType.BOOLEAN_OR if logic == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        for cond in conditions:
            value = cond.value
            match_type_str = cond.match_type
            if is_numeric:
                match_type = NumericMatchType(match_type_str)
            else:
                match_type = StringMatchType(match_type_str)
            add_filter(sub, expression, value, match_type, operator=operator)
        return sub

    STANDARD_EXPRESSION_MAP = {
        "name": PartFilterExpressions.Name(),
        "profile": PartFilterExpressions.Profile(),
        "material": PartFilterExpressions.Material(),
        "finish": PartFilterExpressions.Finish(),
        "phase": TemplateFilterExpressions.CustomString("ASSEMBLY.PHASE"),
    }

    if element_type:
        element_type_classes: list[int] = []
        if isinstance(element_type, ElementType):
            for mapping in get_element_type_mapping().values():
                if element_type.name in mapping:
                    element_type_classes.extend(mapping[element_type.name])
        else:
            raise ValueError("Invalid element_type.")
        type_sub = BinaryFilterExpressionCollection()
        for cls in element_type_classes:
            add_filter(
                type_sub,
                PartFilterExpressions.Class(),
                cls,
                NumericOperatorType.IS_EQUAL,
                operator=BinaryFilterOperatorType.BOOLEAN_OR,
            )
        filter_groups.append(type_sub)

    if tekla_classes:
        if isinstance(tekla_classes, int):
            tekla_classes = [tekla_classes]
        type_sub = BinaryFilterExpressionCollection()
        for cls in tekla_classes:
            add_filter(
                type_sub,
                PartFilterExpressions.Class(),
                cls,
                NumericOperatorType.IS_EQUAL,
                operator=BinaryFilterOperatorType.BOOLEAN_OR,
            )
        filter_groups.append(type_sub)

    if standard_string_filters:
        for key, filter_option in standard_string_filters.items():
            expression = STANDARD_EXPRESSION_MAP[key]
            filter_groups.append(build_filter_group(expression, filter_option))

    if custom_string_filters:
        for field_name, filter_option in custom_string_filters.items():
            custom_property = TemplateAttributeParser.parse(field_name)
            expression = TemplateFilterExpressions.CustomString(custom_property.name)
            filter_groups.append(build_filter_group(expression, filter_option))

    if custom_numeric_filters:
        for field_name, filter_option in custom_numeric_filters.items():
            custom_property = TemplateAttributeParser.parse(field_name)
            expression = TemplateFilterExpressions.CustomNumber(custom_property.name)
            filter_groups.append(build_filter_group(expression, filter_option, is_numeric=True))

    if len(filter_groups) == 1:
        filter_collection.Add(BinaryFilterExpressionItem(filter_groups[0], BinaryFilterOperatorType.BOOLEAN_AND))
    elif len(filter_groups) > 1:
        combined = BinaryFilterExpressionCollection()
        group_operator = BinaryFilterOperatorType.BOOLEAN_OR if combine_with == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        for fg in filter_groups:
            combined.Add(BinaryFilterExpressionItem(fg, group_operator))
        filter_collection.Add(BinaryFilterExpressionItem(combined, BinaryFilterOperatorType.BOOLEAN_AND))

    objects_to_select = model.get_objects_by_filter(filter_collection)
    TeklaModel.select_objects(objects_to_select)

    count = objects_to_select.GetSize()

    return {
        "status": "success" if count else "error",
        "selected_elements": count,
    }


@log_function_call
def tool_select_elements_by_filter_name(model: TeklaModel, filter_name: str) -> dict[str, Any]:
    """
    Selects elements in the Tekla model based on the existing filter.

    Args:
        model: Tekla model instance
        filter_name: Name of the filter to use
    """
    objects_to_select = model.get_objects_by_filter(filter_name)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by named filter", objects_to_select.GetSize())
    return {
        "status": "success" if objects_to_select.GetSize() else "error",
        "selected_elements": objects_to_select.GetSize(),
    }


@log_function_call
def tool_select_elements_by_guid(model: TeklaModel, guids: list[str]) -> dict[str, Any]:
    """
    Selects elements in the Tekla model by their GUID.

    Args:
        model: Tekla model instance
        guids: List of GUIDs to select
    """

    objects_to_select = model.get_objects_by_guid(guids)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by GUID", objects_to_select.Count)
    return {
        "status": "success" if objects_to_select.Count else "error",
        "selected_elements": objects_to_select.Count,
    }


@log_function_call
def tool_select_elements_assemblies_or_main_parts(selected_objects: ModelObjectEnumerator, mode: SelectionMode) -> dict[str, Any]:
    """
    Returns assemblies or main parts for the given selected objects.

    Args:
        selected_objects: Enumerator of selected objects
        mode: Selection mode (Assembly or MainPart)
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
def tool_draw_elements_labels(selected_objects: ModelObjectEnumerator, label: ElementLabel, custom_label: str | None = None) -> dict[str, Any]:
    """
    Draws labels for the given Tekla model objects using the GraphicsDrawer.

    Args:
        selected_objects: Enumerator of selected objects
        label: ElementLabel type to draw
        custom_label: Custom label template string (required if label is CUSTOM)
    """
    color_black = (0.0, 0.0, 0.0)
    drawer = GraphicsDrawer()
    processed_elements = 0
    drawn_labels = 0
    for selected_object in wrap_model_objects(selected_objects):
        if label == ElementLabel.CUSTOM:
            if not custom_label:
                raise ValueError("Custom label parameter has to be set.")
            custom_property = TemplateAttributeParser.parse(custom_label)
            value = selected_object.get_report_property(custom_property.name)
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
        if drawer.DrawText(selected_object.cog, text, Color(*color_black)):
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
def tool_zoom_to_selection(selected_objects: ModelObjectEnumerator) -> dict[str, Any]:
    """
    Zooms the Tekla view to the provided model objects.

    Args:
        selected_objects: Enumerator of selected objects to zoom to
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
def tool_redraw_view() -> dict[str, Any]:
    """
    Redraws the currently active view in Tekla.
    """
    # Tekla 2022 API doesn't have GetActiveView() method, so we redraw all visible views
    # Otherwise, the following code can be used:

    # active_view = ViewHandler.GetActiveView()
    # result = ViewHandler.RedrawView(active_view)

    view_enum = ViewHandler.GetVisibleViews()
    view_redrawn = False

    while view_enum.MoveNext():
        view = view_enum.Current
        view_redrawn = ViewHandler.RedrawView(view)

    logger.info("Active views have been redrawn")
    return {"status": "success" if view_redrawn else "error"}


@log_function_call
def tool_show_only_selected(selected_objects: ModelObjectEnumerator) -> dict[str, Any]:
    """
    Updates the Tekla view to show only the currently selected model objects.

    Args:
        selected_objects: Enumerator of selected objects to show
    """
    Operation.ShowOnlySelected(Operation.UnselectedModeEnum.Hidden)
    logger.info("Hidden all the elements except the selected ones")
    return {
        "status": "success",
        "selected_elements": selected_objects.GetSize(),
    }


@log_function_call
def tool_hide_selected(selected_objects: ModelObjectEnumerator) -> dict[str, Any]:
    """
    Hides selected elements in the Tekla view using ModelObjectVisualization.
    Works with both parts and assemblies.

    Args:
        selected_objects: Enumerator of selected objects to hide
    """

    objects_to_hide = []

    for obj in wrap_model_objects(selected_objects):
        if isinstance(obj, TeklaAssembly):
            objects_to_hide.extend(obj.get_all_children())
        elif isinstance(obj, TeklaPart):
            objects_to_hide.extend(obj.get_all_children(include_all=False))

    tekla_list = List[ModelObject]()
    for model_object in objects_to_hide:
        tekla_list.Add(model_object)
    ModelObjectVisualization.SetTransparency(tekla_list, TemporaryTransparency.HIDDEN)

    return {"status": "success", "hidden_elements": len(objects_to_hide)}


@log_function_call
def tool_color_selected(selected_objects: ModelObjectEnumerator, red: int, green: int, blue: int) -> dict[str, Any]:
    """
    Colors selected elements in the Tekla view using ModelObjectVisualization.
    Works with both parts and assemblies.

    Args:
        selected_objects: Enumerator of selected objects to color
        red: Red component of RGB color (0-255)
        green: Green component of RGB color (0-255)
        blue: Blue component of RGB color (0-255)
    """

    objects_to_color = []

    for obj in wrap_model_objects(selected_objects):
        if isinstance(obj, TeklaAssembly):
            objects_to_color.extend(obj.get_all_children())
        elif isinstance(obj, TeklaPart):
            objects_to_color.extend(obj.get_all_children(include_all=False))

    tekla_list = List[ModelObject]()
    for model_object in objects_to_color:
        tekla_list.Add(model_object)
    color = Color(red / 255.0, green / 255.0, blue / 255.0)
    ModelObjectVisualization.SetTemporaryState(tekla_list, color)

    return {"status": "success", "colored_elements": len(objects_to_color)}


@log_function_call
def tool_cut_elements_with_zero_class_parts(model: TeklaModel, selected_objects: ModelObjectEnumerator, delete_cutting_parts: bool = False, tekla_class: int = 0) -> dict[str, Any]:
    """
    Applies boolean cuts to selected elements in the Tekla model using parts of a specified class as cutting objects.

    Args:
        model: Tekla model instance
        selected_objects: Enumerator of objects to cut
        delete_cutting_parts: Whether to delete cutting parts after operation (default False)
        tekla_class: Tekla class number for cutting parts (default 0)
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
def tool_convert_cut_parts_to_real_parts(model: TeklaModel, selected_objects: ModelObjectEnumerator) -> dict[str, Any]:
    """
    Inserts operative parts from boolean parts as real model objects.

    Args:
        model: Tekla model instance
        selected_objects: Enumerator of selected objects
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
def tool_set_elements_udas(selected_objects: ModelObjectEnumerator, udas: dict[str, Any], mode: UDASetMode) -> dict[str, Any]:
    """
    Applies UDAs to a collection of Tekla model objects.

    Args:
        selected_objects: Enumerator of selected objects
        udas: Dictionary of user-defined attributes to set
        mode: UDASetMode (ADD, OVERWRITE, or REMOVE)
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
def tool_get_elements_udas(selected_objects: ModelObjectEnumerator) -> dict[str, Any]:
    """
    Retrieves GUID, position, and all UDAs for a collection of model objects.

    Args:
        selected_objects: Enumerator of selected objects
    """
    processed_elements = 0
    assemblies: list[dict] = []
    parts: list[dict] = []

    def extract_metadata(selected_object: TeklaModelObject) -> dict[str, Any]:
        return {"guid": selected_object.guid, "position": selected_object.position, "udas": selected_object.get_all_user_properties()}

    for selected_object in wrap_model_objects(selected_objects):
        metadata = extract_metadata(selected_object)
        if isinstance(selected_object, TeklaAssembly):
            assemblies.append(metadata)
        elif isinstance(selected_object, TeklaPart):
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
def tool_get_elements_properties(selected_objects: ModelObjectEnumerator, custom_props_definitions: list[str]) -> dict[str, Any]:
    """
    Extracts and serializes key element properties from a collection of model objects.

    Args:
        selected_objects: Enumerator of selected objects
        custom_props_definitions: List of custom property names to extract
    """
    processed_elements = 0
    assemblies: list[ElementProperties] = []
    parts: list[ElementProperties] = []
    custom_props_errors: dict[str, dict[str, str]] = defaultdict(dict)

    parsed_custom_props: list[ReportProperty] = []
    failed_custom_prop_definitions: list[str] = []
    if custom_props_definitions:
        for custom_prop_definition in custom_props_definitions:
            try:
                parsed_prop = TemplateAttributeParser.parse(custom_prop_definition)
                parsed_custom_props.append(parsed_prop)
            except Exception as e:
                failed_custom_prop_definitions.append(custom_prop_definition)
                logger.warning("Error parsing custom property definition '%s': %s", custom_prop_definition, e)

    def get_single_element_properties(selected_object: TeklaModelObject) -> ElementProperties:
        # Try to get weight safely
        try:
            weight, _ = selected_object.weight
        except AttributeError:
            weight = None

        custom_properties = []
        for custom_property in parsed_custom_props:
            try:
                custom_property_copy = custom_property.model_copy(deep=False)
                custom_property_copy.value = selected_object.get_report_property(custom_property_copy.name)
                custom_properties.append(custom_property_copy)
            except Exception as e:
                custom_props_errors[selected_object.guid][custom_property.name] = str(e)
                logger.warning(
                    "Error extracting custom property '%s' for the object %s: %s",
                    custom_property.name,
                    selected_object.guid,
                    e,
                )

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
        if isinstance(selected_object, TeklaAssembly):
            assemblies.append(metadata)
        elif isinstance(selected_object, TeklaPart):
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
        "invalid_custom_property_definitions": failed_custom_prop_definitions,
        "custom_property_extraction_errors": custom_props_errors,
    }


@log_function_call
def tool_get_elements_cut_parts(selected_objects: ModelObjectEnumerator) -> dict[str, Any]:
    """
    Extracts cut parts from selected elements and groups them by profile.

    Args:
        selected_objects: Enumerator of selected objects
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


@log_function_call
def tool_compare_elements(selected_objects: ModelObjectEnumerator, tolerance: float = 0.01) -> dict[str, Any]:
    """
    Compares two element snapshots and returns the differences.

    Args:
        selected_objects: ModelObjectEnumerator with at least two parts selected
        tolerance: Tolerance for comparing floating-point numbers (default 0.01)
    """
    validate_exactly_two_selected(selected_objects.GetSize())

    # Get the two selected objects and wrap them
    parts = list(selected_objects)
    object_a = wrap_model_object(parts[0])
    object_b = wrap_model_object(parts[1])

    # Validate that both objects are either parts or assemblies
    valid_types = (TeklaPart, TeklaAssembly)
    if not isinstance(object_a, valid_types) or not isinstance(object_b, valid_types):
        return {
            "status": "error",
            "message": "Both objects must be parts or assemblies",
        }

    # Generate snapshots for both objects
    snapshot_a = object_a.to_snapshot()
    snapshot_b = object_b.to_snapshot()

    # Normalize numbers according to tolerance
    snapshot_a_normalized = snapshot_a.normalize(tolerance).model_dump()
    snapshot_b_normalized = snapshot_b.normalize(tolerance).model_dump()

    def are_snapshots_identical(a: Any, b: Any) -> bool:
        """
        Compare two snapshots, ignoring 'id'/'guid' fields.
        """
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b

        if isinstance(a, dict) and isinstance(b, dict):
            keys_a = {k for k in a if k.lower() not in ("id", "guid")}
            keys_b = {k for k in b if k.lower() not in ("id", "guid")}
            if keys_a != keys_b:
                return False
            return all(are_snapshots_identical(a[k], b[k]) for k in keys_a)

        if isinstance(a, list) and isinstance(b, list):
            return a == b

        if hasattr(a, "__dict__") and hasattr(b, "__dict__"):
            return are_snapshots_identical(a.__dict__, b.__dict__)

        return a == b

    identical = are_snapshots_identical(snapshot_a_normalized, snapshot_b_normalized)

    if identical:
        return {
            "status": "success",
            "identical": True,
            "message": "Elements are identical",
        }

    # Return snapshots only when elements differ
    return {
        "status": "success",
        "identical": False,
        "part_a_snapshot": snapshot_a_normalized,
        "part_b_snapshot": snapshot_b_normalized,
        "message": "Elements have differences",
    }
