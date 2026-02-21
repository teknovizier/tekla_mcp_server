"""
Module for Tekla ModelObject wrappers.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable

from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import log_function_call

from tekla_mcp_server.tekla.loader import (
    Assembly,
    BaseWeld,
    Boolean,
    BooleanPart,
    Part,
    ModelObject,
    Point,
    Reinforcement,
    Hashtable,
)

from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser


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
    def cog(self) -> Point:
        """
        Retrieves the center of gravity (COG) point for a given Tekla model object.
        """
        cog_x = self.get_report_property("COG_X")
        cog_y = self.get_report_property("COG_Y")
        cog_z = self.get_report_property("COG_Z")

        return Point(cog_x, cog_y, cog_z)

    @log_function_call
    def get_top_level_assembly(self) -> TeklaModelObject | None:
        """
        Finds and returns the top-level assembly of this Tekla model object.

        It goes up the assembly chain until it reaches the highest one.
        If there's no assembly, it returns None.

        Raises:
            TypeError: If the returned object is not of type Assembly.
        """
        assembly = self._model_object.GetAssembly()
        if assembly is None:
            return None

        while assembly and assembly.GetAssembly():
            assembly = assembly.GetAssembly()

        if assembly is None:
            logger.warning("No assembly found for the object %s.", self.guid)
            return None

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
        property = TemplateAttributeParser.parse(property_name)
        is_ok, value = self.model_object.GetReportProperty(property_name, property.data_type())
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

    @staticmethod
    def _validate_property_type(property_type: type) -> None:
        """
        Validates that the given type is one of the supported types: str, int, or float.

        Raises:
            TypeError: If the type is not supported.
        """
        if property_type not in (str, int, float):
            raise TypeError("Property type must be one of: str, int, float.")


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

    @property
    def profile(self) -> str:
        """
        Returns the profile of the part.
        """
        return self.model_object.Profile.ProfileString

    @property
    def material(self) -> str:
        """
        Returns the material of the part.
        """
        return self.model_object.Material.MaterialString

    @property
    def finish(self) -> str:
        """
        Returns the finish of the part.
        """
        return self.model_object.Finish

    @property
    def tekla_class(self) -> str:
        """
        Returns the Tekla class of the part.
        """
        return self.model_object.Class

    @property
    def weight(self) -> tuple[float, float]:
        """
        Calculate the weight breakdown of a given Tekla model object.

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

    def has_spatial_overlap(self, other: TeklaModelObject) -> bool:
        """
        Checks whether the bounding boxes of this Tekla assembly and another TeklaModelObject intersect.
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
        Attempts to perform a boolean cut operation on this Tekla assembly using a TeklaPart as the cutting part.

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
        Returns the name of the main part.
        """
        return self.main_part.model_object.Name

    @property
    def profile(self) -> str:
        """
        Returns the profile of the main part.
        """
        return self.main_part.model_object.Profile.ProfileString

    @property
    def material(self) -> str:
        """
        Returns the material of the main part.
        """
        return self.main_part.model_object.Material.MaterialString

    @property
    def finish(self) -> str:
        """
        Returns the finish of the main part.
        """
        return self.main_part.model_object.Finish

    @property
    def tekla_class(self) -> str:
        """
        Returns the Tekla class of the main part.
        """
        return self.main_part.model_object.Class

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


def wrap_model_object(model_object: ModelObject) -> TeklaModelObject | None:
    """
    Wraps a Tekla ModelObject in the appropriate wrapper class.

    Returns:
        - TeklaAssembly if the object is an Assembly
        - TeklaPart if the object is a Part
        - TeklaModelObject for any other object types
    """
    if isinstance(model_object, Assembly):
        return TeklaAssembly(model_object)
    elif isinstance(model_object, Part):
        return TeklaPart(model_object)
    elif isinstance(model_object, Boolean) or isinstance(model_object, BaseWeld) or isinstance(model_object, Reinforcement):
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
