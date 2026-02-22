"""
Module for utility functions used for geometry manipulations.
"""

from __future__ import annotations

from functools import wraps
from typing import Any
from collections.abc import Callable

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import StringMatchType, BaseComponent

from tekla_mcp_server.tekla.loader import (
    StringOperatorType,
    Point,
    Vector,
    ModelObject,
    ModelObjectEnumerator,
    Beam,
    TransformationPlane,
    ComponentInput,
    Component,
    Detail,
    Seam,
    PositionTypeEnum,
    AutoDirectionTypeEnum,
    DetailTypeEnum
)
from tekla_mcp_server.tekla.model import TeklaModel

from tekla_mcp_server.utils import log_function_call


# Mappings
# String match types
STRING_MATCH_TYPE_MAPPING = {
    StringMatchType.IS_EQUAL: StringOperatorType.IS_EQUAL,
    StringMatchType.IS_NOT_EQUAL: StringOperatorType.IS_NOT_EQUAL,
    StringMatchType.CONTAINS: StringOperatorType.CONTAINS,
    StringMatchType.NOT_CONTAINS: StringOperatorType.NOT_CONTAINS,
    StringMatchType.STARTS_WITH: StringOperatorType.STARTS_WITH,
    StringMatchType.NOT_STARTS_WITH: StringOperatorType.NOT_STARTS_WITH,
    StringMatchType.ENDS_WITH: StringOperatorType.ENDS_WITH,
    StringMatchType.NOT_ENDS_WITH: StringOperatorType.NOT_ENDS_WITH,
}

def ensure_transformation_plane(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Sets the transformation plane before execution and restores it after.
    Supports functions with either one or two selected objects.
    """

    @wraps(func)
    def wrapper(model: TeklaModel, component: Any, *args: Any, **kwargs: Any) -> Any:
        # Determine the number of objects in args
        selected_object = args[0]  # Supports only the first element

        current_plane = model.model.GetWorkPlaneHandler().GetCurrentTransformationPlane()
        local_plane = TransformationPlane(selected_object.GetCoordinateSystem())

        try:
            model.model.GetWorkPlaneHandler().SetCurrentTransformationPlane(local_plane)
            # Call the actual function
            result = func(model, component, *args, **kwargs)
        finally:
            # Reset transformation plane after execution
            model.model.GetWorkPlaneHandler().SetCurrentTransformationPlane(current_plane)

        return result

    return wrapper


def insert_detail(selected_object: ModelObject, component: BaseComponent, point: Point, reverse: bool = False) -> bool:
    """
    Inserts a custom detail component into a Tekla model at a specified point.
    """
    d = Detail()
    d.Name = component.name
    d.Number = component.number
    d.LoadAttributesFromFile(component.properties_set)
    d.UpVector = Vector(0, 0, 0)
    d.PositionType = PositionTypeEnum.MIDDLE_PLANE
    d.AutoDirectionType = AutoDirectionTypeEnum.AUTODIR_DETAIL
    d.DetailType = DetailTypeEnum.INTERMEDIATE_REVERSE if reverse else DetailTypeEnum.INTERMEDIATE
    d.SetPrimaryObject(selected_object)
    if component.properties:
        for key, value in component.properties.items():
            d.SetAttribute(key, value)
    d.SetReferencePoint(point)

    return d.Insert()


def insert_seam(primary_object: ModelObject, secondary_object: ModelObject, component: BaseComponent, point1: Point, point2: Point) -> bool:
    """
    Inserts a custom seam component into a Tekla model at a specified point.
    """
    s = Seam()
    s.Name = component.name
    s.Number = component.number
    s.LoadAttributesFromFile(component.properties_set)
    s.UpVector = Vector(0, 0, 0)
    s.AutoDirectionType = AutoDirectionTypeEnum.AUTODIR_DETAIL
    s.AutoPosition = True

    s.SetPrimaryObject(primary_object)
    s.SetSecondaryObject(secondary_object)
    if component.properties:
        for key, value in component.properties.items():
            s.SetAttribute(key, value)
    s.SetInputPositions(point1, point2)

    return s.Insert()


def insert_component(selected_object: ModelObject, component: BaseComponent) -> bool:
    """
    Inserts a component into a Tekla model to the specified object.
    """
    c = Component()
    c.Name = component.name
    c.Number = component.number
    c.LoadAttributesFromFile(component.properties_set)
    if component.properties:
        for key, value in component.properties.items():
            c.SetAttribute(key, value)
    ci = ComponentInput()
    ci.AddInputObject(selected_object)
    c.SetComponentInput(ci)
    return c.Insert()


@log_function_call
def get_wall_pairs(selected_objects: ModelObjectEnumerator) -> list[tuple[ModelObject, ModelObject]]:
    """
    Identifies and pairs walls based on their (X, Y) coordinates and Z-levels within a specified tolerance.

    The function:
    - Filters out non-wall objects.
    - Validates that there are exactly two floors.
    - Sorts the walls based on (X, Y, Z) coordinates.
    - Pairs walls into (bottom_wall, top_wall) if their X and Y coordinates match within precision.
    """
    # 50 mm tolerance
    TOLERANCE = 50.0

    def is_within_tolerance(value1: float, value2: float, tolerance: float) -> bool:
        """
        Returns True if values are within the defined tolerance range.
        """
        return abs(value1 - value2) <= tolerance

    selected_walls = []
    for selected_object in selected_objects:
        if isinstance(selected_object, Beam):
            selected_walls.append(selected_object)

    if len(selected_walls) < 2:
        raise ValueError("Less than two elements selected. Please select two elements.")

    # Step 1. Validate number of floors
    floor_set: set[float] = set()
    for wall in selected_walls:
        if round(wall.StartPoint.Z, 2) != round(wall.EndPoint.Z, 2):
            raise ValueError(f"Z-coordinate mismatch for the start point and end point in the wall {wall.Name}.")

        # Check if this Z-value is close to an existing one
        close_match_found = False
        for existing_z in floor_set:
            if is_within_tolerance(existing_z, wall.StartPoint.Z, TOLERANCE):
                # No need to check further
                close_match_found = True
                break

        # Add Z only if no close match is found
        if not close_match_found:
            floor_set.add(wall.StartPoint.Z)

    if len(floor_set) > 2:
        raise ValueError("More than two floors detected.")

    # Step 2. Sort walls by (X, Y) and Z-coordinates
    selected_walls.sort(key=lambda w: (w.StartPoint.X, w.StartPoint.Y, w.StartPoint.Z))

    # Step 3. Pair bottom_wall with top_wall
    wall_pairs: Any = []
    wall_dict: Any = {}

    for wall in selected_walls:
        xy_key = ((round(wall.StartPoint.X, 2), round(wall.StartPoint.Y, 2)), (round(wall.EndPoint.X, 2), round(wall.EndPoint.Y, 2)))

        # Find a matching wall within allowed tolerance
        matched_key = None
        for key in wall_dict:
            if (
                is_within_tolerance(xy_key[0][0], key[0][0], TOLERANCE)
                and is_within_tolerance(xy_key[0][1], key[0][1], TOLERANCE)
                and is_within_tolerance(xy_key[1][0], key[1][0], TOLERANCE)
                and is_within_tolerance(xy_key[1][1], key[1][1], TOLERANCE)
            ):
                matched_key = key
                break

        if matched_key:
            bottom_wall = wall_dict[matched_key]
            top_wall = wall

            # Ensure correct pairing before adding
            if bottom_wall != top_wall:
                # List of tuples as output
                wall_pairs.append((bottom_wall, top_wall))
                del wall_dict[matched_key]  # Remove matched pair from storage
        else:
            wall_dict[xy_key] = wall  # Store as potential bottom wall

    logger.debug("Wall pairs identified: %s", wall_pairs)
    return wall_pairs
