"""
Component handlers registry and implementations.

Provides a plugin-like system for handling specialized Tekla components.
Handlers are auto-discovered from base_components.json based on the 'handler' key.
"""

import math
import re
from typing import TYPE_CHECKING, Any

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import log_function_call

if TYPE_CHECKING:
    from tekla_mcp_server.models import BaseComponent
    from tekla_mcp_server.tekla.loader import BooleanPart, ModelObject


HANDLERS: dict[str, type] = {}


def register_handler(cls: type) -> type:
    """Decorator to register a handler class."""
    HANDLERS[cls.__name__] = cls
    return cls


class HandlerRegistry:
    """
    Registry for component handlers.

    Handlers are discovered from base_components.json config and instantiated
    based on the 'handler.name' field.
    """

    _instances: dict[str, Any] = {}

    @classmethod
    def get(cls, tekla_name: str) -> Any | None:
        """
        Get handler instance by Tekla component name.
        """
        # Return cached if already created
        if tekla_name in cls._instances:
            return cls._instances[tekla_name]

        # Find matching config
        base_components = get_config().base_components

        for config in base_components.values():
            handler_info = config.get("handler")
            if not handler_info:
                continue

            handler_name = handler_info.get("name")
            handler_config = handler_info.get("config")

            handler_cls = HANDLERS.get(handler_name)
            if not handler_cls:
                continue

            try:
                instance = handler_cls(handler_config) if handler_config else handler_cls()
                cls._instances[instance.tekla_name] = instance
            except Exception:
                logger.exception("Failed to instantiate handler '%s'", handler_name)

        return cls._instances.get(tekla_name)

    @classmethod
    def has_handler(cls, tekla_name: str) -> bool:
        """
        Check if a handler exists for the given Tekla component name.
        """
        return cls.get(tekla_name) is not None

    @classmethod
    def clear(cls) -> None:
        """
        Clear registry.
        """
        cls._instances.clear()


@register_handler
class LiftingAnchorsHandler:
    """
    Handler for Lifting Anchor component with intelligent anchor placement logic.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        if config:
            self.safety_margin = config.get("safety_margin", 5)
            self.anchor_types = config.get("anchor_types", {})
        else:
            self.safety_margin = 5
            self.anchor_types = {}
        self._context: dict[str, Any] = {}

    @property
    def tekla_name(self) -> str:
        return "Lifting Anchor"

    @property
    def safety_margin_prop(self) -> int:
        return self.safety_margin

    def pre_process(
        self,
        component: "BaseComponent",
        selected_object: "ModelObject",
    ) -> dict[str, Any]:
        """
        Pre-process hook: calculates anchor placement and sets component properties.

        Args:
            component: Component to configure
            selected_object: Target Tekla object

        Returns:
            Context dict with processing data (number_of_anchors, etc.)
        """
        from tekla_mcp_server.models import ElementTypeModel
        from tekla_mcp_server.tekla.loader import Solid, TransformationPlane
        from tekla_mcp_server.tekla.model_object import wrap_model_object

        weight_factor = 1.05
        recess_width_offset = 100.0

        material, element_type = ElementTypeModel.get_element_type_by_class(selected_object.Class)
        if material != "MATERIAL_CONCRETE":
            raise ValueError(f"Unsupported material type: {material}. Only concrete elements are supported.")

        assembly = wrap_model_object(selected_object.GetAssembly())
        if assembly is None:
            raise ValueError(f"Could not wrap assembly for selected object '{selected_object.Identifier.ID}'.")
        solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
        length = abs(solid.MaximumPoint.X - solid.MinimumPoint.X)
        width = abs(solid.MaximumPoint.Z - solid.MinimumPoint.Z)

        total_weight = float(assembly.get_report_property("WEIGHT")) * weight_factor
        logger.debug("Assuming total weight: %s kg", total_weight)

        number_of_anchors, valid_anchors = self.get_required_anchors(element_type, total_weight)

        first_anchor_key = next(iter(valid_anchors))
        first_anchor_attributes = valid_anchors[first_anchor_key]["attributes"]
        logger.info("Number of anchors required: %s. Selected anchor type: %s", number_of_anchors, first_anchor_key)

        local_plane = TransformationPlane(selected_object.GetCoordinateSystem())
        local_cog = local_plane.TransformationMatrixToLocal.Transform(assembly.cog)

        min_edge_distance = valid_anchors[first_anchor_key]["min_edge_distance"]
        distance_from_start, distance_from_end, double_anchor_spacing = self.calculate_anchor_placement(min_edge_distance, length, local_cog.X, number_of_anchors)
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

        self._context = {
            "number_of_anchors": number_of_anchors,
            "distance_from_start": distance_from_start,
            "distance_from_end": distance_from_end,
            "double_anchor_spacing": double_anchor_spacing,
            "local_cog": local_cog,
            "selected_object": selected_object,
        }

        return self._context

    def post_process(
        self,
        component: "BaseComponent",
        selected_object: "ModelObject",
        initial_count: int,
        context: dict[str, Any],
    ) -> int:
        """
        Post-process hook: handles additional anchor insertion for 4-anchor config and creates recesses.

        Args:
            component: Component that was inserted
            selected_object: Target Tekla object
            initial_count: Initial count of inserted components
            context: Context from pre_process

        Returns:
            Total count of inserted components
        """
        from tekla_mcp_server.tekla.utils import insert_component

        number_of_anchors = context.get("number_of_anchors", 0)
        distance_from_start = context.get("distance_from_start", 0)
        distance_from_end = context.get("distance_from_end", 0)
        double_anchor_spacing = context.get("double_anchor_spacing", 0)
        local_cog = context.get("local_cog")

        counter = initial_count

        if number_of_anchors == 4:
            updated_properties = {
                "DistFromPartStart": distance_from_start + double_anchor_spacing,
                "DistFromPartFinish": distance_from_end + double_anchor_spacing,
            }
            component.update_properties(updated_properties)
            counter += int(insert_component(selected_object, component))
            logger.debug("Inserted additional anchors for 4-anchor configuration. Total: %s", counter)

        self._process_recesses(selected_object, local_cog)
        logger.info("Total lifting anchor components inserted: %s", counter)

        return counter

    def pre_remove(self, selected_objects: tuple["ModelObject", ...]) -> int:
        """
        Pre-remove hook: cleans up associated parts before component removal.

        Args:
            selected_objects: Objects to clean up

        Returns:
            Number of parts removed
        """
        from tekla_mcp_server.tekla.loader import BooleanPart

        counter = 0
        for selected_object in selected_objects:
            for boolean_part in self._iterate_boolean_parts(selected_object):
                if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT and boolean_part.OperativePart.Name == "LIFTING_ANCHOR_RECESS":
                    if boolean_part.Delete():
                        counter += 1
        logger.debug("Total lifting anchor recess boolean cuts removed: %s", counter)
        return counter

    def _iterate_boolean_parts(self, selected_object: "ModelObject") -> list["BooleanPart"]:
        """Iterates through boolean parts of an object."""
        from tekla_mcp_server.tekla.utils import iterate_boolean_parts

        return list(iterate_boolean_parts(selected_object))

    def _process_recesses(self, selected_object: "ModelObject", local_cog: Any) -> None:
        """Creates boolean cuts for lifting anchor recesses."""
        from tekla_mcp_server.tekla.loader import BooleanPart, Solid

        default_offset = 0.0
        default_cut_length = 300.0
        min_ledge_height = 100.0
        magic_offset = 0.99

        for boolean_part in self._iterate_boolean_parts(selected_object):
            operative_part = boolean_part.OperativePart

            if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT and operative_part.Class == "0" and operative_part.Name == "" and operative_part.Profile.ProfileString.startswith("PRMD"):
                solid = selected_object.GetSolid(Solid.SolidCreationTypeEnum.RAW)
                ledge_height = solid.MaximumPoint.Y - operative_part.StartPoint.Y
                if ledge_height > min_ledge_height:
                    self._create_boolean_cut(selected_object, operative_part.StartPoint.X, operative_part.StartPoint.Y, ledge_height, default_offset, default_cut_length)
                elif ledge_height:
                    match = re.search(r"PRMD(\d+)", operative_part.Profile.ProfileString)
                    if match:
                        cut_length = float(match.group(1)) + magic_offset
                        self._create_boolean_cut(selected_object, operative_part.StartPoint.X, operative_part.StartPoint.Y, ledge_height, default_offset, cut_length)

    def _create_boolean_cut(
        self,
        selected_object: "ModelObject",
        x_position: float,
        y_position: float,
        cut_height: float,
        depth_offset: float,
        cut_length: float,
    ) -> bool:
        """Creates a boolean cut on the selected object."""
        from tekla_mcp_server.tekla.loader import Beam, Point, Position, Solid
        from tekla_mcp_server.tekla.model_object import wrap_model_object

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
            if target_object is None:
                raise ValueError(f"Could not wrap target object for boolean cut (ID: {selected_object.Identifier.ID}).")
            if cutter_object is None:
                raise ValueError(f"Could not wrap cutting part for boolean cut (ID: {cutting_part.Identifier.ID}).")
            return target_object.add_cut(cutter_object, True)
        logger.warning("Failed to insert boolean cut part")
        return False

    @log_function_call
    def get_required_anchors(self, element_type: str, element_weight: float, anchor_types: dict | None = None) -> tuple[int, dict]:
        """
        Determines the required number of lifting anchors for an element based on its weight and safety margin.

        This function iteratively tries to find suitable lifting anchors, starting with 2 and increasing to 4
        if necessary. It adjusts the required lifting capacity by applying the specified safety margin and
        selects anchors from the provided anchor types that meet the capacity requirement.
        """
        kg_to_ton = 1000
        percent = 100

        if anchor_types is None:
            anchor_types = self.anchor_types
        valid_anchors = None
        n = 2
        while n <= 4:
            required_capacity = element_weight / n / kg_to_ton

            required_capacity += required_capacity * self.safety_margin / percent

            valid_anchors = {key: value for key, value in anchor_types.items() if value["capacity"] >= required_capacity and element_type in value["element_type"] and value["active"]}

            if valid_anchors:
                logger.debug("Found valid anchors for n=%s: %s", n, list(valid_anchors.keys()))
                break

            n += 2

        if not valid_anchors:
            raise ValueError(f"No lifting anchors found for the element with total weight: {element_weight}.")

        return n, valid_anchors

    @log_function_call
    def calculate_anchor_placement(
        self,
        min_edge_distance: float,
        element_length: float,
        cog_x: float,
        number_of_anchors: int,
    ) -> tuple[float, float, float]:
        """
        Calculates the placement of lifting anchors while ensuring minimum edge distance constraints.

        This function determines the correct distances for placing anchors relative to the center of gravity (COG).
        It ensures that the distances are multiples of 5 and adjusts them dynamically to meet
        the minimum edge distance constraints. Additionally, it verifies that the required anchor distances
        do not exceed the total element length.
        """
        double_anchor_spacing_long_wall = 1000.0
        double_anchor_spacing_shorter_wall = 500.0
        rounding_multiple = 5

        distance_from_cog = element_length / 4
        distance_from_start: float = math.floor((cog_x - distance_from_cog) / rounding_multiple) * rounding_multiple
        distance_from_end: float = math.floor((element_length - cog_x - distance_from_cog) / rounding_multiple) * rounding_multiple

        required_length = distance_from_start + 2 * distance_from_cog + distance_from_end
        double_anchor_spacing = min_edge_distance

        if number_of_anchors == 4:
            if (element_length - distance_from_start - distance_from_end - double_anchor_spacing_long_wall * 2) >= double_anchor_spacing_long_wall:
                double_anchor_spacing = double_anchor_spacing_long_wall
            elif (element_length - distance_from_start - distance_from_end - double_anchor_spacing_shorter_wall * 2) >= double_anchor_spacing_shorter_wall:
                double_anchor_spacing = double_anchor_spacing_shorter_wall

            if distance_from_start - double_anchor_spacing / 2 > min_edge_distance:
                distance_from_start -= double_anchor_spacing / 2

            if distance_from_end - double_anchor_spacing / 2 > min_edge_distance:
                distance_from_end -= double_anchor_spacing / 2

            required_length = distance_from_start + double_anchor_spacing * 3 + distance_from_end

        if required_length > element_length:
            logger.debug(
                "Required anchor distances exceed element length: element_length=%s, required_length=%s. Adjusting distances.",
                element_length,
                required_length,
            )
            while distance_from_start < min_edge_distance and distance_from_end < min_edge_distance:
                distance_from_start += rounding_multiple
                distance_from_end += rounding_multiple

                gap = element_length - distance_from_start - distance_from_end
                if number_of_anchors == 4:
                    gap -= 2 * double_anchor_spacing
                if gap < double_anchor_spacing:
                    raise ValueError("Cannot place the anchors in the wall while keeping all the required distances. The element is too short.")

        return distance_from_start, distance_from_end, double_anchor_spacing
