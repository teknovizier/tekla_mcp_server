"""
This module defines core data structures, enumerations, and models used in the project.
It includes classes representing different precast elements, component types, lifting anchors,
and wall joint configurations.
"""

import math

from enum import Enum
from pydantic import BaseModel, Field, PrivateAttr, conint, confloat, field_validator
from pydantic_core import PydanticCustomError
from typing import ClassVar


# Enums
class SelectionMode(Enum):
    """
    Represents selection modes for Tekla objects.
    """

    ASSEMBLY = "Assembly"
    MAIN_PART = "Main Part"


class UDASetMode(Enum):
    """
    Defines modes for applying UDAs to Tekla objects.
    """

    KEEP = "Keep Existing Values"
    OVERWRITE = "Overwrite Existing Values"


class StringMatchType(Enum):
    """
    Represents the matching types for String objects:
    """

    IS_EQUAL = "Is Equal"
    IS_NOT_EQUAL = "Is Not Equal"
    CONTAINS = "Contains"
    NOT_CONTAINS = "Not Contains"
    STARTS_WITH = "Starts With"
    NOT_STARTS_WITH = "Not Starts With"
    ENDS_WITH = "Ends With"
    NOT_ENDS_WITH = "Not Ends With"


class PrecastElementType(Enum):
    """
    Represents different types of precast concrete elements.
    """

    WALL = "Wall"
    SANDWICH_WALL = "Sandwich Wall"
    STAIR_FLIGHT = "Stair Flight"
    HCS = "Hollow Core Slab"
    MASSIVE_SLAB = "Massive Slab"
    COLUMN = "Column"
    BEAM = "Beam"
    FILIGREE_WALL = "Filigree Wall"
    FILIGREE_SLAB = "Filigree Slab"
    TRIBUNE = "Tribune"
    TT_SLAB = "TT Slab"
    BALCONY_SLAB = "Balcony Slab"
    STAIR_LANDING = "Stair Landing"
    CURVED_STAIR = "Curved Stair"


class ComponentType(Enum):
    """
    Represents different types of components in Tekla.
    """

    COMPONENT = "Component"
    CONNECTION = "Connection"
    CUSTOM_PART = "Custom Part"
    DETAIL = "Detail"
    SEAM = "Seam"


# Mappings
SELECTION_MODES = {e.value for e in SelectionMode}
UDA_SET_MODES = {e.value for e in UDASetMode}
STRING_MATCH_TYPES = {e.value for e in StringMatchType}
PRECAST_ELEMENT_TYPES = {e.value for e in PrecastElementType}
COMPONENT_TYPES = {e.value for e in ComponentType}


# Classes
class EnumWrapper(BaseModel):
    """
    A generic base model for validating string inputs against a predefined set of enum values.

    This class is designed to be subclassed by specific enum models (e.g., SelectionModeModel, UDASetModeModel),
    allowing consistent validation logic and error handling across multiple enum types.
    """

    value: str
    _valid_values: ClassVar[set[str]] = set()
    _error_code: ClassVar[str] = "invalid_enum"

    @field_validator("value", mode="after")
    @classmethod
    def validate_value(cls, v: str) -> str:
        """
        Validates and normalizes the input string.
        - Strips leading/trailing whitespace
        - Checks against allowed values
        """
        normalized = v.strip()
        if normalized not in cls._valid_values:
            raise PydanticCustomError(cls._error_code, f"Invalid value: {v}. Allowed: {', '.join(cls._valid_values)}")
        return normalized


class SelectionModeModel(EnumWrapper):
    """
    Represents a validated selection mode for Tekla objects.
    """

    _valid_values = SELECTION_MODES
    _error_code = "invalid_selection_mode"

    def to_enum(self) -> SelectionMode:
        """
        Converts the validated string value to a enum.
        """
        return SelectionMode(self.value)


class UDASetModeModel(EnumWrapper):
    """
    Represents a validated UDA set mode for Tekla objects.
    """

    _valid_values = UDA_SET_MODES
    _error_code = "invalid_uda_set_mode"

    def to_enum(self) -> UDASetMode:
        """
        Converts the validated string value to a enum.
        """
        return UDASetMode(self.value)


class StringMatchTypeModel(EnumWrapper):
    """
    Represents a validated string match type.
    """

    _valid_values = STRING_MATCH_TYPES
    _error_code = "invalid_string_match_mode"

    def to_enum(self) -> StringMatchType:
        """
        Converts the validated string value to a enum.
        """
        return StringMatchType(self.value)


class PrecastElementTypeModel(EnumWrapper):
    """
    Represents a validated precast element type.
    """

    _valid_values = PRECAST_ELEMENT_TYPES
    _error_code = "invalid_precast_element_type"

    def to_enum(self) -> PrecastElementType:
        """
        Converts the validated string value to a enum.
        """
        return PrecastElementType(self.value)


class ComponentTypeModel(EnumWrapper):
    """
    Represents a validated component type.
    """

    _valid_values = COMPONENT_TYPES
    _error_code = "invalid_component_type"

    def to_enum(self) -> ComponentType:
        """
        Converts the validated string value to a enum.
        """
        return ComponentType(self.value)


class LiftingAnchors(BaseModel):
    """
    Represents the configuration for Lifting Anchor components in the model.
    """

    remove_old_components: bool = Field(default=False, description="Set to true to remove existing components before placing new ones. False if they have to be kept intact.")
    safety_margin: conint(ge=0, le=50) = Field(default=5, description="Bearing capacity reserve in %. Must be between 0 and 50.")

    # Private attributes
    _name: str = PrivateAttr()
    _number: int = PrivateAttr()
    _component_type: ComponentType = PrivateAttr()

    def model_post_init(self, __context) -> None:
        """
        Initializes private attributes after model creation.
        """
        self._name = "Lifting Anchor"
        self._number = 30000080
        self._component_type = ComponentType.COMPONENT

    # Getter methods
    @property
    def name(self) -> str:
        """Returns `_name`"""
        return self._name

    @property
    def number(self) -> int:
        """Returns `_number`"""
        return self._number

    @property
    def component_type(self) -> str:
        """Returns `_component_type`"""
        return self._component_type

    @staticmethod
    def get_required_anchors(element_type: str, element_weight: float, safety_margin: int, anchor_types: dict) -> tuple[int, dict]:
        """
        Determines the required number of lifting anchors for an element based on its weight and safety margin.

        This function iteratively tries to find suitable lifting anchors, starting with 2 and increasing to 4
        if necessary. It adjusts the required lifting capacity by applying the specified safety margin and
        selects anchors from the provided anchor types that meet the capacity requirement.
        """
        valid_anchors = None
        n = 2  # Start with 2 anchors
        while n <= 4:
            required_capacity = element_weight / n / 1000

            # Adjust the capacity to account for reserve margin
            required_capacity += required_capacity * safety_margin / 100

            # Find anchors that meet the capacity requirement
            valid_anchors = {key: value for key, value in anchor_types.items() if value["capacity"] >= required_capacity and element_type in value["element_type"] and value["active"]}

            if valid_anchors:
                break  # Stop if valid anchors are found

            n += 2  # Try with 4 anchors next

        # If no valid anchors found, raise an exception
        if not valid_anchors:
            raise ValueError(f"No lifting anchors found for the element with total weight: {element_weight}.")

        return n, valid_anchors

    @staticmethod
    def calculate_anchor_placement(min_edge_distance: float, element_length: float, cog_x: float, number_of_anchors: int) -> tuple[float, float, float]:
        """
        Calculates the placement of lifting anchors while ensuring minimum edge distance constraints.

        This function determines the correct distances for placing anchors relative to the center of gravity (COG).
        It ensures that the distances are multiples of 5 and adjusts them dynamically to meet
        the minimum edge distance constraints. Additionally, it verifies that the required anchor distances
        do not exceed the total element length.
        """
        DOUBLE_ANCHOR_SPACING_LONG_WALL = 1000.0  # Double anchor spacing for long walls
        DOUBLE_ANCHOR_SPACING_SHORTER_WALL = 500.0  # Double anchor spacing for shorter walls

        # By default, place anchors at L/4 from COG
        distance_from_cog = element_length / 4
        distance_from_start = math.floor((cog_x - distance_from_cog) / 5) * 5
        distance_from_end = math.floor((element_length - cog_x - distance_from_cog) / 5) * 5

        required_length = distance_from_start + 2 * distance_from_cog + distance_from_end
        double_anchor_spacing = min_edge_distance  # Assume the distance between anchors to be equal to the minimum edge distance

        if number_of_anchors == 4:
            if (element_length - distance_from_start - distance_from_end - DOUBLE_ANCHOR_SPACING_LONG_WALL * 2) >= DOUBLE_ANCHOR_SPACING_LONG_WALL:
                double_anchor_spacing = DOUBLE_ANCHOR_SPACING_LONG_WALL
            elif (element_length - distance_from_start - distance_from_end - DOUBLE_ANCHOR_SPACING_SHORTER_WALL * 2) >= DOUBLE_ANCHOR_SPACING_SHORTER_WALL:
                double_anchor_spacing = DOUBLE_ANCHOR_SPACING_SHORTER_WALL

            # Ensure distance_from_start is not less than min_edge_distance
            if distance_from_start - double_anchor_spacing / 2 > min_edge_distance:
                distance_from_start -= double_anchor_spacing / 2

            # Ensure distance_from_end is not less than min_edge_distance
            if distance_from_end - double_anchor_spacing / 2 > min_edge_distance:
                distance_from_end -= double_anchor_spacing / 2

            required_length = distance_from_start + double_anchor_spacing * 3 + distance_from_end

        if required_length > element_length:
            # Reduce the distance from COG, but do not allow the distance between anchors be smaller than min_edge_distance
            while distance_from_start < min_edge_distance and distance_from_end < min_edge_distance:
                # Recalculate distances
                distance_from_start += 5
                distance_from_end += 5

                # Check the minimum distance between anchors
                gap = element_length - distance_from_start - distance_from_end
                if number_of_anchors == 4:
                    gap -= 2 * double_anchor_spacing
                if gap < double_anchor_spacing:
                    raise ValueError("Cannot place the anchors in the wall while keeping all the required distances. The element is too short.")

        return distance_from_start, distance_from_end, double_anchor_spacing


class CustomDetailComponent(BaseModel):
    """
    Base class for custom detail components.
    """

    name: str = Field(description="The name of the custom detail component.")

    # Private attributes
    _number: int = PrivateAttr()
    _component_type: ComponentType = PrivateAttr()

    def model_post_init(self, __context) -> None:
        """
        Initializes private attributes after model creation.
        """
        self._number = -1
        self._component_type = ComponentType.DETAIL

    # Getter methods
    @property
    def number(self) -> int:
        """Returns `_number`"""
        return self._number

    @property
    def component_type(self) -> str:
        """Returns `_component_type`"""
        return self._component_type
