"""
Functional tests for modeling_provider.

Tests beam, column, and panel placement operations.
"""

import pytest

from tekla_mcp_server.providers.modeling_provider import place_beams, place_columns, place_panels, place_slabs, delete_selected, move_elements, place_grid
from tekla_mcp_server.models import BeamInput, ColumnInput, PanelInput, SlabInput, PointInput, PositionInput
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_object, TeklaAssembly


def cleanup_modeling_test_objects():
    """Clean up test objects created by modeling tests."""
    from tekla_mcp_server.models import StringMatchType
    from tekla_mcp_server.tekla.loader import BinaryFilterExpressionCollection, PartFilterExpressions, ObjectFilterExpressions, TeklaStructuresDatabaseTypeEnum
    from tekla_mcp_server.tekla.wrappers.model import TeklaModel
    from tekla_mcp_server.tekla.filter_builder import add_filter

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
        start_point=PointInput(x=0, y=0, z=0),
        end_point=PointInput(x=2000, y=0, z=0),
        profile="300*600",
        material="C30/37",
        tekla_class=11,
        name="MCP_TEST_BEAM",
    )


@pytest.fixture
def column_input():
    """Fixture: Basic column input."""
    return ColumnInput(
        base_point=PointInput(x=0, y=0, z=0),
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
        start_point=PointInput(x=0, y=0, z=0),
        end_point=PointInput(x=3000, y=0, z=0),
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
            start_point=PointInput(x=0, y=0, z=3000),
            end_point=PointInput(x=2000, y=0, z=3000),
            profile="300*600",
            material="C30/37",
            tekla_class=11,
            name="MCP_TEST_BEAM_1",
        ),
        BeamInput(
            start_point=PointInput(x=2000, y=0, z=3000),
            end_point=PointInput(x=4000, y=0, z=3000),
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
        start_point=PointInput(x=0, y=0, z=0),
        end_point=PointInput(x=2000, y=0, z=0),
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
            base_point=PointInput(x=0, y=0, z=0),
            height=3000,
            profile="400*400",
            material="C30/37",
            tekla_class=10,
            name="MCP_TEST_COL_1",
        ),
        ColumnInput(
            base_point=PointInput(x=5000, y=0, z=0),
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
        base_point=PointInput(x=0, y=0, z=0),
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
            start_point=PointInput(x=0, y=0, z=0),
            end_point=PointInput(x=3000, y=0, z=0),
            profile="3000*200",
            material="C30/37",
            tekla_class=1,
            name="MCP_TEST_PANEL_1",
        ),
        PanelInput(
            start_point=PointInput(x=3000, y=0, z=0),
            end_point=PointInput(x=6000, y=0, z=0),
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
        start_point=PointInput(x=0, y=0, z=0),
        end_point=PointInput(x=3000, y=0, z=0),
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


@pytest.fixture
def slab_input():
    """Fixture: Basic slab input."""
    return SlabInput(
        points=[
            PointInput(x=0, y=0, z=0),
            PointInput(x=4000, y=0, z=0),
            PointInput(x=4000, y=3000, z=0),
            PointInput(x=0, y=3000, z=0),
        ],
        profile="200",
        material="C30/37",
        tekla_class=9,
        name="MCP_TEST_SLAB",
    )


def test_place_single_slab(slab_input):
    """Tests placing a single slab."""
    result = place_slabs(slabs=[slab_input])
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 1
    assert result.structured_content["total"] == 1


def test_place_multiple_slabs():
    """Tests placing multiple slabs in one call."""
    slabs = [
        SlabInput(
            points=[
                PointInput(x=0, y=0, z=3000),
                PointInput(x=4000, y=0, z=3000),
                PointInput(x=4000, y=3000, z=3000),
                PointInput(x=0, y=3000, z=3000),
            ],
            profile="200",
            material="C30/37",
            tekla_class=9,
            name="MCP_TEST_SLAB_1",
        ),
        SlabInput(
            points=[
                PointInput(x=5000, y=0, z=3000),
                PointInput(x=9000, y=0, z=3000),
                PointInput(x=9000, y=3000, z=3000),
                PointInput(x=5000, y=3000, z=3000),
            ],
            profile="200",
            material="C30/37",
            tekla_class=9,
            name="MCP_TEST_SLAB_2",
        ),
    ]
    result = place_slabs(slabs=slabs)
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 2


def test_place_slab_with_position():
    """Tests placing a slab with custom position settings."""
    slab = SlabInput(
        points=[
            PointInput(x=0, y=0, z=0),
            PointInput(x=2000, y=0, z=0),
            PointInput(x=2000, y=2000, z=0),
            PointInput(x=0, y=2000, z=0),
        ],
        profile="150",
        material="C25/30",
        tekla_class=9,
        position=PositionInput(plane="MIDDLE", depth="MIDDLE"),
        name="MCP_TEST_SLAB_POS",
    )
    result = place_slabs(slabs=[slab])
    assert result.structured_content["success"] is True


def test_place_slab_empty_list():
    """Tests placing with empty list returns error."""
    result = place_slabs(slabs=[])
    assert result.structured_content["status"] == "error"


def test_place_slab_none_list():
    """Tests placing with None list returns error."""
    result = place_slabs(slabs=None)
    assert result.structured_content["status"] == "error"


def test_place_slab_less_than_3_points():
    """Tests placing slab with less than 3 points returns validation error."""
    with pytest.raises(Exception):
        SlabInput(
            points=[
                PointInput(x=0, y=0, z=0),
                PointInput(x=2000, y=0, z=0),
            ],
            profile="200",
            material="C30/37",
            tekla_class=9,
            name="MCP_TEST_SLAB_BAD",
        )


def test_move_part(panel_input):
    """Move a panel selected as a part."""
    result_place = place_panels(panels=[panel_input])
    guid = result_place.structured_content["results"][0]["guid"]
    obj = TeklaModel().get_objects_by_guid([guid])[0]
    TeklaModel.select_objects([obj])
    result = move_elements(dz=6000.0)
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 1


def test_copy_part(panel_input):
    """Copy a panel (copy=True)."""
    result_place = place_panels(panels=[panel_input])
    guid = result_place.structured_content["results"][0]["guid"]
    obj = TeklaModel().get_objects_by_guid([guid])[0]
    TeklaModel.select_objects([obj])
    result = move_elements(dz=6000.0, copy=True)
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 1


def test_move_assembly(panel_input):
    """Select the assembly instead of the part - _collect_parts must expand it."""
    result_place = place_panels(panels=[panel_input])
    guid = result_place.structured_content["results"][0]["guid"]
    obj = TeklaModel().get_objects_by_guid([guid])[0]
    asm = wrap_model_object(obj.GetAssembly())
    assert isinstance(asm, TeklaAssembly)
    TeklaModel.select_objects([asm.model_object])
    result = move_elements(dz=6000.0)
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 1


def test_copy_assembly(panel_input):
    """Copy via assembly selection."""
    result_place = place_panels(panels=[panel_input])
    guid = result_place.structured_content["results"][0]["guid"]
    obj = TeklaModel().get_objects_by_guid([guid])[0]
    asm = wrap_model_object(obj.GetAssembly())
    assert isinstance(asm, TeklaAssembly)
    TeklaModel.select_objects([asm.model_object])
    result = move_elements(dz=6000.0, copy=True)
    assert result.structured_content["success"] is True
    assert result.structured_content["succeeded"] == 1


def test_move_no_selection():
    """No selection - tool must return an error."""
    TeklaModel.clear_selection()
    result = move_elements(dz=6000.0)
    assert result.structured_content.get("status") == "error"


@pytest.fixture
def grid_cleanup():
    """Delete grids created during the test by their GUIDs."""
    guids: list[str] = []
    yield guids
    if guids:
        model = TeklaModel()
        objects = model.get_objects_by_guid(guids)
        for obj in objects:
            obj.Delete()
        model.commit_changes()


def test_place_grid_basic(grid_cleanup):
    """Place a minimal grid with only X and Y axes."""
    result = place_grid(x=[0, 5000, 10000], y=[0, 5000])
    assert result.structured_content["status"] == "success"
    assert "guid" in result.structured_content
    grid_cleanup.append(result.structured_content["guid"])


def test_place_grid_with_name_and_z(grid_cleanup):
    """Place a grid with a name, Z storeys, and axis labels."""
    result = place_grid(
        x=[0, 6000, 12000],
        y=[0, 4000],
        z=[0, 3000, 6000],
        x_labels=["A", "B", "C"],
        y_labels=["1", "2"],
        z_labels=["+0.000", "+3.000", "+6.000"],
        name="MCP_TEST_GRID",
    )
    assert result.structured_content["status"] == "success"
    assert result.structured_content["name"] == "MCP_TEST_GRID"
    grid_cleanup.append(result.structured_content["guid"])


def test_place_grid_requires_two_x_coords():
    """Single X coordinate is rejected by validation."""
    result = place_grid(x=[0], y=[0, 5000])
    assert result.structured_content["status"] == "error"
    assert "X coordinates" in result.structured_content["message"]


def test_place_grid_requires_two_y_coords():
    """Single Y coordinate is rejected by validation."""
    result = place_grid(x=[0, 5000], y=[0])
    assert result.structured_content["status"] == "error"
    assert "Y coordinates" in result.structured_content["message"]
