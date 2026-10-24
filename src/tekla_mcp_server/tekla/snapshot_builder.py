"""
SnapshotBuilder extracts snapshot data from Tekla objects.
"""

from typing import Any

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import AssemblySnapshot, PartSnapshot, ReinforcementSnapshot

from tekla_mcp_server.tekla.loader import (
    BaseRebarGroup,
    BooleanPart,
    RebarMesh,
    RebarStrand,
    SingleRebar,
)


class SnapshotBuilder:
    """Stateless builder that extracts snapshot data from Tekla objects."""

    @staticmethod
    def build_part_snapshot(part: Any) -> PartSnapshot:
        report_properties = SnapshotBuilder._build_report_properties(part, get_config().get_report_props("part"))
        user_properties = SnapshotBuilder._build_sorted_user_properties(part)
        # Shared by cut parts and welds so the part's origin is read at most once
        origin_cache: dict[str, tuple[float, float, float] | None] = {}
        cutparts = SnapshotBuilder._build_cutparts(part, origin_cache)
        reinforcements = SnapshotBuilder._build_reinforcements(part)
        welds = SnapshotBuilder._build_welds(part, origin_cache)

        return PartSnapshot(
            guid=part.guid,
            id=part.id,
            pos=part.position,
            report_properties=report_properties,
            user_properties=user_properties,
            cutparts=cutparts,
            reinforcements=reinforcements,
            welds=welds,
        )

    @staticmethod
    def build_assembly_snapshot(assembly: Any) -> AssemblySnapshot:
        from tekla_mcp_server.tekla.wrappers.model_object import TeklaAssembly, TeklaPart, wrap_model_objects

        report_properties = SnapshotBuilder._build_report_properties(assembly, get_config().get_report_props("assembly"))
        user_properties = SnapshotBuilder._build_sorted_user_properties(assembly)

        main_part_snapshot = None
        try:
            main_part = assembly.main_part
            if isinstance(main_part, TeklaPart):
                main_part_snapshot = main_part.to_snapshot()
        except ValueError:
            logger.warning("Assembly %s has no main part available", assembly.guid)

        secondaries = []
        for secondary in wrap_model_objects(assembly.model_object.GetSecondaries()):
            if isinstance(secondary, TeklaPart):
                secondaries.append(secondary.to_snapshot())
        secondaries = sorted(secondaries, key=lambda s: (s.id, s.pos))

        subassemblies = []
        for subassembly in wrap_model_objects(assembly.model_object.GetSubAssemblies()):
            if isinstance(subassembly, TeklaAssembly):
                subassemblies.append(subassembly.to_snapshot())
        subassemblies = sorted(subassemblies, key=lambda s: (s.id, s.pos))

        return AssemblySnapshot(
            id=assembly.id,
            guid=assembly.guid,
            pos=assembly.position,
            report_properties=report_properties,
            user_properties=user_properties,
            main_part=main_part_snapshot,
            secondaries=secondaries,
            subassemblies=subassemblies,
        )

    @staticmethod
    def _get_rebar_prop_names(raw_rebar: Any) -> list[str]:
        if isinstance(raw_rebar, (BaseRebarGroup, SingleRebar)):
            return get_config().get_report_props("rebar_group")
        elif isinstance(raw_rebar, RebarMesh):
            return get_config().get_report_props("rebar_mesh")
        elif isinstance(raw_rebar, RebarStrand):
            return get_config().get_report_props("rebar_strand")
        return []

    @staticmethod
    def build_reinforcement_snapshot(rebar: Any) -> ReinforcementSnapshot:
        raw = rebar.model_object
        rebar_type = type(raw).__name__

        prop_names = SnapshotBuilder._get_rebar_prop_names(raw)

        report_properties = SnapshotBuilder._build_report_properties(rebar, prop_names)
        user_properties = SnapshotBuilder._build_sorted_user_properties(rebar)

        father = rebar.father
        father_guid = father.guid if father is not None else None

        return ReinforcementSnapshot(
            id=rebar.id,
            guid=rebar.guid,
            pos=rebar.position,
            report_properties=report_properties,
            user_properties=user_properties,
            father_guid=father_guid,
            rebar_type=rebar_type,
        )

    @staticmethod
    def _build_report_properties(obj: Any, prop_names: list[str]) -> dict[str, Any]:
        props = obj.get_multiple_report_properties(prop_names)
        return dict(sorted(props.items()))

    @staticmethod
    def _build_sorted_user_properties(obj: Any) -> dict[str, Any]:
        props = obj.get_all_user_properties()
        return dict(sorted(props.items()))

    @staticmethod
    def _build_cutparts(part: Any, origin_cache: dict[str, tuple[float, float, float] | None]) -> list[dict[str, Any]]:
        cutparts = []
        boolean_enum = part.model_object.GetBooleans()
        while boolean_enum.MoveNext():
            boolean_part = boolean_enum.Current
            if isinstance(boolean_part, BooleanPart):
                operative_part = boolean_part.OperativePart
                if operative_part:
                    relative_pos = SnapshotBuilder._build_relative_position(operative_part, part.model_object, origin_cache)
                    cutparts.append(
                        {
                            "id": operative_part.Identifier.ID,
                            "guid": operative_part.Identifier.GUID.ToString(),
                            "name": operative_part.Name,
                            "profile": operative_part.Profile.ProfileString,
                            "type": str(boolean_part.Type),
                            "relative_pos": relative_pos,
                        }
                    )
        return sorted(cutparts, key=lambda b: (b["id"], b["name"]))

    @staticmethod
    def _build_reinforcements(part: Any) -> list[dict[str, Any]]:
        from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_object

        reinforcements = []
        reinf_enum = part.model_object.GetReinforcements()
        while reinf_enum.MoveNext():
            rebar = reinf_enum.Current

            prop_names = SnapshotBuilder._get_rebar_prop_names(rebar)

            rebar_wrapped = wrap_model_object(rebar)
            if rebar_wrapped is None:
                logger.warning("_build_reinforcements: could not wrap rebar %s, skipping", rebar.Identifier.ID)
                continue
            rebar_props = rebar_wrapped.get_multiple_report_properties(prop_names)
            rebar_udas = rebar_wrapped.get_all_user_properties()

            reinforcements.append(
                {
                    "id": rebar.Identifier.ID,
                    "guid": rebar.Identifier.GUID.ToString(),
                    "name": rebar.Name,
                    "report_properties": rebar_props,
                    "user_properties": rebar_udas,
                }
            )
        return sorted(reinforcements, key=lambda r: (r["id"], r["name"]))

    @staticmethod
    def _build_welds(part: Any, origin_cache: dict[str, tuple[float, float, float] | None]) -> list[dict[str, Any]]:
        from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_object

        welds = []
        weld_prop_names = get_config().get_report_props("weld")
        weld_enum = part.model_object.GetWelds()
        while weld_enum.MoveNext():
            weld = weld_enum.Current
            weld_wrapped = wrap_model_object(weld)
            weld_props = weld_wrapped.get_multiple_report_properties(weld_prop_names) if weld_wrapped else {}
            relative_pos = SnapshotBuilder._build_relative_position(weld, part.model_object, origin_cache)

            welds.append(
                {
                    "id": weld.Identifier.ID,
                    "guid": weld.Identifier.GUID.ToString(),
                    "report_properties": weld_props,
                    "relative_pos": relative_pos,
                }
            )
        return sorted(welds, key=lambda w: w["id"])

    @staticmethod
    def _get_origin(obj: Any) -> tuple[float, float, float] | None:
        """Reads an object's coordinate system origin, or None if unavailable."""
        try:
            origin = obj.GetCoordinateSystem().Origin
            return (float(origin.X), float(origin.Y), float(origin.Z))
        except Exception as e:
            # Log the error, not the object: a broken object may fail on `Identifier` too
            logger.warning("Failed to read coordinate system origin: %s", e)
            return None

    @staticmethod
    def _build_relative_position(child: Any, parent: Any, origin_cache: dict[str, tuple[float, float, float] | None]) -> dict[str, float] | None:
        """
        Calculates the relative position of a child object to its parent.

        The parent's origin is read on first use and kept in `origin_cache`, so a part
        without cut parts or welds never reads it and one with many reads it once.
        """
        if "origin" not in origin_cache:
            origin_cache["origin"] = SnapshotBuilder._get_origin(parent)
        parent_origin = origin_cache["origin"]
        if parent_origin is None:
            return None
        child_origin = SnapshotBuilder._get_origin(child)
        if child_origin is None:
            return None
        return {
            "dx": child_origin[0] - parent_origin[0],
            "dy": child_origin[1] - parent_origin[1],
            "dz": child_origin[2] - parent_origin[2],
        }
