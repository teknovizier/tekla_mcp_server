"""
Shared fixtures and utilities for functional tests.
"""

import os

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import StringMatchType
from tekla_mcp_server.tekla.loader import Point, Beam, Position
from tekla_mcp_server.tekla.loader import BinaryFilterExpressionCollection, PartFilterExpressions, ObjectFilterExpressions, TeklaStructuresDatabaseTypeEnum
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tools.selection import add_filter


@pytest.fixture(scope="session", autouse=True)
def init_tekla():
    """Initialize Tekla DLLs once at session start to speed up test execution."""
    from tekla_mcp_server.init import load_dlls

    load_dlls()
    TeklaModel()
    yield


def create_mcp_test_beam(name, start_point, end_point, profile, material="Concrete_Undefined", depth_enum=Position.DepthEnum.FRONT, class_type="1"):
    """Utility function to create a beam."""
    beam = Beam()
    beam.Profile.ProfileString = profile
    beam.Material.MaterialString = material
    beam.Class = class_type
    beam.Name = name
    beam.Position.Depth = depth_enum
    beam.StartPoint = start_point
    beam.EndPoint = end_point
    beam.Insert()
    return beam


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
    """Fixture: Test setup and teardown."""
    model = TeklaModel()
    test_wall1 = create_mcp_test_beam("MCP_TEST_WALL1", Point(0, 0, 0), Point(2000, 0, 0), "3000*200")
    test_wall2 = create_mcp_test_beam("MCP_TEST_WALL2", Point(0, 0, 3020), Point(2000, 0, 3020), "3000*200")
    test_wall3 = create_mcp_test_beam("MCP_TEST_WALL3", Point(2000, 0, 0), Point(4000, 0, 0), "3000*200")
    test_wall4 = create_mcp_test_beam("MCP_TEST_WALL4", Point(2000, 0, 3020), Point(4000, 0, 3020), "3000*200")

    test_wall5 = create_mcp_test_beam("MCP_TEST_WALL5", Point(0, 0, 6040), Point(2000, 0, 6040), "3000*200")
    test_wall6 = create_mcp_test_beam("MCP_TEST_WALL5", Point(0, 0, 9060), Point(2000, 0, 9060), "3000*200")
    test_wall7 = create_mcp_test_beam("MCP_TEST_WALL7", Point(0, 0, 12080), Point(2000, 0, 12080), "2000*150")
    test_wall8 = create_mcp_test_beam("MCP_TEST_WALL8", Point(0, 200, 0), Point(2000, 200, 0), "3000*200")

    test_sw1 = create_mcp_test_beam("MCP_TEST_SW1", Point(4000, 0, 0), Point(6000, 0, 0), "3000*200", class_type="8")
    test_slab1 = create_mcp_test_beam("MCP_TEST_SLAB1", Point(1000, 0, 3020), Point(1000, 6000, 3020), "P20(200X1200)", class_type="3")

    void1 = create_mcp_test_beam("MCP_TEST_VOID_WALL3", Point(3000, 0, 1000), Point(3000, 200, 1000), "D400", class_type="0")
    void2 = create_mcp_test_beam("MCP_TEST_VOID_FLOATING", Point(3000, 0, 10000), Point(3000, 200, 10000), "D400", class_type="0")

    model.commit_changes()

    yield {
        "model": model,
        "walls": [test_wall1, test_wall2, test_wall3, test_wall4],
        "test_wall1": test_wall1,
        "test_wall2": test_wall2,
        "test_wall3": test_wall3,
        "test_wall4": test_wall4,
        "test_wall5": test_wall5,
        "test_wall6": test_wall6,
        "test_wall7": test_wall7,
        "test_wall8": test_wall8,
        "test_sw1": test_sw1,
        "test_slab1": test_slab1,
        "void1": void1,
        "void2": void2,
    }

    cleanup_mcp_test_objects()
    model.commit_changes()
