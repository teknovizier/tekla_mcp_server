"""
SnapshotBuilder extracts snapshot data from Tekla objects.
"""

from typing import Any

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import AssemblySnapshot, PartSnapshot

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
        cutparts = SnapshotBuilder._build_cutparts(part)
        reinforcements = SnapshotBuilder._build_reinforcements(part)
        welds = SnapshotBuilder._build_welds(part)

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
    def _build_report_properties(obj: Any, prop_names: list[str]) -> dict[str, Any]:
        props = obj.get_multiple_report_properties(prop_names)
        return dict(sorted(props.items()))

    @staticmethod
    def _build_sorted_user_properties(obj: Any) -> dict[str, Any]:
        props = obj.get_all_user_properties()
        return dict(sorted(props.items()))

    @staticmethod
    def _build_cutparts(part: Any) -> list[dict[str, Any]]:
        cutparts = []
        boolean_enum = part.model_object.GetBooleans()
        while boolean_enum.MoveNext():
            boolean_part = boolean_enum.Current
            if isinstance(boolean_part, BooleanPart):
                operative_part = boolean_part.OperativePart
                if operative_part:
                    relative_pos = SnapshotBuilder._build_relative_position(operative_part, part.model_object)
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
        from tekla_mcp_server.tekla.wrappers.model_object import TeklaModelObject, wrap_model_object

        reinforcements = []
        reinf_enum = part.model_object.GetReinforcements()
        while reinf_enum.MoveNext():
            rebar = reinf_enum.Current
            wrapped_rebar = TeklaModelObject(rebar)

            if isinstance(rebar, (BaseRebarGroup, SingleRebar)):
                prop_names = get_config().get_report_props("rebar_group")
            elif isinstance(rebar, RebarMesh):
                prop_names = get_config().get_report_props("rebar_mesh")
            elif isinstance(rebar, RebarStrand):
                prop_names = get_config().get_report_props("rebar_strand")
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
        return sorted(reinforcements, key=lambda r: (r["id"], r["name"]))

    @staticmethod
    def _build_welds(part: Any) -> list[dict[str, Any]]:
        from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_object

        welds = []
        weld_enum = part.model_object.GetWelds()
        while weld_enum.MoveNext():
            weld = weld_enum.Current
            weld_wrapped = wrap_model_object(weld)
            weld_props = weld_wrapped.get_multiple_report_properties(get_config().get_report_props("weld")) if weld_wrapped else {}
            relative_pos = SnapshotBuilder._build_relative_position(weld, part.model_object)

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
    def _build_relative_position(child: Any, parent: Any) -> dict[str, float] | None:
        """Calculates the relative position of a child object to its parent."""
        try:
            child_pos = child.GetCoordinateSystem().Origin
            parent_pos = parent.GetCoordinateSystem().Origin
            return {
                "dx": float(child_pos.X - parent_pos.X),
                "dy": float(child_pos.Y - parent_pos.Y),
                "dz": float(child_pos.Z - parent_pos.Z),
            }
        except Exception:
            logger.warning("Failed to calculate relative position for child %s", child.Identifier.ID)
            return None
