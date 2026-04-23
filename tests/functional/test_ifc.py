"""
Functional tests for ifc_provider.

Tests IFC property copy operations.
"""

from tekla_mcp_server.providers.ifc_provider import copy_properties_from_ifc
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


class TestCopyPropertiesFromIfc:
    """Tests for copy_properties_from_ifc function."""

    def test_copy_properties_only_tekla_wall1_selected_returns_error(self, model_objects):
        """Select only MCP_TEST_WALL1 without IFC references."""
        TeklaModel.select_objects([model_objects["test_wall1"]])

        result = copy_properties_from_ifc(user_properties={})

        assert result.structured_content["status"] == "error"
        assert "no ifc" in result.structured_content["message"].lower()

    def test_copy_properties_both_walls_selected_returns_error(self, model_objects):
        """Select MCP_TEST_WALL1 and MCP_TEST_WALL2 without IFC."""
        TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

        result = copy_properties_from_ifc(user_properties={})

        assert result.structured_content["status"] == "error"
        assert "no ifc" in result.structured_content["message"].lower()
