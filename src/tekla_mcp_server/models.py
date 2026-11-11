"""
This module defines core data structures, enumerations, and models used in the project.
"""

import hashlib
import json
import math
from enum import StrEnum
from typing import Annotated, Any, Self, Literal

from pydantic import BaseModel, Field, PrivateAttr, field_validator, field_serializer, model_validator
from pydantic_core import PydanticCustomError

from tekla_mcp_server.config import get_config


TYPE_MAP = {"str": str, "int": int, "float": float}
TYPE_DEFAULTS = {"str": str(), "int": int(), "float": float()}


def _coerce_custom_property(value: Any, expected_type: str) -> Any:
    """
    Coerce a custom property value to its schema type without losing data.

    Args:
        value: Value supplied by the caller
        expected_type: Schema type name, a key of `TYPE_MAP`

    Returns:
        The value converted to the schema type

    Raises:
        TypeError: If the value's type cannot represent the schema type
        ValueError: If the conversion would lose data or the value is not finite
    """
    # Tekla stores a bool written to an int attribute as 1/0, so it is a valid on/off flag
    if isinstance(value, bool) and expected_type == "int":
        return int(value)
    # For float or str a bool would be written as an int, which the component ignores
    if value is None or isinstance(value, (bool, dict, list, tuple, set)):
        raise TypeError(f"Unsupported value type {type(value).__name__}")

    if expected_type == "str":
        return value if isinstance(value, str) else str(value)

    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite value {value!r}")
    if expected_type == "float":
        return value if isinstance(value, float) else number
    # int - keep real ints exact, reject fractions like 2.7 instead of truncating them to 2
    if isinstance(value, int):
        return value
    if not number.is_integer():
        raise ValueError(f"Non-integral value {value!r}")
    return int(number)


# Literals
Plane = Literal["LEFT", "MIDDLE", "RIGHT"]
Depth = Literal["FRONT", "MIDDLE", "BEHIND"]
Rotation = Literal["FRONT", "TOP", "BACK", "BELOW"]


# Enums
class DrawingType(StrEnum):
    """
    Tekla drawing types.
    """

    GA = "G"
    ASSEMBLY = "A"
    SINGLE_PART = "W"
    CAST_UNIT = "C"
    MULTIDRAWING = "M"


class SelectionMode(StrEnum):
    """
    Controls whether selection is done to the assembly, its main part or all its parts.
    """

    ASSEMBLY = "Assembly"
    MAIN_PART = "Main Part"
    PARTS = "Parts"


class DrawingExportFormat(StrEnum):
    """
    File format for drawing export.
    """

    DXF = "dxf"
    DWG = "dwg"
    DGN = "dgn"


class DrawingExportVersion(StrEnum):
    """
    AutoCAD file version for DWG/DXF drawing export.
    """

    V2000 = "2000"
    V2004 = "2004"
    V2007 = "2007"
    V2010 = "2010"
    V2013 = "2013"


# Export format -> .dwgsetting FileAttributes/@FileExtension value.
FORMAT_TO_FILE_EXTENSION: dict[DrawingExportFormat, str] = {
    DrawingExportFormat.DXF: ".dxf",
    DrawingExportFormat.DWG: ".dwg",
    DrawingExportFormat.DGN: ".dgn",
}

# Export version -> .dwgsetting FileAttributes/@FileVersion token. Applies to
# all formats, including DGN, which carries a FileVersion just like DWG/DXF.
# All five verified against live Tekla: each exported DXF's $ACADVER header
# matched the expected AutoCAD release code (vAC15=AC1015=2000 ... vAC27=AC1027=2013).
DWG_FILE_VERSION_MAP: dict[DrawingExportVersion, str] = {
    DrawingExportVersion.V2000: "Dwg.UI.DwgFileVersion.vAC15",
    DrawingExportVersion.V2004: "Dwg.UI.DwgFileVersion.vAC18",
    DrawingExportVersion.V2007: "Dwg.UI.DwgFileVersion.vAC21",
    DrawingExportVersion.V2010: "Dwg.UI.DwgFileVersion.vAC24",
    DrawingExportVersion.V2013: "Dwg.UI.DwgFileVersion.vAC27",
}


class BeamType(StrEnum):
    """
    Tekla beam object subtypes.
    """

    BEAM = "Beam"
    COLUMN = "Column"
    PANEL = "Panel"


class StringMatchType(StrEnum):
    """
    Matching operators for string filter conditions.
    """

    IS_EQUAL = "Is Equal"
    IS_NOT_EQUAL = "Is Not Equal"
    CONTAINS = "Contains"
    NOT_CONTAINS = "Not Contains"
    STARTS_WITH = "Starts With"
    NOT_STARTS_WITH = "Not Starts With"
    ENDS_WITH = "Ends With"
    NOT_ENDS_WITH = "Not Ends With"


class NumericMatchType(StrEnum):
    """
    Matching operators for numeric filter conditions.
    """

    IS_EQUAL = "Is Equal"
    IS_NOT_EQUAL = "Is Not Equal"
    SMALLER_THAN = "Smaller Than"
    SMALLER_OR_EQUAL = "Smaller Or Equal"
    GREATER_THAN = "Greater Than"
    GREATER_OR_EQUAL = "Greater Or Equal"


class ElementType(StrEnum):
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


class ComponentType(StrEnum):
    """
    Represents different types of components in Tekla.
    """

    COMPONENT = "Component"
    CONNECTION = "Connection"
    CUSTOM_PART = "Custom Part"
    DETAIL = "Detail"
    SEAM = "Seam"


class ElementLabel(StrEnum):
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


# Classes
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
        """
        Ensure `match_type` is a valid string match type.

        Args:
            v: Match type

        Returns:
            The validated match type

        Raises:
            PydanticCustomError: If the match type is invalid
        """
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

    conditions: StringFilterCondition | Annotated[list[StringFilterCondition], Field(min_length=1)]
    logic: str = "OR"

    @field_validator("logic", mode="before")
    @classmethod
    def validate_logic(cls, v: str) -> str:
        """
        Ensure `logic` is 'AND' or 'OR'.

        Args:
            v: Logic mode

        Returns:
            The validated logic mode

        Raises:
            PydanticCustomError: If the logic is invalid
        """
        valid_values = {"AND", "OR"}
        if v not in valid_values:
            raise PydanticCustomError(
                "invalid_filter_logic",
                f"Invalid logic '{v}'. Must be one of: {valid_values}",
            )
        return v

    def to_dict(self) -> dict[str, str] | list[dict[str, str]]:
        """
        Converts conditions to dict format for tool function.

        Returns:
            Condition dict or list of dicts
        """
        if isinstance(self.conditions, list):
            return [{"match_type": cond.match_type, "value": cond.value} for cond in self.conditions]
        return {"match_type": self.conditions.match_type, "value": self.conditions.value}

    def get_values(self) -> str | list[str]:
        """
        Extracts value(s) from conditions.

        Returns:
            Value or list of values
        """
        if isinstance(self.conditions, list):
            return [c.value for c in self.conditions]
        return self.conditions.value

    def get_match_type(self) -> str:
        """
        Extracts match_type from first condition.

        Returns:
            Match type
        """
        if isinstance(self.conditions, list):
            return self.conditions[0].match_type
        return self.conditions.match_type

    def get_logic(self) -> str:
        """
        Returns the logic mode (AND/OR).

        Returns:
            'AND' or 'OR'
        """
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
        """
        Ensure `match_type` is a valid numeric match type.

        Args:
            v: Match type

        Returns:
            The validated match type

        Raises:
            PydanticCustomError: If the match type is invalid
        """
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

    conditions: NumericFilterCondition | Annotated[list[NumericFilterCondition], Field(min_length=1)]
    logic: str = "AND"

    @field_validator("logic", mode="before")
    @classmethod
    def validate_logic(cls, v: str) -> str:
        """
        Ensure `logic` is 'AND' or 'OR'.

        Args:
            v: Logic mode

        Returns:
            The validated logic mode

        Raises:
            PydanticCustomError: If the logic is invalid
        """
        valid_values = {"AND", "OR"}
        if v not in valid_values:
            raise PydanticCustomError(
                "invalid_filter_logic",
                f"Invalid logic '{v}'. Must be one of: {valid_values}",
            )
        return v

    def to_dict(self) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Converts conditions to dict format for tool function.

        Returns:
            Condition dict or list of dicts
        """
        if isinstance(self.conditions, list):
            return [{"match_type": cond.match_type, "value": cond.value} for cond in self.conditions]
        return {"match_type": self.conditions.match_type, "value": self.conditions.value}

    def get_logic(self) -> str:
        """
        Returns the logic mode (AND/OR).

        Returns:
            'AND' or 'OR'
        """
        return self.logic


class ElementTypes:
    """
    Namespace for element-type class lookups backed by the config.
    """

    @staticmethod
    def get_class_mapping() -> dict[int, tuple[str, str]]:
        """
        Returns class to element mapping: tekla_class -> (material, type_name).

        When a class number appears under more than one material group (e.g. class
        13 is both a concrete column and a reinforcement mesh), the first occurrence
        wins. element_types.json lists structural groups (concrete, steel) before
        reinforcement/embedded, so a shared class resolves to its structural type.

        Returns:
            Class to (material, type name) mapping
        """
        mapping: dict[int, tuple[str, str]] = {}
        for material, types in get_config().element_types.items():
            for type_name, config in types.items():
                for tekla_class in config.get("tekla_classes", []):
                    mapping.setdefault(tekla_class, (material, type_name))
        return mapping

    @staticmethod
    def get_element_type_by_class(tekla_class: str | int) -> tuple[str, str]:
        """
        Returns (material, element type name) for a given class number using the mapping.

        Args:
            tekla_class: Tekla class number

        Returns:
            Material and element type name

        Raises:
            ValueError: If the class number is not in any element type mapping.
        """
        if isinstance(tekla_class, str):
            tekla_class = int(tekla_class)
        result = ElementTypes.get_class_mapping().get(tekla_class)
        if result is None:
            raise ValueError(f"Class number {tekla_class} not found in the list of allowed classes.")
        return result

    @staticmethod
    def get_default_numbering(tekla_class: int) -> dict[str, "NumberingSeries"] | None:
        """
        Returns numbering configuration for a given class number.

        Args:
            tekla_class: Tekla class number

        Returns:
            Numbering series by key or `None`
        """
        config = get_config().get_element_types_flat().get(tekla_class)
        if not config:
            return None
        result: dict[str, "NumberingSeries"] = {}
        if config.get("assembly_prefix"):
            result["assembly_number"] = NumberingSeries(
                prefix=config["assembly_prefix"],
                start_number=config["assembly_start_number"],
            )
        if config.get("part_prefix"):
            result["part_number"] = NumberingSeries(
                prefix=config["part_prefix"],
                start_number=config["part_start_number"],
            )
        return result if result else None

    @staticmethod
    def get_default_name(tekla_class: int) -> str | None:
        """
        Returns default name for a given class number.

        Args:
            tekla_class: Tekla class number

        Returns:
            Default name or `None`
        """
        config = get_config().get_element_types_flat().get(tekla_class)
        return config.get("name") if config else None


class BaseComponent(BaseModel):
    """
    Base class for Tekla components.
    """

    name: str = Field(description="The Tekla name of the component")
    properties_set: str | None = Field(default="standard", description="The name of the Tekla component properties set to use")
    custom_properties: dict[str, Any] | str | None = Field(default=None, description="Custom properties to apply to the component")

    # Private properties
    _number: int = PrivateAttr()
    _component_type: ComponentType = PrivateAttr()
    _properties: dict[str, Any] | None = PrivateAttr(default=None)

    @field_validator("custom_properties", mode="before")
    @classmethod
    def validate_custom_properties(cls, v, info):
        """
        Parse and type-check custom properties against the schema.

        Args:
            v: Custom properties dict or JSON string
            info: Validation info

        Returns:
            Coerced custom properties

        Raises:
            ValueError: If properties are invalid
        """
        if v is None:
            return v

        if isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                raise ValueError("custom_properties must be valid JSON")

        if not isinstance(v, dict):
            raise ValueError("custom_properties must be a dictionary")

        # A failed 'name' is already reported by its own validator, don't add a misleading second error
        if "name" not in info.data:
            return v
        name = info.data["name"]
        if not name:
            raise ValueError("'name' required for custom_properties validation")

        component_def = get_config().get_component_by_tekla_name(name)
        schema = component_def.get("custom_properties") if component_def else None
        if not schema:
            return v

        errors = []
        # Coerce into a copy so the caller's dict is never modified
        coerced = dict(v)

        for key, value in v.items():
            if key not in schema:
                errors.append(f"Unknown property: '{key}'")
                continue
            expected_type = schema[key].get("type")
            if expected_type not in TYPE_MAP:
                continue
            try:
                coerced[key] = _coerce_custom_property(value, expected_type)
            except (ValueError, TypeError):
                errors.append(f"Invalid value for '{key}': expected {expected_type}, got {type(value).__name__} {value!r}")

        if errors:
            raise ValueError("; ".join(errors))

        return coerced

    def model_post_init(self, __context) -> None:
        """
        Initializes private attributes after model creation.

        Args:
            __context: Pydantic validation context
        """
        component_def = get_config().get_component_by_tekla_name(self.name)

        self._number = component_def.get("number", -1) if component_def else -1
        self._component_type = ComponentType.DETAIL if self._number == -1 else ComponentType.COMPONENT

        if self.properties_set is None:
            self.properties_set = "standard"

        # `validate_custom_properties` runs first and has already parsed any JSON string
        # into a dict and rejected everything that is not one, so only a dict reaches here
        if isinstance(self.custom_properties, dict) and self.custom_properties:
            if self._properties is None:
                self._properties = {}
            self._properties.update(self.custom_properties)

    # Getters
    @property
    def number(self) -> int:
        return self._number

    @property
    def component_type(self) -> ComponentType:
        return self._component_type

    @property
    def properties(self) -> dict[str, Any] | None:
        return self._properties

    # Setters
    def set_properties(self, properties: dict[str, Any]) -> None:
        """
        Replaces the entire properties dictionary.

        Args:
            properties: New properties dict
        """
        self._properties = properties

    def update_properties(self, updates: dict[str, Any]) -> None:
        """
        Adds or updates multiple properties at once.
        Creates the dictionary if the dictionary doesn't exist yet.

        Args:
            updates: Properties to add or update
        """
        if self._properties is None:
            self._properties = {}
        self._properties.update(updates)


class NumberingSeries(BaseModel):
    """
    The NumberingSeries class describes how an object is to be numbered.
    """

    prefix: str = Field(description="The prefix in numbering")
    start_number: int = Field(description="The start number in numbering")


class ReportProperty(BaseModel):
    """
    Represents key properties of a global report property in Tekla.
    """

    name: str = Field(description="The name of the report property")
    data_type: type = Field(description="The data type of the report property")
    unit: str | None = Field(description="The unit of the report property")
    value: float | str | int | None = Field(default=None, description="The value of the report property")

    @field_validator("data_type", mode="before")
    @classmethod
    def map_string_to_type(cls, v: str) -> type:
        """
        Converts a string like `FLOAT` to the corresponding Python type.

        Args:
            v: Type name or type

        Returns:
            Python type

        Raises:
            TypeError: If the string does not name a supported type.
        """
        if isinstance(v, type):
            return v  # already a Python type
        if isinstance(v, str):
            type_map = {"FLOAT": float, "CHARACTER": str, "INTEGER": int}
            return type_map.get(v.upper(), str)  # .upper() for safety
        raise TypeError(f"Cannot convert {v!r} to a Python type")

    @field_serializer("data_type")
    def serialize_type(self, v: type, _info) -> str:
        """
        Converts the data_type class object to its name string for JSON output.

        Args:
            v: Data type class
            _info: Serialization info

        Returns:
            Type name
        """
        return v.__name__


class ModelObjectSnapshot(BaseModel):
    """
    Base class for Tekla object snapshots.
    """

    id: int = Field(description="The ID of the model object")
    guid: str = Field(description="The GUID of the model object")
    pos: str = Field(description="The position of the model object")
    report_properties: dict[str, Any] = Field(default_factory=dict, description="Report properties of the model object")
    user_properties: dict[str, Any] = Field(default_factory=dict, description="User properties of the model object")

    @staticmethod
    def _sort_key_for_comparison(value: Any) -> tuple:
        """
        Generate a stable sort key for comparison, excluding id and guid fields.

        Args:
            value: Value to build the key for

        Returns:
            Tagged sort key tuple
        """
        # Tag every branch with a discriminator so heterogeneous lists sort without TypeError.
        if isinstance(value, dict):
            return ("d", tuple((k, ModelObjectSnapshot._sort_key_for_comparison(v)) for k, v in sorted(value.items()) if k.lower() not in ("id", "guid")))
        elif isinstance(value, list):
            return ("l", tuple(sorted(ModelObjectSnapshot._sort_key_for_comparison(v) for v in value)))
        return ("s", str(type(value).__name__) + ":" + str(value))

    @staticmethod
    def _deterministic_sort_key(item: dict[str, Any]) -> tuple:
        """
        Generate deterministic sort key with hash tiebreaker for consistent ordering.

        Args:
            item: Dict to build the key for

        Returns:
            Content key and hash tuple
        """
        content_key = ModelObjectSnapshot._sort_key_for_comparison(item)
        # Use MD5
        content_hash = hashlib.md5(str(content_key).encode("utf-8")).hexdigest()
        return (content_key, content_hash)

    def normalize(self, tolerance: float) -> Self:
        """
        Recursively rounds all float values to the nearest multiple of tolerance.

        Args:
            tolerance: Rounding tolerance

        Returns:
            Normalized snapshot copy
        """
        normalized_props = self._normalize_dict(self.report_properties, tolerance)
        normalized_user_props = self._normalize_dict(self.user_properties, tolerance)
        return self._normalize_self(normalized_props, normalized_user_props, tolerance)

    def _normalize_value(self, value: Any, tolerance: float) -> Any:
        """
        Round floats and sort lists in a value recursively.

        Args:
            value: Value to normalize
            tolerance: Rounding tolerance

        Returns:
            Normalized value
        """
        if value is None:
            return None
        if isinstance(value, float):
            # A zero tolerance means exact comparison, and NaN/inf cannot be quantized
            if tolerance <= 0 or not math.isfinite(value):
                return value
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
        """
        Normalize dict values and drop `None` entries.

        Args:
            d: Dict to normalize
            tolerance: Rounding tolerance

        Returns:
            Normalized dict
        """
        return {k: self._normalize_value(v, tolerance) for k, v in d.items() if v is not None}

    def _normalize_self(self, normalized_props: dict[str, Any], normalized_user_props: dict[str, Any], tolerance: float) -> Self:
        """
        Build a normalized copy of the snapshot.

        Args:
            normalized_props: Normalized report properties
            normalized_user_props: Normalized user properties
            tolerance: Rounding tolerance

        Returns:
            Normalized snapshot copy

        Raises:
            NotImplementedError: Always, subclasses must override
        """
        raise NotImplementedError


class PartSnapshot(ModelObjectSnapshot):
    """
    Represents a snapshot of a Tekla part for comparison purposes.
    """

    cutparts: list[dict[str, Any]] = Field(default_factory=list, description="List of cut parts that belong to the part")
    reinforcements: list[dict[str, Any]] = Field(default_factory=list, description="List of reinforcements that belong to the part")
    welds: list[dict[str, Any]] = Field(default_factory=list, description="List of welds that belong to the part")

    def _normalize_self(self, normalized_props: dict[str, Any], normalized_user_props: dict[str, Any], tolerance: float) -> Self:
        """
        Build a normalized copy of the part snapshot.

        Args:
            normalized_props: Normalized report properties
            normalized_user_props: Normalized user properties
            tolerance: Rounding tolerance

        Returns:
            Normalized snapshot copy
        """
        cutparts = [self._normalize_dict(cp, tolerance) for cp in self.cutparts if cp is not None]
        cutparts.sort(key=ModelObjectSnapshot._deterministic_sort_key)

        reinforcements = [self._normalize_dict(r, tolerance) for r in self.reinforcements if r is not None]
        reinforcements.sort(key=ModelObjectSnapshot._deterministic_sort_key)

        welds = [self._normalize_dict(w, tolerance) for w in self.welds if w is not None]
        welds.sort(key=ModelObjectSnapshot._deterministic_sort_key)

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
        """
        Convert snapshot to diff-friendly view for comparison.

        Returns:
            Comparable snapshot fields
        """
        return {
            "pos": self.pos,
            "report_properties": self.report_properties,
            "user_properties": self.user_properties,
            "cutparts": self.cutparts,
            "reinforcements": self.reinforcements,
            "welds": self.welds,
        }


class ReinforcementSnapshot(ModelObjectSnapshot):
    """
    Represents a snapshot of a directly-selected Tekla reinforcement object.
    """

    father_guid: str | None = Field(description="GUID of the parent part this reinforcement belongs to")
    rebar_type: str = Field(description="Tekla class name of the reinforcement (e.g. BaseRebarGroup, RebarMesh, RebarStrand, SingleRebar)")

    def _normalize_self(self, normalized_props: dict[str, Any], normalized_user_props: dict[str, Any], tolerance: float) -> Self:
        """
        Build a normalized copy of the reinforcement snapshot.

        Args:
            normalized_props: Normalized report properties
            normalized_user_props: Normalized user properties
            tolerance: Rounding tolerance

        Returns:
            Normalized snapshot copy
        """
        return self.__class__(
            id=self.id,
            guid=self.guid,
            pos=self.pos,
            report_properties=normalized_props,
            user_properties=normalized_user_props,
            father_guid=self.father_guid,
            rebar_type=self.rebar_type,
        )

    def to_diff_view(self) -> dict[str, Any]:
        """
        Convert snapshot to diff-friendly view for comparison.

        NOTE: `father_guid` is intentionally excluded - it is a relationship pointer,
        not a property of the reinforcement itself, and would cause false positives when
        comparing identical rebars that happen to belong to different parent parts.

        Returns:
            Comparable snapshot fields
        """
        return {
            "pos": self.pos,
            "rebar_type": self.rebar_type,
            "report_properties": self.report_properties,
            "user_properties": self.user_properties,
        }


class AssemblySnapshot(ModelObjectSnapshot):
    """
    Represents a snapshot of a Tekla assembly for comparison purposes.
    """

    main_part: PartSnapshot | None = Field(default=None, description="Snapshot of the main part of the assembly")
    secondaries: list[PartSnapshot] = Field(default_factory=list, description="List of secondary part snapshots")
    subassemblies: list["AssemblySnapshot"] = Field(default_factory=list, description="List of subassembly snapshots")

    def _normalize_self(self, normalized_props: dict[str, Any], normalized_user_props: dict[str, Any], tolerance: float) -> Self:
        """
        Build a normalized copy of the assembly snapshot.

        Args:
            normalized_props: Normalized report properties
            normalized_user_props: Normalized user properties
            tolerance: Rounding tolerance

        Returns:
            Normalized snapshot copy
        """
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
        """
        Convert snapshot to diff-friendly view for comparison.

        Returns:
            Comparable snapshot fields
        """
        return {
            "pos": self.pos,
            "report_properties": self.report_properties,
            "user_properties": self.user_properties,
            "main_part": self.main_part.to_diff_view() if self.main_part else None,
            "secondaries": [s.to_diff_view() for s in self.secondaries],
            "subassemblies": [s.to_diff_view() for s in self.subassemblies],
        }


# Placement Models
class PointInput(BaseModel):
    """Input model for 3D point coordinates."""

    x: float = Field(allow_inf_nan=False, description="X coordinate of the point")
    y: float = Field(allow_inf_nan=False, description="Y coordinate of the point")
    z: float = Field(allow_inf_nan=False, description="Z coordinate of the point")


class OffsetInput(BaseModel):
    """Input model for beam start/end point offsets."""

    dx: float = Field(allow_inf_nan=False, description="Offset in X direction in object's coordinate system")
    dy: float = Field(allow_inf_nan=False, description="Offset in Y direction in object's coordinate system")
    dz: float = Field(allow_inf_nan=False, description="Offset in Z direction in object's coordinate system")


class PositionInput(BaseModel):
    """Input model for beam position settings."""

    plane: Plane = Field("MIDDLE", description="Plane position")
    plane_offset: float = Field(default=0.0, allow_inf_nan=False, description="Offset in mm along plane axis")
    depth: Depth = Field("MIDDLE", description="Depth position")
    depth_offset: float = Field(default=0.0, allow_inf_nan=False, description="Offset in mm along depth axis")
    rotation: Rotation = Field("FRONT", description="Rotation position")
    rotation_offset: float = Field(0.0, allow_inf_nan=False, description="Rotation offset in degrees")


class TeklaPartInput(BaseModel):
    """Base input model for every placed part (beam, column, panel, slab)."""

    profile: str = Field(description="Element profile name, e.g. '300*600', 'HEA200'")
    material: str = Field(description="Element material grade, e.g. 'C30/37', 'S235JR'")
    tekla_class: int = Field(description="Tekla class number, e.g. 11, 100")
    name: str | None = Field(default=None, description="Element name")
    position: PositionInput | None = Field(default=None, description="Position settings for the element")
    part_number: NumberingSeries | None = Field(default=None, description="Part numbering series")
    assembly_number: NumberingSeries | None = Field(default=None, description="Assembly numbering series")


class TeklaBeamInput(TeklaPartInput):
    """Base input model for beam-like elements (beam, column, panel)."""

    # Only beam-like parts have start/end points to offset, slabs are contour plates
    start_point_offset: OffsetInput | None = Field(default=None, description="Start point offset (dx, dy, dz)")
    end_point_offset: OffsetInput | None = Field(default=None, description="End point offset (dx, dy, dz)")


class BeamInput(TeklaBeamInput):
    """Input model for a single beam definition."""

    start_point: PointInput = Field(description="Start point coordinates")
    end_point: PointInput = Field(description="End point coordinates")


class ColumnInput(TeklaBeamInput):
    """Input model for a single column definition."""

    base_point: PointInput = Field(description="Base point coordinates")
    height: float = Field(gt=0, allow_inf_nan=False, description="Column height in mm")


class PanelInput(TeklaBeamInput):
    """Input model for a single panel definition."""

    start_point: PointInput = Field(description="Start point coordinates")
    end_point: PointInput = Field(description="End point coordinates")


class SlabInput(TeklaPartInput):
    """Input model for a single slab definition."""

    points: list[PointInput] = Field(description="List of contour points defining slab outline (minimum 3 points)")
    profile: str = Field(description="Slab profile/thickness (e.g. '200', '300')")

    @field_validator("points")
    @classmethod
    def validate_points(cls, v: list[PointInput]) -> list[PointInput]:
        """
        Ensure the slab has at least 3 contour points.

        Args:
            v: Slab contour points

        Returns:
            The validated points

        Raises:
            PydanticCustomError: If fewer than 3 points
        """
        if len(v) < 3:
            raise PydanticCustomError("invalid_points", f"At least 3 points are required to define a slab, got {len(v)}")
        return v


class PlacementResult(BaseModel):
    """Result model for a single element placement."""

    success: bool
    guid: str | None = None
    message: str | None = None


class BatchPlacementResult(BaseModel):
    """Result model for batch element placement."""

    success: bool
    total: int
    succeeded: int
    failed: int
    results: list[PlacementResult]
    message: str


class AttachmentPair(BaseModel):
    """An object -> target attachment pair."""

    object_guid: str = Field(description="GUID of the object to attach (e.g. from `check_for_orphans` or `get_elements_properties`)")
    target_guid: str = Field(description="GUID of the parent assembly to attach the object to (e.g. from `check_for_orphans` or `get_elements_properties`)")


class ViewAttributes(BaseModel):
    """Display attributes to update on a drawing view. At least one attribute must be set."""

    view_key: str = Field(description="View key to update (from `get_drawing_views`)")
    scale: float | None = Field(None, gt=0, description="New scale value (e.g. 20 for 1:20)")
    show_part_openings_or_recess_symbol: bool | None = Field(None, description="Whether to show opening/recess symbols for parts in the view")
    reflected_view: bool | None = Field(None, description="Whether the view is shown reflected (mirrored)")
    undeformed_view: bool | None = Field(None, description="Whether parts are shown in their undeformed state")
    unfolded_view: bool | None = Field(None, description="Whether parts are shown unfolded")

    @model_validator(mode="after")
    def _at_least_one_set(self) -> "ViewAttributes":
        """
        Ensure at least one view attribute is set.

        Returns:
            The validated model

        Raises:
            ValueError: If no attribute is set
        """
        if all(v is None for v in (self.scale, self.show_part_openings_or_recess_symbol, self.reflected_view, self.undeformed_view, self.unfolded_view)):
            raise ValueError("At least one attribute must be set")
        return self
