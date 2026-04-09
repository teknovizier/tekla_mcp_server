"""
This module defines core data structures, enumerations, and models used in the project.
"""

import json
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Self

from pydantic import BaseModel, Field, PrivateAttr, field_validator, field_serializer
from pydantic_core import PydanticCustomError

from tekla_mcp_server.config import get_config


TYPE_MAP = {"str": str, "int": int, "float": float}
TYPE_DEFAULTS = {"str": str(), "int": int(), "float": float()}


# Enums
class SelectionMode(Enum):
    """
    Represents selection modes for Tekla objects.
    """

    ASSEMBLY = "Assembly"
    MAIN_PART = "Main Part"


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


class DrawingType(Enum):
    GA = "GA"
    ASSEMBLY = "Assembly"
    SINGLE_PART = "SinglePart"
    CAST_UNIT = "CastUnit"
    MULTIDRAWING = "MultiDrawing"
    UNKNOWN = "Unknown"


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
    PHASE = "Phase"
    CUSTOM = "Custom"


# Mappings
SELECTION_MODES = {e.value for e in SelectionMode}

DRAWING_TYPES = {e.value for e in DrawingType}
ELEMENT_TYPES = {e.value for e in ElementType}
COMPONENT_TYPES = {e.value for e in ComponentType}
ELEMENT_LABELS = {e.value for e in ElementLabel}


@lru_cache
def get_element_type_mapping() -> dict[str, dict[str, list[int]]]:
    """Returns element type mapping from config."""
    return get_config().element_types


@lru_cache
def get_base_components() -> dict[str, Any]:
    """Returns base components from config."""
    return get_config().base_components


@lru_cache
def get_class_to_element() -> dict[int, tuple[str, str]]:
    """Returns class to element mapping."""
    return get_config().class_to_element


@lru_cache(maxsize=32)
def get_custom_properties_schema(component_key: str) -> dict[str, dict[str, str]] | None:
    """
    Returns the custom_properties schema for a component config key.

    Args:
        component_key: The config key (e.g., "lifting_anchor", "border_rebar")

    Returns:
        Dictionary of custom properties with their descriptions and types, or None if not defined
    """
    component = get_base_components().get(component_key)
    if component:
        return component.get("custom_properties")
    return None


@lru_cache
def get_macros() -> list[str]:
    """Returns list of available Tekla macros from configured directories."""
    directories = get_config().tekla_macro_directories
    macro_names: list[str] = []

    for directory in directories:
        dir_path = Path(directory)
        if dir_path.is_dir():
            for file in dir_path.rglob("*.cs"):
                macro_names.append(file.name)

    return sorted(macro_names)


@lru_cache
def get_filters(file_extension: str) -> list[str]:
    """
    Returns list of available Tekla filter names from files with the specified extension.

    Searches in:
    - XS_FIRM
    - XS_PROJECT
    - ModelPath/attributes directory

    Args:
        file_extension: File extension to search for (e.g., ".SObjGrp", ".VObjGrp")

    Returns sorted list of filter names without the extension.
    """
    from tekla_mcp_server.tekla.loader import TeklaStructuresSettings
    from tekla_mcp_server.tekla.model import TeklaModel

    if not file_extension.startswith("."):
        file_extension = f".{file_extension}"

    paths: list[Path] = []

    for option_name in ("XS_FIRM", "XS_PROJECT"):
        _, option = TeklaStructuresSettings.GetAdvancedOption(option_name, str())
        if not option:
            continue
        for path_str in option.split(";"):
            path = Path(path_str.strip())
            if path.is_dir():
                paths.append(path.resolve())

    try:
        model = TeklaModel()
        model_path = model.model.GetInfo().ModelPath
        if model_path:
            attributes_dir = Path(model_path) / "attributes"
            if attributes_dir.is_dir():
                paths.append(attributes_dir.resolve())
    except Exception:
        pass

    filter_names: set[str] = {"standard"}
    for dir_path in paths:
        for file in dir_path.rglob(f"*{file_extension}"):
            filter_names.add(file.stem)

    return sorted(filter_names)


# Classes
class EnumWrapper(BaseModel):
    """
    A generic base model for validating string inputs against a predefined set of enum values.

    This class is designed to be subclassed by specific enum models (e.g., SelectionModeModel),
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


class DrawingTypeModel(EnumWrapper):
    """
    Represents a validated drawing type for Tekla drawings.
    """

    _valid_values = DRAWING_TYPES
    _error_code = "invalid_drawing_type"

    def to_enum(self) -> DrawingType:
        """
        Converts the validated string value to an enum.
        """
        return DrawingType(self.value)


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

    @field_validator("custom_properties", mode="before")
    @classmethod
    def validate_custom_properties(cls, v, info):
        if v is None:
            return v

        if isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                raise ValueError("custom_properties must be valid JSON")

        if not isinstance(v, dict):
            raise ValueError("custom_properties must be a dictionary")

        name = info.data.get("name")
        if not name:
            raise ValueError("'name' required for custom_properties validation")

        base_components = get_base_components()
        component_def = next((c for c in base_components.values() if c.get("tekla_name") == name), None)
        schema = component_def.get("custom_properties") if component_def else None
        if not schema:
            return v

        errors = []

        for key, value in v.items():
            if key not in schema:
                errors.append(f"Unknown property: '{key}'")
            else:
                expected_type = schema[key].get("type")
                if expected_type:
                    expected_python_type = TYPE_MAP.get(expected_type)
                    if expected_python_type and not isinstance(value, expected_python_type):
                        try:
                            v[key] = expected_python_type(value)
                        except (ValueError, TypeError):
                            errors.append(f"Invalid value for '{key}': expected {expected_type}, got {type(value).__name__}")

        if errors:
            raise ValueError("; ".join(errors))

        return v

    def model_post_init(self, __context) -> None:
        """
        Initializes private attributes after model creation.
        """
        base_components = get_base_components()
        component_def = None
        for key, comp in base_components.items():
            if comp.get("tekla_name") == self.name:
                component_def = comp
                break

        self._number = component_def.get("number", -1) if component_def else -1
        self._component_type = ComponentType.DETAIL if self._number == -1 else ComponentType.COMPONENT

        if self.properties_set is None:
            self.properties_set = "standard"

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


class NumberingSeries(BaseModel):
    """
    The NumberingSeries class describes how an object is to be numbered.

    Attributes:
        prefix: The prefix in numbering.
        start_number: The start number in numbering.
    """

    prefix: str
    start_number: int


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


class ModelObjectSnapshot(BaseModel):
    """
    Base class for Tekla object snapshots:
    - GUID
    - ID
    - Position
    - Report properties
    - User properties
    """

    id: int
    guid: str
    pos: str
    report_properties: dict[str, Any] = Field(default_factory=dict)
    user_properties: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def _sort_key_for_comparison(value: Any) -> tuple | str:
        """Generate a stable sort key for comparison, excluding id and guid fields."""
        if isinstance(value, dict):
            return tuple((k, ModelObjectSnapshot._sort_key_for_comparison(v)) for k, v in sorted(value.items()) if k.lower() not in ("id", "guid"))
        elif isinstance(value, list):
            return tuple(sorted(ModelObjectSnapshot._sort_key_for_comparison(v) for v in value))
        return str(type(value).__name__) + ":" + str(value)

    @staticmethod
    def _deterministic_sort_key(item: dict[str, Any]) -> tuple:
        """Generate deterministic sort key with hash tiebreaker for consistent ordering."""
        content_key = ModelObjectSnapshot._sort_key_for_comparison(item)
        content_hash = hash(str(content_key))
        return (content_key, content_hash)

    def normalize(self, tolerance: float) -> Self:
        """
        Recursively rounds all float values to the nearest multiple of tolerance.
        """
        normalized_props = self._normalize_dict(self.report_properties, tolerance)
        normalized_user_props = self._normalize_dict(self.user_properties, tolerance)
        return self._normalize_self(normalized_props, normalized_user_props, tolerance)

    def _normalize_value(self, value: Any, tolerance: float) -> Any:
        if value is None:
            return None
        if isinstance(value, float):
            quantized = round(value / tolerance) * tolerance
            return float(f"{quantized:.10f}")
        elif isinstance(value, dict):
            result = {k: self._normalize_value(v, tolerance) for k, v in value.items() if v is not None}
            return result if result else None
        elif isinstance(value, list):
            normalized = [self._normalize_value(item, tolerance) for item in value if item is not None]
            if normalized:
                normalized.sort(key=ModelObjectSnapshot._sort_key_for_comparison)
            return normalized if normalized else None
        return value

    def _normalize_dict(self, d: dict[str, Any], tolerance: float) -> dict[str, Any]:
        return {k: self._normalize_value(v, tolerance) for k, v in d.items() if v is not None}

    def _normalize_self(self, normalized_props: dict[str, Any], normalized_user_props: dict[str, Any], tolerance: float) -> Self:
        raise NotImplementedError


class PartSnapshot(ModelObjectSnapshot):
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

    cutparts: list[dict[str, Any]] = Field(default_factory=list)
    reinforcements: list[dict[str, Any]] = Field(default_factory=list)
    welds: list[dict[str, Any]] = Field(default_factory=list)

    def _normalize_self(self, normalized_props: dict[str, Any], normalized_user_props: dict[str, Any], tolerance: float) -> Self:
        cutparts = [self._normalize_dict(cp, tolerance) for cp in self.cutparts if cp is not None]
        cutparts.sort(key=ModelObjectSnapshot._deterministic_sort_key) if cutparts else None

        reinforcements = [self._normalize_dict(r, tolerance) for r in self.reinforcements if r is not None]
        reinforcements.sort(key=ModelObjectSnapshot._deterministic_sort_key) if reinforcements else None

        welds = [self._normalize_dict(w, tolerance) for w in self.welds if w is not None]
        welds.sort(key=ModelObjectSnapshot._deterministic_sort_key) if welds else None

        return self.__class__(
            id=self.id,
            guid=self.guid,
            pos=self.pos,
            report_properties=normalized_props,
            user_properties=normalized_user_props,
            cutparts=cutparts,
            reinforcements=reinforcements,
            welds=welds,
        )

    def to_diff_view(self) -> dict[str, Any]:
        """Convert snapshot to diff-friendly view for comparison."""
        return {
            "pos": self.pos,
            "report_properties": self.report_properties,
            "user_properties": self.user_properties,
            "cutparts": self.cutparts,
            "reinforcements": self.reinforcements,
            "welds": self.welds,
        }


class AssemblySnapshot(ModelObjectSnapshot):
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

    main_part: PartSnapshot | None = None
    secondaries: list[PartSnapshot] = Field(default_factory=list)
    subassemblies: list["AssemblySnapshot"] = Field(default_factory=list)

    def _normalize_self(self, normalized_props: dict[str, Any], normalized_user_props: dict[str, Any], tolerance: float) -> Self:
        return self.__class__(
            id=self.id,
            guid=self.guid,
            pos=self.pos,
            report_properties=normalized_props,
            user_properties=normalized_user_props,
            main_part=self.main_part.normalize(tolerance) if self.main_part else None,
            secondaries=[s.normalize(tolerance) for s in self.secondaries],
            subassemblies=[s.normalize(tolerance) for s in self.subassemblies],
        )

    def to_diff_view(self) -> dict[str, Any]:
        """Convert snapshot to diff-friendly view for comparison."""
        return {
            "pos": self.pos,
            "report_properties": self.report_properties,
            "user_properties": self.user_properties,
            "main_part": self.main_part.to_diff_view() if self.main_part else None,
            "secondaries": [s.to_diff_view() for s in self.secondaries],
            "subassemblies": [s.to_diff_view() for s in self.subassemblies],
        }
