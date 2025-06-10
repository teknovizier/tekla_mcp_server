"""
Module for utility classes and functions used for geometry manipulations.
"""

import json
import re
from functools import wraps
from pathlib import Path
from typing import Callable, Any, Union

from init import load_dlls, logger
from models import (
    StringMatchType,
    PrecastElementType,
    ComponentType,
    LiftingAnchors,
    CustomDetailComponent,
)

# Tekla OpenAPI imports
load_dlls()
from System.Collections import ArrayList
from Tekla.Structures import Identifier, PositionTypeEnum, DetailTypeEnum, AutoDirectionTypeEnum, TeklaStructuresDatabaseTypeEnum
from Tekla.Structures.Geometry3d import Point, Vector

from Tekla.Structures.Model import (
    Model,
    ModelObject,
    ModelObjectSelector as ModelSelector,
    ModelObjectEnumerator,
    Assembly,
    Operations,
    ModelObject,
    Beam,
    BooleanPart,
    PolyBeam,
    Position,
    TransformationPlane,
    Solid,
    ComponentInput,
    Component,
    Detail,
    Seam,
)
from Tekla.Structures.Model.UI import ModelObjectSelector, GraphicsDrawer, Color
from Tekla.Structures.Filtering import (
    FilterExpression,
    BinaryFilterOperatorType,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    NumericOperatorType,
    NumericConstantFilterExpression,
    StringOperatorType,
    StringConstantFilterExpression,
    BinaryFilterExpression,
)
from Tekla.Structures.Filtering.Categories import PartFilterExpressions, ObjectFilterExpressions


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

# Precast element types
with open(Path(__file__).parent.joinpath("config", "precast_element_types.json"), "r", encoding="utf-8") as file:
    precast_element_types = json.load(file)
    PRECAST_ELEMENT_TYPE_MAPPING = {getattr(PrecastElementType, key): value for key, value in precast_element_types.items()}

# Lifting anchor types
with open(Path(__file__).parent.joinpath("config", "lifting_anchor_types.json"), "r", encoding="utf-8") as file:
    LIFTING_ANCHOR_TYPES = json.load(file)


def get_tekla_model() -> Model:
    """
    Checks the connection status of the Tekla model and returns the Model object.
    """
    model = Model()
    # Check model connection status
    if not model.GetConnectionStatus():
        raise ConnectionError("Cannot connect to Tekla model. Please check that Tekla Structures is running and the model is opened.")

    return model


def get_cog_coordinates(element: ModelObject) -> Point:
    """
    Retrieves the center of gravity (COG) point for a given Tekla model object.
    """

    is_ok_x, cog_x = element.GetReportProperty("COG_X", float())
    is_ok_y, cog_y = element.GetReportProperty("COG_Y", float())
    is_ok_z, cog_z = element.GetReportProperty("COG_Z", float())

    if not (is_ok_x and is_ok_y and is_ok_z):
        raise AttributeError("Failed to retrieve COG for the object.")

    return Point(cog_x, cog_y, cog_z)


def get_model_and_selected_objects() -> tuple[Model, ModelObjectEnumerator]:
    """
    Returns the Tekla model and currently selected objects.

    Raises an error if no objects are selected.
    """
    model = get_tekla_model()
    selector = ModelObjectSelector()
    selected_objects = selector.GetSelectedObjects()

    if not selected_objects.GetSize():
        raise ValueError("No elements selected.")

    return model, selected_objects


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


def get_element_type_by_class(class_number: str) -> str | None:
    """
    Returns the element type name for a given class number using the provided mapping.
    """
    try:
        class_number = int(class_number)
    except (ValueError, TypeError):
        return None

    for element_type, class_numbers in PRECAST_ELEMENT_TYPE_MAPPING.items():
        if class_number in class_numbers:
            return element_type
    return None


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


def process_detail_or_component(selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: Model, component: Any, *args: Any, **kwargs: Any) -> int:
    """
    Processes a list of selected objects, applying a callback to each object that is an instance of Beam.
    Used for components that require only one primary object.
    """
    c_counter = 0
    for selected_object in selected_objects:
        if isinstance(selected_object, Beam):
            success = callback(model, component, selected_object, *args, **kwargs)
            if success:
                c_counter += success
    model.CommitChanges()
    return c_counter


def process_seam_or_connection(selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: Model, component: Any, *args: Any, **kwargs: Any) -> int:
    """
    Processes seams or connections between selected objects in the model.
    This function is intended for use with components that require two objects, such as wall joints.
    It validates the number of selected objects, ensuring that exactly two are selected.
    """
    # These types of components require two objects
    total_selected = selected_objects.GetSize()
    if total_selected == 1:
        raise ValueError("Only one element selected. Please select two elements.")
    if total_selected > 2:
        raise ValueError("More than two elements selected.")
    wall_pairs = get_wall_pairs(selected_objects)
    c_counter = 0
    for pair in wall_pairs:
        success = callback(model, component, pair[1], pair[0], *args, **kwargs)
        if success:
            c_counter += success
    model.CommitChanges()
    return c_counter


def remove_components(model: Model, component: Union[LiftingAnchors, CustomDetailComponent], *selected_objects: ModelObject) -> int:
    """
    Removes components with the specified number and name from the specified object in the Tekla model.
    """
    counter = 0
    for comp in selected_objects[0].GetComponents():  # Process only the first object
        if comp.Number == component.number and comp.Name == component.name:
            if comp.Delete():
                counter += 1

    return counter


def remove_lifting_anchors(model: Model, component: LiftingAnchors, *selected_objects: ModelObject) -> int:
    """
    Removes lifting anchors components.
    """
    # First remove all additional cuts
    for selected_object in selected_objects:
        boolean_part_enum = selected_object.GetBooleans()
        while boolean_part_enum.MoveNext():
            boolean_part = boolean_part_enum.Current
            operative_part = boolean_part.OperativePart
            if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT and operative_part.Name == "LIFTING_ANCHOR_RECESS":
                boolean_part.Delete()

    # Then remove components
    return remove_components(model, component, *selected_objects)


@ensure_transformation_plane
def insert_lifting_anchors(model: Model, component: LiftingAnchors, selected_object: ModelObject) -> int:
    """
    Inserts lifting anchors to the specified object in the Tekla model.
    """
    assembly = selected_object.GetAssembly()
    solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
    length = abs(solid.MaximumPoint.X - solid.MinimumPoint.X)
    width = abs(solid.MaximumPoint.Z - solid.MinimumPoint.Z)

    # Get cast unit total weight
    is_ok, weight = assembly.GetReportProperty("WEIGHT", float())
    if not is_ok:
        raise AttributeError("Failed to retrieve element weight.")

    # Assume the total element weight is increased by 5% to account for the weight of subassemblies and rebars
    total_weight = weight * 1.05

    # Get element type by class
    element_type = get_element_type_by_class(selected_object.Class)
    if not element_type:
        raise ValueError("Failed to get element type.")

    # Calculate the necessary number of anchors and get their type
    number_of_anchors, valid_anchors = LiftingAnchors.get_required_anchors(element_type, total_weight, component.safety_margin, LIFTING_ANCHOR_TYPES)

    # Get the first anchor's attributes
    first_anchor_key = next(iter(valid_anchors))
    first_anchor_attributes = valid_anchors[first_anchor_key]["attributes"]

    # Get initial COG X-coordinate
    cog = get_cog_coordinates(assembly)
    local_plane = TransformationPlane(selected_object.GetCoordinateSystem())
    local_cog = local_plane.TransformationMatrixToLocal.Transform(cog)

    min_edge_distance = valid_anchors[first_anchor_key]["min_edge_distance"]

    # Calculate the placement of lifting anchors
    distance_from_start, distance_from_end, double_anchor_spacing = LiftingAnchors.calculate_anchor_placement(min_edge_distance, length, local_cog.X, number_of_anchors)

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
    counter = insert_component(selected_object, component.number, component.name, attributes)
    if number_of_anchors == 4:
        # Add more anchors at distance_between_anchors from the first ones
        attributes["DistFromPartStart"] = distance_from_start + double_anchor_spacing
        attributes["DistFromPartFinish"] = distance_from_end + double_anchor_spacing
        counter += insert_component(selected_object, component.number, component.name, attributes)  # Add one more component

    # Add recesses where necessary
    def create_boolean_cut(x_position: float, y_position: float, cut_height: float, depth_offset: float, cut_length: float) -> bool:
        """
        Creates a boolean cut and applies it to the selected element.
        """
        # Define start and end points for the boolean cut
        cut_start = Point(x_position, y_position, solid.MinimumPoint.Z - 25.0)
        cut_end = Point(x_position, y_position, solid.MaximumPoint.Z + 25.0)

        # Create the boolean cutting part as a rectangular beam
        cutting_part = Beam()
        cutting_part.Class = BooleanPart.BooleanOperativeClassName  # Set as a boolean operator
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
            boolean_cut = BooleanPart()
            boolean_cut.Father = selected_object
            boolean_cut.SetOperativePart(cutting_part)
            boolean_cut.Type = BooleanPart.BooleanTypeEnum.BOOLEAN_CUT
            boolean_cut.Insert()

            cutting_part.Delete()  # Delete the temporary cutting object
            return True

        return False

    # Iterate through all boolean parts within the element, identify the recesses for lifting anchors, and create additional cuts where needed
    boolean_part_enum = selected_object.GetBooleans()
    while boolean_part_enum.MoveNext():
        boolean_part = boolean_part_enum.Current
        operative_part = boolean_part.OperativePart

        # Rely on these properties for proper identification:
        # - The type is BOOLEAN_CUT
        # - The Tekla class is 0
        # - The name is empty
        # - The profile starts with "PRMD"
        if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT and operative_part.Class == "0" and operative_part.Name == "" and operative_part.Profile.ProfileString.startswith("PRMD"):
            # Create the boolean part only if the recess is positioned below the highest Y coordinate of the element solid
            DEFAULT_OFFSET = 0.0  # Assume zero offset, should probbaly be offset = 25.0 if local_cog.X < operative_part.StartPoint.X else -25.0
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

    return counter


@ensure_transformation_plane
def insert_custom_detail_component(model: Model, component: CustomDetailComponent, selected_object: ModelObject) -> int:
    """
    Inserts a custom detail component to the specified object in the Tekla model.
    """
    counter = insert_detail(selected_object, component.number, component.name, selected_object.GetCoordinateSystem().Origin)
    return counter


def select_elements_by_filter(element_type: Union[list[int], PrecastElementType] = None, name: str = None, name_match_type: StringMatchType = StringMatchType.IS_EQUAL) -> int:
    """
    Selects elements in the Tekla model based on type, class, and name filters.
    """
    if not element_type and not name:
        raise ValueError("At least one argument (element type or Tekla class or name) must be provided.")

    model = get_tekla_model()
    filter_collection = BinaryFilterExpressionCollection()

    # Filter on parts
    filter_parts = BinaryFilterExpression(ObjectFilterExpressions.Type(), NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(TeklaStructuresDatabaseTypeEnum.PART))
    filter_collection.Add(BinaryFilterExpressionItem(filter_parts, BinaryFilterOperatorType.BOOLEAN_AND))

    # Filter on element types = Tekla classes
    if element_type:
        tekla_classes = []
        if isinstance(element_type, list):
            tekla_classes = element_type
        elif isinstance(element_type, PrecastElementType):
            tekla_classes = PRECAST_ELEMENT_TYPE_MAPPING.get(element_type, [])
        else:
            raise ValueError("Invalid input. Please enter a Tekla class number or element type.")

        filter_collection_class = BinaryFilterExpressionCollection()
        for tekla_class in tekla_classes:
            filter_class = BinaryFilterExpression(PartFilterExpressions.Class(), NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(tekla_class))
            filter_collection_class.Add(BinaryFilterExpressionItem(filter_class, BinaryFilterOperatorType.BOOLEAN_OR))
        filter_collection.Add(BinaryFilterExpressionItem(filter_collection_class))

    # Filter on name
    if name:
        match_type = STRING_MATCH_TYPE_MAPPING.get(name_match_type)
        filter_name = BinaryFilterExpression(PartFilterExpressions.Name(), match_type, StringConstantFilterExpression(name))
        filter_collection.Add(BinaryFilterExpressionItem(filter_name, BinaryFilterOperatorType.BOOLEAN_AND))

    tekla_objects = model.GetModelObjectSelector().GetObjectsByFilter(filter_collection)
    filtered_parts = ArrayList()
    for tekla_object in tekla_objects:
        filtered_parts.Add(tekla_object)

    selector = ModelObjectSelector()
    selector.Select(filtered_parts)
    assert tekla_objects.GetSize(), filtered_parts.Count
    return filtered_parts.Count


def get_selected_elements_as_assemblies(selected_objects: ModelObjectEnumerator) -> int:
    """
    Returns assemblies for the given selected objects.
    """
    # Process filtered parts
    filtered_parts = ArrayList()
    for selected_object in selected_objects:
        assembly = selected_object.GetAssembly()
        if isinstance(assembly, Assembly):
            filtered_parts.Add(assembly)

    selector = ModelObjectSelector()
    selector.Select(filtered_parts)

    return filtered_parts.Count


def draw_names_on_elements(selected_objects: ModelObjectEnumerator) -> int:
    """
    Draws names for the given Tekla model objects using the GraphicsDrawer.
    """
    drawer = GraphicsDrawer()
    count = 0
    for selected_object in selected_objects:
        if isinstance(selected_object, ModelObject):
            drawer.DrawText(get_cog_coordinates(selected_object), selected_object.Name, Color(0.0, 0.0, 0.0))
            count += 1
    return count


def insert_boolean_parts_as_real_parts(model: Model, selected_objects: ModelObjectEnumerator) -> int:
    """
    Inserts operative parts from boolean parts as real model objects.
    """
    inserted_count = 0
    for selected_object in selected_objects:
        boolean_part_enum = selected_object.GetBooleans()
        while boolean_part_enum.MoveNext():
            boolean_part = boolean_part_enum.Current
            if isinstance(boolean_part, BooleanPart):
                operative_part = boolean_part.OperativePart
                if operative_part.Insert():
                    inserted_count += 1
    if inserted_count > 0:
        model.CommitChanges()
    return inserted_count
