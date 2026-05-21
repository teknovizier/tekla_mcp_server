"""
Functional tests for operations_provider.

Tests operations like boolean cuts, cut part conversion, and macro execution.
"""

from tekla_mcp_server.providers.operations_provider import (
    check_for_invalid_objects,
    check_for_orphans,
    clash_check,
    cut_elements_with_zero_class_parts,
    convert_cut_parts_to_real_parts,
    run_macro,
)
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


def test_check_for_orphans_no_selection():
    """Tests that check_for_orphans returns error when nothing selected."""
    result = check_for_orphans(mode="embeds")
    assert result.structured_content["status"] == "error"


def test_check_for_orphans_with_selection(model_objects):
    """Tests check_for_orphans with selected elements."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = check_for_orphans(mode="embeds")
    assert result.structured_content["status"] in ["success", "warning"]
    assert result.structured_content["selected_elements"] == 1
    assert "embeds_evaluated" in result.structured_content
    assert "orphaned_embeds_count" in result.structured_content


def test_check_for_orphans_rebars_mode(model_objects):
    """Tests check_for_orphans in rebars mode (separate code path from embeds)."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = check_for_orphans(mode="rebars")
    assert result.structured_content["status"] in ["success", "warning"]
    assert result.structured_content["selected_elements"] == 1
    assert "rebar_objects_evaluated" in result.structured_content
    assert "orphaned_rebar_objects_count" in result.structured_content


def test_cut_elements_with_zero_class_parts(model_objects):
    """Tests cut_elements_with_zero_class_parts tool."""
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    result = cut_elements_with_zero_class_parts(delete_cutting_parts=False)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_elements"] == 2


def test_convert_cut_parts_to_real_parts_without_cuts(model_objects):
    """Tests convert_cut_parts_to_real_parts when no cuts are present."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = convert_cut_parts_to_real_parts()
    assert result.structured_content["status"] == "warning"


def test_convert_cut_parts_to_real_parts_with_cut(model_objects):
    """Tests convert_cut_parts_to_real_parts when a valid cut part exists."""
    TeklaModel.select_objects([model_objects["test_wall3"]])
    result = convert_cut_parts_to_real_parts()
    assert result.structured_content["status"] == "success"


def test_run_macro_nonexistent():
    """Tests that run_macro returns an error for non-existent macro."""
    result = run_macro(macro_name="NonExistentMacro.cs")
    assert result.structured_content["status"] == "error"


def test_check_for_invalid_objects_no_selection():
    """Tests that check_for_invalid_objects returns success when nothing selected."""
    result = check_for_invalid_objects()
    assert result.structured_content["status"] in ["success", "warning"]
    assert result.structured_content["selected_count"] >= 0


def test_check_for_invalid_objects_with_selection(model_objects):
    """Tests check_for_invalid_objects with selected elements."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = check_for_invalid_objects()
    assert result.structured_content["status"] in ["success", "warning"]
    assert result.structured_content["selected_count"] == 1
    assert "total_evaluated" in result.structured_content
    assert "invalid_parts_count" in result.structured_content
    assert "invalid_reinforcements_count" in result.structured_content
    assert "invalid_assemblies_count" in result.structured_content


def test_no_clash_separate_walls(model_objects):
    """Wall A alone - nothing to clash against."""
    TeklaModel.select_objects([model_objects["test_clash_wall_a"]])
    result = clash_check()
    assert result.structured_content["clashes_count"] == 0


def test_clash_overlapping_walls(model_objects):
    """Wall A + Wall B overlap by 500 mm - one CLASH_TYPE_CLASH with overlap >= 0."""
    TeklaModel.select_objects([model_objects["test_clash_wall_a"], model_objects["test_clash_wall_b"]])
    result = clash_check()
    clashes = result.structured_content["clashes"]
    assert len(clashes) == 1
    assert clashes[0]["clash_type"] == "CLASH_TYPE_CLASH"
    assert clashes[0]["overlap"] >= 0


def test_clash_containment(model_objects):
    """Wall C is entirely inside Wall A - clash type CLASH_TYPE_ISINSIDE."""
    TeklaModel.select_objects([model_objects["test_clash_wall_a"], model_objects["test_clash_wall_c"]])
    result = clash_check()
    clashes = result.structured_content["clashes"]
    assert len(clashes) == 1
    assert clashes[0]["clash_type"] == "CLASH_TYPE_ISINSIDE"


def test_clash_result_fields(model_objects):
    """Each clash record carries the expected object fields."""
    TeklaModel.select_objects([model_objects["test_clash_wall_a"], model_objects["test_clash_wall_b"]])
    result = clash_check()
    obj = result.structured_content["clashes"][0]["object1"]
    assert obj["guid"] is not None
    assert obj["name"] in ("MCP_TEST_CLASH_WALL_A", "MCP_TEST_CLASH_WALL_B")
    assert obj["profile"] != "N/A"
    assert obj["material"] != "N/A"
    assert obj["tekla_class"] == 1


def test_exclude_classes_filters_out_clash(model_objects):
    """Excluding class 1 drops all clashes between class 1 walls."""
    TeklaModel.select_objects([model_objects["test_clash_wall_a"], model_objects["test_clash_wall_b"]])
    result = clash_check(exclude_classes=[1])
    assert result.structured_content["clashes_count"] == 0
