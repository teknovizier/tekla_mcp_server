"""
Unit tests for modeling tools.

Tests input models and placement logic.
"""

import importlib
import os
from unittest.mock import patch

import pytest
from pydantic_core import ValidationError

from tekla_mcp_server.models import (
    PointInput,
    PositionInput,
    TeklaBeamInput,
    BeamInput,
    ColumnInput,
    PanelInput,
    SlabInput,
    PlacementResult,
    BatchPlacementResult,
)


class TestPointInput:
    """Tests for PointInput model."""

    def test_valid_point(self):
        """Test creating a valid point."""
        point = PointInput(x=1000.0, y=2000.0, z=3000.0)
        assert point.x == 1000.0
        assert point.y == 2000.0
        assert point.z == 3000.0

    def test_point_with_defaults(self):
        """Test point with zero defaults."""
        point = PointInput(x=0, y=0, z=0)
        assert point.x == 0
        assert point.y == 0
        assert point.z == 0


class TestPositionInput:
    """Tests for PositionInput model."""

    def test_valid_position_defaults(self):
        """Test position with default values."""
        pos = PositionInput()
        assert pos.plane == "MIDDLE"
        assert pos.depth == "MIDDLE"
        assert pos.rotation == "FRONT"
        assert pos.plane_offset == 0.0
        assert pos.depth_offset == 0.0
        assert pos.rotation_offset == 0.0

    @pytest.mark.parametrize("plane", ["LEFT", "MIDDLE", "RIGHT"])
    def test_valid_plane_values(self, plane):
        """Test valid plane values."""
        pos = PositionInput(plane=plane)
        assert pos.plane == plane.upper()

    @pytest.mark.parametrize("plane", ["INVALID", "Center", "top"])
    def test_invalid_plane_raises(self, plane):
        """Test invalid plane raises validation error."""
        with pytest.raises(ValidationError):
            PositionInput(plane=plane)

    @pytest.mark.parametrize("depth", ["FRONT", "MIDDLE", "BEHIND"])
    def test_valid_depth_values(self, depth):
        """Test valid depth values."""
        pos = PositionInput(depth=depth)
        assert pos.depth == depth.upper()

    @pytest.mark.parametrize("depth", ["INVALID", "Back", "bottom"])
    def test_invalid_depth_raises(self, depth):
        """Test invalid depth raises validation error."""
        with pytest.raises(ValidationError):
            PositionInput(depth=depth)

    @pytest.mark.parametrize("rotation", ["FRONT", "TOP", "BACK"])
    def test_valid_rotation_values(self, rotation):
        """Test valid rotation values."""
        pos = PositionInput(rotation=rotation)
        assert pos.rotation == rotation.upper()

    @pytest.mark.parametrize("rotation", ["INVALID", "Bottom", "side"])
    def test_invalid_rotation_raises(self, rotation):
        """Test invalid rotation raises validation error."""
        with pytest.raises(ValidationError):
            PositionInput(rotation=rotation)


class TestTeklaBeamInput:
    """Tests for TeklaBeamInput base model."""

    def test_valid_base_inputs(self):
        """Test creating base input with common fields."""
        beam_input = TeklaBeamInput(profile="300*600", material="C30/37", tekla_class=11)
        assert beam_input.profile == "300*600"
        assert beam_input.material == "C30/37"
        assert beam_input.tekla_class == 11
        assert beam_input.name is None
        assert beam_input.position is None

    def test_base_with_name(self):
        """Test base input with optional name."""
        beam_input = TeklaBeamInput(profile="HEA200", material="S235JR", tekla_class=100, name="MyBeam")
        assert beam_input.name == "MyBeam"

    def test_base_with_position(self):
        """Test base input with position."""
        pos = PositionInput(plane="LEFT", depth="FRONT")
        beam_input = TeklaBeamInput(profile="HEA200", material="S235JR", tekla_class=100, position=pos)
        assert beam_input.position.plane == "LEFT"


class TestPointOffsetSchema:
    """Start/end point offsets are exposed only for beam-like inputs."""

    @pytest.mark.parametrize("model", [BeamInput, ColumnInput, PanelInput])
    def test_beam_like_inputs_expose_offsets(self, model):
        """Beam-like schemas advertise both point offsets."""
        properties = model.model_json_schema()["properties"]
        assert "start_point_offset" in properties
        assert "end_point_offset" in properties

    def test_slab_input_does_not_expose_offsets(self):
        """Slab schema has no point offsets, since contour plates cannot use them."""
        properties = SlabInput.model_json_schema()["properties"]
        assert "start_point_offset" not in properties
        assert "end_point_offset" not in properties


class TestBeamInput:
    """Tests for BeamInput model."""

    def test_valid_beam(self):
        """Test creating a valid beam input."""
        start = PointInput(x=0, y=0, z=0)
        end = PointInput(x=5000, y=0, z=0)
        beam = BeamInput(start_point=start, end_point=end, profile="300*600", material="C30/37", tekla_class=11)
        assert beam.start_point.x == 0
        assert beam.end_point.x == 5000

    def test_beam_inherits_base(self):
        """Test beam inherits base fields."""
        beam = BeamInput(
            start_point=PointInput(x=0, y=0, z=0),
            end_point=PointInput(x=1000, y=0, z=0),
            profile="HEA200",
            material="S235JR",
            tekla_class=100,
            name="TestBeam",
        )
        assert beam.name == "TestBeam"


class TestColumnInput:
    """Tests for ColumnInput model."""

    def test_valid_column(self):
        """Test creating a valid column input."""
        col = ColumnInput(
            base_point=PointInput(x=0, y=0, z=0),
            height=3000,
            profile="400*400",
            material="C30/37",
            tekla_class=10,
        )
        assert col.base_point.x == 0
        assert col.height == 3000

    def test_column_height_validation(self):
        """Test column height must be positive."""
        with pytest.raises(ValidationError):
            ColumnInput(
                base_point=PointInput(x=0, y=0, z=0),
                height=0,
                profile="400*400",
                material="C30/37",
                tekla_class=10,
            )

    def test_string_height_coerced(self):
        """A numeric string height is coerced instead of crashing the validator."""
        col = ColumnInput(
            base_point=PointInput(x=0, y=0, z=0),
            height="3000",
            profile="400*400",
            material="C30/37",
            tekla_class=10,
        )
        assert col.height == 3000.0

    @pytest.mark.parametrize("height", [-100, -0.1, -3000, "0", None, "abc", float("nan"), float("inf")])
    def test_invalid_height_raises(self, height):
        """Test non-positive, non-numeric and non-finite heights raise validation error."""
        with pytest.raises(ValidationError):
            ColumnInput(
                base_point=PointInput(x=0, y=0, z=0),
                height=height,
                profile="400*400",
                material="C30/37",
                tekla_class=10,
            )


class TestPanelInput:
    """Tests for PanelInput model."""

    def test_valid_panel(self):
        """Test creating a valid panel input."""
        panel = PanelInput(
            start_point=PointInput(x=0, y=0, z=0),
            end_point=PointInput(x=3000, y=0, z=3000),
            profile="3000*200",
            material="C30/37",
            tekla_class=1,
        )
        assert panel.start_point.x == 0
        assert panel.end_point.z == 3000


class TestPlacementResult:
    """Tests for PlacementResult model."""

    def test_valid_result_success(self):
        """Test successful placement result."""
        result = PlacementResult(success=True, guid="ABC123", message="Inserted successfully")
        assert result.success is True
        assert result.guid == "ABC123"

    def test_valid_result_failure(self):
        """Test failed placement result."""
        result = PlacementResult(success=False, message="Insert failed")
        assert result.success is False
        assert result.guid is None


class TestBatchPlacementResult:
    """Tests for BatchPlacementResult model."""

    def test_valid_batch_all_success(self):
        """Test batch result with all successes."""
        results = [
            PlacementResult(success=True, guid="GUID1", message="OK"),
            PlacementResult(success=True, guid="GUID2", message="OK"),
        ]
        batch = BatchPlacementResult(success=True, total=2, succeeded=2, failed=0, results=results, message="All placed")
        assert batch.success is True
        assert batch.succeeded == 2

    def test_valid_batch_partial_success(self):
        """Test batch result with some failures."""
        results = [
            PlacementResult(success=True, guid="GUID1", message="OK"),
            PlacementResult(success=False, message="Failed"),
        ]
        batch = BatchPlacementResult(success=False, total=2, succeeded=1, failed=1, results=results, message="1 failed")
        assert batch.success is False
        assert batch.succeeded == 1
        assert batch.failed == 1


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skipping (Tekla not available in CI)")
class TestCommitFailureNote:
    """Tests for the _commit_failure_note helper."""

    def test_commit_success_adds_nothing(self):
        from tekla_mcp_server.providers.modeling_provider import _commit_failure_note

        assert _commit_failure_note(True, "placing 3 beams") == ""

    def test_commit_success_does_not_redraw(self):
        mp_module = importlib.import_module("tekla_mcp_server.providers.modeling_provider")

        with patch.object(mp_module, "_redraw_active_views") as redraw:
            mp_module._commit_failure_note(True, "placing 3 beams")
        redraw.assert_not_called()

    def test_commit_failure_redraws_and_says_the_changes_are_shown(self):
        """Uncommitted changes are in the model but hidden until a redraw, so the note redraws and says so."""
        mp_module = importlib.import_module("tekla_mcp_server.providers.modeling_provider")

        with patch.object(mp_module, "_redraw_active_views", return_value=True) as redraw:
            note = mp_module._commit_failure_note(False, "placing 3 beams")
        redraw.assert_called_once()
        assert "commit_changes() failed" in note and "view was redrawn to show them" in note and "check them before retrying" in note
        assert "reverted" not in note and "not persisted" not in note

    def test_failed_redraw_tells_the_user_to_redraw(self):
        mp_module = importlib.import_module("tekla_mcp_server.providers.modeling_provider")

        with patch.object(mp_module, "_redraw_active_views", return_value=False):
            note = mp_module._commit_failure_note(False, "placing 3 beams")
        assert "not shown until the view is redrawn" in note
