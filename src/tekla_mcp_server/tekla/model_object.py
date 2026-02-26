"""
Module for Tekla ModelObject wrappers.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable

from tekla_mcp_server.init import logger
from tekla_mcp_server.models import AssemblySnapshot, PartSnapshot
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
    BaseRebarGroup,
    RebarMesh,
    RebarStrand,
    SingleRebar,
)

ASSEMBLY_REPORT_PROPS = [
    "AREA",
    "ASSEMBLY_PREFIX",
    "HEIGHT",
    "HIERARCHY_LEVEL",
    "LENGTH",
    "LENGTH_GROSS",
    "MATERIAL_TYPE",
    "NAME",
    "VOLUME",
    "WEIGHT",
    "WEIGHT_NET",
    "WEIGHT_GROSS",
    "WIDTH",
]

PART_REPORT_PROPS = [
    "AREA",
    "ASSEMBLY_PREFIX",
    "FINISH",
    "HEIGHT",
    "HIERARCHY_LEVEL",
    "LENGTH",
    "LENGTH_GROSS",
    "MATERIAL",
    "MATERIAL_TYPE",
    "NAME",
    "PART_PREFIX",
    "PART_START_NUMBER",
    "PROFILE",
    "RADIUS",
    "VOLUME",
    "WEIGHT",
    "WEIGHT_NET",
    "WEIGHT_GROSS",
    "WIDTH",
]

REBAR_GROUP_PROPS = [
    "DIM_A",
    "DIM_B",
    "DIM_C",
    "DIM_D",
    "DIM_E",
    "DIM_F",
    "DIM_G",
    "DIM_H1",
    "DIM_H2",
    "DIM_I",
    "DIM_J",
    "DIM_K1",
    "DIM_K2",
    "DIM_L",
    "DIM_O",
    "DIM_R",
    "DIM_R_ALL",
    "DIM_TD",
    "DIM_WEIGHT",
    "DIM_X",
    "DIM_Y",
    "GRADE",
    "GROUP_TYPE",
    "LENGTH",
    "LENGTH_GROSS",
    "LENGTH_MAX",
    "LENGTH_MIN",
    "MATERIAL",
    "NAME",
    "NUMBER",
    "REBAR_POS",
    "SHAPE",
    "SHAPE_INTERNAL",
    "SIZE",
    "WEIGHT",
    "WEIGHT_TOTAL",
]

REBAR_MESH_PROPS = [
    "CC",
    "CC_CROSS",
    "CC_LONG",
    "CC_MAX",
    "CC_MAX_CROSS",
    "CC_MAX_LONG",
    "CC_MIN",
    "CC_MIN_CROSS",
    "CC_MIN_LONG",
    "GRADE",
    "LENGTH",
    "MATERIAL",
    "MATERIAL_TYPE",
    "MESH_POS",
    "NAME",
    "NUMBER",
    "PREFIX",
    "SIZE",
    "WEIGHT",
]

REBAR_STRAND_PROPS = [
    "GRADE",
    "LENGTH",
    "LENGTH_GROSS",
    "LENGTH_MAX",
    "LENGTH_MIN",
    "MATERIAL",
    "MATERIAL_TYPE",
    "NAME",
    "NUMBER",
    "PREFIX",
    "SIZE",
    "STRAND_N_PATTERN",
    "STRAND_N_STRAND",
    "STRAND_POS",
    "STRAND_PULL_FORCE",
    "WEIGHT",
    "WEIGHT_TOTAL",
]

WELD_REPORT_PROPS = [
    "WELD_ACTUAL_LENGTH1",
    "WELD_ACTUAL_LENGTH2",
    "WELD_ADDITIONAL_SIZE1",
    "WELD_ADDITIONAL_SIZE2",
    "WELD_ANGLE1",
    "WELD_ANGLE2",
    "WELD_CROSSSECTION_AREA1",
    "WELD_CROSSSECTION_AREA2",
    "WELD_EFFECTIVE_THROAT",
    "WELD_EFFECTIVE_THROAT2",
    "WELD_FILLTYPE1",
    "WELD_FILLTYPE2",
    "WELD_FINISH1",
    "WELD_FINISH2",
    "WELD_INCREMENT_AMOUNT1",
    "WELD_INCREMENT_AMOUNT2",
    "WELD_INTERMITTENT_TYPE",
    "WELD_LENGTH1",
    "WELD_LENGTH2",
    "WELD_PERIOD1",
    "WELD_PERIOD2",
    "WELD_ROOT_FACE_THICKNESS",
    "WELD_ROOT_FACE_THICKNESS2",
    "WELD_ROOT_OPENING",
    "WELD_ROOT_OPENING2",
    "WELD_SIZE1",
    "WELD_SIZE2",
    "WELD_SIZE_PREFIX_ABOVE",
    "WELD_SIZE_PREFIX_BELOW",
    "WELD_TYPE1",
    "WELD_TYPE2",
    "WELD_VOLUME",
    "WELD_ASSEMBLYTYPE",
    "WELD_DEFAULT",
    "WELD_ELECTRODE_CLASSIFICATION",
    "WELD_ELECTRODE_COEFFICIENT",
    "WELD_ELECTRODE_STRENGTH",
    "WELD_ERRORLIST",
    "WELD_NDT_INSPECTION",
    "WELD_NUMBER",
    "WELD_PROCESS_TYPE",
    "WELD_TEXT",
    "WELD_EDGE_AROUND",
    "WELD_FATHER_CODE",
    "WELD_FATHER_NUMBER",
]

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

        # Fetch report properties and user-defined attributes
        report_properties = self.get_multiple_report_properties(PART_REPORT_PROPS)
        user_properties = self.get_all_user_properties()

        # Sort dictionaries by key to eliminate order differences
        report_properties = dict(sorted(report_properties.items()))
        user_properties = dict(sorted(user_properties.items()))

        # Extract cutparts (boolean operations applied to the part)
        cutparts = []
        boolean_enum = self.model_object.GetBooleans()
        while boolean_enum.MoveNext():
            boolean_part = boolean_enum.Current
            if isinstance(boolean_part, BooleanPart):
                operative_part = boolean_part.OperativePart
                if operative_part:
                    # Calculate relative position to the main part
                    try:
                        boolean_pos = operative_part.GetCoordinateSystem().Origin
                        main_pos = self.model_object.GetCoordinateSystem().Origin
                        relative_position = {
                            "dx": float(boolean_pos.X - main_pos.X),
                            "dy": float(boolean_pos.Y - main_pos.Y),
                            "dz": float(boolean_pos.Z - main_pos.Z),
                        }
                    except Exception:
                        relative_position = None

                    cutparts.append(
                        {
                            "id": operative_part.Identifier.ID,
                            "guid": operative_part.Identifier.GUID.ToString(),
                            "name": operative_part.Name,
                            "profile": operative_part.Profile.ProfileString,
                            "type": str(boolean_part.Type),
                            "relative_position": relative_position,
                        }
                    )

        cutparts = sorted(cutparts, key=lambda b: (b["id"], b["name"]))

        # Extract reinforcements (rebar groups, meshes, strands)
        reinforcements = []
        reinf_enum = self.model_object.GetReinforcements()
        while reinf_enum.MoveNext():
            rebar = reinf_enum.Current
            wrapped_rebar = TeklaModelObject(rebar)

            # Select appropriate properties based on rebar type
            if isinstance(rebar, (BaseRebarGroup, SingleRebar)):
                prop_names = REBAR_GROUP_PROPS
            elif isinstance(rebar, RebarMesh):
                prop_names = REBAR_MESH_PROPS
            elif isinstance(rebar, RebarStrand):
                prop_names = REBAR_STRAND_PROPS
            else:
                prop_names = []

            rebar_wrapped = wrap_model_object(rebar)
            rebar_props = rebar_wrapped.get_multiple_report_properties(prop_names) if rebar_wrapped else {}
            rebar_udas = wrapped_rebar.get_all_user_properties()

            reinforcements.append(
                {
                    "id": rebar.Identifier.ID,
                    "guid": rebar.Identifier.GUID.ToString(),
                    "name": rebar.Name,
                    "report_properties": rebar_props,
                    "user_properties": rebar_udas,
                }
            )

        reinforcements = sorted(reinforcements, key=lambda r: (r["id"], r["name"]))

        # Extract welds
        welds = []
        weld_enum = self.model_object.GetWelds()
        while weld_enum.MoveNext():
            weld = weld_enum.Current
            weld_wrapped = wrap_model_object(weld)
            weld_props = weld_wrapped.get_multiple_report_properties(WELD_REPORT_PROPS) if weld_wrapped else {}

            # Calculate relative position to the main part
            try:
                weld_pos = weld.GetCoordinateSystem().Origin
                main_pos = self.model_object.GetCoordinateSystem().Origin
                relative_position = {
                    "dx": float(weld_pos.X - main_pos.X),
                    "dy": float(weld_pos.Y - main_pos.Y),
                    "dz": float(weld_pos.Z - main_pos.Z),
                }
            except Exception:
                relative_position = None

            welds.append(
                {
                    "id": weld.Identifier.ID,
                    "guid": weld.Identifier.GUID.ToString(),
                    "report_properties": weld_props,
                    "relative_position": relative_position,
                }
            )

        welds = sorted(welds, key=lambda w: (w["id"]))

        return PartSnapshot(
            guid=self.guid,
            id=self.id,
            pos=self.position,
            report_properties=report_properties,
            user_properties=user_properties,
            cutparts=cutparts,
            reinforcements=reinforcements,
            welds=welds,
        )


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

        # Fetch report properties and user-defined attributes
        report_properties = self.get_multiple_report_properties(ASSEMBLY_REPORT_PROPS)
        user_properties = self.get_all_user_properties()

        # Sort dictionaries by key to eliminate order differences
        report_properties = dict(sorted(report_properties.items()))
        user_properties = dict(sorted(user_properties.items()))

        # Extract main part snapshot
        main_part = self.main_part
        main_part_snapshot = None
        if isinstance(main_part, TeklaPart):
            main_part_snapshot = main_part.to_snapshot()

        # Extract secondaries snapshots
        secondaries = []
        for secondary in wrap_model_objects(self.model_object.GetSecondaries()):
            if isinstance(secondary, TeklaPart):
                secondaries.append(secondary.to_snapshot())

        secondaries = sorted(secondaries, key=lambda s: (s.id, s.name))

        # Extract subassemblies snapshots
        subassemblies = []
        for subassembly in wrap_model_objects(self.model_object.GetSubAssemblies()):
            if isinstance(subassembly, TeklaAssembly):
                subassemblies.append(subassembly.to_snapshot())

        subassemblies = sorted(subassemblies, key=lambda s: (s.id, s.pos))

        return AssemblySnapshot(
            id=self.id,
            guid=self.guid,
            pos=self.position,
            report_properties=report_properties,
            user_properties=user_properties,
            main_part=main_part_snapshot,
            secondaries=secondaries,
            subassemblies=subassemblies,
        )


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
