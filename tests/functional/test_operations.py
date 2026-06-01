"""
Functional tests for operations_provider.

Tests operations like boolean cuts, cut part conversion, and macro execution.
"""

from tekla_mcp_server.models import AttachmentPair
from tekla_mcp_server.providers.operations_provider import (
    attach_rebars,
    attach_assemblies,
    check_for_invalid_objects,
    check_for_orphans,
    clash_check,
    cut_elements_with_cutters,
    convert_cut_parts_to_real_parts,
    run_macro,
)
from tekla_mcp_server.tekla.wrappers.model_object import ZERO_GUID
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


OTHER_GUID = "11111111-1111-1111-1111-111111111111"


def test_check_for_orphans_no_selection():
    """Tests that check_for_orphans returns error when nothing selected."""
    result = check_for_orphans(mode="subassemblies")
    assert result.structured_content["status"] == "error"


def test_check_for_orphans_with_selection(model_objects):
    """Tests check_for_orphans in subassemblies mode with selected elements."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = check_for_orphans(mode="subassemblies")
    assert result.structured_content["status"] in ["success", "warning"]
    assert result.structured_content["mode"] == "subassemblies"
    assert result.structured_content["selected_count"] == 1
    assert "evaluated_count" in result.structured_content
    assert "orphaned_count" in result.structured_content
    assert isinstance(result.structured_content["orphaned"], list)


def test_check_for_orphans_rebars_mode(model_objects):
    """Tests check_for_orphans in rebars mode (separate code path from subassemblies)."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = check_for_orphans(mode="rebars")
    assert result.structured_content["status"] in ["success", "warning"]
    assert result.structured_content["mode"] == "rebars"
    assert result.structured_content["selected_count"] == 1
    assert "evaluated_count" in result.structured_content
    assert "orphaned_count" in result.structured_content
    assert isinstance(result.structured_content["orphaned"], list)


def test_check_for_orphans_pairs_shape(model_objects):
    """Each detected orphan carries object_guid + target_guid so attach can consume it verbatim."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = check_for_orphans(mode="subassemblies")
    for entry in result.structured_content["orphaned"]:
        assert "object_guid" in entry
        assert "target_guid" in entry


def test_attach_assemblies_empty_pairs():
    """Empty pairs is a structured no-op success - nothing to attach, no commit."""
    result = attach_assemblies(pairs=[])
    assert result.structured_content["status"] == "success"
    assert result.structured_content["attached_count"] == 0
    assert result.structured_content["attached"] == []
    assert result.structured_content["skipped"] == []


def test_attach_rebars_empty_pairs():
    """Empty pairs is a structured no-op success for the rebars tool too."""
    result = attach_rebars(pairs=[])
    assert result.structured_content["status"] == "success"
    assert result.structured_content["attached_count"] == 0
    assert result.structured_content["attached"] == []
    assert result.structured_content["skipped"] == []


def test_attach_assemblies_duplicate_pair():
    """An exact duplicate pair is skipped 'duplicate_pair' so it can't be double-counted."""
    pair = AttachmentPair(object_guid=ZERO_GUID, target_guid=OTHER_GUID)
    result = attach_assemblies(pairs=[pair, pair])
    reasons = [s["reason"] for s in result.structured_content["skipped"]]
    assert "duplicate_pair" in reasons
    assert result.structured_content["attached_count"] == 0


def test_attach_assemblies_unresolvable_guid():
    """A pair whose object GUID doesn't resolve is skipped 'object_not_found'; an all-skipped batch is an error."""
    result = attach_assemblies(pairs=[AttachmentPair(object_guid=ZERO_GUID, target_guid=OTHER_GUID)])
    assert result.structured_content["status"] == "error"
    assert result.structured_content["attached_count"] == 0
    assert result.structured_content["skipped"][0]["reason"] == "object_not_found"


def test_attach_rebars_unresolvable_guid():
    """A pair whose object GUID doesn't resolve is skipped 'object_not_found'; an all-skipped batch is an error."""
    result = attach_rebars(pairs=[AttachmentPair(object_guid=ZERO_GUID, target_guid=OTHER_GUID)])
    assert result.structured_content["status"] == "error"
    assert result.structured_content["attached_count"] == 0
    assert result.structured_content["skipped"][0]["reason"] == "object_not_found"


def test_attach_assemblies_target_not_found(model_objects):
    """A pair whose target GUID doesn't resolve is skipped 'target_not_found'."""
    obj_guid = model_objects["test_wall1"].Identifier.GUID.ToString()
    result = attach_assemblies(pairs=[AttachmentPair(object_guid=obj_guid, target_guid=OTHER_GUID)])
    assert result.structured_content["status"] == "error"
    assert result.structured_content["skipped"][0]["reason"] == "target_not_found"


def test_attach_rebars_target_not_found(model_objects):
    """A pair whose target GUID doesn't resolve is skipped 'target_not_found'."""
    obj_guid = model_objects["test_wall1"].Identifier.GUID.ToString()
    result = attach_rebars(pairs=[AttachmentPair(object_guid=obj_guid, target_guid=OTHER_GUID)])
    assert result.structured_content["status"] == "error"
    assert result.structured_content["skipped"][0]["reason"] == "target_not_found"


def test_attach_assemblies_self_attach_rejected():
    """object_guid == target_guid is rejected 'self_attach' before any resolution."""
    result = attach_assemblies(pairs=[AttachmentPair(object_guid=ZERO_GUID, target_guid=ZERO_GUID)])
    assert result.structured_content["status"] == "error"
    assert result.structured_content["attached_count"] == 0
    assert result.structured_content["skipped"][0]["reason"] == "self_attach"


def test_attach_rebars_self_attach_rejected():
    """object_guid == target_guid is rejected 'self_attach' before any resolution."""
    result = attach_rebars(pairs=[AttachmentPair(object_guid=ZERO_GUID, target_guid=ZERO_GUID)])
    assert result.structured_content["status"] == "error"
    assert result.structured_content["attached_count"] == 0
    assert result.structured_content["skipped"][0]["reason"] == "self_attach"


def test_cut_elements_with_cutters_by_class(model_objects):
    """Tests cut_elements_with_cutters using cutting_class."""
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    result = cut_elements_with_cutters(cutter_class=0, delete_cutting_parts=False)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 2
    assert result.structured_content["processed_count"] >= 1


def test_cut_elements_with_cutters_by_guid(model_objects):
    """Tests cut_elements_with_cutters using cutter_guids."""
    cutter_guid = model_objects["void2"].Identifier.GUID.ToString()
    TeklaModel.select_objects([model_objects["test_wall4"]])
    result = cut_elements_with_cutters(cutter_guids=[cutter_guid], delete_cutting_parts=False)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["performed_cuts_count"] >= 1
    assert result.structured_content["processed_count"] == 1


def test_cut_elements_with_cutters_invalid_guid(model_objects):
    """Tests cut_elements_with_cutters with a non-existent GUID returns warning."""
    TeklaModel.select_objects([model_objects["test_wall3"]])
    result = cut_elements_with_cutters(cutter_guids=["00000000-0000-0000-0000-000000000000"])
    assert result.structured_content["status"] == "warning"
    assert result.structured_content["performed_cuts_count"] == 0


def test_convert_cut_parts_to_real_parts_without_cuts(model_objects):
    """Tests convert_cut_parts_to_real_parts when no cuts are present."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = convert_cut_parts_to_real_parts()
    assert result.structured_content["status"] == "warning"
    assert result.structured_content["processed_count"] == 2


def test_convert_cut_parts_to_real_parts_with_cut(model_objects):
    """Tests convert_cut_parts_to_real_parts when a valid cut part exists."""
    TeklaModel.select_objects([model_objects["test_wall3"]])
    result = convert_cut_parts_to_real_parts()
    assert result.structured_content["status"] == "success"
    assert result.structured_content["processed_count"] == 1


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
    assert result.structured_content["total_evaluated_count"] >= 1
    assert result.structured_content["invalid_parts_count"] >= 0
    assert result.structured_content["invalid_reinforcements_count"] >= 0
    assert result.structured_content["invalid_assemblies_count"] >= 0


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


def test_filter_name_completes_successfully(model_objects):
    """clash_check with filter_name pre-selects matching objects and returns a valid result."""
    TeklaModel.select_objects([model_objects["test_clash_wall_a"], model_objects["test_clash_wall_b"]])
    result = clash_check(filter_name="standard")
    assert result.structured_content["status"] in ["success", "warning"]
    assert "clashes_count" in result.structured_content


def test_filter_name_restores_original_selection(model_objects):
    """Original selection is restored after clash_check with filter_name finishes."""
    walls = [model_objects["test_clash_wall_a"], model_objects["test_clash_wall_b"]]
    TeklaModel.select_objects(walls)
    clash_check(filter_name="standard")
    selected_guids = {obj.Identifier.GUID.ToString() for obj in TeklaModel().get_selected_objects()}
    expected_guids = {w.Identifier.GUID.ToString() for w in walls}
    assert selected_guids == expected_guids
