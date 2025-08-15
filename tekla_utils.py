"""
Module for utility classes and functions used for geometry manipulations.
"""

import re

from functools import wraps
from typing import Any
from collections.abc import Callable, Iterable

from init import load_dlls, read_config, logger
from models import StringMatchType, ReportProperty

# Tekla OpenAPI imports
load_dlls()
from System.Collections import ArrayList
from Tekla.Structures import PositionTypeEnum, DetailTypeEnum, AutoDirectionTypeEnum
from Tekla.Structures.Geometry3d import Point, Vector

from Tekla.Structures.Model import (
    Model,
    ModelObject,
    ModelObjectEnumerator,
    ModelObjectSelector,
    Assembly,
    BooleanPart,
    Beam,
    PolyBeam,
    Position,
    TransformationPlane,
    ComponentInput,
    Component,
    Detail,
    Seam,
)
from Tekla.Structures.Model.UI import ModelObjectSelector as ModelObjectSelectorUI
from Tekla.Structures.Filtering import StringOperatorType, FilterExpression

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


# Classes
class TeklaModel:
    """
    A wrapper class around the Tekla Structures Model object.
    """

    def __init__(self):
        self.model = Model()
        if not self.model.GetConnectionStatus():
            raise ConnectionError("Cannot connect to Tekla model. Please check that Tekla Structures is running and the model is opened.")

    def get_all_objects(self) -> ModelObjectEnumerator:
        """
        Returns all objects in the model.
        """
        selector = ModelObjectSelector()
        return selector.GetAllObjects()

    def get_selected_objects(self) -> ModelObjectEnumerator:
        """
        Returns currently selected objects in the model.

        Raises:
            ValueError: If no objects are selected.
        """
        selector = ModelObjectSelectorUI()
        selected_objects = selector.GetSelectedObjects()

        if not selected_objects.GetSize():
            raise ValueError("No objects are currently selected in the model.")

        return selected_objects

    def get_objects_by_filter(self, model_filter: FilterExpression | str) -> ModelObjectEnumerator:
        """
        Returns objects in the model selected by the given selection filter definition.

        Raises:
            TypeError: If the provided filter type is not FilterExpression or str.
            ValueError: If no objects can be selected.
        """
        selector = ModelObjectSelector()
        if isinstance(model_filter, FilterExpression):
            objects_to_select = selector.GetObjectsByFilter(model_filter)
        elif isinstance(model_filter, str):
            objects_to_select = selector.GetObjectsByFilterName(model_filter)
        else:
            raise TypeError(f"Invalid filter type: {type(model_filter)}. Expected FilterExpression or str.")

        if not objects_to_select.GetSize():
            raise ValueError("No objects match the provided filter expression.")

        return objects_to_select

    @staticmethod
    def select_objects(model_objects: Iterable) -> bool:
        """
        Selects the given model objects in the model.
        """
        selector = ModelObjectSelectorUI()
        array_list = ArrayList()
        for model_object in model_objects:
            array_list.Add(model_object)

        return selector.Select(array_list)


def parse_template_attribute(attribute_name: str) -> ReportProperty:
    """
    Lazily loads and parses Tekla attribute definitions from the template file.

    On first call, this function reads the Tekla template attributes file once,
    parses all attribute definitions, and caches them in memory. Subsequent calls
    return cached results instantly without re-reading the file.
    """
    if not hasattr(parse_template_attribute, "_cache"):
        parse_template_attribute._cache = {}
        parse_template_attribute._loaded = False

    # Load file only once
    if not parse_template_attribute._loaded:
        config = read_config()
        with open(config["content_attributes_file_path"], "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("//") or stripped.startswith("[") or stripped.lower().startswith("name"):
                    continue

                first_split = re.split(r"\s", stripped, maxsplit=1)
                if len(first_split) < 2:
                    continue

                name = first_split[0].strip()
                remainder = first_split[1].strip()
                rest_parts = re.split(r"\s{2,}", remainder)
                while len(rest_parts) < 8:
                    rest_parts.append(None)

                dtype = rest_parts[0]
                unit = rest_parts[6] if rest_parts[6] != "*" else None

                parse_template_attribute._cache[name] = ReportProperty(name=name, data_type=dtype, unit=unit)

        parse_template_attribute._loaded = True

    # Return from cache
    if attribute_name in parse_template_attribute._cache:
        return parse_template_attribute._cache[attribute_name]

    raise ValueError(f"Attribute '{attribute_name}' not found.")


def get_report_property(element: ModelObject, property_name: str, property_type: type) -> str | int | float:
    """
    Retrieves a report property for a given Tekla model object.

    Raises:
        TypeError: If the provided property type is not str, int, or float.
        AttributeError: If the property retrieval fails for the given element.
    """
    if property_type not in (str, int, float):
        raise TypeError("Property type must be one of these types: str, int, float.")

    is_ok, value = element.GetReportProperty(property_name, property_type())
    if not is_ok:
        raise AttributeError(f"Failed to retrieve property `{property_name}` for the element with GUID `{element.Identifier.GUID.ToString()}`.")

    return value


def get_user_property(element: ModelObject, property_name: str, property_type: type) -> str | int | float:
    """
    Retrieves a user property for a given Tekla model object.

    Raises:
        TypeError: If the provided property type is not str, int, or float.
        AttributeError: If the property retrieval fails for the given element.
    """
    if property_type not in (str, int, float):
        raise TypeError("Property type must be one of these types: str, int, float.")

    is_ok, value = element.GetUserProperty(property_name, property_type())
    if not is_ok:
        raise AttributeError(f"Failed to retrieve property `{property_name}` for the element with GUID `{element.Identifier.GUID.ToString()}`.")

    return value


def get_cog_coordinates(element: ModelObject) -> Point:
    """
    Retrieves the center of gravity (COG) point for a given Tekla model object.
    """
    cog_x = get_report_property(element, "COG_X", float)
    cog_y = get_report_property(element, "COG_Y", float)
    cog_z = get_report_property(element, "COG_Z", float)

    return Point(cog_x, cog_y, cog_z)


def get_weight(element: ModelObject) -> tuple[float, float]:
    """
    Calculate the weight breakdown of a given object.

    This function returns two weight values:
    - The total weight of the element, including its main part, secondary parts, and subassemblies.
    - The total weight of all reinforcement bars associated with the main part, secondary parts, and any rebar subassemblies.
    """
    weight_main_part = 0.0
    weight_secondaries = 0.0
    weight_subassemblies = 0.0
    weight_rebars = 0.0

    # Get the main part
    mainpart = element.GetMainPart() if isinstance(element, Assembly) else element
    weight_main_part = get_report_property(mainpart, "WEIGHT", float)

    # Rebars on main part
    for rebar in mainpart.GetReinforcements():
        weight_rebar = get_report_property(rebar, "WEIGHT_TOTAL", float)
        weight_rebars += weight_rebar

    if isinstance(element, Assembly):
        # Secondary parts and their rebars
        for secondary in element.GetSecondaries():
            weight_secondary = get_report_property(secondary, "WEIGHT", float)
            weight_secondaries += weight_secondary

            for rebar in secondary.GetReinforcements():
                weight_rebar = get_report_property(rebar, "WEIGHT_TOTAL", float)
                weight_rebars += weight_rebar

        # Subassemblies
        for subassembly in element.GetSubAssemblies():
            weight_sub = get_report_property(subassembly, "WEIGHT", float)
            try:
                rebar_type = get_report_property(subassembly, "REBAR_ASSEMBLY_TYPE", str)
                assert rebar_type  # Must be truthy for rebar assemblies
                weight_rebars += weight_sub
            except AttributeError:
                weight_subassemblies += weight_sub

    total_parts_weight = weight_main_part + weight_secondaries + weight_subassemblies

    return total_parts_weight, weight_rebars


def ensure_transformation_plane(func: Callable[..., Any]) -> Any:
    """
    Sets the transformation plane before execution and restores it after.
    Supports functions with either one or two selected objects.
    """

    @wraps(func)
    def wrapper(model: Model, component: Any, *args: Any, **kwargs: Any) -> Any:
        # Determine the number of objects in args
        selected_object = args[0]  # Supports only the first elements

        current_plane = model.GetWorkPlaneHandler().GetCurrentTransformationPlane()
        local_plane = TransformationPlane(selected_object.GetCoordinateSystem())

        try:
            model.GetWorkPlaneHandler().SetCurrentTransformationPlane(local_plane)
            # Call the actual function
            result = func(model, component, *args, **kwargs)
        finally:
            # Reset transformation plane after execution
            model.GetWorkPlaneHandler().SetCurrentTransformationPlane(current_plane)

        return result

    return wrapper


def insert_detail(selected_object: ModelObject, number: int, name: str, point: Point, attributes: dict[str, Any] | None = None, reverse: bool = False) -> bool:
    """
    Inserts a custom detail component into a Tekla model at a specified point.
    """
    d = Detail()
    d.Name = name
    d.Number = number
    d.LoadAttributesFromFile("standard")
    d.UpVector = Vector(0, 0, 0)
    d.PositionType = PositionTypeEnum.MIDDLE_PLANE
    d.AutoDirectionType = AutoDirectionTypeEnum.AUTODIR_DETAIL
    d.DetailType = DetailTypeEnum.INTERMEDIATE_REVERSE if reverse else DetailTypeEnum.INTERMEDIATE
    d.SetPrimaryObject(selected_object)
    if attributes:
        for key, value in attributes.items():
            d.SetAttribute(key, value)
    d.SetReferencePoint(point)

    return d.Insert()


def insert_seam(primary_object: ModelObject, secondary_object: ModelObject, number: int, name: str, point1: Point, point2: Point, attributes: dict[str, Any] | None = None) -> bool:
    """
    Inserts a custom seam component into a Tekla model at a specified point.
    """
    s = Seam()
    s.Name = name
    s.Number = number
    s.LoadAttributesFromFile("standard")
    s.UpVector = Vector(0, 0, 0)
    s.AutoDirectionType = AutoDirectionTypeEnum.AUTODIR_DETAIL
    s.AutoPosition = True

    s.SetPrimaryObject(primary_object)
    s.SetSecondaryObject(secondary_object)
    if attributes:
        for key, value in attributes.items():
            s.SetAttribute(key, value)
    s.SetInputPositions(point1, point2)

    return s.Insert()


def insert_component(selected_object: ModelObject, number: int, name: str, attributes: dict[str, Any] | None = None) -> bool:
    """
    Inserts a component into a Tekla model to the specified object.
    """
    c = Component()
    c.Name = name
    c.Number = number
    c.LoadAttributesFromFile("standard")
    if attributes:
        for key, value in attributes.items():
            c.SetAttribute(key, value)
    ci = ComponentInput()
    ci.AddInputObject(selected_object)
    c.SetComponentInput(ci)
    return c.Insert()


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
    floor_set = set()
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
    wall_pairs = []
    wall_dict = {}

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

    return wall_pairs
