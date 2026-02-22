"""
This module defines core data structures, enumerations, and models used in the project.
It includes classes representing different elements, component types, lifting anchors,
and wall joint configurations.
"""

import json
import math
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, Field, PrivateAttr, field_validator, field_serializer
from pydantic_core import PydanticCustomError

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import log_function_call


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


class NumericMatchType(Enum):
    """
    Represents the matching types for Numeric objects:
    """

    IS_EQUAL = "Is Equal"
    IS_NOT_EQUAL = "Is Not Equal"
    SMALLER_THAN = "Smaller Than"
    SMALLER_OR_EQUAL = "Smaller Or Equal"
    GREATER_THAN = "Greater Than"
    GREATER_OR_EQUAL = "Greater Or Equal"


class StandardStringFilterKey(str, Enum):
    """
    Valid keys for standard string filters.
    These correspond to built-in Tekla properties.
    """

    NAME = "name"
    PROFILE = "profile"
    MATERIAL = "material"
    FINISH = "finish"
    PHASE = "phase"


class ElementType(Enum):
    """
    Represents different types of elements in Tekla.
    """

    # Concrete
    CONCRETE_WALL = "Wall"
    CONCRETE_SANDWICH_WALL = "Sandwich Wall"
    CONCRETE_STAIR_FLIGHT = "Stair Flight"
    CONCRETE_HCS = "Hollow Core Slab"
    CONCRETE_MASSIVE_SLAB = "Massive Slab"
    CONCRETE_COLUMN = "Column"
    CONCRETE_BEAM = "Beam"
    CONCRETE_FILIGREE_WALL = "Filigree Wall"
    CONCRETE_FILIGREE_SLAB = "Filigree Slab"
    CONCRETE_TRIBUNE = "Tribune"
    CONCRETE_TT_SLAB = "TT Slab"
    CONCRETE_BALCONY_SLAB = "Balcony Slab"
    CONCRETE_STAIR_LANDING = "Stair Landing"
    CONCRETE_CURVED_STAIR = "Curved Stair"

    # Steel
    STEEL_BEAM = "Steel Beam"
    STEEL_COLUMN = "Steel Column"
    STEEL_TRUSS = "Steel Truss"
    STEEL_BRACE = "Steel Brace"


class ComponentType(Enum):
    """
    Represents different types of components in Tekla.
    """

    COMPONENT = "Component"
    CONNECTION = "Connection"
    CUSTOM_PART = "Custom Part"
    DETAIL = "Detail"
    SEAM = "Seam"


class ElementLabel(Enum):
    """
    Represents the supported label types that can be drawn in the Tekla view.
    """

    POSITION = "Position"
    GUID = "GUID"
    NAME = "Name"
    PROFILE = "Profile"
    MATERIAL = "Material"
    FINISH = "Finish"
    CLASS = "Class"
    WEIGHT = "Weight"
    CUSTOM = "Custom"


# Mappings
SELECTION_MODES = {e.value for e in SelectionMode}
UDA_SET_MODES = {e.value for e in UDASetMode}
ELEMENT_TYPES = {e.value for e in ElementType}
COMPONENT_TYPES = {e.value for e in ComponentType}
ELEMENT_LABELS = {e.value for e in ElementLabel}


def get_element_type_mapping() -> dict[str, dict[str, list[int]]]:
    """Returns element type mapping from config."""
    return get_config().element_types


def get_lifting_anchor_types() -> dict[str, Any]:
    """Returns lifting anchor types from config."""
    return get_config().lifting_anchor_types


def get_base_components() -> dict[str, Any]:
    """Returns base components from config."""
    return get_config().base_components


def get_class_to_element() -> dict[int, tuple[str, str]]:
    """Returns class to element mapping."""
    return get_config().class_to_element


def get_custom_properties_schema(component_name: str) -> dict[str, dict[str, str]] | None:
    """
    Returns the custom_properties schema for a given component name.

    Args:
        component_name: The name of the component

    Returns:
        Dictionary of custom properties with their descriptions and types, or None if not defined
    """
    component = get_base_components().get(component_name)
    if component:
        return component.get("custom_properties")
    return None


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


class StringFilterCondition(BaseModel):
    """
    Encapsulates a string filter condition with match type and value.
    Validates match_type against valid StringMatchType values.
    """

    match_type: str
    value: str

    @field_validator("match_type", mode="before")
    @classmethod
    def validate_match_type(cls, v: str) -> str:
        valid_values = {e.value for e in StringMatchType}
        if v not in valid_values:
            raise PydanticCustomError(
                "invalid_string_match_mode",
                f"Invalid match_type '{v}'. Must be one of: {valid_values}",
            )
        return v


class StringFilterOption(BaseModel):
    """
    Encapsulates string filter conditions for a property.
    Supports single condition or list of conditions with configurable logic.
    """

    conditions: StringFilterCondition | list[StringFilterCondition]
    logic: str = "OR"

    @field_validator("logic", mode="before")
    @classmethod
    def validate_logic(cls, v: str) -> str:
        valid_values = {"AND", "OR"}
        if v not in valid_values:
            raise PydanticCustomError(
                "invalid_filter_logic",
                f"Invalid logic '{v}'. Must be one of: {valid_values}",
            )
        return v

    def to_dict(self) -> dict[str, str] | list[dict[str, str]]:
        """Converts conditions to dict format for tool function."""
        if isinstance(self.conditions, list):
            return [{"match_type": cond.match_type, "value": cond.value} for cond in self.conditions]
        return {"match_type": self.conditions.match_type, "value": self.conditions.value}

    def get_values(self) -> str | list[str]:
        """Extracts value(s) from conditions."""
        if isinstance(self.conditions, list):
            return [c.value for c in self.conditions]
        return self.conditions.value

    def get_match_type(self) -> str:
        """Extracts match_type from first condition."""
        if isinstance(self.conditions, list):
            return self.conditions[0].match_type
        return self.conditions.match_type

    def get_logic(self) -> str:
        """Returns the logic mode (AND/OR)."""
        return self.logic


class NumericFilterCondition(BaseModel):
    """
    Encapsulates a numeric filter condition with match type and value.
    Validates match_type against valid NumericMatchType values.
    """

    match_type: str
    value: float

    @field_validator("match_type", mode="before")
    @classmethod
    def validate_match_type(cls, v: str) -> str:
        valid_values = {e.value for e in NumericMatchType}
        if v not in valid_values:
            raise PydanticCustomError(
                "invalid_numeric_match_mode",
                f"Invalid match_type '{v}'. Must be one of: {valid_values}",
            )
        return v


class NumericFilterOption(BaseModel):
    """
    Encapsulates numeric filter conditions for a property.
    Supports single condition or list of conditions with configurable logic.
    """

    conditions: NumericFilterCondition | list[NumericFilterCondition]
    logic: str = "AND"

    @field_validator("logic", mode="before")
    @classmethod
    def validate_logic(cls, v: str) -> str:
        valid_values = {"AND", "OR"}
        if v not in valid_values:
            raise PydanticCustomError(
                "invalid_filter_logic",
                f"Invalid logic '{v}'. Must be one of: {valid_values}",
            )
        return v

    def to_dict(self) -> dict[str, Any] | list[dict[str, Any]]:
        """Converts conditions to dict format for tool function."""
        if isinstance(self.conditions, list):
            return [{"match_type": cond.match_type, "value": cond.value} for cond in self.conditions]
        return {"match_type": self.conditions.match_type, "value": self.conditions.value}

    def get_logic(self) -> str:
        """Returns the logic mode (AND/OR)."""
        return self.logic


class ElementTypeModel(EnumWrapper):
    """
    Represents a validated element type.
    """

    _valid_values = ELEMENT_TYPES
    _error_code = "invalid_element_type"

    def to_enum(self) -> ElementType:
        """
        Converts the validated string value to a enum.
        """
        return ElementType(self.value)

    @staticmethod
    def get_element_type_by_class(class_number: str | int) -> tuple[str, str]:
        """
        Returns (material, element type name) for a given class number using the mapping.
        """
        if isinstance(class_number, str):
            class_number = int(class_number)
        result = get_class_to_element().get(class_number)
        if result is None:
            raise ValueError(f"Class number {class_number} not found in the list of allowed classes.")
        return result


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


class ElementLabelModel(EnumWrapper):
    """
    Represents a validated element label.
    """

    _valid_values = ELEMENT_LABELS
    _error_code = "invalid_element_label"

    def to_enum(self) -> ElementLabel:
        """
        Converts the validated string value to a enum.
        """
        return ElementLabel(self.value)


class BaseComponent(BaseModel):
    """
    Base class for Tekla components.
    """

    name: str = Field(description="The name of the Tekla component.")
    properties_set: str | None = Field(default="standard", description="The name of the Tekla component properties set to use (`standard` by default).")
    custom_properties: dict[str, Any] | str | None = Field(default=None, description="Custom properties to apply to the component. Can be a dictionary or JSON string.")

    # Private properties
    _number: int = PrivateAttr()
    _component_type: ComponentType = PrivateAttr()
    _properties: dict[str, Any] | None = PrivateAttr(default=None)

    def model_post_init(self, __context) -> None:
        """
        Initializes private attributes after model creation.
        """
        self._number = get_base_components().get(self.name, {}).get("number", -1)
        self._component_type = ComponentType.DETAIL if self._number == -1 else ComponentType.COMPONENT  # Default to custom detail component

        if self.properties_set is None:
            self.properties_set = "standard"

        # Initialize properties from custom_properties if provided
        if self.custom_properties:
            if isinstance(self.custom_properties, str):
                try:
                    custom_props = json.loads(self.custom_properties)
                    if not isinstance(custom_props, dict):
                        raise ValueError("custom_properties JSON must parse to a dictionary")
                    if self._properties is None:
                        self._properties = {}
                    self._properties.update(custom_props)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON in custom_properties: {e}") from e
            elif isinstance(self.custom_properties, dict):
                if self._properties is None:
                    self._properties = {}
                self._properties.update(self.custom_properties)
            else:
                raise TypeError("custom_properties must be a dictionary or JSON string")

    # Getters
    @property
    def number(self) -> int:
        """Returns `_number`"""
        return self._number

    @property
    def component_type(self) -> ComponentType:
        """Returns `_component_type`"""
        return self._component_type

    @property
    def properties(self) -> dict[str, Any] | None:
        """Returns `_properties`"""
        return self._properties

    # Setters
    def set_properties(self, properties: dict[str, Any]) -> None:
        """
        Replaces the entire properties dictionary.
        """
        self._properties = properties

    def update_properties(self, updates: dict[str, Any]) -> None:
        """
        Adds or updates multiple properties at once.
        Creates the dictionary if the dictionary doesn't exist yet.
        """
        if self._properties is None:
            self._properties = {}
        self._properties.update(updates)


class LiftingAnchorsComponent(BaseComponent):
    """
    Specialized component for Lifting Anchor with intelligent behavior.
    """

    name: str = Field(default="Lifting Anchor", init=False, description="The name of the Tekla component. Always `Lifting Anchor`.")

    # Private attributes
    _safety_margin: int = PrivateAttr()

    def __init__(self, **data):
        data["name"] = "Lifting Anchor"
        super().__init__(**data)

    def model_post_init(self, __context):
        self._safety_margin = get_base_components().get(self.name, {}).get("safety_margin", 5)
        super().model_post_init(__context)

    # Getters
    @property
    def safety_margin(self) -> int:
        """Returns `_safety_margin`"""
        return self._safety_margin

    @staticmethod
    @log_function_call
    def get_required_anchors(element_type: str, element_weight: float, safety_margin: int, anchor_types: dict | None = None) -> tuple[int, dict]:
        """
        Determines the required number of lifting anchors for an element based on its weight and safety margin.

        This function iteratively tries to find suitable lifting anchors, starting with 2 and increasing to 4
        if necessary. It adjusts the required lifting capacity by applying the specified safety margin and
        selects anchors from the provided anchor types that meet the capacity requirement.
        """
        kg_to_ton = 1000
        percent = 100

        if anchor_types is None:
            anchor_types = get_lifting_anchor_types()
        valid_anchors = None
        n = 2  # Start with 2 anchors
        while n <= 4:
            required_capacity = element_weight / n / kg_to_ton

            # Adjust the capacity to account for reserve margin
            required_capacity += required_capacity * safety_margin / percent

            # Find anchors that meet the capacity requirement
            valid_anchors = {key: value for key, value in anchor_types.items() if value["capacity"] >= required_capacity and element_type in value["element_type"] and value["active"]}

            if valid_anchors:
                logger.debug("Found valid anchors for n=%s: %s", n, list(valid_anchors.keys()))
                break  # Stop if valid anchors are found

            n += 2  # Try with 4 anchors next

        # If no valid anchors found, raise an exception
        if not valid_anchors:
            raise ValueError(f"No lifting anchors found for the element with total weight: {element_weight}.")

        return n, valid_anchors

    @staticmethod
    @log_function_call
    def calculate_anchor_placement(min_edge_distance: float, element_length: float, cog_x: float, number_of_anchors: int) -> tuple[float, float, float]:
        """
        Calculates the placement of lifting anchors while ensuring minimum edge distance constraints.

        This function determines the correct distances for placing anchors relative to the center of gravity (COG).
        It ensures that the distances are multiples of 5 and adjusts them dynamically to meet
        the minimum edge distance constraints. Additionally, it verifies that the required anchor distances
        do not exceed the total element length.
        """
        double_anchor_spacing_long_wall = 1000.0  # Double anchor spacing for long walls
        double_anchor_spacing_shorter_wall = 500.0  # Double anchor spacing for shorter walls
        rounding_multiple = 5

        # By default, place anchors at L/4 from COG
        distance_from_cog = element_length / 4
        distance_from_start: float = math.floor((cog_x - distance_from_cog) / rounding_multiple) * rounding_multiple
        distance_from_end: float = math.floor((element_length - cog_x - distance_from_cog) / rounding_multiple) * rounding_multiple

        required_length = distance_from_start + 2 * distance_from_cog + distance_from_end
        double_anchor_spacing = min_edge_distance  # Assume the distance between anchors to be equal to the minimum edge distance

        if number_of_anchors == 4:
            if (element_length - distance_from_start - distance_from_end - double_anchor_spacing_long_wall * 2) >= double_anchor_spacing_long_wall:
                double_anchor_spacing = double_anchor_spacing_long_wall
            elif (element_length - distance_from_start - distance_from_end - double_anchor_spacing_shorter_wall * 2) >= double_anchor_spacing_shorter_wall:
                double_anchor_spacing = double_anchor_spacing_shorter_wall

            # Ensure distance_from_start is not less than min_edge_distance
            if distance_from_start - double_anchor_spacing / 2 > min_edge_distance:
                distance_from_start -= double_anchor_spacing / 2

            # Ensure distance_from_end is not less than min_edge_distance
            if distance_from_end - double_anchor_spacing / 2 > min_edge_distance:
                distance_from_end -= double_anchor_spacing / 2

            required_length = distance_from_start + double_anchor_spacing * 3 + distance_from_end

        if required_length > element_length:
            logger.debug("Required anchor distances exceed element length: element_length=%s, required_length=%s. Adjusting distances.", element_length, required_length)
            # Reduce the distance from COG, but do not allow the distance between anchors be smaller than min_edge_distance
            while distance_from_start < min_edge_distance and distance_from_end < min_edge_distance:
                # Recalculate distances
                distance_from_start += rounding_multiple
                distance_from_end += rounding_multiple

                # Check the minimum distance between anchors
                gap = element_length - distance_from_start - distance_from_end
                if number_of_anchors == 4:
                    gap -= 2 * double_anchor_spacing
                if gap < double_anchor_spacing:
                    raise ValueError("Cannot place the anchors in the wall while keeping all the required distances. The element is too short.")

        return distance_from_start, distance_from_end, double_anchor_spacing


class ReportProperty(BaseModel):
    """
    Represents key properties of a global attribute in Tekla:
    - Attribute name
    - Data type (converted from string to Python type)
    - Unit
    - Value
    """

    name: str
    data_type: type
    unit: str | None
    value: float | str | int | None = None

    @field_validator("data_type", mode="before")
    @classmethod
    def map_string_to_type(cls, v: str) -> type:
        """
        Converts a string like `FLOAT` to the corresponding Python type.
        """
        if isinstance(v, type):
            return v  # already a Python type
        if isinstance(v, str):
            type_map = {"FLOAT": float, "CHARACTER": str, "INTEGER": int}
            return type_map.get(v.upper(), str)  # .upper() for safety
        raise TypeError(f"Cannot convert {v!r} to a Python type")

    @field_serializer("data_type")
    def serialize_type(self, v: type, _info):
        """
        Converts the data_type class object to its name string for JSON output.
        """
        return v.__name__


class ElementProperties(BaseModel):
    """
    Represents key properties of an Assembly or Part object extracted from Tekla:
    - Position
    - GUID
    - Name
    - Profile
    - Material
    - Finish
    - Class
    - Weight in kg
    - Any available custom properties
    """

    position: str
    guid: str
    name: str
    profile: str
    material: str
    finish: str
    tekla_class: str
    weight: float
    custom_properties: list[ReportProperty] | None


class PartSnapshot(BaseModel):
    """
    Represents a snapshot of a Tekla part for comparison purposes:
    - GUID
    - ID
    - Position
    - Report properties
    - User properties
    - Cut parts
    - Reinforcements
    - Welds
    """

    id: int
    guid: str
    pos: str
    report_properties: dict[str, Any] = Field(default_factory=dict)
    user_properties: dict[str, Any] = Field(default_factory=dict)
    cutparts: list[dict[str, Any]] = Field(default_factory=list)
    reinforcements: list[dict[str, Any]] = Field(default_factory=list)
    welds: list[dict[str, Any]] = Field(default_factory=list)


class AssemblySnapshot(BaseModel):
    """
    Represents a snapshot of a Tekla assembly for comparison purposes:
    - GUID
    - ID
    - Position
    - Report properties
    - User properties
    - Main part snapshot
    - Secondaries snapshots
    - Subassemblies snapshots
    """

    id: int
    guid: str
    pos: str
    report_properties: dict[str, Any] = Field(default_factory=dict)
    user_properties: dict[str, Any] = Field(default_factory=dict)
    main_part: PartSnapshot | None = None
    secondaries: list[PartSnapshot] = Field(default_factory=list)
    subassemblies: list["AssemblySnapshot"] = Field(default_factory=list)
