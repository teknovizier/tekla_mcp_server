"""
Component tools for Tekla model operations.
"""

import re
from collections.abc import Callable
from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    BaseComponent,
    ComponentType,
    ElementTypeModel,
    LiftingAnchorsComponent,
)
from tekla_mcp_server.tekla.loader import (
    Beam,
    BooleanPart,
    ModelObject,
    ModelObjectEnumerator,
    Point,
    Position,
    Solid,
    TransformationPlane,
)
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tekla.model_object import (
    wrap_model_object,
)
from tekla_mcp_server.tekla.utils import (
    ensure_transformation_plane,
    get_wall_pairs,
    insert_component,
    insert_detail,
)
from tekla_mcp_server.utils import log_function_call


@log_function_call
def manage_components_on_selected_objects(callback: Callable[..., int], component: Any, custom_properties_errors: list[str] | None = None, *args: Any, **kwargs: Any) -> dict[str, Any]:
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
    selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: TeklaModel, component: Any, custom_properties_errors: list[str] | None = None, *args: Any, **kwargs: Any
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
    from tekla_mcp_server.tekla.loader import Beam

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
    selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: TeklaModel, component: Any, custom_properties_errors: list[str] | None = None, *args: Any, **kwargs: Any
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
    from tekla_mcp_server.tools.selection import validate_exactly_two_selected

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
    weight_factor = 1.05
    safety_margin = 5
    recess_width_offset = 100.0

    is_lifting_anchor = isinstance(component, LiftingAnchorsComponent)

    if is_lifting_anchor:
        material, element_type = ElementTypeModel.get_element_type_by_class(selected_object.Class)
        if material != "Concrete":
            raise ValueError(f"Unsupported material type: {material}. Only concrete elements are supported.")

        assembly = wrap_model_object(selected_object.GetAssembly())
        solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
        length = abs(solid.MaximumPoint.X - solid.MinimumPoint.X)
        width = abs(solid.MaximumPoint.Z - solid.MinimumPoint.Z)

        total_weight = float(assembly.get_report_property("WEIGHT")) * weight_factor

        logger.debug("Assuming total weight: %s kg", total_weight)

        safety_margin = getattr(component, "safety_margin", safety_margin)
        number_of_anchors, valid_anchors = LiftingAnchorsComponent.get_required_anchors(element_type, total_weight, safety_margin)

        first_anchor_key = next(iter(valid_anchors))
        first_anchor_attributes = valid_anchors[first_anchor_key]["attributes"]
        logger.info("Number of anchors required: %s. Selected anchor type: %s", number_of_anchors, first_anchor_key)

        local_plane = TransformationPlane(selected_object.GetCoordinateSystem())
        local_cog = local_plane.TransformationMatrixToLocal.Transform(assembly.cog)

        min_edge_distance = valid_anchors[first_anchor_key]["min_edge_distance"]

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

    if component.number == -1:
        counter = int(insert_detail(selected_object, component, selected_object.GetCoordinateSystem().Origin))
        logger.debug("Inserted %s custom detail components", counter)
    else:
        counter = int(insert_component(selected_object, component))
        logger.debug("Inserted %s components", counter)

    if is_lifting_anchor:
        if number_of_anchors == 4:
            updated_properties = {
                "DistFromPartStart": distance_from_start + double_anchor_spacing,
                "DistFromPartFinish": distance_from_end + double_anchor_spacing,
            }
            component.update_properties(updated_properties)
            counter += int(insert_component(selected_object, component))
            logger.debug("Inserted additional anchors for 4-anchor configuration. Total number of anchor components: %s", counter)

        process_lifting_anchor_recesses(selected_object, local_cog)
        logger.info("Total lifting anchor components inserted: %s", counter)

    return counter


def process_lifting_anchor_recesses(selected_object: ModelObject, local_cog: Any) -> None:
    """
    Iterates through all boolean parts within the element, identifies the recesses for lifting anchors,
    and creates additional cuts where needed.
    """
    boolean_part_enum = selected_object.GetBooleans()
    while boolean_part_enum.MoveNext():
        boolean_part = boolean_part_enum.Current
        if isinstance(boolean_part, BooleanPart):
            operative_part = boolean_part.OperativePart

            if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT and operative_part.Class == "0" and operative_part.Name == "" and operative_part.Profile.ProfileString.startswith("PRMD"):
                solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
                default_offset = 0.0
                default_cut_length = 300.0
                min_ledge_height = 100.0
                magic_offset = 0.99
                ledge_height = solid.MaximumPoint.Y - operative_part.StartPoint.Y
                if ledge_height > min_ledge_height:
                    create_boolean_cut(selected_object, operative_part.StartPoint.X, operative_part.StartPoint.Y, ledge_height, default_offset, default_cut_length)
                elif ledge_height:
                    match = re.search(r"PRMD(\d+)", operative_part.Profile.ProfileString)
                    if match:
                        cut_length = float(match.group(1)) + magic_offset
                        create_boolean_cut(selected_object, operative_part.StartPoint.X, operative_part.StartPoint.Y, ledge_height, default_offset, cut_length)


def create_boolean_cut(selected_object: ModelObject, x_position: float, y_position: float, cut_height: float, depth_offset: float, cut_length: float) -> bool:
    """
    Creates a boolean cut and applies it to the selected element.
    """
    z_offset = 25.0
    logger.debug("Creating boolean cut at X=%s, Y=%s, height=%s, length=%s", x_position, y_position, cut_height, cut_length)
    solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
    cut_start = Point(x_position, y_position, solid.MinimumPoint.Z - z_offset)
    cut_end = Point(x_position, y_position, solid.MaximumPoint.Z + z_offset)

    cutting_part = Beam()
    cutting_part.Class = "0"
    cutting_part.Material.MaterialString = "ZERO WEIGHT"
    cutting_part.Name = "LIFTING_ANCHOR_RECESS"
    cutting_part.Profile.ProfileString = f"{cut_length}*{cut_height}"

    cutting_part.StartPoint = cut_start
    cutting_part.EndPoint = cut_end
    cutting_part.Position.Depth = Position.DepthEnum.MIDDLE
    cutting_part.Position.Plane = Position.PlaneEnum.LEFT
    cutting_part.Position.DepthOffset = depth_offset

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

    for comp in selected_objects[0].GetComponents():
        if comp.Number == component.number and comp.Name == component.name:
            if comp.Delete():
                counter += 1
    logger.info("Total components removed: %s", counter)
    return counter
