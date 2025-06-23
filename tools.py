"""
Module for tools used for Tekla model operations.
"""

from typing import Any, Callable, Union
import re

from init import load_dlls, logger
from models import (
    StringMatchType,
    PrecastElementType,
    ComponentType,
    LiftingAnchors,
    CustomDetailComponent,
)

from utils import (
    get_tekla_model,
    get_model_and_selected_objects,
    get_cog_coordinates,
    get_element_type_by_class,
    get_wall_pairs,
    ensure_transformation_plane,
    insert_component,
    insert_detail,
    insert_seam,
    ELEMENT_TYPE_MAPPING,
    STRING_MATCH_TYPE_MAPPING,
    LIFTING_ANCHOR_TYPES,
)

# Tekla OpenAPI imports
load_dlls()
from System.Collections import ArrayList
from Tekla.Structures import TeklaStructuresDatabaseTypeEnum
from Tekla.Structures.Geometry3d import Point
from Tekla.Structures.Model import (
    Model,
    ModelObject,
    ModelObjectEnumerator,
    Assembly,
    Beam,
    BooleanPart,
    Position,
    Solid,
    TransformationPlane,
)
from Tekla.Structures.Model.UI import ModelObjectSelector, GraphicsDrawer, Color
from Tekla.Structures.Filtering import (
    BinaryFilterOperatorType,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    NumericOperatorType,
    NumericConstantFilterExpression,
    StringConstantFilterExpression,
    BinaryFilterExpression,
)
from Tekla.Structures.Filtering.Categories import PartFilterExpressions, ObjectFilterExpressions


# Helper functions
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


# Tools functions
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
    material, element_type = get_element_type_by_class(selected_object.Class)
    if not material or not element_type:
        raise ValueError("Failed to get element type.")
    if material != "Concrete":
        raise ValueError(f"Unsupported material type: {material}. Only concrete elements are supported.")

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
            tekla_classes = []
            for material_types in ELEMENT_TYPE_MAPPING.values():
                if element_type.name in material_types:
                    tekla_classes.extend(material_types[element_type.name])
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
