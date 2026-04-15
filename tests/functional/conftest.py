"""
Shared fixtures and utilities for functional tests.
"""

import os

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import StringMatchType
from tekla_mcp_server.tekla.loader import BinaryFilterExpressionCollection, PartFilterExpressions, ObjectFilterExpressions, TeklaStructuresDatabaseTypeEnum
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.providers.selection_provider import add_filter
from tekla_mcp_server.providers.modeling_provider import place_panels, place_beams
from tekla_mcp_server.models import BeamInput, PanelInput, PointInput


@pytest.fixture(scope="session", autouse=True)
def init_tekla():
    """Initialize Tekla DLLs once at session start to speed up test execution."""
    from tekla_mcp_server.init import load_dlls

    load_dlls()
    TeklaModel()
    yield


def cleanup_mcp_test_objects():
    """Utility function to clean up all MCP test objects by name pattern."""
    model = TeklaModel()

    filter_collection = BinaryFilterExpressionCollection()
    add_filter(filter_collection, ObjectFilterExpressions.Type(), TeklaStructuresDatabaseTypeEnum.PART)
    add_filter(filter_collection, PartFilterExpressions.Name(), "MCP_TEST_", StringMatchType.STARTS_WITH)

    test_objects = model.get_objects_by_filter(filter_collection)

    if test_objects:
        for test_obj in test_objects:
            test_obj.Delete()
        model.commit_changes()


@pytest.fixture(scope="module")
def model_objects():
    """Fixture: Test setup and teardown using place_panels and place_beams."""
    model = TeklaModel()

    panels = [
        PanelInput(start_point=PointInput(x=0, y=0, z=0), end_point=PointInput(x=2000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL1"),
        PanelInput(start_point=PointInput(x=0, y=0, z=3020), end_point=PointInput(x=2000, y=0, z=3020), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL2"),
        PanelInput(start_point=PointInput(x=2000, y=0, z=0), end_point=PointInput(x=4000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL3"),
        PanelInput(start_point=PointInput(x=2000, y=0, z=3020), end_point=PointInput(x=4000, y=0, z=3020), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL4"),
        PanelInput(start_point=PointInput(x=0, y=0, z=6040), end_point=PointInput(x=2000, y=0, z=6040), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL5"),
        PanelInput(start_point=PointInput(x=0, y=0, z=9060), end_point=PointInput(x=2000, y=0, z=9060), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL5"),
        PanelInput(start_point=PointInput(x=0, y=0, z=12080), end_point=PointInput(x=2000, y=0, z=12080), profile="2000*150", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL7"),
        PanelInput(start_point=PointInput(x=0, y=200, z=0), end_point=PointInput(x=2000, y=200, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL8"),
        PanelInput(start_point=PointInput(x=4000, y=0, z=0), end_point=PointInput(x=6000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=8, name="MCP_TEST_SW1"),
    ]

    slabs = [
        BeamInput(
            start_point=PointInput(x=1000, y=0, z=3020), end_point=PointInput(x=1000, y=6000, z=3020), profile="P20(200X1200)", material="Concrete_Undefined", tekla_class=3, name="MCP_TEST_SLAB1"
        ),
    ]

    voids = [
        BeamInput(start_point=PointInput(x=3000, y=0, z=1000), end_point=PointInput(x=3000, y=200, z=1000), profile="D400", material="Concrete_Undefined", tekla_class=0, name="MCP_TEST_VOID_WALL3"),
        BeamInput(
            start_point=PointInput(x=3000, y=0, z=10000), end_point=PointInput(x=3000, y=200, z=10000), profile="D400", material="Concrete_Undefined", tekla_class=0, name="MCP_TEST_VOID_FLOATING"
        ),
    ]

    result_panels = place_panels(panels=panels)
    result_slabs = place_beams(beams=slabs)
    result_voids = place_beams(beams=voids)

    def get_single_object(guid: str):
        objects = model.get_objects_by_guid([guid])
        return objects[0] if objects else None

    panel_guids = [r["guid"] for r in result_panels.structured_content["results"]]
    yield {
        "model": model,
        "walls": [get_single_object(g) for g in panel_guids[:4]],
        "test_wall1": get_single_object(panel_guids[0]),
        "test_wall2": get_single_object(panel_guids[1]),
        "test_wall3": get_single_object(panel_guids[2]),
        "test_wall4": get_single_object(panel_guids[3]),
        "test_wall5": get_single_object(panel_guids[4]),
        "test_wall6": get_single_object(panel_guids[5]),
        "test_wall7": get_single_object(panel_guids[6]),
        "test_wall8": get_single_object(panel_guids[7]),
        "test_sw1": get_single_object(panel_guids[8]),
        "test_slab1": get_single_object(result_slabs.structured_content["results"][0]["guid"]),
        "void1": get_single_object(result_voids.structured_content["results"][0]["guid"]),
        "void2": get_single_object(result_voids.structured_content["results"][1]["guid"]),
    }

    cleanup_mcp_test_objects()
    model.commit_changes()
