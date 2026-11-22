"""
Functional tests for operations_provider.

Tests operations like boolean cuts, cut part conversion, macro execution,
report creation and the nearby-element search.
"""

from pathlib import Path

import pytest

from tekla_mcp_server.config import get_advanced_option_directories
from tekla_mcp_server.models import AttachmentPair, BeamInput, PanelInput, PointInput
from tekla_mcp_server.providers.modeling_provider import place_beams, place_panels
from tekla_mcp_server.providers.properties_provider import get_elements_cut_parts
from tekla_mcp_server.providers.operations_provider import (
    attach_rebars,
    attach_assemblies,
    check_for_invalid_objects,
    check_for_orphans,
    clash_check,
    create_report,
    cut_elements_with_cutters,
    find_nearby_elements,
    convert_cut_parts_to_real_parts,
    run_macro,
)
from tekla_mcp_server.tekla.loader import Point, TransformationPlane, Vector
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
    assert result.structured_content["evaluated_count"] >= 0
    assert result.structured_content["orphaned_count"] >= 0
    assert isinstance(result.structured_content["orphaned"], list)


def test_check_for_orphans_rebars_mode(model_objects):
    """Tests check_for_orphans in rebars mode (separate code path from subassemblies)."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = check_for_orphans(mode="rebars")
    assert result.structured_content["status"] in ["success", "warning"]
    assert result.structured_content["mode"] == "rebars"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["evaluated_count"] >= 0
    assert result.structured_content["orphaned_count"] >= 0
    assert isinstance(result.structured_content["orphaned"], list)


def test_check_for_orphans_pairs_shape(model_objects):
    """Each detected orphan carries object_guid + target_guid so attach can consume it verbatim."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = check_for_orphans(mode="subassemblies")
    for entry in result.structured_content["orphaned"]:
        assert "object_guid" in entry
        assert "target_guid" in entry


def test_attach_assemblies_empty_pairs():
    """Empty pairs is an error, nothing to attach."""
    result = attach_assemblies(pairs=[])
    assert result.structured_content["status"] == "error"


def test_attach_rebars_empty_pairs():
    """Empty pairs is an error for the rebars tool too."""
    result = attach_rebars(pairs=[])
    assert result.structured_content["status"] == "error"


def test_attach_assemblies_duplicate_pair():
    """Repeated pairs, including spelling variants of the GUIDs, are processed once."""
    pair = AttachmentPair(object_guid=ZERO_GUID, target_guid=OTHER_GUID)
    variant = AttachmentPair(object_guid=f" {{{ZERO_GUID.upper()}}} ", target_guid=OTHER_GUID)
    result = attach_assemblies(pairs=[pair, pair, variant])
    assert len(result.structured_content["skipped"]) == 1
    assert result.structured_content["attached_count"] == 0


def test_attach_assemblies_unresolvable_guid():
    """A pair whose object GUID doesn't resolve is skipped 'object_not_found'; an all-skipped batch is an error."""
    result = attach_assemblies(pairs=[AttachmentPair(object_guid=ZERO_GUID, target_guid=OTHER_GUID)])
    assert result.structured_content["status"] == "error"
    assert result.structured_content["attached_count"] == 0
    assert result.structured_content["skipped"][0]["reason"] == "object_not_found"
    assert result.structured_content["missing_guids"] == [ZERO_GUID]


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


def test_cut_elements_with_cutters_skips_selected_cutters(model_objects):
    """A selected part that is also a cutter is skipped, not cut by itself or other cutters."""
    void_guid = model_objects["void1"].Identifier.GUID.ToString()
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["void1"]])
    result = cut_elements_with_cutters(cutter_class=0, delete_cutting_parts=False)
    assert result.structured_content["selected_count"] == 2
    assert result.structured_content["skipped_cutter_guids"] == [void_guid]


def test_cut_elements_with_cutters_by_guid(model_objects):
    """Tests cut_elements_with_cutters using cutter_guids."""
    cutter_guid = model_objects["void2"].Identifier.GUID.ToString()
    TeklaModel.select_objects([model_objects["test_wall4"]])
    # The repeated spelling variant must not cut a second time
    result = cut_elements_with_cutters(cutter_guids=[cutter_guid, cutter_guid.upper()], delete_cutting_parts=False)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["performed_cuts_count"] == 1
    assert result.structured_content["processed_count"] == 1
    assert result.structured_content["missing_guids"] == []
    assert result.structured_content["unsupported_guids"] == []


def test_cut_elements_with_cutters_partly_missing_guids(model_objects):
    """A missing cutter GUID is reported and the found cutter still cuts, giving 'partial'."""
    # Own wall and cutter, so no fixture wall gets a cut that later tests do not expect
    wall = PanelInput(
        start_point=PointInput(x=20000, y=0, z=0), end_point=PointInput(x=22000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL_PARTIAL"
    )
    void = BeamInput(
        start_point=PointInput(x=21000, y=0, z=1000), end_point=PointInput(x=21000, y=200, z=1000), profile="D400", material="Concrete_Undefined", tekla_class=0, name="MCP_TEST_VOID_PARTIAL"
    )
    wall_guid = place_panels(panels=[wall]).structured_content["results"][0]["guid"]
    cutter_guid = place_beams(beams=[void]).structured_content["results"][0]["guid"]
    TeklaModel.select_objects([TeklaModel().get_object_by_guid(wall_guid)])
    result = cut_elements_with_cutters(cutter_guids=[cutter_guid, OTHER_GUID])
    assert result.structured_content["status"] == "partial"
    assert result.structured_content["performed_cuts_count"] == 1
    assert result.structured_content["missing_guids"] == [OTHER_GUID]


def test_cut_elements_with_cutters_by_cut_part_guid():
    """A cut part GUID from `get_elements_cut_parts` is accepted as a cutter for another part."""
    # Two walls in the same place and an own cutter, so no fixture wall gets a cut that later tests do not expect
    wall = PanelInput(
        start_point=PointInput(x=24000, y=0, z=0), end_point=PointInput(x=26000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_WALL_CUT_PART"
    )
    void = BeamInput(
        start_point=PointInput(x=25000, y=0, z=1000), end_point=PointInput(x=25000, y=200, z=1000), profile="D400", material="Concrete_Undefined", tekla_class=0, name="MCP_TEST_VOID_CUT_PART"
    )
    first_guid, second_guid = (r["guid"] for r in place_panels(panels=[wall, wall]).structured_content["results"])
    place_beams(beams=[void])
    model = TeklaModel()
    TeklaModel.select_objects([model.get_object_by_guid(first_guid)])
    assert cut_elements_with_cutters(cutter_class=0, delete_cutting_parts=True).structured_content["performed_cuts_count"] >= 1

    cut_parts = get_elements_cut_parts().structured_content
    cut_part_guid = cut_parts["cutting_parts"][0]["guid"]
    TeklaModel.select_objects([model.get_object_by_guid(second_guid)])
    # Deleting the cutter would delete the first wall's cut, so it must be kept
    result = cut_elements_with_cutters(cutter_guids=[cut_part_guid], delete_cutting_parts=True)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["performed_cuts_count"] == 1
    assert result.structured_content["unsupported_guids"] == []
    assert (result.structured_content["deleted_cutters_count"], result.structured_content["kept_cut_part_guids"]) == (0, [cut_part_guid])
    TeklaModel.select_objects([model.get_object_by_guid(first_guid)])
    assert [c["guid"] for c in get_elements_cut_parts().structured_content["cutting_parts"]] == [cut_part_guid]


def test_attach_assemblies_conflicting_targets_attach_nothing():
    """An assembly paired with two target assemblies is not attached to either."""
    beams = [
        BeamInput(start_point=PointInput(x=30000, y=y, z=0), end_point=PointInput(x=32000, y=y, z=0), profile="300*600", material="C30/37", tekla_class=11, name="MCP_TEST_ATTACH")
        for y in (0, 1000, 2000)
    ]
    model = TeklaModel()
    obj, first, second = (model.get_object_by_guid(r["guid"]).GetAssembly() for r in place_beams(beams=beams).structured_content["results"])
    obj_guid, first_guid, second_guid = (a.Identifier.GUID.ToString() for a in (obj, first, second))

    result = attach_assemblies(pairs=[AttachmentPair(object_guid=obj_guid, target_guid=first_guid), AttachmentPair(object_guid=obj_guid, target_guid=second_guid)])

    assert (result.structured_content["status"], result.structured_content["attached_count"]) == ("error", 0)
    assert result.structured_content["skipped"] == [{"object_guid": obj_guid, "reason": "conflicting_targets", "target_guids": [first_guid, second_guid]}]
    for target in (first, second):
        target.Select()
        assert target.GetSubAssemblies().Count == 0


def test_cut_elements_with_cutters_invalid_guid(model_objects):
    """Tests cut_elements_with_cutters with only a non-existent GUID returns error."""
    TeklaModel.select_objects([model_objects["test_wall3"]])
    result = cut_elements_with_cutters(cutter_guids=["00000000-0000-0000-0000-000000000000"])
    assert result.structured_content["status"] == "error"
    assert "00000000-0000-0000-0000-000000000000" in result.structured_content["message"]


def test_convert_cut_parts_to_real_parts_without_cuts(model_objects):
    """Tests convert_cut_parts_to_real_parts when no cuts are present."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = convert_cut_parts_to_real_parts()
    assert result.structured_content["status"] == "warning"
    assert result.structured_content["selected_count"] == 2
    assert result.structured_content["processed_count"] == 2


def test_convert_cut_parts_to_real_parts_with_cut(model_objects):
    """Tests convert_cut_parts_to_real_parts when a valid cut part exists."""
    TeklaModel.select_objects([model_objects["test_wall3"]])
    result = convert_cut_parts_to_real_parts()
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["processed_count"] == 1


def test_run_macro_nonexistent():
    """Tests that run_macro returns an error for non-existent macro."""
    result = run_macro(macro_name="NonExistentMacro.cs")
    assert result.structured_content["status"] == "error"


def test_check_for_invalid_objects_no_selection():
    """Tests that check_for_invalid_objects returns error when nothing selected."""
    TeklaModel.clear_selection()
    result = check_for_invalid_objects()
    assert result.structured_content["status"] == "error"


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
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["clashes_count"] == 0


def test_clash_overlapping_walls(model_objects):
    """Wall A + Wall B overlap by 500 mm - one CLASH_TYPE_CLASH with overlap >= 0."""
    TeklaModel.select_objects([model_objects["test_clash_wall_a"], model_objects["test_clash_wall_b"]])
    result = clash_check()
    assert result.structured_content["selected_count"] == 2
    clashes = result.structured_content["clashes"]
    assert len(clashes) == 1
    assert clashes[0]["clash_type"] == "CLASH_TYPE_CLASH"
    assert clashes[0]["overlap"] >= 0


def test_clash_containment(model_objects):
    """Wall C is entirely inside Wall A - clash type CLASH_TYPE_ISINSIDE."""
    TeklaModel.select_objects([model_objects["test_clash_wall_a"], model_objects["test_clash_wall_c"]])
    result = clash_check()
    assert result.structured_content["selected_count"] == 2
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


def test_create_report_custom_filename_and_folder(model_objects, tmp_path):
    """Creates a report with explicit output_filename and output_folder."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    result = create_report(
        template_name="Cast_Unit_List",
        output_filename="my_report",
        output_folder=str(tmp_path),
        title1="Custom Title",
        title2="Subtitle",
    )

    assert result.structured_content["status"] == "success"
    assert result.structured_content["template_name"] == "Cast_Unit_List"
    assert result.structured_content["selected_count"] == 2
    assert result.structured_content["file_name"] == "my_report.xsr"
    assert result.structured_content["output_folder"] == str(tmp_path)
    assert result.structured_content["size_bytes"] > 0
    assert "3000*200" in result.structured_content["content_preview"]


def test_create_report_no_filename_uses_template_name(model_objects, tmp_path):
    """Omitted output_filename falls back to the template name."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    result = create_report(
        template_name="Cast_Unit_List",
        output_folder=str(tmp_path),
    )

    assert result.structured_content["file_name"] == "Cast_Unit_List.xsr"
    assert result.structured_content["output_folder"] == str(tmp_path)
    assert "3000*200" in result.structured_content["content_preview"]


def test_create_report_no_folder_uses_default(model_objects):
    """Omitted output_folder uses XS_REPORT_OUTPUT_DIRECTORY; only file_name is returned on success."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    # This test writes into the real XS_REPORT_OUTPUT_DIRECTORY, so clean up the file
    # afterwards to avoid polluting the environment and leaving stale reports behind.
    report_dirs = get_advanced_option_directories("XS_REPORT_OUTPUT_DIRECTORY")
    created_file = Path(report_dirs[0]) / "default_folder_test.xsr" if report_dirs else None

    try:
        result = create_report(
            template_name="Cast_Unit_List",
            output_filename="default_folder_test",
        )

        status = result.structured_content["status"]
        assert status in ("success", "warning"), f"Unexpected status: {status}"
        assert result.structured_content["file_name"] == "default_folder_test.xsr"

        if status == "success":
            assert "output_folder" not in result.structured_content, "output_folder should not be exposed when user did not provide it"
            assert result.structured_content["size_bytes"] > 0
            assert "3000*200" in result.structured_content["content_preview"]
    finally:
        if created_file is not None and created_file.exists():
            created_file.unlink()


# Nearby tests. Relations are checked on the shared `model_objects` walls that no earlier
# test in this module changes (WALL1, WALL2, WALL8, SW1 and the clash walls). Their rows
# are looked up by GUID, so other shared objects in the radius cannot break the asserts.
# Only the radius limits need an exact neighbour list, so they get their own small layout


def _guid(obj) -> str:
    """GUID of a Tekla model object."""
    return obj.Identifier.GUID.ToString()


def _nearby_rows(result) -> dict[str, dict]:
    """Neighbour rows of the single source, keyed by GUID."""
    sources = result.structured_content["sources"]
    assert len(sources) == 1
    return {row["guid"]: row for row in sources[0]["neighbours"]}


def test_find_nearby_elements_touching_walls(model_objects):
    """WALL1 touches WALL3 at its end (+X) and WALL8 along its face (+Y), and WALL2 sits 20 mm above it."""
    rows = _nearby_rows(find_nearby_elements(guids=[_guid(model_objects["test_wall1"])], radius_mm=100.0))
    assert _guid(model_objects["test_wall1"]) not in rows

    end = rows[_guid(model_objects["test_wall3"])]
    assert (end["relation"], end["gap_mm"], end["sides"]) == ("touching", pytest.approx(0.0, abs=0.5), ["+X"])

    face = rows[_guid(model_objects["test_wall8"])]
    assert (face["relation"], face["sides"]) == ("touching", ["+Y"])
    assert face["orientation"]["length"]["label"] == "parallel"
    # WALL1 is 2000 long and 3000 high, so its largest extent (`length`) is the height
    assert face["axis_overlap_mm"]["length"] == pytest.approx(3000.0, abs=0.5)
    assert face["axis_overlap_mm"]["width"] == pytest.approx(2000.0, abs=0.5)

    above = rows[_guid(model_objects["test_wall2"])]
    assert (above["relation"], above["gap_mm"], above["penetration_mm"], above["sides"]) == ("near", pytest.approx(20.0, abs=0.5), 0.0, ["above"])
    assert above["same_assembly"] is False


def test_find_nearby_elements_overlapping_walls(model_objects):
    """
    CLASH_WALL_B overlaps CLASH_WALL_A by 500 mm in height, but the shortest way out is
    sideways through the 200 mm thickness. CLASH_WALL_C (100 thick) sits inside A, so its
    way out is 150 mm. Both are `boxes_overlap` and come before touching rows.
    """
    sc = find_nearby_elements(guids=[_guid(model_objects["test_clash_wall_a"])], radius_mm=10.0).structured_content
    neighbours = sc["sources"][0]["neighbours"]
    rows = {row["guid"]: row for row in neighbours}

    b = rows[_guid(model_objects["test_clash_wall_b"])]
    assert (b["relation"], b["gap_mm"], b["penetration_mm"]) == ("boxes_overlap", 0.0, pytest.approx(200.0, abs=0.5))
    c = rows[_guid(model_objects["test_clash_wall_c"])]
    assert (c["relation"], c["gap_mm"], c["penetration_mm"]) == ("boxes_overlap", 0.0, pytest.approx(150.0, abs=0.5))

    sw1 = rows[_guid(model_objects["test_sw1"])]
    assert (sw1["relation"], sw1["sides"]) == ("touching", ["-X"])
    relations = [row["relation"] for row in neighbours]
    assert relations.index("touching") > max(i for i, r in enumerate(relations) if r == "boxes_overlap")


def test_find_nearby_elements_assembly_mode(model_objects):
    """In assembly mode a source part resolves to its assembly and rows name the closest part pair."""
    wall1, wall2 = model_objects["test_wall1"], model_objects["test_wall2"]
    sc = find_nearby_elements(guids=[_guid(wall1)], mode="assembly", radius_mm=100.0).structured_content
    assert sc["status"] == "success"
    source = sc["sources"][0]
    assert source["type"] == "Assembly"
    row = next(row for row in source["neighbours"] if row["closest_parts"]["neighbour"] == _guid(wall2))
    assert row["closest_parts"]["source"] == _guid(wall1)
    assert (row["gap_mm"], row["sides"], row["parts_within_radius"]) == (pytest.approx(20.0, abs=0.5), ["above"], 1)


def test_find_nearby_elements_ignores_work_plane(model_objects):
    """Results do not depend on the active work plane, and the plane is restored."""
    source = _guid(model_objects["test_wall1"])
    expected = find_nearby_elements(guids=[source], radius_mm=100.0).structured_content["sources"]

    handler = TeklaModel().model.GetWorkPlaneHandler()
    saved = handler.GetCurrentTransformationPlane()
    rotated = TransformationPlane(Point(1000, 2000, 0), Vector(1, 1, 0), Vector(-1, 1, 0))
    probe = Point(1000, 0, 0)
    try:
        handler.SetCurrentTransformationPlane(rotated)
        before = handler.GetCurrentTransformationPlane().TransformationMatrixToLocal.Transform(probe)
        actual = find_nearby_elements(guids=[source], radius_mm=100.0).structured_content["sources"]
        after = handler.GetCurrentTransformationPlane().TransformationMatrixToLocal.Transform(probe)
    finally:
        handler.SetCurrentTransformationPlane(saved)

    assert actual == expected
    assert (after.X, after.Y, after.Z) == pytest.approx((before.X, before.Y, before.Z))


def test_find_nearby_elements_reports_unusable_inputs(model_objects):
    """A GUID not in the model is skipped with a reason, the call still answers for the rest."""
    unknown = "4b0e9c1a-0000-0000-0000-000000000001"
    sc = find_nearby_elements(guids=[_guid(model_objects["test_wall1"]), unknown], radius_mm=10.0).structured_content
    assert sc["status"] == "partial"
    assert {"guid": unknown, "type": None, "reason": "not_found"} in sc["skipped"]


def test_find_nearby_elements_no_usable_source():
    """Only unknown GUIDs is an error."""
    sc = find_nearby_elements(guids=["4b0e9c1a-0000-0000-0000-000000000002"]).structured_content
    assert sc["status"] == "error"


def test_find_nearby_elements_unknown_filter(model_objects):
    """A filter name that does not exist is an error."""
    sc = find_nearby_elements(guids=[_guid(model_objects["test_wall1"])], filter_name="MCP_TEST_NO_SUCH_FILTER").structured_content
    assert sc["status"] == "error"
    assert "MCP_TEST_NO_SUCH_FILTER" in sc["message"]


def test_find_nearby_elements_standard_filter_keeps_all(model_objects):
    """The 'standard' filter matches everything, so it gives the same neighbours as no filter."""
    source = _guid(model_objects["test_wall1"])
    plain = find_nearby_elements(guids=[source], radius_mm=100.0).structured_content
    filtered = find_nearby_elements(guids=[source], radius_mm=100.0, filter_name="standard").structured_content
    assert filtered["filter_name"] == "standard"
    assert filtered["sources"] == plain["sources"]


def test_find_nearby_elements_pages_through_all_neighbours(model_objects):
    """Pages fetched with `next_offset` give every neighbour once, in the same order as one big page."""
    source = _guid(model_objects["test_wall1"])
    full = find_nearby_elements(guids=[source], radius_mm=200.0, limit=50).structured_content["sources"][0]
    assert full["neighbours_found"] >= 3 and not full["has_more"]

    paged: list[str] = []
    offset: int | None = 0
    while offset is not None:
        page = find_nearby_elements(guids=[source], radius_mm=200.0, limit=2, offset=offset).structured_content
        entry = page["sources"][0]
        assert entry["offset"] == offset
        assert len(entry["neighbours"]) <= 2
        assert page["has_more"] == entry["has_more"]
        paged += [row["guid"] for row in entry["neighbours"]]
        offset = entry["next_offset"]
    assert paged == [row["guid"] for row in full["neighbours"]]


# Own layout for the radius limits and the slab bearing, 3.4 m clear of the shared walls
_NEARBY_X0 = 12000.0


@pytest.fixture(scope="module")
def nearby_layout():
    """
    Place a 2000 x 200 x 1000 source panel, four panels at clear distances of 50, 99, 101 and 150 mm,
    and a slab bearing 180 mm onto the source, then delete them all.

    Panels extend up from the reference line and are centred across it.
    """
    x0 = _NEARBY_X0

    def panel(start: tuple[float, float, float], end: tuple[float, float, float], profile: str, name: str) -> PanelInput:
        """Panel input with points relative to the layout origin."""
        return PanelInput(
            start_point=PointInput(x=x0 + start[0], y=start[1], z=start[2]),
            end_point=PointInput(x=x0 + end[0], y=end[1], z=end[2]),
            profile=profile,
            material="Concrete_Undefined",
            tekla_class=1,
            name=name,
        )

    panels = {
        "source": panel((0, 0, 0), (2000, 0, 0), "1000*200", "MCP_TEST_NEARBY_SRC"),
        "gap_50": panel((2050, 0, 0), (2550, 0, 0), "1000*200", "MCP_TEST_NEARBY_50"),
        "gap_99": panel((-599, 0, 0), (-99, 0, 0), "1000*200", "MCP_TEST_NEARBY_99"),
        "gap_101": panel((0, 301, 0), (2000, 301, 0), "1000*200", "MCP_TEST_NEARBY_101"),
        "gap_150": panel((0, -350, 0), (2000, -350, 0), "1000*200", "MCP_TEST_NEARBY_150"),
        # Occupies x [-100, 1100] relative, y [-80, 5000], z [1000, 1265]
        "slab": panel((500, -80, 1000), (500, 5000, 1000), "265*1200", "MCP_TEST_NEARBY_SLAB"),
    }
    results = place_panels(panels=list(panels.values())).structured_content["results"]
    guids = dict(zip(panels, (r["guid"] for r in results), strict=True))
    model = TeklaModel()
    model.commit_changes()
    yield guids
    for obj in model.get_objects_by_guid(list(guids.values())):
        obj.Delete()
    model.commit_changes()


def test_find_nearby_elements_radius_and_order(nearby_layout):
    """Only parts within the radius are returned, sorted by gap, without the source itself."""
    g = nearby_layout
    sc = find_nearby_elements(guids=[g["source"]], radius_mm=100.0).structured_content
    assert sc["status"] == "success"
    assert sc["geometry_basis"] == "oriented_boxes"
    returned = [row["guid"] for row in sc["sources"][0]["neighbours"]]
    assert g["source"] not in returned
    assert g["gap_101"] not in returned and g["gap_150"] not in returned
    walls = [row for row in sc["sources"][0]["neighbours"] if row["guid"] in (g["gap_50"], g["gap_99"])]
    assert [row["guid"] for row in walls] == [g["gap_50"], g["gap_99"]]
    assert walls[0]["gap_mm"] == pytest.approx(50.0, abs=0.5)
    assert walls[1]["gap_mm"] == pytest.approx(99.0, abs=0.5)
    assert (walls[0]["relation"], walls[0]["penetration_mm"], walls[0]["sides"]) == ("near", 0.0, ["+X"])
    assert walls[1]["sides"] == ["-X"]


def test_find_nearby_elements_orientation_ignores_touch_tolerance():
    """A 400 x 360 column has a clear thickness, so a loose touch tolerance must not make it unclear."""
    beam = BeamInput(start_point=PointInput(x=40000, y=0, z=0), end_point=PointInput(x=43000, y=0, z=0), profile="300*600", material="C30/37", tekla_class=11, name="MCP_TEST_NEARBY_BEAM")
    column = BeamInput(start_point=PointInput(x=43400, y=0, z=-2000), end_point=PointInput(x=43400, y=0, z=2000), profile="400*360", material="C30/37", tekla_class=13, name="MCP_TEST_NEARBY_COLUMN")
    beam_guid, column_guid = (r["guid"] for r in place_beams(beams=[beam, column]).structured_content["results"])
    model = TeklaModel()
    try:
        for tolerance in (1.0, 50.0):
            row = _nearby_rows(find_nearby_elements(guids=[beam_guid], radius_mm=500.0, touch_tolerance_mm=tolerance))[column_guid]
            assert row["orientation"]["thickness"] == {"angle_deg": 90.0, "label": "perpendicular"}, tolerance
    finally:
        for obj in model.get_objects_by_guid([beam_guid, column_guid]):
            obj.Delete()
        model.commit_changes()


def test_find_nearby_elements_slab_bearing(nearby_layout):
    """A slab laid on the source wall touches it, lies above it and overlaps 180 mm across its thickness."""
    g = nearby_layout
    slab = _nearby_rows(find_nearby_elements(guids=[g["source"]], radius_mm=10.0))[g["slab"]]
    assert slab["relation"] == "touching"
    assert slab["gap_mm"] == pytest.approx(0.0, abs=0.5)
    assert slab["sides"] == ["above"]
    assert slab["axis_overlap_mm"]["thickness"] == pytest.approx(180.0, abs=0.5)
    assert slab["orientation"]["length"]["label"] == "perpendicular"
    assert slab["orientation"]["thickness"]["label"] == "perpendicular"
