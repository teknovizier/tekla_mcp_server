"""
Module for Tekla ModelObject wrappers.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterable
from typing import Any, overload

from tekla_mcp_server.config import get_config, get_tolerance
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import AssemblySnapshot, NumberingSeries, PartSnapshot, ReinforcementSnapshot, BeamType, OffsetInput, PointInput, PositionInput
from tekla_mcp_server.utils import validate_property_type

from tekla_mcp_server.tekla.loader import (
    Assembly,
    Beam,
    BaseWeld,
    BooleanPart,
    ContourPlate,
    ContourPoint,
    Part,
    ModelObject,
    Offset,
    Point,
    LineSegment,
    Position,
    Reinforcement,
    Solid,
    Hashtable,
    Phase,
    ReferenceModelObject,
)


from tekla_mcp_server.tekla.snapshot_builder import SnapshotBuilder
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser

ZERO_GUID = "00000000-0000-0000-0000-000000000000"


def get_tekla_classes(material_key: str) -> set[int]:
    """Get all tekla_classes for a material group from the config."""
    material = get_config().element_types.get(material_key, {})
    return {tekla_class for type_config in material.values() for tekla_class in type_config.get("tekla_classes", [])}


# Class IDs identifying embedded-detail subassemblies
EMBEDDED_DETAILS_CLASSES: set[int] = get_tekla_classes("MATERIAL_EMBEDDED")
# Class IDs identifying reinforcement objects
REINFORCEMENT_CLASSES: set[int] = get_tekla_classes("MATERIAL_REINFORCEMENT")


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

    def overlaps(self, other: BoundingBox, tol: float | None = None) -> bool:
        """
        Check if bounding boxes overlap within tolerance.
        """
        if tol is None:
            tol = get_tolerance("default", 20.0)
        return (
            self.min_x <= other.max_x + tol
            and self.max_x >= other.min_x - tol
            and self.min_y <= other.max_y + tol
            and self.max_y >= other.min_y - tol
            and self.min_z <= other.max_z + tol
            and self.max_z >= other.min_z - tol
        )

    def matches(self, other: BoundingBox, tol: float | None = None, center_tol_factor: float | None = None) -> bool:
        """
        Match using spatial overlap + centroid distance.
        """
        if tol is None:
            tol = get_tolerance("default", 20.0)
        if center_tol_factor is None:
            center_tol_factor = get_tolerance("center_tolerance_factor", default=0.1)
        if not self.overlaps(other, tol):
            return False

        c1, c2 = self.centroid, other.centroid
        dist = math.sqrt((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2)

        diag = max(self.diagonal, other.diagonal)
        adaptive_tol = max(center_tol_factor * diag, tol)

        return dist <= adaptive_tol


def _ray_cast_inside(solid_self: Solid, solid_other: Solid) -> bool:
    """
    Odd/even ray-cast test - returns True if the center of the overlapping AABB
    of the two solids lies inside `solid_other`.

    Casts a ray in a non-axis-aligned direction to avoid grazing hits, counts
    only forward-half-space intersections. An odd count means inside.
    Does not handle invalid solids. Callers must validate before calling.
    """
    cmin, cmax = solid_self.MinimumPoint, solid_self.MaximumPoint
    emin, emax = solid_other.MinimumPoint, solid_other.MaximumPoint
    # Optimization: skip ray cast when AABBs have no positive-width overlap.
    # Zero-width (touching) AABBs return False immediately - the `>=` guard
    # catches them before any ray is cast. This is correct for a tangential
    # touch: touching objects do not contain each other.
    if max(cmin.X, emin.X) >= min(cmax.X, emax.X) or max(cmin.Y, emin.Y) >= min(cmax.Y, emax.Y) or max(cmin.Z, emin.Z) >= min(cmax.Z, emax.Z):
        return False
    cx = (max(cmin.X, emin.X) + min(cmax.X, emax.X)) * 0.5
    cy = (max(cmin.Y, emin.Y) + min(cmax.Y, emax.Y)) * 0.5
    cz = (max(cmin.Z, emin.Z) + min(cmax.Z, emax.Z)) * 0.5

    # Ray direction: irrational-ratio, non-axis-aligned values avoid accidental
    # alignment with flat faces or edges (which would cause a grazing/tangent hit
    # counted as 0 or 2 intersections instead of 1, corrupting the parity).
    # Magnitudes are ~1 km in Tekla's mm units - large enough to exit any realistic
    # structural element from any origin inside it, small enough to stay within
    # floating-point precision for the Tekla geometry kernel.
    dx, dy, dz = 1.2345e6, 0.9182e6, 0.4571e6
    hits = solid_other.Intersect(LineSegment(Point(cx, cy, cz), Point(cx + dx, cy + dy, cz + dz)))
    if hits is None:
        return False
    count = sum(1 for i in range(hits.Count) if (hits[i].X - cx) * dx + (hits[i].Y - cy) * dy + (hits[i].Z - cz) * dz > 0)
    return count % 2 == 1


class SolidGeometryMixin:
    """Mixin for wrapped model objects that support Tekla solid geometry queries."""

    @property
    def model_object(self) -> ModelObject:
        raise NotImplementedError

    def get_solid(self) -> Solid:
        """
        Returns the solid of the model object.
        """
        return self.model_object.GetSolid()

    def is_inside(self, other: TeklaModelObject) -> bool:
        """
        Return True if `self` object lies inside `other` using an odd/even ray-cast test.

        A ray is cast from the center of the overlapping AABB region in a non-axis-aligned
        direction to avoid grazing hits. Only forward-half-space intersections are counted.
        An odd count means the origin is inside the solid, an even count means outside.

        When `other` is a TeklaPart and the NORMAL solid test returns False, a RAW
        (pre-boolean-cut) solid fallback is attempted automatically. The fallback is
        gated on a centroid pre-check: the candidate's own centroid must lie within the
        container's RAW-solid AABB. Using RAW (not NORMAL) ensures embeds inside a
        boolean-cut corner are not rejected when the NORMAL AABB is tighter than the
        original material envelope. Legitimate neighbours whose centroid is entirely
        outside the original part are still rejected.

        Notes:
        - Simple convex and moderately concave geometry (L/T shapes) is typically handled
          correctly. Highly concave or re-entrant solids may produce false results if the
          ray exits and re-enters through the concavity, yielding an even parity count.
        - Near-tangent or very thin geometry may still produce false positives or negatives.
        - Any geometry/kernel failure conservatively returns True to avoid false negatives.
        """
        try:
            # Get solids - prefer NORMAL (includes cuts/booleans) for both sides.
            # Some Tekla types don't support SolidCreationTypeEnum, so fall back to GetSolid().
            if isinstance(other, TeklaPart):
                solid_other = other.get_solid(Solid.SolidCreationTypeEnum.NORMAL)
            elif isinstance(other, SolidGeometryMixin):
                solid_other = other.get_solid()
            else:
                logger.warning("is_inside: unknown container type %s, defaulting to inside", type(other).__name__)
                return True  # conservative
            if isinstance(self, TeklaPart):
                solid_self = self.get_solid(Solid.SolidCreationTypeEnum.NORMAL)
            elif isinstance(self, SolidGeometryMixin):
                solid_self = self.get_solid()
            if not solid_other or not solid_other.IsValid():
                logger.warning("is_inside: container solid invalid (%s), defaulting to inside", "None" if not solid_other else "!IsValid()")
                return True  # conservative
            if not solid_self or not solid_self.IsValid():
                logger.warning("is_inside: self solid invalid (%s), defaulting to inside", "None" if not solid_self else "!IsValid()")
                return True  # conservative

            # Primary test against NORMAL solid
            if _ray_cast_inside(solid_self, solid_other):
                return True

            # NORMAL returned False - fall back to RAW solid for TeklaPart containers.
            # Embeds in boolean-cut sleeve holes sit in the void of the NORMAL solid
            # but are physically within the original wall material.
            # Gate on a centroid pre-check to reject neighbouring structural elements
            # whose bounding box grazes the container but whose centre is outside it.
            if not isinstance(other, TeklaPart):
                return False

            solid_raw = other.get_solid(Solid.SolidCreationTypeEnum.RAW)
            if not solid_raw or not solid_raw.IsValid():
                return True  # conservative

            # Gate on RAW AABB (not NORMAL) so that embeds inside a boolean-cut
            # corner are not rejected: the RAW solid covers the full original
            # material volume, whereas the NORMAL AABB may be tighter after a cut
            # removes a corner. Legitimate neighbours whose centroid lies entirely
            # outside the original part are still rejected.
            cmin, cmax = solid_self.MinimumPoint, solid_self.MaximumPoint
            rmin, rmax = solid_raw.MinimumPoint, solid_raw.MaximumPoint
            scx, scy, scz = (cmin.X + cmax.X) * 0.5, (cmin.Y + cmax.Y) * 0.5, (cmin.Z + cmax.Z) * 0.5
            if not (rmin.X <= scx <= rmax.X and rmin.Y <= scy <= rmax.Y and rmin.Z <= scz <= rmax.Z):
                return False  # centroid outside RAW AABB - not embedded

            return _ray_cast_inside(solid_self, solid_raw)
        except Exception:
            logger.warning("is_inside containment test failed, defaulting to inside")
            return True  # conservative


def wrap_model_object(model_object: ModelObject) -> TeklaModelObject | None:
    """
    Wraps a Tekla ModelObject in the appropriate wrapper class.

    Returns:
        - TeklaAssembly if the object is an Assembly
        - TeklaBeam if the object is a Beam
        - TeklaContourPlate if the object is a ContourPlate
        - TeklaPart if the object is a Part
        - TeklaReferenceModelObject if the object is a ReferenceModelObject
        - TeklaReinforcement if the object is a TeklaReinforcement
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
    elif isinstance(model_object, Reinforcement):
        return TeklaReinforcement(model_object)
    elif isinstance(model_object, BaseWeld):
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


def _get_top_assembly(assembly: ModelObject) -> "TeklaAssembly":
    """
    Walks up the object tree and returns the topmost Assembly wrapper.
    """
    parent = assembly.GetAssembly()
    while parent is not None:
        assembly = parent
        parent = assembly.GetAssembly()
    return TeklaAssembly(assembly)


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
    def element_type(self) -> str:
        """
        Returns the Tekla C# class name of the model object (e.g. 'Beam', 'ContourPlate', 'Assembly').
        """
        return type(self._model_object).__name__

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
        """
        Get bounding box from report properties.
        """
        try:
            return BoundingBox(self)
        except Exception:
            return None

    def modify(self) -> bool:
        """
        Commits pending property changes to the model.
        Returns True if successful.
        """
        return self.model_object.Modify()

    def delete(self) -> bool:
        """
        Deletes the object from the model.
        Returns True if successful.
        """
        return self.model_object.Delete()

    def get_top_level_assembly(self) -> "TeklaAssembly | None":
        """
        Gets top level assembly.
        """
        try:
            assembly = self._model_object.GetAssembly()
        except Exception:
            return None
        if assembly is None:
            return None
        return _get_top_assembly(assembly)

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
        validate_property_type(property_type)
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
        validate_property_type(type(property_value))
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

    def _set_property(self, prop_name: str, value: str) -> None:
        """
        Helper to set a property on the model object.

        Args:
            prop_name: Name of the property. Supports dotted paths up to two levels
                deep (e.g. 'Profile.ProfileString'). Deeper paths raise ValueError.
            value: Value to set

        Raises:
            ValueError: If the property path is too deep.
        """
        parts = prop_name.split(".")
        if len(parts) == 1:
            setattr(self.model_object, parts[0], value)
        elif len(parts) == 2:
            setattr(getattr(self.model_object, parts[0]), parts[1], value)
        else:
            raise ValueError(f"Property path too deep: '{prop_name}'")
        self.modify()


class TeklaReferenceModelObject(TeklaModelObject):
    """
    A wrapper class around the Tekla Structures ReferenceModelObject object.
    """

    def get_report_property(self, property_name: str) -> str | int | float:
        """
        Retrieves a report property from ReferenceModelObject.

        First tries using TemplateAttributeParser via base class method.
        Falls back to using str type if not found in attribute definitions.
        Falls back to trying with "EXTERNAL." prefix for IFC properties.

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
                is_ok, value = self.model_object.GetReportProperty(f"EXTERNAL.{property_name}", str())
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
        """
        Sets the name of the assembly.
        """
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
        self.modify()

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

    def is_embedded_detail(self) -> bool:
        """
        Return True if this assembly is an embedded detail,
        identified by its main part's `tekla_class`.

        Raises:
            ValueError: If the main part is not available.
        """
        main_part = self.main_part
        return isinstance(main_part, TeklaPart) and main_part.tekla_class in EMBEDDED_DETAILS_CLASSES

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
            except AttributeError:
                rebar_type = ""
            if rebar_type:
                weight_rebars += float(weight_sub)
            else:
                weight_subassemblies += float(weight_sub)

        total_parts_weight = weight_main_part + weight_secondaries + weight_subassemblies

        return total_parts_weight, weight_rebars

    def get_top_level_assembly(self) -> "TeklaAssembly":
        """
        Gets the top assembly for the given assembly.
        """
        return _get_top_assembly(self._model_object)

    def get_top_level_parts(self) -> list[TeklaPart]:
        """
        Returns the top-level parts of this assembly (main + secondaries).

        Does not recurse into subassemblies - only the parts directly owned
        by this assembly are returned.
        """
        parts: list[TeklaPart] = []
        try:
            mp = self.main_part
            if isinstance(mp, TeklaPart):
                parts.append(mp)
        except ValueError:
            logger.warning("Assembly has no main part - using secondaries only")
        try:
            secondaries = self.model_object.GetSecondaries()
        except Exception:
            logger.warning("Failed to get secondaries for assembly")
            return parts
        for sec in wrap_model_objects(secondaries):
            if isinstance(sec, TeklaPart):
                parts.append(sec)
        return parts

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
    ) -> dict[str, Any]:
        """
        Sets properties on the assembly.
        Returns a summary of changes made, including a list of per-property errors.
        """
        changes: dict[str, int] = {
            "name": 0,
            "assembly_prefix": 0,
            "assembly_start_number": 0,
            "phase": 0,
            "udas": 0,
        }
        errors: list[dict[str, str]] = []

        if name is not None:
            try:
                self.name = name
                changes["name"] = 1
            except Exception as e:
                errors.append({"property": "name", "reason": str(e)})

        if assembly_prefix is not None:
            try:
                self.model_object.AssemblyNumber.Prefix = assembly_prefix
                self.modify()
                changes["assembly_prefix"] = 1
            except Exception as e:
                errors.append({"property": "assembly_prefix", "reason": str(e)})

        if assembly_start_number is not None:
            try:
                self.model_object.AssemblyNumber.StartNumber = assembly_start_number
                self.modify()
                changes["assembly_start_number"] = 1
            except Exception as e:
                errors.append({"property": "assembly_start_number", "reason": str(e)})

        if phase is not None:
            try:
                if self.model_object.SetPhase(Phase(phase)):
                    self.modify()
                    changes["phase"] = 1
                else:
                    errors.append({"property": "phase", "reason": "SetPhase returned False"})
            except Exception as e:
                errors.append({"property": "phase", "reason": str(e)})

        if user_properties:
            for key, value in user_properties.items():
                try:
                    if self.set_user_property(key, value):
                        changes["udas"] += 1
                    else:
                        errors.append({"property": f"uda:{key}", "reason": "SetUserProperty returned False"})
                except Exception as e:
                    errors.append({"property": f"uda:{key}", "reason": str(e)})

        return {**changes, "errors": errors}


class TeklaPart(TeklaModelObject, SolidGeometryMixin):
    """
    A wrapper class around the Tekla Structures Part object.
    """

    @overload
    def get_solid(self) -> Solid: ...

    @overload
    def get_solid(self, creation_type: Solid.SolidCreationTypeEnum) -> Solid: ...
    def get_solid(self, creation_type: Solid.SolidCreationTypeEnum = None) -> Solid:
        """
        Returns the solid of the part.
        Pass a SolidCreationTypeEnum for a specific solid type.
        """
        if creation_type is None:
            return self.model_object.GetSolid()

        return self.model_object.GetSolid(creation_type)

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
    def tekla_class(self) -> int:
        """
        Returns the Tekla class of the part as an integer.

        Tekla exposes Class as a string, but semantically it is a numeric
        category. Non-numeric values are normalized to 0.
        """
        try:
            return int(self.model_object.Class)
        except (TypeError, ValueError):
            return 0

    @tekla_class.setter
    def tekla_class(self, value: int | str) -> None:
        """Sets the Tekla class of the part."""
        self._set_property("Class", str(value))

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
        self.modify()

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
        self.modify()

    @property
    def weight(self) -> tuple[float, float]:
        """
        Calculate the weight breakdown of a given part.

        This function returns two weight values:
        - The total weight of the element.
        - The total weight of all reinforcement bars associated with the element.
        """
        weight_main_part = float(self.get_report_property("WEIGHT"))

        weight_rebars = 0.0
        for rebar in wrap_model_objects(self.model_object.GetReinforcements()):
            weight_rebar = rebar.get_report_property("WEIGHT_TOTAL")
            weight_rebars += float(weight_rebar)

        return weight_main_part, weight_rebars

    def get_top_level_assembly(self) -> TeklaAssembly | None:
        """
        Gets the part's containing assembly and walk up to the top.
        """
        assembly = self._model_object.GetAssembly()
        if assembly is None:
            logger.warning("No assembly found for part %s.", self.guid)
            return None
        return _get_top_assembly(assembly)

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

    def has_spatial_overlap(self, other: SolidGeometryMixin) -> bool:
        """
        Checks whether the bounding boxes of this Tekla part and another SolidGeometryMixin object intersect.
        """
        solid_self = self.get_solid()
        solid_other = other.get_solid()

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
                    if cutting_part.delete():
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
        tekla_class: int | None = None,
        finish: str | None = None,
        phase: int | None = None,
        part_prefix: str | None = None,
        part_start_number: int | None = None,
        assembly_prefix: str | None = None,
        assembly_start_number: int | None = None,
        user_properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Sets properties on the part.
        Returns a summary of changes made, including a list of per-property errors.
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
        errors: list[dict[str, str]] = []

        if name is not None:
            try:
                self.name = name
                changes["name"] = 1
            except Exception as e:
                errors.append({"property": "name", "reason": str(e)})

        if profile is not None:
            try:
                self.profile = profile
                changes["profile"] = 1
            except Exception as e:
                errors.append({"property": "profile", "reason": str(e)})

        if material is not None:
            try:
                self.material = material
                changes["material"] = 1
            except Exception as e:
                errors.append({"property": "material", "reason": str(e)})

        if tekla_class is not None:
            try:
                self.tekla_class = tekla_class
                changes["tekla_class"] = 1
            except Exception as e:
                errors.append({"property": "tekla_class", "reason": str(e)})

        if finish is not None:
            try:
                self.finish = finish
                changes["finish"] = 1
            except Exception as e:
                errors.append({"property": "finish", "reason": str(e)})

        if part_prefix is not None:
            try:
                self.model_object.PartNumber.Prefix = part_prefix
                self.modify()
                changes["part_prefix"] = 1
            except Exception as e:
                errors.append({"property": "part_prefix", "reason": str(e)})

        if part_start_number is not None:
            try:
                self.model_object.PartNumber.StartNumber = part_start_number
                self.modify()
                changes["part_start_number"] = 1
            except Exception as e:
                errors.append({"property": "part_start_number", "reason": str(e)})

        if assembly_prefix is not None:
            try:
                self.model_object.AssemblyNumber.Prefix = assembly_prefix
                self.modify()
                changes["assembly_prefix"] = 1
            except Exception as e:
                errors.append({"property": "assembly_prefix", "reason": str(e)})

        if assembly_start_number is not None:
            try:
                self.model_object.AssemblyNumber.StartNumber = assembly_start_number
                self.modify()
                changes["assembly_start_number"] = 1
            except Exception as e:
                errors.append({"property": "assembly_start_number", "reason": str(e)})

        if phase is not None:
            try:
                if self.model_object.SetPhase(Phase(phase)):
                    self.modify()
                    changes["phase"] = 1
                else:
                    errors.append({"property": "phase", "reason": "SetPhase returned False"})
            except Exception as e:
                errors.append({"property": "phase", "reason": str(e)})

        if user_properties:
            for key, value in user_properties.items():
                try:
                    if self.set_user_property(key, value):
                        changes["udas"] += 1
                    else:
                        errors.append({"property": f"uda:{key}", "reason": "SetUserProperty returned False"})
                except Exception as e:
                    errors.append({"property": f"uda:{key}", "reason": str(e)})

        return {**changes, "errors": errors}

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
        self.modify()

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
        self.modify()

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
        """Sets the contour points of the slab, replacing any existing points."""
        self.model_object.Contour.ContourPoints.Clear()
        for pt in points:
            contour_point = ContourPoint()
            contour_point.X = pt.X
            contour_point.Y = pt.Y
            contour_point.Z = pt.Z
            self.model_object.AddContourPoint(contour_point)
        self.modify()

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
            profile: Profile/thickness (e.g. '200', '300')
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


class TeklaReinforcement(TeklaModelObject, SolidGeometryMixin):
    """
    A wrapper class around the Tekla Structures Reinforcement object.
    """

    @property
    def position(self) -> str:
        """
        Returns the position number of the reinforcement element.
        """
        return str(self.get_report_property("REBAR_POS"))

    @property
    def name(self) -> str:
        """
        Returns the name of the reinforcement element.
        """
        return self.model_object.Name

    @name.setter
    def name(self, value: str) -> None:
        """
        Sets the name of the reinforcement element.
        """
        self._set_property("Name", value)

    @property
    def tekla_class(self) -> int:
        """
        Returns the Tekla class of the reinforcement element as an integer.

        Tekla exposes Class as a string, but semantically it is a numeric
        category. Non-numeric values are normalized to 0.
        """
        try:
            return int(self.model_object.Class)
        except (TypeError, ValueError):
            return 0

    @tekla_class.setter
    def tekla_class(self, value: int | str) -> None:
        """
        Sets the Tekla class of the reinforcement element.
        """
        self._set_property("Class", str(value))

    @property
    def father(self) -> TeklaModelObject | None:
        """
        The part the reinforcement element is attached to.
        """
        raw = self.model_object.Father
        if raw is None:
            return None
        return wrap_model_object(raw)

    @father.setter
    def father(self, value: TeklaModelObject | None) -> None:
        """
        Sets the father part of this reinforcement element.
        """
        self.model_object.Father = value.model_object if value is not None else None
        self.modify()

    @property
    def rebar_number(self) -> NumberingSeries:
        """
        Returns the numbering series of the reinforcement.
        """
        ns = self.model_object.NumberingSeries
        return NumberingSeries(prefix=ns.Prefix, start_number=ns.StartNumber)

    def get_top_level_assembly(self) -> TeklaAssembly | None:
        """
        Returns the top-level assembly of the reinforcement's father part.
        """
        host = self.father
        if host is None:
            logger.warning("No Father found for reinforcement %s.", self.guid)
            return None
        return host.get_top_level_assembly()

    def get_properties(self, report_props_definitions: list[str] | None = None) -> dict[str, Any]:
        """
        Gets element properties for Reinforcement.
        """
        props = super().get_properties(report_props_definitions)
        props["position"] = self.position
        props["name"] = self.name
        props["tekla_class"] = self.tekla_class
        props["rebar_type"] = type(self.model_object).__name__
        rebar_number = self.rebar_number
        props["rebar_prefix"] = rebar_number.prefix
        props["rebar_start_number"] = rebar_number.start_number
        father = self.father
        props["father_guid"] = father.guid if father is not None else None
        return props

    def to_snapshot(self) -> ReinforcementSnapshot:
        """
        Creates a typed snapshot of this reinforcement object.
        Returns a ReinforcementSnapshot with report properties, UDAs, father GUID, and rebar type.
        """
        return SnapshotBuilder.build_reinforcement_snapshot(self)
