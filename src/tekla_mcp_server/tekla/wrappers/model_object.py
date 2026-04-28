"""
Module for Tekla ModelObject wrappers.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterable
from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import AssemblySnapshot, NumberingSeries, PartSnapshot, BeamType, OffsetInput, PointInput, PositionInput

from tekla_mcp_server.tekla.loader import (
    Assembly,
    Beam,
    BaseWeld,
    Boolean,
    BooleanPart,
    ContourPlate,
    ContourPoint,
    Part,
    ModelObject,
    Offset,
    Point,
    Position,
    Reinforcement,
    Hashtable,
    Phase,
    ReferenceModelObject,
)


from tekla_mcp_server.tekla.snapshot_builder import SnapshotBuilder
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser


DEFAULT_TOLERANCE = 50.0  # mm

POSITION_PLANE_MAP = {
    "LEFT": Position.PlaneEnum.LEFT,
    "MIDDLE": Position.PlaneEnum.MIDDLE,
    "RIGHT": Position.PlaneEnum.RIGHT,
}
POSITION_DEPTH_MAP = {
    "FRONT": Position.DepthEnum.FRONT,
    "MIDDLE": Position.DepthEnum.MIDDLE,
    "BEHIND": Position.DepthEnum.BEHIND,
}
POSITION_ROTATION_MAP = {
    "FRONT": Position.RotationEnum.FRONT,
    "TOP": Position.RotationEnum.TOP,
    "BACK": Position.RotationEnum.BACK,
    "BELOW": Position.RotationEnum.BELOW,
}


class BoundingBox:
    """
    Bounding box calculated from Tekla report properties.

    Extracts BOUNDING_BOX_MIN/MAX_X/Y/Z report properties from a Tekla model object
    and provides geometric analysis methods.

    Attributes:
        min_x: Minimum X coordinate
        max_x: Maximum X coordinate
        min_y: Minimum Y coordinate
        max_y: Maximum Y coordinate
        min_z: Minimum Z coordinate
        max_z: Maximum Z coordinate
    """

    def __init__(self, model_object: TeklaModelObject):
        self.min_x = float(model_object.get_report_property("BOUNDING_BOX_MIN_X"))
        self.max_x = float(model_object.get_report_property("BOUNDING_BOX_MAX_X"))
        self.min_y = float(model_object.get_report_property("BOUNDING_BOX_MIN_Y"))
        self.max_y = float(model_object.get_report_property("BOUNDING_BOX_MAX_Y"))
        self.min_z = float(model_object.get_report_property("BOUNDING_BOX_MIN_Z"))
        self.max_z = float(model_object.get_report_property("BOUNDING_BOX_MAX_Z"))

    @property
    def centroid(self) -> tuple[float, float, float]:
        """
        Center point of bounding box.
        """
        return (
            (self.min_x + self.max_x) / 2,
            (self.min_y + self.max_y) / 2,
            (self.min_z + self.max_z) / 2,
        )

    @property
    def diagonal(self) -> float:
        """
        Diagonal length of bounding box.
        """
        return math.sqrt((self.max_x - self.min_x) ** 2 + (self.max_y - self.min_y) ** 2 + (self.max_z - self.min_z) ** 2)

    def overlaps(self, other: BoundingBox, tol: float = DEFAULT_TOLERANCE) -> bool:
        """
        Check if bounding boxes overlap within tolerance.
        """
        return (
            self.min_x <= other.max_x + tol
            and self.max_x >= other.min_x - tol
            and self.min_y <= other.max_y + tol
            and self.max_y >= other.min_y - tol
            and self.min_z <= other.max_z + tol
            and self.max_z >= other.min_z - tol
        )

    def matches(self, other: BoundingBox, tol: float = DEFAULT_TOLERANCE, center_tol_factor: float = 0.05) -> bool:
        """
        Match using spatial overlap + centroid distance.
        """
        if not self.overlaps(other, tol):
            return False

        c1, c2 = self.centroid, other.centroid
        dist = math.sqrt((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2)

        diag = max(self.diagonal, other.diagonal)
        adaptive_tol = max(center_tol_factor * diag, tol)

        return dist <= adaptive_tol


def wrap_model_object(model_object: ModelObject) -> TeklaModelObject | None:
    """
    Wraps a Tekla ModelObject in the appropriate wrapper class.

    Returns:
        - TeklaAssembly if the object is an Assembly
        - TeklaBeam if the object is a Beam
        - TeklaContourPlate if the object is a ContourPlate
        - TeklaPart if the object is a Part
        - TeklaReferenceModelObject if the object is a ReferenceModelObject
        - TeklaModelObject for any other object types
    """
    if isinstance(model_object, Assembly):
        return TeklaAssembly(model_object)
    elif isinstance(model_object, Beam):
        return TeklaBeam(model_object)
    elif isinstance(model_object, ContourPlate):
        return TeklaContourPlate(model_object)
    elif isinstance(model_object, Part):
        return TeklaPart(model_object)
    elif isinstance(model_object, ReferenceModelObject):
        return TeklaReferenceModelObject(model_object)
    elif isinstance(model_object, (Boolean, BaseWeld, Reinforcement)):
        return TeklaModelObject(model_object)
    else:
        return None


def wrap_model_objects(model_objects: Iterable) -> Generator[TeklaModelObject, None, None]:
    """
    Wraps each Tekla ModelObject in the appropriate wrapper class.

    Currently only some of the objects are supported, the other object types will be ignored.
    """
    for model_object in model_objects:
        wrapped = wrap_model_object(model_object)
        if wrapped is not None:
            yield wrapped


class TeklaModelObject:
    """
    A base wrapper class around the Tekla Structures ModelObject object.
    """

    def __init__(self, model_object: ModelObject):
        self._model_object = model_object

    @property
    def model_object(self) -> ModelObject:
        """
        Returns the underlying ModelObject instance.
        """
        return self._model_object

    @property
    def id(self) -> int:
        """
        Returns the ID of the Tekla model object.
        """
        return self.model_object.Identifier.ID

    @property
    def guid(self) -> str:
        """
        Returns the GUID of the Tekla model object.
        """
        return self.model_object.Identifier.GUID.ToString()

    @property
    def phase(self) -> int:
        """
        Returns the phase number of the Tekla model object.
        """
        is_ok, phase = self.model_object.GetPhase()
        if not is_ok:
            raise AttributeError("Failed to retrieve phase.")

        return phase.PhaseNumber

    @property
    def cog(self) -> Point:
        """
        Retrieves the center of gravity (COG) point for a given Tekla model object.
        """
        cog_x = self.get_report_property("COG_X")
        cog_y = self.get_report_property("COG_Y")
        cog_z = self.get_report_property("COG_Z")

        return Point(cog_x, cog_y, cog_z)

    @property
    def bounding_box(self) -> BoundingBox | None:
        """Get bounding box from report properties."""
        try:
            return BoundingBox(self)
        except Exception:
            return None

    def get_top_level_assembly(self) -> TeklaModelObject | None:
        """
        Finds and returns the top-level assembly of this Tekla model object.

        It goes up the assembly chain until it reaches the highest one.
        If there's no assembly, it returns None.
        If the object itself is an Assembly, it is considered top-level.

        Raises:
            TypeError: If the returned object is not of type Assembly.
        """
        obj = self._model_object

        # If it's not an Assembly - get its assembly
        if not isinstance(obj, Assembly):
            assembly = obj.GetAssembly()
            if assembly is None:
                logger.warning("No assembly found for object %s.", self.guid)
                return None
        else:
            assembly = obj

        # Always go up if there's a parent
        parent = assembly.GetAssembly()
        while parent is not None:
            assembly = parent
            parent = assembly.GetAssembly()

        if not isinstance(assembly, Assembly):
            raise TypeError(f"Expected Assembly object, got {type(assembly).__name__}.")

        return TeklaAssembly(assembly)

    def get_report_property(self, property_name: str) -> str | int | float:
        """
        Retrieves a report property for a given Tekla model object.
        Uses TemplateAttributeParser to determine the data type.

        Raises:
            ValueError: If the property is not found in Tekla's attribute definitions.
            AttributeError: If the property retrieval fails for the given element.
        """
        report_property = TemplateAttributeParser.get_attribute(property_name)
        is_ok, value = self.model_object.GetReportProperty(property_name, report_property.data_type())
        if not is_ok:
            raise AttributeError(f"Failed to retrieve property `{property_name}`.")

        return value

    def get_user_property(self, property_name: str, property_type: type) -> str | int | float:
        """
        Retrieves a user property for a given Tekla model object.

        Raises:
            TypeError: If the provided property type is not str, int, or float.
            AttributeError: If the property retrieval fails for the given element.
        """
        self._validate_property_type(property_type)
        is_ok, value = self.model_object.GetUserProperty(property_name, property_type())
        if not is_ok:
            raise AttributeError(f"Failed to retrieve property `{property_name}`.")

        return value

    def set_user_property(self, property_name: str, property_value: str | int | float) -> bool:
        """
        Sets a user property for a given Tekla model object.

        Raises:
            TypeError: If the provided property type is not str, int, or float.
        """
        self._validate_property_type(type(property_value))
        return self.model_object.SetUserProperty(property_name, property_value)

    def get_all_user_properties(self) -> dict[str, str | int | float]:
        """
        Gets all user properties for a given Tekla model object.
        """
        hash_table = Hashtable()
        self.model_object.GetAllUserProperties(hash_table)
        return {key: hash_table[key] for key in hash_table.Keys}

    def get_multiple_report_properties(self, prop_names: list[str]) -> dict[str, str | int | float | None]:
        """
        Fetches multiple report properties.
        """
        result: dict[str, str | int | float | None] = {}
        for prop in prop_names:
            try:
                result[prop] = self.get_report_property(prop)
            except Exception:
                result[prop] = None
        return result

    def get_properties(self, report_props_definitions: list[str] | None = None) -> dict[str, Any]:
        """
        Gets element properties as dict.
        Override in subclasses to add type-specific properties.
        """
        return {
            "guid": self.guid,
            "phase": self.phase,
            "user_properties": self.get_all_user_properties(),
            "report_properties": self._get_report_properties(report_props_definitions),
        }

    def _get_report_properties(self, report_props_definitions: list[str] | None = None) -> list[dict[str, Any]]:
        """
        Internal method to extract report properties.
        """
        if not report_props_definitions:
            return []

        resolution = TemplateAttributeParser.resolve_attributes(report_props_definitions)
        resolved = resolution.get("resolved", [])

        result = []
        for attr_name in resolved:
            value = None
            parsed_prop = None
            try:
                parsed_prop = TemplateAttributeParser.get_attribute(attr_name)
                value = self.get_report_property(attr_name)
            except KeyError:
                logger.debug("Attribute '%s' not found in cache", attr_name)
            except Exception:
                logger.debug("Property '%s' not available for this element", attr_name)

            if parsed_prop is not None:
                result.append(
                    {
                        "name": parsed_prop.name,
                        "data_type": parsed_prop.data_type.__name__,
                        "unit": parsed_prop.unit,
                        "value": value,
                    }
                )
        return result

    @staticmethod
    def _validate_property_type(property_type: type) -> None:
        """
        Validates that the given type is one of the supported types: str, int, or float.

        Raises:
            TypeError: If the type is not supported.
        """
        if property_type not in (str, int, float):
            raise TypeError("Property type must be one of: str, int, float.")

    def _set_property(self, prop_name: str, value: str) -> None:
        """
        Helper to set a property on the model object.

        Args:
            prop_name: Name of the property (supports dotted paths like "Profile.ProfileString")
            value: Value to set
        """
        if "." in prop_name:
            parts = prop_name.split(".")
            setattr(getattr(self.model_object, parts[0]), parts[1], value)
        else:
            setattr(self.model_object, prop_name, value)
        self.model_object.Modify()


class TeklaReferenceModelObject(TeklaModelObject):
    """
    A wrapper class around the Tekla Structures ReferenceModelObject object.
    """

    def get_report_property(self, property_name: str) -> str | int | float:
        """
        Retrieves a report property from ReferenceModelObject.

        First tries using TemplateAttributeParser via base class method.
        Falls back to using str type if not found in attribute definitions.

        Args:
            property_name: Name of the report property to retrieve

        Returns:
            Property value as str, int, or float

        Raises:
            AttributeError: If the property retrieval fails
        """
        try:
            return super().get_report_property(property_name)
        except KeyError:
            is_ok, value = self.model_object.GetReportProperty(property_name, str())
            if not is_ok:
                raise AttributeError(f"Failed to retrieve property `{property_name}`.")

        return value

    def get_properties(self, report_props_definitions: list[str] | None = None) -> dict[str, Any]:
        """
        Gets element properties as dict for IFC reference objects.
        """
        props = super().get_properties(report_props_definitions)
        props["guid"] = self.get_report_property("GUID")
        return props


class TeklaAssembly(TeklaModelObject):
    """
    A wrapper class around the Tekla Structures Assembly object.
    """

    @property
    def position(self) -> str:
        """
        Returns the position number of the assembly.
        """
        return str(self.get_report_property("ASSEMBLY_POS"))

    @property
    def name(self) -> str:
        """
        Returns the name of the assembly.
        """
        return self.model_object.Name

    @name.setter
    def name(self, value: str) -> None:
        """Sets the name of the assembly."""
        self._set_property("Name", value)

    @property
    def assembly_number(self) -> NumberingSeries:
        """
        Returns the assembly numbering series.
        """
        ns = self.model_object.AssemblyNumber
        return NumberingSeries(prefix=ns.Prefix, start_number=ns.StartNumber)

    @assembly_number.setter
    def assembly_number(self, value: NumberingSeries) -> None:
        """Sets the assembly numbering series."""
        self.model_object.AssemblyNumber.Prefix = value.prefix
        self.model_object.AssemblyNumber.StartNumber = value.start_number
        self.model_object.Modify()

    @property
    def main_part(self) -> TeklaModelObject:
        """
        Returns the main part of the assembly.

        Raises:
            ValueError: If the main part is not available.
        """
        main_part = wrap_model_object(self._model_object.GetMainPart())
        if main_part is None:
            raise ValueError("Main part is not available")
        return main_part

    @property
    def weight(self) -> tuple[float, float]:
        """
        Calculate the weight breakdown of a given Tekla assembly.

        This function returns two weight values:
        - The total weight of the element, including its main part, secondary parts, and subassemblies.
        - The total weight of all reinforcement bars associated with the main part, secondary parts, and any rebar subassemblies.
        """
        weight_main_part = float(self.main_part.get_report_property("WEIGHT"))

        weight_secondaries = 0.0
        weight_subassemblies = 0.0
        weight_rebars = 0.0

        for rebar in wrap_model_objects(self.main_part.model_object.GetReinforcements()):
            weight_rebar = rebar.get_report_property("WEIGHT_TOTAL")
            weight_rebars += float(weight_rebar)

        for secondary in wrap_model_objects(self.model_object.GetSecondaries()):
            weight_secondary = secondary.get_report_property("WEIGHT")
            weight_secondaries += float(weight_secondary)

            for rebar in wrap_model_objects(secondary.model_object.GetReinforcements()):
                weight_rebar = rebar.get_report_property("WEIGHT_TOTAL")
                weight_rebars += float(weight_rebar)

        for subassembly in wrap_model_objects(self.model_object.GetSubAssemblies()):
            weight_sub = subassembly.get_report_property("WEIGHT")
            try:
                rebar_type = subassembly.get_report_property("REBAR_ASSEMBLY_TYPE")
                assert rebar_type
                weight_rebars += float(weight_sub)
            except AttributeError:
                weight_subassemblies += float(weight_sub)

        total_parts_weight = weight_main_part + weight_secondaries + weight_subassemblies

        return total_parts_weight, weight_rebars

    def get_all_children(self, include_all: bool = True) -> list[ModelObject]:
        """
        Returns all model objects belonging to this assembly.

        Args:
            include_all: If True, includes welds, reinforcements, secondaries, subassemblies.
        """
        objects = []
        stack = [self._model_object]

        while stack:
            current = stack.pop()

            if isinstance(current, Assembly):
                main = current.GetMainPart()
                if main:
                    objects.extend(TeklaPart(main).get_all_children(include_all))

                secondaries = current.GetSecondaries()
                for sec in secondaries:
                    objects.extend(TeklaPart(sec).get_all_children(include_all))

                subs = current.GetSubAssemblies()
                for sub in subs:
                    stack.append(sub)

            elif isinstance(current, Part):
                if include_all:
                    objects.extend(TeklaPart(current).get_all_children(include_all))
                else:
                    objects.append(current)

        return objects

    def to_snapshot(self) -> AssemblySnapshot:
        """
        Creates a snapshot of the Assembly containing:
        - Report properties
        - User defined attributes (UDAs)
        - Main part
        - Secondaries
        - Subassemblies
        """
        return SnapshotBuilder.build_assembly_snapshot(self)

    def get_properties(self, report_props_definitions: list[str] | None = None) -> dict[str, Any]:
        """
        Gets element properties for Assembly.
        """
        props = super().get_properties(report_props_definitions)
        props["position"] = self.position
        props["name"] = self.name
        props["assembly_prefix"] = self.assembly_number.prefix
        props["assembly_start_number"] = self.assembly_number.start_number
        return props

    def set_properties(
        self,
        name: str | None = None,
        assembly_prefix: str | None = None,
        assembly_start_number: int | None = None,
        phase: int | None = None,
        user_properties: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        """
        Sets properties on the assembly.
        Returns a summary of changes made.
        """
        changes: dict[str, int] = {
            "name": 0,
            "assembly_prefix": 0,
            "assembly_start_number": 0,
            "phase": 0,
            "udas": 0,
        }

        if name is not None:
            self.name = name
            changes["name"] = 1

        if assembly_prefix is not None:
            self.model_object.AssemblyNumber.Prefix = assembly_prefix
            self.model_object.Modify()
            changes["assembly_prefix"] = 1

        if assembly_start_number is not None:
            self.model_object.AssemblyNumber.StartNumber = assembly_start_number
            self.model_object.Modify()
            changes["assembly_start_number"] = 1

        if phase is not None:
            if self.model_object.SetPhase(Phase(phase)):
                self.model_object.Modify()
                changes["phase"] = 1

        if user_properties:
            for key, value in user_properties.items():
                if self.set_user_property(key, value):
                    changes["udas"] += 1

        return changes


class TeklaPart(TeklaModelObject):
    """
    A wrapper class around the Tekla Structures Part object.
    """

    @property
    def position(self) -> str:
        """
        Returns the position number of the part.
        """
        return str(self.get_report_property("PART_POS"))

    @property
    def name(self) -> str:
        """
        Returns the name of the part.
        """
        return self.model_object.Name

    @name.setter
    def name(self, value: str) -> None:
        """Sets the name of the part."""
        self._set_property("Name", value)

    @property
    def profile(self) -> str:
        """
        Returns the profile of the part.
        """
        return self.model_object.Profile.ProfileString

    @profile.setter
    def profile(self, value: str) -> None:
        """Sets the profile of the part."""
        self._set_property("Profile.ProfileString", value)

    @property
    def material(self) -> str:
        """
        Returns the material of the part.
        """
        return self.model_object.Material.MaterialString

    @material.setter
    def material(self, value: str) -> None:
        """Sets the material of the part."""
        self._set_property("Material.MaterialString", value)

    @property
    def finish(self) -> str:
        """
        Returns the finish of the part.
        """
        return self.model_object.Finish

    @finish.setter
    def finish(self, value: str) -> None:
        """Sets the finish of the part."""
        self._set_property("Finish", value)

    @property
    def tekla_class(self) -> str:
        """
        Returns the Tekla class of the part.
        """
        return self.model_object.Class

    @tekla_class.setter
    def tekla_class(self, value: str) -> None:
        """Sets the Tekla class of the part."""
        self._set_property("Class", value)

    @property
    def part_number(self) -> NumberingSeries:
        """
        Returns the part numbering series.
        """
        ns = self.model_object.PartNumber
        return NumberingSeries(prefix=ns.Prefix, start_number=ns.StartNumber)

    @part_number.setter
    def part_number(self, value: NumberingSeries) -> None:
        """Sets the part numbering series."""
        self.model_object.PartNumber.Prefix = value.prefix
        self.model_object.PartNumber.StartNumber = value.start_number
        self.model_object.Modify()

    @property
    def assembly_number(self) -> NumberingSeries:
        """
        Returns the assembly numbering series.
        """
        ns = self.model_object.AssemblyNumber
        return NumberingSeries(prefix=ns.Prefix, start_number=ns.StartNumber)

    @assembly_number.setter
    def assembly_number(self, value: NumberingSeries) -> None:
        """Sets the assembly numbering series."""
        self.model_object.AssemblyNumber.Prefix = value.prefix
        self.model_object.AssemblyNumber.StartNumber = value.start_number
        self.model_object.Modify()

    @property
    def weight(self) -> tuple[float, float]:
        """
        Calculate the weight breakdown of a given part.

        This function returns two weight values:
        - The total weight of the element.
        - The total weight of all reinforcement bars associated with the element.
        """
        weight_main_part = float(self.get_report_property("WEIGHT"))

        weight_secondaries = 0.0
        weight_subassemblies = 0.0
        weight_rebars = 0.0

        for rebar in wrap_model_objects(self.model_object.GetReinforcements()):
            weight_rebar = rebar.get_report_property("WEIGHT_TOTAL")
            weight_rebars += float(weight_rebar)

        total_parts_weight = weight_main_part + weight_secondaries + weight_subassemblies

        return total_parts_weight, weight_rebars

    def get_properties(self, report_props_definitions: list[str] | None = None) -> dict[str, Any]:
        """
        Gets element properties including position for Part.
        """
        props = super().get_properties(report_props_definitions)
        props["position"] = self.position
        props["name"] = self.name
        props["profile"] = self.profile
        props["material"] = self.material
        props["finish"] = self.finish
        props["tekla_class"] = self.tekla_class
        props["part_prefix"] = self.part_number.prefix
        props["part_start_number"] = self.part_number.start_number
        props["assembly_prefix"] = self.assembly_number.prefix
        props["assembly_start_number"] = self.assembly_number.start_number
        return props

    def has_spatial_overlap(self, other: TeklaModelObject) -> bool:
        """
        Checks whether the bounding boxes of this Tekla part and another TeklaModelObject intersect.
        """
        solid_self = self.model_object.GetSolid()
        solid_other = other.model_object.GetSolid()

        if not (solid_self and solid_other):
            return False

        min_self, max_self = solid_self.MinimumPoint, solid_self.MaximumPoint
        min_other, max_other = solid_other.MinimumPoint, solid_other.MaximumPoint

        return min_self.X <= max_other.X and max_self.X >= min_other.X and min_self.Y <= max_other.Y and max_self.Y >= min_other.Y and min_self.Z <= max_other.Z and max_self.Z >= min_other.Z

    def add_cut(self, cutting_part: TeklaPart, delete_cutting_part: bool = False) -> bool:
        """
        Attempts to perform a boolean cut operation on this Tekla part using a TeklaPart as the cutting part.

        The method first checks for self-cutting and spatial overlap between the objects. If valid, it sets the cutting part
        as a Boolean operator and performs the cut. It then compares the volume before and after the operation to verify
        that the cut had an effect. Optionally deletes the cutting part from the model if the cut was successful.
        """
        if self.model_object is None or cutting_part.model_object is None:
            logger.warning("Boolean cut skipped: one or both model objects are None")
            return False

        if self.model_object is cutting_part.model_object:
            logger.warning("Boolean cut skipped: self-cutting detected")
            return False

        if not self.has_spatial_overlap(cutting_part):
            logger.warning("Boolean cut skipped: no spatial overlap")
            return False

        volume_before = float(self.get_report_property("VOLUME"))

        cutting_part.model_object.Class = BooleanPart.BooleanOperativeClassName

        boolean_cut = BooleanPart()
        boolean_cut.Father = self.model_object
        boolean_cut.SetOperativePart(cutting_part.model_object)
        boolean_cut.Type = BooleanPart.BooleanTypeEnum.BOOLEAN_CUT

        if boolean_cut.Insert():
            volume_after = float(self.get_report_property("VOLUME"))
            if volume_after < volume_before:
                if delete_cutting_part:
                    guid = cutting_part.guid
                    if cutting_part.model_object.Delete():
                        logger.debug("Cutting part %s deleted after boolean cut", guid)

                logger.debug("Boolean cut successful. Volume before: %s, after: %s", volume_before, volume_after)
                return True
        else:
            logger.debug("Boolean cut insertion failed")

        return False

    def get_all_children(self, include_all: bool = True) -> list[ModelObject]:
        """
        Returns all model objects belonging to this part.

        Args:
            include_all: If True, includes welds and reinforcements.
        """
        objects = [self._model_object]

        if include_all:
            welds = self._model_object.GetWelds()
            while welds.MoveNext():
                objects.append(welds.Current)

            reinfs = self._model_object.GetReinforcements()
            while reinfs.MoveNext():
                objects.append(reinfs.Current)

        return objects

    def to_snapshot(self) -> PartSnapshot:
        """
        Creates a snapshot of the Part containing:
        - Report properties
        - User defined attributes (UDAs)
        - Cutparts (boolean operations)
        - Reinforcements (rebar groups, meshes, strands)
        - Welds
        """
        return SnapshotBuilder.build_part_snapshot(self)

    def set_properties(
        self,
        name: str | None = None,
        profile: str | None = None,
        material: str | None = None,
        tekla_class: str | None = None,
        finish: str | None = None,
        phase: int | None = None,
        part_prefix: str | None = None,
        part_start_number: int | None = None,
        assembly_prefix: str | None = None,
        assembly_start_number: int | None = None,
        user_properties: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        """
        Sets properties on the part.
        Returns a summary of changes made.
        """
        changes: dict[str, int] = {
            "name": 0,
            "profile": 0,
            "material": 0,
            "tekla_class": 0,
            "finish": 0,
            "phase": 0,
            "part_prefix": 0,
            "part_start_number": 0,
            "assembly_prefix": 0,
            "assembly_start_number": 0,
            "udas": 0,
        }

        if name is not None:
            self.name = name
            changes["name"] = 1

        if profile is not None:
            self.profile = profile
            changes["profile"] = 1

        if material is not None:
            self.material = material
            changes["material"] = 1

        if tekla_class is not None:
            self.tekla_class = tekla_class
            changes["tekla_class"] = 1

        if finish is not None:
            self.finish = finish
            changes["finish"] = 1

        if part_prefix is not None:
            self.model_object.PartNumber.Prefix = part_prefix
            self.model_object.Modify()
            changes["part_prefix"] = 1

        if part_start_number is not None:
            self.model_object.PartNumber.StartNumber = part_start_number
            self.model_object.Modify()
            changes["part_start_number"] = 1

        if assembly_prefix is not None:
            self.model_object.AssemblyNumber.Prefix = assembly_prefix
            self.model_object.Modify()
            changes["assembly_prefix"] = 1

        if assembly_start_number is not None:
            self.model_object.AssemblyNumber.StartNumber = assembly_start_number
            self.model_object.Modify()
            changes["assembly_start_number"] = 1

        if phase is not None:
            if self.model_object.SetPhase(Phase(phase)):
                self.model_object.Modify()
                changes["phase"] = 1

        if user_properties:
            for key, value in user_properties.items():
                if self.set_user_property(key, value):
                    changes["udas"] += 1

        return changes

    def apply_position(self, position: PositionInput | None):
        if not position:
            return self

        pos = self.model_object.Position
        pos.Plane = POSITION_PLANE_MAP.get(position.plane, Position.PlaneEnum.MIDDLE)
        pos.Depth = POSITION_DEPTH_MAP.get(position.depth, Position.DepthEnum.MIDDLE)
        pos.Rotation = POSITION_ROTATION_MAP.get(position.rotation, Position.RotationEnum.FRONT)

        pos.PlaneOffset = position.plane_offset
        pos.DepthOffset = position.depth_offset
        pos.RotationOffset = position.rotation_offset
        return self

    def finalize_placement(self, part_number, assembly_number):
        if self.model_object.Insert():
            if assembly_number:
                self.assembly_number = assembly_number
            if part_number:
                self.part_number = part_number
            return self
        return None


class TeklaBeam(TeklaPart):
    """
    Wrapper around Tekla Beam object.

    Inherits from TeklaPart.
    """

    def __init__(self, beam: Beam | None = None):
        super().__init__(beam)
        self._beam = beam

    @property
    def start_point(self) -> Point:
        """Returns the start point of the beam."""
        return self.model_object.StartPoint

    @start_point.setter
    def start_point(self, value: Point) -> None:
        """Sets the start point of the beam."""
        self._set_property("StartPoint", value)

    @property
    def end_point(self) -> Point:
        """Returns the end point of the beam."""
        return self.model_object.EndPoint

    @end_point.setter
    def end_point(self, value: Point) -> None:
        """Sets the end point of the beam."""
        self._set_property("EndPoint", value)

    @property
    def start_point_offset(self) -> Offset:
        """Returns the start point offset of the beam."""
        return self.model_object.StartPointOffset

    @start_point_offset.setter
    def start_point_offset(self, value: OffsetInput) -> None:
        """Sets the start point offset of the beam."""
        offset = self.model_object.StartPointOffset
        offset.Dx = value.dx
        offset.Dy = value.dy
        offset.Dz = value.dz
        self.model_object.Modify()

    @property
    def end_point_offset(self) -> Offset:
        """Returns the end point offset of the beam."""
        return self.model_object.EndPointOffset

    @end_point_offset.setter
    def end_point_offset(self, value: OffsetInput) -> None:
        """Sets the end point offset of the beam."""
        offset = self.model_object.EndPointOffset
        offset.Dx = value.dx
        offset.Dy = value.dy
        offset.Dz = value.dz
        self.model_object.Modify()

    def apply_defaults(self, beam_type: BeamType) -> "TeklaBeam":
        """Apply default position settings based on beam type."""
        if beam_type == BeamType.COLUMN:
            self.model_object.Position.Depth = Position.DepthEnum.MIDDLE
            self.model_object.Position.Rotation = Position.RotationEnum.FRONT
            self.model_object.Position.Plane = Position.PlaneEnum.MIDDLE
        elif beam_type == BeamType.PANEL or beam_type == BeamType.BEAM:
            self.model_object.Position.Depth = Position.DepthEnum.FRONT
            self.model_object.Position.Rotation = Position.RotationEnum.TOP
            self.model_object.Position.Plane = Position.PlaneEnum.MIDDLE
        return self

    @staticmethod
    def create(
        start_point: PointInput,
        end_point: PointInput,
        profile: str,
        material: str,
        tekla_class: int,
        name: str | None = None,
        position: PositionInput | None = None,
        beam_type: BeamType = BeamType.BEAM,
        start_point_offset: OffsetInput | None = None,
        end_point_offset: OffsetInput | None = None,
        part_number: NumberingSeries | None = None,
        assembly_number: NumberingSeries | None = None,
    ) -> "TeklaBeam" | None:
        """
        Create and insert a new beam.

        Args:
            start: Start point
            end: End point
            profile: Profile name
            material: Material grade
            tekla_class: Tekla class number
            name: Element name (optional)
            position: Position settings (optional)
            beam_type: Type of beam - Beam, Column, or Panel (default: Beam)
            start_point_offset: Start point offset (optional)
            end_point_offset: End point offset (optional)
            part_number: NumberingSeries for part numbering (optional)
            assembly_number: NumberingSeries for assembly numbering (optional)

        Returns:
            TeklaBeam: The created beam wrapper
        """
        beam = Beam()
        beam.StartPoint = Point(start_point.x, start_point.y, start_point.z)
        beam.EndPoint = Point(end_point.x, end_point.y, end_point.z)
        beam.Profile.ProfileString = profile
        beam.Material.MaterialString = material
        beam.Class = str(tekla_class)
        if name:
            beam.Name = name

        if start_point_offset:
            beam.StartPointOffset.Dx = start_point_offset.dx
            beam.StartPointOffset.Dy = start_point_offset.dy
            beam.StartPointOffset.Dz = start_point_offset.dz

        if end_point_offset:
            beam.EndPointOffset.Dx = end_point_offset.dx
            beam.EndPointOffset.Dy = end_point_offset.dy
            beam.EndPointOffset.Dz = end_point_offset.dz

        tekla_beam = TeklaBeam(beam)
        tekla_beam.apply_position(position) if position else tekla_beam.apply_defaults(beam_type)
        return tekla_beam.finalize_placement(part_number, assembly_number)


class TeklaContourPlate(TeklaPart):
    """
    Wrapper around Tekla ContourPlate object.

    Inherits from TeklaPart.
    """

    def __init__(self, slab: ContourPlate | None = None):
        super().__init__(slab)
        self._slab = slab

    @property
    def contour_points(self) -> list[Point]:
        """Returns the contour points of the slab."""
        contour = self.model_object.Contour
        points = []
        enum = contour.ContourPoints
        while enum.MoveNext():
            points.append(enum.Current)
        return points

    @contour_points.setter
    def contour_points(self, points: list[Point]) -> None:
        """Sets the contour points of the slab."""
        for pt in points:
            contour_point = ContourPoint()
            contour_point.X = pt.x
            contour_point.Y = pt.y
            contour_point.Z = pt.z
            self.model_object.AddContourPoint(contour_point)
        self.model_object.Modify()

    def apply_defaults(self) -> "TeklaContourPlate":
        """Apply default position settings for a slab."""
        self.model_object.Position.Depth = Position.DepthEnum.MIDDLE
        self.model_object.Position.Rotation = Position.RotationEnum.TOP
        self.model_object.Position.Plane = Position.PlaneEnum.MIDDLE
        return self

    @staticmethod
    def create(
        points: list[PointInput],
        profile: str,
        material: str,
        tekla_class: int,
        name: str | None = None,
        position: PositionInput | None = None,
        part_number: NumberingSeries | None = None,
        assembly_number: NumberingSeries | None = None,
    ) -> "TeklaContourPlate" | None:
        """
        Create and insert a new slab.

        Args:
            points: List of contour points defining slab outline
            profile: Profile/thickness (e.g., '200', '300')
            material: Material grade
            tekla_class: Tekla class number
            name: Element name (optional)
            position: Position settings (optional)
            part_number: NumberingSeries for part numbering (optional)
            assembly_number: NumberingSeries for assembly numbering (optional)

        Returns:
            TeklaContourPlate: The created slab wrapper
        """
        slab = ContourPlate()
        slab.Profile.ProfileString = profile
        slab.Material.MaterialString = material
        slab.Class = str(tekla_class)
        if name:
            slab.Name = name

        for pt in points:
            contour_point = ContourPoint()
            contour_point.X = pt.x
            contour_point.Y = pt.y
            contour_point.Z = pt.z
            slab.AddContourPoint(contour_point)

        tekla_slab = TeklaContourPlate(slab)
        tekla_slab.apply_position(position) if position else tekla_slab.apply_defaults()
        return tekla_slab.finalize_placement(part_number, assembly_number)
