"""
Functional tests for modeling_provider.

Tests beam, column, and panel placement operations.
"""

import pytest

from tekla_mcp_server.providers.modeling_provider import place_beams, place_columns, place_panels, delete_selected
from tekla_mcp_server.models import BeamInput, ColumnInput, PanelInput, PointInput, PositionInput


def cleanup_modeling_test_objects():
    """Clean up test objects created by modeling tests."""
    from tekla_mcp_server.models import StringMatchType
    from tekla_mcp_server.tekla.loader import BinaryFilterExpressionCollection, PartFilterExpressions, ObjectFilterExpressions, TeklaStructuresDatabaseTypeEnum
    from tekla_mcp_server.tekla.wrappers.model import TeklaModel
    from tekla_mcp_server.providers.selection_provider import add_filter

    model = TeklaModel()
    filter_collection = BinaryFilterExpressionCollection()
    add_filter(filter_collection, ObjectFilterExpressions.Type(), TeklaStructuresDatabaseTypeEnum.PART)
    add_filter(filter_collection, PartFilterExpressions.Name(), "MCP_TEST_", StringMatchType.STARTS_WITH)

    test_objects = model.get_objects_by_filter(filter_collection)

    if test_objects:
        for test_obj in test_objects:
            test_obj.Delete()
        model.commit_changes()


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Cleanup test objects after each test."""
    yield
    cleanup_modeling_test_objects()


@pytest.fixture
def beam_input():
    """Fixture: Basic beam input."""
    return BeamInput(
        start=PointInput(x=0, y=0, z=0),
        end=PointInput(x=2000, y=0, z=0),
        profile="300*600",
        material="C30/37",
        tekla_class=11,
        name="MCP_TEST_BEAM",
    )


@pytest.fixture
def column_input():
    """Fixture: Basic column input."""
    return ColumnInput(
        base=PointInput(x=0, y=0, z=0),
        height=3000,
        profile="400*400",
        material="C30/37",
        tekla_class=10,
        name="MCP_TEST_COLUMN",
    )


@pytest.fixture
def panel_input():
    """Fixture: Basic panel input."""
    return PanelInput(
        start=PointInput(x=0, y=0, z=0),
        end=PointInput(x=3000, y=0, z=0),
        profile="3000*200",
        material="C30/37",
        tekla_class=1,
        name="MCP_TEST_PANEL",
    )


def test_place_single_beam(beam_input):
    """Tests placing a single beam."""
    result = place_beams(beams=[beam_input])
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 1
    assert result.structured_content["total"] == 1


def test_place_multiple_beams():
    """Tests placing multiple beams in one call."""
    beams = [
        BeamInput(
            start=PointInput(x=0, y=0, z=3000),
            end=PointInput(x=2000, y=0, z=3000),
            profile="300*600",
            material="C30/37",
            tekla_class=11,
            name="MCP_TEST_BEAM_1",
        ),
        BeamInput(
            start=PointInput(x=2000, y=0, z=3000),
            end=PointInput(x=4000, y=0, z=3000),
            profile="300*600",
            material="C30/37",
            tekla_class=11,
            name="MCP_TEST_BEAM_2",
        ),
    ]
    result = place_beams(beams=beams)
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 2


def test_place_beam_with_position():
    """Tests placing a beam with custom position settings."""
    beam = BeamInput(
        start=PointInput(x=0, y=0, z=0),
        end=PointInput(x=2000, y=0, z=0),
        profile="HEA200",
        material="S235JR",
        tekla_class=100,
        position=PositionInput(plane="LEFT", depth="MIDDLE"),
        name="MCP_TEST_BEAM_POS",
    )
    result = place_beams(beams=[beam])
    assert result.structured_content["success"] is True


def test_place_beam_empty_list():
    """Tests placing with empty list returns error."""
    result = place_beams(beams=[])
    assert result.structured_content["status"] == "error"


def test_place_beam_none_list():
    """Tests placing with None list returns error."""
    result = place_beams(beams=None)
    assert result.structured_content["status"] == "error"


def test_place_single_column(column_input):
    """Tests placing a single column."""
    result = place_columns(columns=[column_input])
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 1


def test_place_multiple_columns():
    """Tests placing multiple columns in one call."""
    columns = [
        ColumnInput(
            base=PointInput(x=0, y=0, z=0),
            height=3000,
            profile="400*400",
            material="C30/37",
            tekla_class=10,
            name="MCP_TEST_COL_1",
        ),
        ColumnInput(
            base=PointInput(x=5000, y=0, z=0),
            height=3000,
            profile="400*400",
            material="C30/37",
            tekla_class=10,
            name="MCP_TEST_COL_2",
        ),
    ]
    result = place_columns(columns=columns)
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 2


def test_place_column_with_position():
    """Tests placing a column with custom position settings."""
    col = ColumnInput(
        base=PointInput(x=0, y=0, z=0),
        height=3000,
        profile="HEA300",
        material="S235JR",
        tekla_class=101,
        position=PositionInput(plane="MIDDLE", depth="MIDDLE"),
        name="MCP_TEST_COLUMN_POS",
    )
    result = place_columns(columns=[col])
    assert result.structured_content["success"] is True


def test_place_column_empty_list():
    """Tests placing columns with empty list returns error."""
    result = place_columns(columns=[])
    assert result.structured_content["status"] == "error"


def test_place_column_none_list():
    """Tests placing columns with None returns error."""
    result = place_columns(columns=None)
    assert result.structured_content["status"] == "error"


def test_place_single_panel(panel_input):
    """Tests placing a single panel."""
    result = place_panels(panels=[panel_input])
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 1


def test_place_multiple_panels():
    """Tests placing multiple panels in one call."""
    panels = [
        PanelInput(
            start=PointInput(x=0, y=0, z=0),
            end=PointInput(x=3000, y=0, z=0),
            profile="3000*200",
            material="C30/37",
            tekla_class=1,
            name="MCP_TEST_PANEL_1",
        ),
        PanelInput(
            start=PointInput(x=3000, y=0, z=0),
            end=PointInput(x=6000, y=0, z=0),
            profile="3000*200",
            material="C30/37",
            tekla_class=1,
            name="MCP_TEST_PANEL_2",
        ),
    ]
    result = place_panels(panels=panels)
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 2


def test_place_panel_with_position():
    """Tests placing a panel with custom position settings."""
    panel = PanelInput(
        start=PointInput(x=0, y=0, z=0),
        end=PointInput(x=3000, y=0, z=0),
        profile="3000*200",
        material="C30/37",
        tekla_class=1,
        position=PositionInput(plane="MIDDLE", depth="FRONT"),
        name="MCP_TEST_PANEL_POS",
    )
    result = place_panels(panels=[panel])
    assert result.structured_content["success"] is True


def test_place_panel_empty_list():
    """Tests placing panels with empty list returns error."""
    result = place_panels(panels=[])
    assert result.structured_content["status"] == "error"


def test_place_panel_none_list():
    """Tests placing panels with None returns error."""
    result = place_panels(panels=None)
    assert result.structured_content["status"] == "error"


def test_delete_selected_no_selection():
    """Tests delete_selected with no selection returns error."""
    from tekla_mcp_server.tekla.wrappers.model import TeklaModel

    TeklaModel.clear_selection()
    result = delete_selected()
    assert result.structured_content["status"] == "error"
