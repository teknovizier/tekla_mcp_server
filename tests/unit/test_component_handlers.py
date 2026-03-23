"""
Unit tests for component handlers.

Tests the HandlerRegistry and LiftingAnchorsHandler classes.
"""

import pytest

from tekla_mcp_server.tekla.component_handlers import HandlerRegistry, LiftingAnchorsHandler


@pytest.fixture
def anchor_types():
    return {
        "A": {"element_type": ["CONCRETE_WALL"], "active": True, "capacity": 1.5},
        "B": {"element_type": ["CONCRETE_WALL"], "active": True, "capacity": 2.0},
        "C": {"element_type": ["CONCRETE_WALL"], "active": True, "capacity": 0.5},
    }


@pytest.fixture
def handler(anchor_types):
    return LiftingAnchorsHandler(config={"safety_margin": 10, "anchor_types": anchor_types})


class TestLiftingAnchorsHandler:
    def test_handler_tekla_name(self, handler):
        assert handler.tekla_name == "Lifting Anchor"

    def test_handler_safety_margin(self, handler):
        assert handler.safety_margin_prop == 10

    def test_get_required_anchors_two_anchors(self, handler, anchor_types):
        n, valid = handler.get_required_anchors("CONCRETE_WALL", 2000)
        assert n == 2
        assert "A" in valid or "B" in valid

    def test_get_required_anchors_four_anchors(self, handler):
        """Use low capacity anchors to force 4-anchor requirement."""
        handler.anchor_types = {"A": {"element_type": ["CONCRETE_WALL"], "active": True, "capacity": 1.0}}
        n, valid = handler.get_required_anchors("CONCRETE_WALL", 3600)
        assert n == 4

    def test_get_required_anchors_no_valid_anchors(self, handler):
        with pytest.raises(ValueError, match="No lifting anchors found"):
            handler.get_required_anchors("CONCRETE_WALL", 10000)

    def test_calculate_anchor_placement_two_anchors(self, handler):
        res = handler.calculate_anchor_placement(300.0, 5000.0, 2500.0, 2)
        assert len(res) == 3
        assert all(isinstance(x, (int, float)) for x in res)

    def test_calculate_anchor_placement_four_anchors(self, handler):
        res = handler.calculate_anchor_placement(300.0, 5000.0, 2500.0, 4)
        assert len(res) == 3
        assert all(isinstance(x, (int, float)) for x in res)

    def test_calculate_anchor_placement_short_element(self, handler):
        """Test with 4 anchors on a very short element - should raise ValueError."""
        with pytest.raises(ValueError, match="too short"):
            handler.calculate_anchor_placement(900.0, 1000.0, 500.0, 4)


class TestHandlerRegistry:
    def test_get_returns_handler_for_lifting_anchor(self):
        handler = HandlerRegistry.get("Lifting Anchor")
        assert handler is not None
        assert isinstance(handler, LiftingAnchorsHandler)

    def test_has_handler(self):
        assert HandlerRegistry.has_handler("Lifting Anchor") is True
        assert HandlerRegistry.has_handler("NonExistent") is False

    def test_clear(self):
        HandlerRegistry.clear()
        assert HandlerRegistry._instances == {}
