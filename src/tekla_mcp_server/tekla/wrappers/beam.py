"""
Module for Tekla Beam wrapper.

Provides TeklaBeam class for working with Beam objects.
"""

from __future__ import annotations

from tekla_mcp_server.models import BeamType, NumberingSeries, PointInput, PositionInput
from tekla_mcp_server.tekla.loader import Beam, Point, Position
from tekla_mcp_server.tekla.wrappers.model_object import TeklaPart
from tekla_mcp_server.tekla.utils import POSITION_PLANE_MAP, POSITION_DEPTH_MAP, POSITION_ROTATION_MAP


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
        self.model_object.StartPoint = value

    @property
    def end_point(self) -> Point:
        """Returns the end point of the beam."""
        return self.model_object.EndPoint

    @end_point.setter
    def end_point(self, value: Point) -> None:
        """Sets the end point of the beam."""
        self.model_object.EndPoint = value

    def apply_position(self, position: PositionInput | None = None) -> "TeklaBeam":
        """Apply position settings to the beam."""
        if position:
            self.model_object.Position.Plane = POSITION_PLANE_MAP.get(position.plane, Position.PlaneEnum.MIDDLE)
            self.model_object.Position.Depth = POSITION_DEPTH_MAP.get(position.depth, Position.DepthEnum.MIDDLE)
            self.model_object.Position.Rotation = POSITION_ROTATION_MAP.get(position.rotation, Position.RotationEnum.FRONT)
            self.model_object.Position.PlaneOffset = position.plane_offset
            self.model_object.Position.DepthOffset = position.depth_offset
            self.model_object.Position.RotationOffset = position.rotation_offset
        return self

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
        start: PointInput,
        end: PointInput,
        profile: str,
        material: str,
        tekla_class: int,
        name: str | None = None,
        position: PositionInput | None = None,
        beam_type: BeamType = BeamType.BEAM,
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
            part_number: NumberingSeries for part numbering (optional)
            assembly_number: NumberingSeries for assembly numbering (optional)

        Returns:
            TeklaBeam: The created beam wrapper
        """
        beam = Beam()
        beam.StartPoint = Point(start.x, start.y, start.z)
        beam.EndPoint = Point(end.x, end.y, end.z)
        beam.Profile.ProfileString = profile
        beam.Material.MaterialString = material
        beam.Class = str(tekla_class)
        if name:
            beam.Name = name

        tekla_beam = TeklaBeam(beam)

        if position:
            tekla_beam.apply_position(position)
        else:
            tekla_beam.apply_defaults(beam_type)

        if tekla_beam.model_object.Insert():
            if assembly_number is not None:
                tekla_beam.assembly_number = assembly_number
            if part_number is not None:
                tekla_beam.part_number = part_number
            return tekla_beam

        return None
