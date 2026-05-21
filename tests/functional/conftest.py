"""
Shared fixtures and utilities for functional tests.
"""

import os

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import BeamInput, PanelInput, PointInput, StringMatchType
from tekla_mcp_server.tekla.loader import BinaryFilterExpressionCollection, PartFilterExpressions, ObjectFilterExpressions, TeklaStructuresDatabaseTypeEnum, ModelObjectVisualization, ViewHandler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.filter_builder import add_filter
from tekla_mcp_server.providers.modeling_provider import place_panels, place_beams
from tekla_mcp_server.tekla.utils import get_active_views


@pytest.fixture(scope="session", autouse=True)
def init_tekla():
    """Initialize Tekla DLLs once at session start to speed up test execution."""
    from tekla_mcp_server.init import load_dlls

    load_dlls()
    TeklaModel()
    yield


@pytest.fixture(scope="session", autouse=True)
def clear_view_settings():
    """Reset temporary visualization states and redraw views after the test session."""

    yield

    ModelObjectVisualization.ClearAllTemporaryStates()
    for view in get_active_views():
        ViewHandler.RedrawView(view)


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
        PanelInput(start_point=PointInput(x=0, y=0, z=9060), end_point=PointInput(x=2000, y=0, z=9060), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL5"),  # Name must match the previous object for the comparison tool test
        PanelInput(start_point=PointInput(x=0, y=0, z=12080), end_point=PointInput(x=2000, y=0, z=12080), profile="2000*150", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL7"),
        PanelInput(start_point=PointInput(x=0, y=200, z=0), end_point=PointInput(x=2000, y=200, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL8"),
        PanelInput(start_point=PointInput(x=4000, y=0, z=0), end_point=PointInput(x=6000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=8, name="MCP_TEST_SW1"),

        # Clash check walls
        PanelInput(start_point=PointInput(x=6000, y=0, z=0), end_point=PointInput(x=8000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_CLASH_WALL_A"),
        PanelInput(start_point=PointInput(x=6000, y=0, z=2500), end_point=PointInput(x=8000, y=0, z=2500), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_CLASH_WALL_B"),
        PanelInput(start_point=PointInput(x=6500, y=0, z=500), end_point=PointInput(x=7500, y=0, z=500), profile="1000*100", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_CLASH_WALL_C"),
    ]

    slabs = [
        BeamInput(
            start_point=PointInput(x=1000, y=0, z=3020), end_point=PointInput(x=1000, y=6000, z=3020), profile="P20(200X1200)", material="Concrete_Undefined", tekla_class=3, name="MCP_TEST_SLAB1"
        ),
    ]

    voids = [
        BeamInput(start_point=PointInput(x=3000, y=0, z=1000), end_point=PointInput(x=3000, y=200, z=1000), profile="D400", material="Concrete_Undefined", tekla_class=0, name="MCP_TEST_VOID_WALL3"),
        BeamInput(start_point=PointInput(x=3000, y=0, z=4020), end_point=PointInput(x=3000, y=200, z=4020), profile="D400", material="Concrete_Undefined", tekla_class=555, name="MCP_TEST_VOID_GUID_WALL4"),
        BeamInput(
            start_point=PointInput(x=3000, y=0, z=10000), end_point=PointInput(x=3000, y=200, z=10000), profile="D400", material="Concrete_Undefined", tekla_class=0, name="MCP_TEST_VOID_FLOATING"
        ),
    ]

    result_panels = place_panels(panels=panels)
    result_slabs = place_beams(beams=slabs)
    result_voids = place_beams(beams=voids)

    panel_guids = [r["guid"] for r in result_panels.structured_content["results"]]
    slab_guids = [r["guid"] for r in result_slabs.structured_content["results"]]
    void_guids = [r["guid"] for r in result_voids.structured_content["results"]]

    all_objects = list(model.get_objects_by_guid(panel_guids + slab_guids + void_guids))
    p = all_objects[: len(panel_guids)]
    s = all_objects[len(panel_guids) : len(panel_guids) + len(slab_guids)]
    v = all_objects[len(panel_guids) + len(slab_guids) :]

    yield {
        "model": model,
        "walls": p[:4],
        "test_wall1": p[0],
        "test_wall2": p[1],
        "test_wall3": p[2],
        "test_wall4": p[3],
        "test_wall5": p[4],
        "test_wall6": p[5],
        "test_wall7": p[6],
        "test_wall8": p[7],
        "test_sw1": p[8],
        "test_clash_wall_a": p[9],
        "test_clash_wall_b": p[10],
        "test_clash_wall_c": p[11],
        "test_slab1": s[0],
        "void1": v[0],
        "void2": v[1],
        "void3": v[2],
    }

    cleanup_mcp_test_objects()
    model.commit_changes()


