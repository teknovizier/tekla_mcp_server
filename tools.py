"""
Module for tools used for Tekla model operations.
"""

from typing import Any
from collections import defaultdict
from collections.abc import Callable
import json
import re

from init import load_dlls, logger
from models import (
    ELEMENT_TYPE_MAPPING,
    SelectionMode,
    UDASetMode,
    StringMatchType,
    ElementType,
    ComponentType,
    ElementLabel,
    LiftingAnchors,
    CustomDetailComponent,
    ElementTypeModel,
    ElementProperties,
)

from tekla_utils import (
    STRING_MATCH_TYPE_MAPPING,
    TeklaModel,
    TeklaModelObject,
    parse_template_attribute,
    get_wall_pairs,
    ensure_transformation_plane,
    insert_component,
    insert_detail,
    insert_seam,
)

# Tekla OpenAPI imports
load_dlls()
from System.Collections import ArrayList
from Tekla.Structures import Identifier, TeklaStructuresDatabaseTypeEnum
from Tekla.Structures.Geometry3d import AABB, Point
from Tekla.Structures.Model import (
    Model,
    ModelObject,
    ModelObjectEnumerator,
    Assembly,
    Beam,
    BooleanPart,
    Part,
    Position,
    Solid,
    TransformationPlane,
)
from Tekla.Structures.Model.UI import Color, GraphicsDrawer, ModelObjectSelector, ViewHandler
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
def process_detail_or_component(selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: Model, component: Any, *args: Any, **kwargs: Any) -> dict:
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
    model.CommitChanges()

    return {
        "status": "success" if processed_components else "error",
        "total_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "processed_components": processed_components,
    }


def process_seam_or_connection(selected_objects: ModelObjectEnumerator, callback: Callable[..., int], model: Model, component: Any, *args: Any, **kwargs: Any) -> dict:
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

    processed_elements = 0
    processed_components = 0

    wall_pairs = get_wall_pairs(selected_objects)
    for pair in wall_pairs:
        success = callback(model, component, pair[1], pair[0], *args, **kwargs)
        if success:
            processed_components += success
    model.CommitChanges()

    return {
        "status": "success" if processed_components else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "inserted_components": processed_components,
    }


# Tools functions
def remove_components(model: Model, component: LiftingAnchors | CustomDetailComponent, *selected_objects: ModelObject) -> int:
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
    # Get element type by class
    material, element_type = ElementTypeModel.get_element_type_by_class(selected_object.Class)
    if not material or not element_type:
        raise ValueError("Failed to get element type.")
    if material != "Concrete":
        raise ValueError(f"Unsupported material type: {material}. Only concrete elements are supported.")

    assembly = TeklaModelObject(selected_object.GetAssembly())
    solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
    length = abs(solid.MaximumPoint.X - solid.MinimumPoint.X)
    width = abs(solid.MaximumPoint.Z - solid.MinimumPoint.Z)

    # Get cast unit total weight
    weight = assembly.get_report_property("WEIGHT", float)

    # Assume the total element weight is increased by 5% to account for the weight of subassemblies and rebars
    total_weight = weight * 1.05

    # Calculate the necessary number of anchors and get their type
    number_of_anchors, valid_anchors = LiftingAnchors.get_required_anchors(element_type, total_weight, component.safety_margin)

    # Get the first anchor's attributes
    first_anchor_key = next(iter(valid_anchors))
    first_anchor_attributes = valid_anchors[first_anchor_key]["attributes"]

    # Get initial COG X-coordinate
    local_plane = TransformationPlane(selected_object.GetCoordinateSystem())
    local_cog = local_plane.TransformationMatrixToLocal.Transform(assembly.cog)

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


def select_elements_by_filter(
    element_type: int | list[int] | ElementType = None,
    name: str = None,
    name_match_type: StringMatchType = StringMatchType.IS_EQUAL,
    profile: str = None,
    profile_match_type: StringMatchType = StringMatchType.IS_EQUAL,
) -> dict:
    """
    Selects elements in the Tekla model based on type, class, and name filters.
    """
    if not element_type and not name:
        raise ValueError("At least one argument (element type or Tekla class or name) must be provided.")

    filter_collection = BinaryFilterExpressionCollection()

    # Filter on parts
    filter_parts = BinaryFilterExpression(ObjectFilterExpressions.Type(), NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(TeklaStructuresDatabaseTypeEnum.PART))
    filter_collection.Add(BinaryFilterExpressionItem(filter_parts, BinaryFilterOperatorType.BOOLEAN_AND))

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
            filter_class = BinaryFilterExpression(PartFilterExpressions.Class(), NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(tekla_class))
            filter_collection_class.Add(BinaryFilterExpressionItem(filter_class, BinaryFilterOperatorType.BOOLEAN_OR))
        filter_collection.Add(BinaryFilterExpressionItem(filter_collection_class))

    # Filter on name
    if name:
        match_type = STRING_MATCH_TYPE_MAPPING.get(name_match_type)
        filter_name = BinaryFilterExpression(PartFilterExpressions.Name(), match_type, StringConstantFilterExpression(name))
        filter_collection.Add(BinaryFilterExpressionItem(filter_name, BinaryFilterOperatorType.BOOLEAN_AND))

    # Filter on profile
    if profile:
        match_type = STRING_MATCH_TYPE_MAPPING.get(profile_match_type)
        filter_profile = BinaryFilterExpression(PartFilterExpressions.Profile(), match_type, StringConstantFilterExpression(profile))
        filter_collection.Add(BinaryFilterExpressionItem(filter_profile, BinaryFilterOperatorType.BOOLEAN_AND))

    objects_to_select = TeklaModel().get_objects_by_filter(filter_collection)
    TeklaModel.select_objects(objects_to_select)

    return {
        "status": "success" if objects_to_select.GetSize() else "error",
        "selected_elements": objects_to_select.GetSize(),
    }


def select_elements_by_filter_name(filter_name: str) -> dict:
    """
    Selects elements in the Tekla model based on the existing filter.
    """
    objects_to_select = TeklaModel().get_objects_by_filter(filter_name)
    TeklaModel.select_objects(objects_to_select)

    return {
        "status": "success" if objects_to_select.GetSize() else "error",
        "selected_elements": objects_to_select.GetSize(),
    }


def select_elements_by_guid(guids: list[str]) -> dict:
    """
    Selects elements in the Tekla model by their GUID.
    """
    model = TeklaModel().model

    objects_to_select = ArrayList()
    for guid in guids:
        obj = model.SelectModelObject(Identifier(guid))
        if obj is not None:
            objects_to_select.Add(obj)

    selector = ModelObjectSelector()
    selector.Select(objects_to_select)

    return {
        "status": "success" if objects_to_select.Count else "error",
        "selected_elements": objects_to_select.Count,
    }


def select_assemblies_or_main_parts(selected_objects: ModelObjectEnumerator, mode: SelectionMode) -> dict:
    """
    Returns assemblies or main parts for the given selected objects.
    """
    processed_elements = 0
    selected_object_types = ""
    # Process filtered parts
    filtered_parts = ArrayList()
    for selected_object in selected_objects:
        try:
            selected_object = TeklaModelObject(selected_object)
            assembly = selected_object.get_top_level_assembly()
        except TypeError:
            continue
        if mode == SelectionMode.ASSEMBLY:
            filtered_parts.Add(assembly.model_object)
            selected_object_types = "selected_assemblies"
        elif mode == SelectionMode.MAIN_PART:
            filtered_parts.Add(assembly.main_part.model_object)
            selected_object_types = "selected_main_parts"
        processed_elements += 1

    selector = ModelObjectSelector()
    selector.Select(filtered_parts)

    return {
        "status": "success" if filtered_parts.Count else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        selected_object_types: filtered_parts.Count,
    }


def draw_labels_on_elements(selected_objects: ModelObjectEnumerator, label: ElementLabel) -> dict:
    """
    Draws labels for the given Tekla model objects using the GraphicsDrawer.
    """
    drawer = GraphicsDrawer()
    processed_elements = 0
    drawn_labels = 0
    for selected_object in selected_objects:
        selected_object = TeklaModelObject(selected_object)
        labels = {
            ElementLabel.POSITION: selected_object.position,
            ElementLabel.GUID: selected_object.guid,
            ElementLabel.NAME: selected_object.name,
            ElementLabel.PROFILE: selected_object.profile,
            ElementLabel.MATERIAL: selected_object.material,
            ElementLabel.FINISH: selected_object.finish,
            ElementLabel.CLASS: selected_object.tekla_class,
        }
        text = labels.get(label, ElementLabel.NAME)
        if drawer.DrawText(selected_object.cog, text, Color(0.0, 0.0, 0.0)):
            drawn_labels += 1
        processed_elements += 1

    return {
        "status": "success" if drawn_labels else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "drawn_labels": drawn_labels,
    }


def zoom_to_selected_elements(selected_objects: ModelObjectEnumerator) -> dict:
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

    return {
        "status": "success" if result else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
    }


def insert_boolean_parts_as_real_parts(model: Model, selected_objects: ModelObjectEnumerator) -> dict:
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
        model.CommitChanges()

    return {
        "status": "success" if inserted_booleans else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "converted_booleans": inserted_booleans,
    }


def set_udas_on_elements(selected_objects: ModelObjectEnumerator, udas: dict[str, Any], mode: UDASetMode) -> dict:
    """
    Applies UDAs to a collection of Tekla model objects.
    """
    processed_elements = 0
    updated_attributes = 0
    skipped_attributes = 0
    for selected_object in selected_objects:
        selected_object = TeklaModelObject(selected_object)
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

    return {
        "status": "success" if updated_attributes else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "skipped_attributes": skipped_attributes,
        "updated_attributes": updated_attributes,
    }


def get_all_udas_for_elements(selected_objects: ModelObjectEnumerator) -> dict:
    """
    Retrieves GUID, position, and all UDAs for a collection of model objects.
    """
    processed_elements = 0
    assemblies: list[dict] = []
    parts: list[dict] = []

    def extract_metadata(selected_object: TeklaModelObject) -> dict:
        return {"guid": selected_object.guid, "position": selected_object.position, "udas": selected_object.get_all_user_properties()}

    for selected_object in selected_objects:
        selected_object = TeklaModelObject(selected_object)
        metadata = extract_metadata(selected_object)
        if selected_object.is_assembly:
            assemblies.append(metadata)
        elif selected_object.is_part:
            parts.append(metadata)
        processed_elements += 1

    return {
        "status": "success" if assemblies or parts else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "assemblies": assemblies,
        "parts": parts,
    }


def get_elements_props(selected_objects: ModelObjectEnumerator, custom_props_definitions: list[str]):
    """
    Extracts and serializes key element properties from a collection of model objects.
    """
    processed_elements = 0
    assemblies: list[ElementProperties] = []
    parts: list[ElementProperties] = []
    custom_props_errors = defaultdict(dict)

    def get_single_element_properties(selected_object: TeklaModelObject) -> ElementProperties:
        weight, _ = selected_object.weight
        custom_properties = []
        if custom_props_definitions:
            for custom_prop_definition in custom_props_definitions:
                try:
                    custom_property = parse_template_attribute(custom_prop_definition)
                    custom_property.value = selected_object.get_report_property(custom_property.name, custom_property.data_type)
                    custom_properties.append(custom_property)
                except Exception as e:
                    custom_props_errors[selected_object.guid][custom_prop_definition] = str(e)

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

    for selected_object in selected_objects:
        selected_object = TeklaModelObject(selected_object)
        metadata = get_single_element_properties(selected_object).model_copy(deep=True)
        if selected_object.is_assembly:
            assemblies.append(metadata)
        elif selected_object.is_part:
            parts.append(metadata)
        processed_elements += 1

    # JSON serialization
    serialized_assemblies = json.dumps([a.model_dump() for a in assemblies], ensure_ascii=False, indent=2)
    serialized_parts = json.dumps([a.model_dump() for a in parts], ensure_ascii=False, indent=2)

    return {
        "status": "success" if assemblies or parts else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "assemblies_list": serialized_assemblies,
        "parts_list": serialized_parts,
        "custom_properties_errors": custom_props_errors,
    }
