"""
Functional tests for properties_provider.

Tests getting and setting element properties, UDAs, numbering, cut parts, comparison
and IFC property copy operations.
"""

import pytest

from tekla_mcp_server.providers.properties_provider import (
    get_elements_properties,
    set_elements_properties,
    get_elements_cut_parts,
    compare_elements,
    clear_elements_udas,
    get_elements_coordinates,
    get_elements_bounding_boxes,
    copy_properties_from_ifc,
)
from tekla_mcp_server.providers.selection_provider import select_elements_assemblies_or_main_parts, select_elements_by_guid
from tekla_mcp_server.tekla.interop import to_array_list
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


def test_set_elements_properties(model_objects):
    """Tests set_elements_properties function with assemblies."""
    TeklaModel.select_objects([model_objects["test_wall7"]])

    result = set_elements_properties(name="MCP_TEST_NEW_NAME", profile="2000*150", material="C16/20", tekla_class=8, finish="FR")
    assert result.structured_content["status"] == "success"
    assert result.structured_content["processed_count"] == 1
    assert result.structured_content["modified_count"] == 1
    assert result.structured_content["changes_applied"]["name"] == 1
    assert result.structured_content["changes_applied"]["profile"] == 1
    assert result.structured_content["changes_applied"]["material"] == 1
    assert result.structured_content["changes_applied"]["tekla_class"] == 1
    assert result.structured_content["changes_applied"]["finish"] == 1

    TeklaModel.select_objects([model_objects["test_wall7"]])
    result = get_elements_properties()
    parts = result.structured_content["parts"]
    assert len(parts) == 1
    assert parts[0]["name"] == "MCP_TEST_NEW_NAME"
    assert parts[0]["profile"] == "2000*150"
    assert parts[0]["material"] == "C16/20"
    assert parts[0]["tekla_class"] == 8
    assert parts[0]["finish"] == "FR"


def test_set_elements_properties_with_user_properties(model_objects):
    """Tests set_elements_properties with user_properties (UDAs)."""
    TeklaModel.select_objects([model_objects["test_wall1"]])

    user_props = {"MCP_TEST_UDA1": "TestValue1", "MCP_TEST_UDA2": "TestValue2"}
    result = set_elements_properties(user_properties=user_props)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["processed_count"] == 1
    assert result.structured_content["changes_applied"]["udas"] == 2


def test_get_elements_properties_contains_required_fields(model_objects):
    """Tests that get_elements_properties returns all required fields for parts."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Main Part")
    result = get_elements_properties()

    parts = result.structured_content["parts"]
    assert len(parts) >= 1
    props = parts[0]

    assert "position" in props
    assert "guid" in props
    assert "name" in props
    assert "phase" in props
    assert "profile" in props
    assert "material" in props
    assert "finish" in props
    assert "tekla_class" in props
    assert "user_properties" in props
    assert "report_properties" in props


def test_get_elements_properties_with_report_props_definitions(model_objects):
    """Tests get_elements_properties with custom report property definitions."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")

    result = get_elements_properties(report_props_definitions=["ASSEMBLY_POS"])

    assemblies = result.structured_content["assemblies"]
    assert len(assemblies) == 2
    for assembly in assemblies:
        assert "position" in assembly
        assert assembly["position"] is not None


def test_set_elements_properties_all_part_properties(model_objects):
    """Tests setting ALL part properties and verifying all are read back correctly."""
    TeklaModel.select_objects([model_objects["test_wall1"]])

    result = set_elements_properties(
        name="MCP_PART_ALL_TEST",
        profile="2500*300",
        material="C50/60",
        tekla_class=9,
        finish="R",
        phase=2,
    )
    assert result.structured_content["status"] == "success"
    assert result.structured_content["modified_count"] == 1
    assert result.structured_content["changes_applied"]["name"] == 1
    assert result.structured_content["changes_applied"]["profile"] == 1
    assert result.structured_content["changes_applied"]["material"] == 1
    assert result.structured_content["changes_applied"]["tekla_class"] == 1
    assert result.structured_content["changes_applied"]["finish"] == 1
    assert result.structured_content["changes_applied"]["phase"] == 1

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Main Part")
    result = get_elements_properties()
    parts = result.structured_content["parts"]
    assert len(parts) >= 1
    assert parts[0]["name"] == "MCP_PART_ALL_TEST"
    assert parts[0]["profile"] == "2500*300"
    assert parts[0]["material"] == "C50/60"
    assert parts[0]["tekla_class"] == 9
    assert parts[0]["finish"] == "R"
    assert parts[0]["phase"] == 2


def test_set_elements_properties_all_assembly_properties(model_objects):
    """Tests setting ALL assembly properties and verifying all are read back correctly."""
    TeklaModel.select_objects([model_objects["test_wall1"]])

    result = set_elements_properties(
        name="MCP_ASSEMBLY_ALL_TEST",
        assembly_prefix="FULL",
        assembly_start_number=888,
        phase=3,
    )
    assert result.structured_content["status"] == "success"
    assert result.structured_content["modified_count"] == 1
    assert result.structured_content["changes_applied"]["name"] == 1
    assert result.structured_content["changes_applied"]["assembly_prefix"] == 1
    assert result.structured_content["changes_applied"]["assembly_start_number"] == 1
    assert result.structured_content["changes_applied"]["phase"] == 1

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result = get_elements_properties()
    assemblies = result.structured_content["assemblies"]
    assert len(assemblies) >= 1
    assert assemblies[0]["name"] == "MCP_ASSEMBLY_ALL_TEST"
    assert assemblies[0]["assembly_prefix"] == "FULL"
    assert assemblies[0]["assembly_start_number"] == 888
    assert assemblies[0]["phase"] == 3


def test_parts_and_assemblies_have_different_properties(model_objects):
    """Tests that parts and assemblies have different property sets - no cross-contamination."""
    TeklaModel.select_objects([model_objects["test_wall1"]])

    set_elements_properties(
        name="MCP_TEST_CROSS_TEST",
        profile="3000*400",
        material="C30/37",
    )

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Main Part")
    result_parts = get_elements_properties()
    parts = result_parts.structured_content["parts"]

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result_assemblies = get_elements_properties()
    assemblies = result_assemblies.structured_content["assemblies"]

    assert len(parts) >= 1
    assert len(assemblies) >= 1

    assert parts[0]["name"] == "MCP_TEST_CROSS_TEST"
    assert parts[0]["profile"] == "3000*400"
    assert parts[0]["material"] == "C30/37"
    assert "assembly_prefix" in parts[0]
    assert "assembly_start_number" in parts[0]

    assert assemblies[0]["name"] == "MCP_TEST_CROSS_TEST"
    assert "profile" not in assemblies[0]
    assert "material" not in assemblies[0]
    assert "tekla_class" not in assemblies[0]
    assert "finish" not in assemblies[0]
    assert "assembly_prefix" in assemblies[0]
    assert "assembly_start_number" in assemblies[0]


def test_set_elements_properties_multiple_elements(model_objects):
    """Tests set_elements_properties on multiple elements."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    result = set_elements_properties(tekla_class=77)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["processed_count"] == 2
    assert result.structured_content["modified_count"] == 2
    assert result.structured_content["changes_applied"]["tekla_class"] == 2


def test_set_elements_properties_empty_selection(model_objects):
    """Tests set_elements_properties with no elements selected."""
    TeklaModel.select_objects([])

    result = set_elements_properties(name="ShouldNotFail")
    assert result.structured_content["status"] == "error"


def test_get_elements_properties_parts_vs_assemblies(model_objects):
    """Tests that parts and assemblies are returned separately."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result_assemblies = get_elements_properties()

    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    select_elements_assemblies_or_main_parts(mode="Main Part")
    result_parts = get_elements_properties()

    assemblies = result_assemblies.structured_content["assemblies"]
    parts = result_parts.structured_content["parts"]

    assert len(assemblies) > 0
    assert len(parts) > 0


def test_get_elements_properties_numbering_fields(model_objects):
    """Tests that get_elements_properties returns numbering fields for parts and assemblies."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Main Part")
    result_parts = get_elements_properties()
    parts = result_parts.structured_content["parts"]

    assert len(parts) >= 1
    assert "part_prefix" in parts[0]
    assert "part_start_number" in parts[0]
    assert "assembly_prefix" in parts[0]
    assert "assembly_start_number" in parts[0]
    assert "phase" in parts[0]

    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result_assemblies = get_elements_properties()
    assemblies = result_assemblies.structured_content["assemblies"]

    assert len(assemblies) >= 1
    assert "assembly_prefix" in assemblies[0]
    assert "assembly_start_number" in assemblies[0]
    assert "phase" in assemblies[0]
    assert "name" in assemblies[0]
    assert "position" in assemblies[0]
    assert "guid" in assemblies[0]


def test_set_elements_properties_numbering(model_objects):
    """Tests set_elements_properties with numbering parameters."""
    TeklaModel.select_objects([model_objects["test_wall7"]])

    result = set_elements_properties(
        assembly_prefix="TEST",
        assembly_start_number=100,
    )
    assert result.structured_content["status"] == "success"
    assert result.structured_content["changes_applied"]["assembly_prefix"] == 1
    assert result.structured_content["changes_applied"]["assembly_start_number"] == 1

    TeklaModel.select_objects([model_objects["test_wall7"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result = get_elements_properties()
    assemblies = result.structured_content["assemblies"]
    assert assemblies[0]["assembly_prefix"] == "TEST"
    assert assemblies[0]["assembly_start_number"] == 100


def test_get_elements_properties_user_properties(model_objects):
    """Tests that user_properties field is populated."""
    TeklaModel.select_objects([model_objects["test_wall7"]])

    user_props = {"UDA_FOR_TEST": "TestValue123"}
    result = set_elements_properties(user_properties=user_props)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["changes_applied"]["udas"] >= 1

    TeklaModel.select_objects([model_objects["test_wall7"]])
    select_elements_assemblies_or_main_parts(mode="Main Part")
    result = get_elements_properties()
    parts = result.structured_content["parts"]

    assert len(parts) >= 1
    assert "user_properties" in parts[0]


def test_get_elements_properties_both_assemblies_and_parts(model_objects):
    """Tests that selecting both assemblies and parts returns both lists in single call."""
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])

    select_elements_assemblies_or_main_parts(mode="Assembly")
    result_assemblies = get_elements_properties()
    assemblies = result_assemblies.structured_content["assemblies"]

    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    select_elements_assemblies_or_main_parts(mode="Main Part")
    result_parts = get_elements_properties()
    parts = result_parts.structured_content["parts"]

    assert len(assemblies) > 0, "Expected assemblies in result"
    assert len(parts) > 0, "Expected parts in result"


def test_get_elements_properties_basic_assembly_properties(model_objects):
    """Tests get_elements_properties: basic assembly properties."""
    TeklaModel.select_objects(
        [
            model_objects["test_wall1"],
            model_objects["test_wall2"],
            model_objects["test_sw1"],
            model_objects["test_slab1"],
        ]
    )
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result = get_elements_properties()

    assert result.structured_content["status"] == "success"
    assemblies = result.structured_content["assemblies"]
    assert isinstance(assemblies, list)
    assert len(assemblies) == 4


def test_get_elements_properties_known_values_for_assemblies(model_objects):
    """Tests get_elements_properties: profile values for assemblies."""
    TeklaModel.select_objects(
        [
            model_objects["test_wall1"],
            model_objects["test_slab1"],
        ]
    )
    select_elements_assemblies_or_main_parts(mode="Assembly")
    result = get_elements_properties()

    assemblies = result.structured_content["assemblies"]
    assert len(assemblies) >= 1

    names = [a["name"] for a in assemblies]
    assert "MCP_TEST_WALL1" in names or "MCP_TEST_SLAB1" in names


def test_get_elements_properties_valid_report_properties(model_objects):
    """Tests get_elements_properties: valid report properties with exact values."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")

    result = get_elements_properties(report_props_definitions=["ASSEMBLY_POS"])

    assemblies = result.structured_content["assemblies"]
    assert len(assemblies) >= 1
    assert "report_properties" in assemblies[0]
    assert len(assemblies[0]["report_properties"]) > 0


def test_get_elements_properties_invalid_and_missing_report_properties(model_objects):
    """Tests get_elements_properties: invalid report properties are tracked."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Assembly")

    result = get_elements_properties(report_props_definitions=["NON_EXISTENT_PROPERTY"])

    assert "resolution_errors" in result.structured_content
    assert "extraction_errors" in result.structured_content
    assert isinstance(result.structured_content["resolution_errors"], list)
    assert isinstance(result.structured_content["extraction_errors"], list)


def test_get_elements_cut_parts_with_cuts(model_objects):
    """Tests get_elements_cut_parts: elements with cut parts."""
    from tekla_mcp_server.providers.operations_provider import cut_elements_with_cutters

    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    cut_elements_with_cutters(cutter_class=0, delete_cutting_parts=False)

    TeklaModel.select_objects([model_objects["test_wall3"]])
    result = get_elements_cut_parts()

    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 1
    cuts = result.structured_content["parts_with_cuts"][0]["cuts"]
    assert any(cut["type"] == "BOOLEAN_CUT" for cut in cuts)
    assert all(cut["guid"] for cut in cuts)


def test_get_elements_cut_parts_without_cuts(model_objects):
    """Tests get_elements_cut_parts: elements without cut parts."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = get_elements_cut_parts()

    assert result.structured_content["status"] == "warning"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["total_cut_parts_count"] == 0
    assert result.structured_content["total_fittings_count"] == 0
    assert result.structured_content["total_cut_planes_count"] == 0
    assert result.structured_content["total_edge_chamfers_count"] == 0


def test_compare_elements_numbering_not_up_to_date(model_objects):
    """Tests compare_elements when numbering is not up-to-date."""
    TeklaModel.select_objects([model_objects["test_wall5"], model_objects["test_wall6"]])
    result = compare_elements()

    assert result.structured_content["status"] == "error"
    assert "numbering" in result.structured_content["message"].lower()


def test_compare_identical_parts(model_objects):
    """Tests compare_elements: identical parts → identical=True, no diff key."""
    TeklaModel.select_objects([model_objects["test_wall5"], model_objects["test_wall6"]])
    result = compare_elements(ignore_numbering=True)

    sc = result.structured_content
    assert sc["status"] == "success"
    assert sc["identical"] is True
    assert len(sc["elements"]) == 2
    assert "diff" not in sc


def test_compare_different_parts_different_profile(model_objects):
    """Tests compare_elements: different profiles → identical=False, diff is present."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall7"]])
    result = compare_elements(ignore_numbering=True)

    sc = result.structured_content
    assert sc["status"] == "success"
    assert sc["identical"] is False
    assert "diff" in sc
    assert isinstance(sc["diff"], dict)
    assert sc["diff"]  # must be non-empty


def test_compare_three_elements(model_objects):
    """Tests compare_elements with three elements: elements legend has 3 entries."""
    TeklaModel.select_objects(
        [
            model_objects["test_wall1"],
            model_objects["test_wall2"],
            model_objects["test_wall3"],
        ]
    )
    result = compare_elements(ignore_numbering=True)

    sc = result.structured_content
    assert sc["status"] == "success"
    assert len(sc["elements"]) == 3


def test_compare_elements_legend_has_guid_and_pos(model_objects):
    """Each `elements` entry carries a non-empty guid and a pos mark, one per selected element."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall7"]])
    result = compare_elements(ignore_numbering=True)

    elements = result.structured_content["elements"]
    assert len(elements) == 2
    assert all(isinstance(e["guid"], str) and e["guid"] for e in elements)
    assert all(isinstance(e["pos"], str) for e in elements)
    assert len({e["guid"] for e in elements}) == 2


def test_compare_diff_values_aligned_with_elements(model_objects):
    """Every leaf value list in diff must have exactly len(elements) entries at any nesting depth."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall7"]])
    result = compare_elements(ignore_numbering=True)

    sc = result.structured_content
    assert sc["identical"] is False
    n = len(sc["elements"])

    def check_leaf_lengths(val: object, path: str = "") -> None:
        if isinstance(val, list):
            assert len(val) == n, f"diff[{path}] has {len(val)} entries, expected {n}"
        elif isinstance(val, dict):
            for k, v in val.items():
                check_leaf_lengths(v, f"{path}.{k}" if path else k)

    for field, value in sc["diff"].items():
        check_leaf_lengths(value, field)


def test_compare_legend_maps_values_to_elements(model_objects):
    """The odd one out's value sits at its own index in `elements`, whatever order Tekla returns."""
    odd, twins = model_objects["test_wall7"], [model_objects["test_wall5"], model_objects["test_wall6"]]
    TeklaModel.select_objects([*twins, odd])
    sc = compare_elements(ignore_numbering=True).structured_content

    guids = [e["guid"] for e in sc["elements"]]
    profiles = sc["diff"]["report_properties"]["PROFILE"]
    assert profiles[guids.index(odd.Identifier.GUID.ToString())] == "2000*150"
    for twin in twins:
        assert profiles[guids.index(twin.Identifier.GUID.ToString())] == "3000*200"


def _compare_cut_walls(cut_offsets: list[list[float]]) -> dict:
    """
    Compare fresh walls cut by D400 voids at the given offsets from each wall start, then delete them.

    Args:
        cut_offsets: Per wall, the X offsets of its cuts

    Returns:
        The `compare_elements` structured content
    """
    from tekla_mcp_server.models import BeamInput, PanelInput, PointInput
    from tekla_mcp_server.providers.modeling_provider import place_beams, place_panels
    from tekla_mcp_server.providers.operations_provider import cut_elements_with_cutters

    model = TeklaModel()
    starts = [190000 + i * 3000 for i in range(len(cut_offsets))]
    walls = [
        PanelInput(start_point=PointInput(x=x, y=0, z=0), end_point=PointInput(x=x + 2000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_CMP_CUT")
        for x in starts
    ]
    wall_guids = [r["guid"] for r in place_panels(panels=walls).structured_content["results"]]
    void_guids: list[str] = []
    try:
        for x, wall_guid, offsets in zip(starts, wall_guids, cut_offsets, strict=True):
            voids = [
                BeamInput(
                    start_point=PointInput(x=x + dx, y=0, z=1000), end_point=PointInput(x=x + dx, y=200, z=1000), profile="D400", material="Concrete_Undefined", tekla_class=0, name="MCP_TEST_CMP_VOID"
                )
                for dx in offsets
            ]
            cutters = [r["guid"] for r in place_beams(beams=voids).structured_content["results"]]
            void_guids += cutters
            TeklaModel.select_objects(list(model.get_objects_by_guid([wall_guid])))
            assert cut_elements_with_cutters(cutter_guids=cutters).structured_content["performed_cuts_count"] == len(offsets)

        TeklaModel.select_objects(list(model.get_objects_by_guid(wall_guids)))
        return compare_elements(ignore_numbering=True).structured_content
    finally:
        for obj in model.get_objects_by_guid(wall_guids + void_guids):
            obj.Delete()
        model.commit_changes()


def _leaf_lists(val: object):
    """Every list in a diff, without descending into the lists themselves."""
    if isinstance(val, list):
        yield val
    elif isinstance(val, dict):
        for v in val.values():
            yield from _leaf_lists(v)


def test_compare_cut_parts_keyed_by_position():
    """Cut part lists of equal length are diffed by position, so every list left in the diff stays aligned with `elements`."""
    # Two cuts per wall: the first at the same spot, the second moved on the second wall
    sc = _compare_cut_walls([[500, 1500], [500, 1200]])
    cut_diff = sc["diff"]["cutparts"]
    assert isinstance(cut_diff, dict) and len(cut_diff) == 1, cut_diff
    assert next(iter(cut_diff)).startswith("#")
    assert all(len(leaf) == 2 for leaf in _leaf_lists(sc["diff"]))


def test_compare_cut_parts_different_count():
    """With different cut counts, only the cuts not every wall has are reported, next to each wall's count."""
    # The shared cut at 500 is left out, only the extra cut at 1500 is reported
    sc = _compare_cut_walls([[500, 1500], [500]])
    cut_diff = sc["diff"]["cutparts"]
    assert sc["elements"][0]["guid"] != sc["elements"][1]["guid"]
    assert sorted(cut_diff["count"]) == [1, 2]
    extra = cut_diff["not_in_all"]
    two_cut_index = cut_diff["count"].index(2)
    assert len(extra[two_cut_index]) == 1 and extra[1 - two_cut_index] == []
    assert all(len(leaf) == 2 for leaf in _leaf_lists(sc["diff"]))


def test_compare_rebars_reports_bar_count_and_spacing():
    """Rebar groups laid out with a different spacing differ in bar count and exact spacing, on the right element."""
    from tekla_mcp_server.models import PanelInput, PointInput
    from tekla_mcp_server.providers.components_provider import modify_components, put_components
    from tekla_mcp_server.providers.modeling_provider import place_panels

    model = TeklaModel()
    walls = [
        PanelInput(start_point=PointInput(x=x, y=0, z=0), end_point=PointInput(x=x + 2000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_CMP_MESH")
        for x in (210000, 213000)
    ]
    wall_guids = [r["guid"] for r in place_panels(panels=walls).structured_content["results"]]
    try:
        standard, dense = model.get_objects_by_guid(wall_guids)
        TeklaModel.select_objects([standard, dense])
        put_components(component_name="MeshBars")
        TeklaModel.select_objects([dense])
        modify_components(component_name="MeshBars", custom_properties={"SpacBarsBottPri": 100.0})

        def bottom_primary(wall):
            return next(r for r in model.get_object_by_guid(wall.Identifier.GUID.ToString()).GetReinforcements() if r.Class == 3)

        rebars = [bottom_primary(standard), bottom_primary(dense)]
        TeklaModel.select_objects(rebars)
        sc = compare_elements(ignore_numbering=True).structured_content
        props = sc["diff"]["report_properties"]
        index = {e["guid"]: i for i, e in enumerate(sc["elements"])}
        standard_i, dense_i = (index[r.Identifier.GUID.ToString()] for r in rebars)

        assert props["NUMBER_OF_BARS_IN_GROUP"][dense_i] > props["NUMBER_OF_BARS_IN_GROUP"][standard_i]
        assert props["NUMBER_OF_BARS_IN_GROUP"][dense_i] == rebars[1].GetRebarGeometries(False).Count
        assert props["CC_EXACT"][standard_i] != props["CC_EXACT"][dense_i]
    finally:
        for obj in model.get_objects_by_guid(wall_guids):
            obj.Delete()
        model.commit_changes()


class _Panel:
    """A wall with one cut, a mesh and a strand, plus copies made with `copy_elements`. Everything is deleted afterwards."""

    X = 240000

    def __init__(self) -> None:
        from tekla_mcp_server.models import BeamInput, PanelInput, PointInput
        from tekla_mcp_server.providers.modeling_provider import place_beams, place_panels
        from tekla_mcp_server.providers.operations_provider import cut_elements_with_cutters
        from tekla_mcp_server.tekla.interop import to_array_list
        from tekla_mcp_server.tekla.loader import Polygon, Point, RebarMesh, RebarStrand

        self.model = TeklaModel()
        self.created: list[str] = []
        x = self.X
        res = place_panels(
            panels=[
                PanelInput(
                    start_point=PointInput(x=x, y=0, z=0), end_point=PointInput(x=x + 2000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_CMP_PANEL"
                )
            ]
        )
        self.created.append(res.structured_content["results"][0]["guid"])
        wall = self.wall

        cutter = place_beams(
            beams=[
                BeamInput(
                    start_point=PointInput(x=x + 500, y=-150, z=1000),
                    end_point=PointInput(x=x + 500, y=150, z=1000),
                    profile="D400",
                    material="Concrete_Undefined",
                    tekla_class=0,
                    name="MCP_TEST_CMP_VOID",
                )
            ]
        )
        cutter_guid = cutter.structured_content["results"][0]["guid"]
        self.created.append(cutter_guid)
        TeklaModel.select_objects([wall])
        assert cut_elements_with_cutters(cutter_guids=[cutter_guid]).structured_content["performed_cuts_count"] == 1

        # Mesh and strand modelled on a real precast panel: custom polygon mesh at 150 spacing, two strands near the top
        solid = wall.GetSolid()
        y = (solid.MinimumPoint.Y + solid.MaximumPoint.Y) / 2
        z0, z1 = solid.MinimumPoint.Z, solid.MaximumPoint.Z
        mesh = RebarMesh()
        mesh.Father = wall
        mesh.Name, mesh.Class, mesh.Grade = "MESH", 13, "NK500AB-W"
        mesh.MeshType = RebarMesh.RebarMeshTypeEnum.POLYGON_MESH
        mesh.CatalogName = "Custom Mesh"
        mesh.LongitudinalSize = mesh.CrossSize = "8"
        mesh.LongitudinalSpacingMethod = RebarMesh.RebarMeshSpacingMethodEnum.SPACING_TYPE_SAME_DISTANCE
        mesh.LongitudinalDistances = to_array_list([150.0])
        mesh.CrossDistances = to_array_list([150.0])
        mesh.CrossBarLocation = RebarMesh.RebarMeshCrossBarLocationEnum.LOCATION_TYPE_ABOVE
        mesh.RadiusValues = to_array_list([5.0])
        mesh.OnPlaneOffsets = to_array_list([20.0])
        polygon = Polygon()
        for px, pz in ((x + 1950, z1 - 50), (x + 50, z1 - 50), (x + 50, z0 + 50), (x + 1950, z0 + 50)):
            polygon.Points.Add(Point(px, y, pz))
        mesh.Polygon = polygon
        mesh.StartPoint, mesh.EndPoint = Point(x + 1950, y, z0 + 50), Point(x + 1950, y, z1 - 50)
        assert mesh.Insert()

        strand = RebarStrand()
        strand.Father = wall
        strand.Name, strand.Class, strand.Size, strand.Grade = "STRAND", 12, "9.3", "Undefined_strand"
        start, end = Point(x + 2000, y, z1 - 200), Point(x, y, z1 - 200)
        pattern = Polygon()
        pattern.Points.Add(Point(start.X, start.Y, start.Z))
        pattern.Points.Add(Point(end.X, end.Y, end.Z))
        strand.Patterns = to_array_list([pattern])
        strand.StartPoint, strand.EndPoint = start, end
        assert strand.Insert()
        self.model.commit_changes()

    @property
    def wall(self):
        return self.model.get_object_by_guid(self.created[0])

    def copy(self):
        """Copy the wall with `copy_elements` and return the copy, found by its moved bounding box."""
        from tekla_mcp_server.providers.modeling_provider import copy_elements
        from tekla_mcp_server.tekla.loader import ModelObjectSelector, Part, Point

        dy = 20000 * len(self.created)
        wall = self.wall
        TeklaModel.select_objects([wall])
        assert copy_elements(dy=dy).structured_content["success"]
        mn, mx = wall.GetSolid().MinimumPoint, wall.GetSolid().MaximumPoint
        for obj in ModelObjectSelector().GetObjectsByBoundingBox(Point(mn.X - 1, mn.Y + dy - 1, mn.Z - 1), Point(mx.X + 1, mx.Y + dy + 1, mx.Z + 1)):
            if isinstance(obj, Part) and obj.Name == wall.Name:
                self.created.append(obj.Identifier.GUID.ToString())
                return obj
        raise AssertionError("copy not found")

    def rebar(self, part, kind_name: str):
        """The single strand or mesh of `part`, freshly read."""
        fresh = self.model.get_object_by_guid(part.Identifier.GUID.ToString())
        return next(r for r in fresh.GetReinforcements() if type(r).__name__ == kind_name)

    def delete(self) -> None:
        operatives = []
        for guid in self.created:
            obj = self.model.get_object_by_guid(guid)
            if obj is not None:
                operatives += [b.OperativePart for b in obj.GetBooleans() if b.OperativePart is not None]
                obj.Delete()
        for obj in operatives:
            obj.Delete()
        self.model.commit_changes()


@pytest.fixture
def panel():
    """A fresh `_Panel`, deleted with all its copies after the test."""
    built = _Panel()
    yield built
    built.delete()


def _compare_objects(objs: list) -> dict:
    """`compare_elements` on `objs`, checking every diff list stays aligned with `elements`."""
    TeklaModel.select_objects(objs)
    sc = compare_elements(ignore_numbering=True).structured_content
    assert sc["status"] == "success", sc
    assert {e["guid"] for e in sc["elements"]} == {o.Identifier.GUID.ToString() for o in objs}
    assert all(len(leaf) == len(objs) for leaf in _leaf_lists(sc.get("diff", {})))
    return sc


def _value_of(sc: dict, obj, *path: str):
    """Diff value for `obj` at `path`, looked up through the `elements` legend."""
    node = sc["diff"]
    for key in path:
        node = node[key]
    return node[[e["guid"] for e in sc["elements"]].index(obj.Identifier.GUID.ToString())]


def _changed_reinforcement(sc: dict) -> str:
    """Position key of the single reinforcement that differs."""
    keys = [k for k in sc["diff"]["reinforcements"] if k.startswith("#")]
    assert len(keys) == 1, sc["diff"]["reinforcements"]
    return keys[0]


def test_compare_copy_is_identical(panel):
    """A plain copy with its cut, mesh and strand compares as identical to the original."""
    sc = _compare_objects([panel.wall, panel.copy()])
    assert sc["identical"] is True, sc.get("diff")


def test_compare_strand_pull_force_changed_on_copy(panel):
    """A higher strand pull force on the copy is the only difference, on the copy's side."""
    copy = panel.copy()
    strand = panel.rebar(copy, "RebarStrand")
    strand.PullPerStrand = strand.PullPerStrand + 50000.0
    assert strand.Modify()
    TeklaModel().commit_changes()

    sc = _compare_objects([panel.wall, copy])
    position = _changed_reinforcement(sc)
    assert set(sc["diff"]) == {"reinforcements"}
    assert set(sc["diff"]["reinforcements"][position]["report_properties"]) == {"STRAND_PULL_FORCE"}
    path = ("reinforcements", position, "report_properties", "STRAND_PULL_FORCE")
    assert _value_of(sc, copy, *path) > _value_of(sc, panel.wall, *path)


def test_compare_mesh_spacing_changed_on_copy(panel):
    """A wider mesh spacing on the copy shows as fewer bars and a different exact spacing in both directions."""
    copy = panel.copy()
    mesh = panel.rebar(copy, "RebarMesh")
    mesh.LongitudinalDistances = to_array_list([200.0])
    mesh.CrossDistances = to_array_list([200.0])
    assert mesh.Modify()
    TeklaModel().commit_changes()

    sc = _compare_objects([panel.wall, copy])
    position = _changed_reinforcement(sc)
    props = sc["diff"]["reinforcements"][position]["report_properties"]
    assert {"NUMBER_OF_BARS_IN_GROUP", "CC_EXACT_LONG", "CC_EXACT_CROSS"} <= set(props)
    bars = ("reinforcements", position, "report_properties", "NUMBER_OF_BARS_IN_GROUP")
    assert _value_of(sc, copy, *bars) < _value_of(sc, panel.wall, *bars)

    # Comparing the two meshes directly reports the same difference
    direct = _compare_objects([panel.rebar(panel.wall, "RebarMesh"), panel.rebar(copy, "RebarMesh")])
    assert {"NUMBER_OF_BARS_IN_GROUP", "CC_EXACT_LONG", "CC_EXACT_CROSS"} <= set(direct["diff"]["report_properties"])


def test_compare_strand_removed_on_copy(panel):
    """With the strand deleted on the copy, the counts differ and only the original's strand is reported."""
    copy = panel.copy()
    assert panel.rebar(copy, "RebarStrand").Delete()
    TeklaModel().commit_changes()

    sc = _compare_objects([panel.wall, copy])
    assert _value_of(sc, panel.wall, "reinforcements", "count") == 2
    assert _value_of(sc, copy, "reinforcements", "count") == 1
    missing = _value_of(sc, panel.wall, "reinforcements", "not_in_all")
    assert [r["name"] for r in missing] == ["STRAND"]
    assert _value_of(sc, copy, "reinforcements", "not_in_all") == []


def test_compare_cut_moved_on_copy(panel):
    """A cut moved 100 mm on the copy is reported under its position with the shifted offset."""
    from tekla_mcp_server.tekla.loader import Operation, Vector

    copy = panel.copy()
    operative = next(iter(panel.model.get_object_by_guid(copy.Identifier.GUID.ToString()).GetBooleans())).OperativePart
    assert Operation.MoveObject(operative, Vector(100, 0, 0))
    TeklaModel().commit_changes()

    sc = _compare_objects([panel.wall, copy])
    dx = ("cutparts", "#1", "relative_pos", "dx")
    assert round(_value_of(sc, copy, *dx) - _value_of(sc, panel.wall, *dx)) == 100


def test_compare_three_way_one_copy_changed(panel):
    """Original, an unchanged copy and a copy with a different strand grade: only the changed copy stands out."""
    twin, odd = panel.copy(), panel.copy()
    strand = panel.rebar(odd, "RebarStrand")
    strand.Grade = "MCP_TEST_GRADE"
    assert strand.Modify()
    TeklaModel().commit_changes()

    sc = _compare_objects([panel.wall, odd, twin])
    grade = ("reinforcements", _changed_reinforcement(sc), "report_properties", "GRADE")
    assert _value_of(sc, odd, *grade) == "MCP_TEST_GRADE"
    assert _value_of(sc, panel.wall, *grade) == _value_of(sc, twin, *grade) == "Undefined_strand"


def test_compare_strand_against_mesh(panel):
    """A strand and a mesh are both reinforcement, so they compare instead of being rejected as mixed types."""
    sc = _compare_objects([panel.rebar(panel.wall, "RebarStrand"), panel.rebar(panel.wall, "RebarMesh")])
    assert sc["identical"] is False


def test_compare_identical_has_no_diff_key(model_objects):
    """When all elements are identical, no diff key is present in the response."""
    TeklaModel.select_objects([model_objects["test_wall5"], model_objects["test_wall6"]])
    result = compare_elements(ignore_numbering=True)

    assert result.structured_content["identical"] is True
    assert "diff" not in result.structured_content


def test_compare_mixed_results(model_objects):
    """3 elements where one has a different profile: identical=False, all diff leaves are len-3."""
    # wall5 and wall6 share profile/material/class/name; wall7 has a different profile.
    # Selection order from Tekla is not guaranteed — assert only on aggregate properties.
    TeklaModel.select_objects(
        [
            model_objects["test_wall5"],
            model_objects["test_wall6"],
            model_objects["test_wall7"],
        ]
    )
    result = compare_elements(ignore_numbering=True)

    sc = result.structured_content
    assert sc["status"] == "success"
    assert len(sc["elements"]) == 3
    assert sc["identical"] is False
    assert "diff" in sc

    def check_leaf_lengths(val: object, path: str = "") -> None:
        if isinstance(val, list):
            assert len(val) == 3, f"diff[{path}] has {len(val)} entries, expected 3"
        elif isinstance(val, dict):
            for k, v in val.items():
                check_leaf_lengths(v, f"{path}.{k}" if path else k)

    for field, value in sc["diff"].items():
        check_leaf_lengths(value, field)


def test_compare_diff_contains_only_differing_values(model_objects):
    """Every leaf list in diff must contain at least 2 distinct values - identical fields must be stripped."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall7"]])
    result = compare_elements(ignore_numbering=True)

    sc = result.structured_content
    assert sc["identical"] is False

    def assert_leaf_values_differ(val: object, path: str = "") -> None:
        if isinstance(val, list):
            distinct = {str(v) for v in val}
            assert len(distinct) > 1, f"diff[{path}] has all-identical values - should have been stripped: {val}"
        elif isinstance(val, dict):
            for k, v in val.items():
                assert_leaf_values_differ(v, f"{path}.{k}" if path else k)

    for field, value in sc["diff"].items():
        assert_leaf_values_differ(value, field)


def test_compare_content_mirrors_structured_content(model_objects):
    """content is derived from structured_content, which carries no full snapshots."""
    import json

    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall7"]])
    result = compare_elements(ignore_numbering=True)

    sc = result.structured_content
    assert set(sc) == {"status", "identical", "elements", "diff"}
    assert json.loads(result.content[0].text) == sc


def test_clear_elements_udas_all(model_objects):
    """Set a UDA then clear all UDAs, expect the cleared count to be > 0."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    set_elements_properties(user_properties={"MCP_TEST_UDA_TO_CLEAR": "ToBeCleared"})

    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = clear_elements_udas()

    assert result.structured_content["status"] == "success"
    assert result.structured_content["cleared_udas_count"] >= 1


def test_clear_elements_udas_specific(model_objects):
    """Clearing a specific UDA by name leaves other UDAs intact."""
    TeklaModel.select_objects([model_objects["test_wall2"]])
    set_elements_properties(user_properties={"MCP_TEST_UDA_A": "ValueA", "MCP_TEST_UDA_B": "ValueB"})

    TeklaModel.select_objects([model_objects["test_wall2"]])
    result = clear_elements_udas(uda_names=["MCP_TEST_UDA_A"])

    assert result.structured_content["status"] == "success"
    assert result.structured_content["cleared_udas_count"] == 1


def test_get_elements_coordinates_beam(model_objects):
    """Get coordinates for a placed beam (test_slab1 is a beam-typed object)."""
    TeklaModel.select_objects([model_objects["test_slab1"]])
    result = get_elements_coordinates()

    assert result.structured_content["status"] == "success"
    elements = result.structured_content["elements"]
    assert len(elements) == 1
    assert elements[0]["type"] == "Beam"
    assert "start_point" in elements[0]
    assert "end_point" in elements[0]
    assert {"x", "y", "z"} <= set(elements[0]["start_point"].keys())
    assert "start_point_offset" in elements[0]
    assert "end_point_offset" in elements[0]


def test_get_elements_coordinates_empty_selection():
    """No selection: tool returns an error."""
    TeklaModel.clear_selection()
    result = get_elements_coordinates()
    assert result.structured_content["status"] == "error"


def test_compare_elements_no_selection():
    """Zero elements selected: _validate_at_least_two_selected count=0 branch."""
    TeklaModel.clear_selection()
    result = compare_elements(ignore_numbering=True)
    assert result.structured_content["status"] == "error"


def test_compare_elements_single_element(model_objects):
    """One element selected: _validate_at_least_two_selected count=1 branch."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = compare_elements(ignore_numbering=True)
    assert result.structured_content["status"] == "error"
    assert "two elements" in result.structured_content["message"].lower()


def test_set_elements_properties_no_op(model_objects):
    """No properties provided: tool returns warning, no changes applied."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = set_elements_properties()
    assert result.structured_content["modified_count"] == 0
    assert all(count == 0 for count in result.structured_content["changes_applied"].values())


def test_set_elements_properties_reports_property_errors_field(model_objects):
    """`property_errors` field is always present in the response (added in commit cb4e8b2)."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = set_elements_properties(name="MCP_TEST_ERR_FIELD")
    assert "property_errors" in result.structured_content
    assert isinstance(result.structured_content["property_errors"], list)


def test_get_elements_properties_snapshot_mode(model_objects):
    """Snapshot mode returns parts/assemblies lists with full PartSnapshot / AssemblySnapshot dumps."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_elements_assemblies_or_main_parts(mode="Main Part")
    result = get_elements_properties(mode="snapshot")

    assert result.structured_content["status"] == "success"
    assert "parts" in result.structured_content
    assert "assemblies" in result.structured_content
    assert "errors" in result.structured_content
    parts = result.structured_content["parts"]
    assert len(parts) >= 1
    # Snapshots are richer than the flat view: cutparts/welds/reinforcements keys exist
    assert "cutparts" in parts[0]
    assert "welds" in parts[0]
    assert "reinforcements" in parts[0]


def test_get_elements_properties_snapshot_mode_includes_reinforcements_key(model_objects):
    """Snapshot mode returns a top-level `reinforcements` list (empty when no rebars selected)."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = get_elements_properties(mode="snapshot")

    assert "reinforcements" in result.structured_content
    assert isinstance(result.structured_content["reinforcements"], list)


def test_get_elements_properties_flat_mode_includes_reinforcements_key(model_objects):
    """Flat mode includes `reinforcements` in structured_content (empty list when none selected)."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = get_elements_properties(mode="flat")

    assert "reinforcements" in result.structured_content
    assert isinstance(result.structured_content["reinforcements"], list)


def test_get_elements_properties_guids_only_mode(model_objects):
    """guids_only mode returns just the selection's GUIDs, with no property payload."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = get_elements_properties(mode="guids_only")

    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 2
    assert result.structured_content["processed_count"] == 2
    guids = result.structured_content["guids"]
    assert len(guids) == 2
    assert all(isinstance(g, str) and g for g in guids)
    # Lightweight mode: no flat/snapshot property payload
    assert "parts" not in result.structured_content
    assert "assemblies" not in result.structured_content


def test_get_elements_properties_guids_only_round_trips_through_select_by_guid(model_objects):
    """GUIDs from guids_only mode re-select the exact same objects (zero missing)."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    guids = get_elements_properties(mode="guids_only").structured_content["guids"]

    TeklaModel.clear_selection()
    result = select_elements_by_guid(guids=guids)

    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == len(guids)
    assert result.structured_content["missing_guids"] == []


def test_copy_properties_from_ifc_only_tekla_selected_returns_error(model_objects):
    """Select only a Tekla wall without any IFC references: expect error."""
    TeklaModel.select_objects([model_objects["test_wall1"]])

    result = copy_properties_from_ifc(user_properties={})

    assert result.structured_content["status"] == "error"
    assert "no ifc" in result.structured_content["message"].lower()


def test_copy_properties_from_ifc_both_tekla_walls_returns_error(model_objects):
    """Select two Tekla walls without IFC references: expect error."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])

    result = copy_properties_from_ifc(user_properties={})

    assert result.structured_content["status"] == "error"
    assert "no ifc" in result.structured_content["message"].lower()


def test_get_elements_bounding_boxes_wall(model_objects):
    """Tests bounding box for a wall panel: structure, element_type, and geometry."""
    TeklaModel.select_objects([model_objects["test_wall2"]])
    result = get_elements_bounding_boxes()

    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["processed_count"] == 1

    elements = result.structured_content["elements"]
    assert len(elements) == 1

    e = elements[0]
    assert "guid" in e
    assert e["element_type"] == "Beam"
    assert {"x", "y", "z"} == set(e["min"].keys())
    assert {"x", "y", "z"} == set(e["max"].keys())
    assert {"x", "y", "z"} == set(e["centroid"].keys())

    assert e["min"]["x"] <= e["max"]["x"]
    assert e["min"]["y"] <= e["max"]["y"]
    assert e["min"]["z"] <= e["max"]["z"]

    # test_wall2: (0,0,3020) → (2000,0,3020), profile "3000*200"
    # Tekla positions the beam so the profile extends from the reference line upward (+Z).
    # Y-extent matches the profile width (200), Y-centroid is 0 (centered).
    assert e["max"]["x"] - e["min"]["x"] == pytest.approx(2000.0, abs=1.0)
    assert e["max"]["y"] - e["min"]["y"] == pytest.approx(200.0, abs=1.0)
    assert e["max"]["z"] - e["min"]["z"] == pytest.approx(3000.0, abs=1.0)
    assert e["centroid"]["x"] == pytest.approx(1000.0, abs=1.0)
    assert e["centroid"]["y"] == pytest.approx(0.0, abs=1.0)
    assert e["centroid"]["z"] == pytest.approx(4520.0, abs=1.0)


def test_get_elements_bounding_boxes_slab(model_objects):
    """Tests bounding box for a slab beam: structure, element_type, and Y extent."""
    TeklaModel.select_objects([model_objects["test_slab1"]])
    result = get_elements_bounding_boxes()

    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["processed_count"] == 1

    elements = result.structured_content["elements"]
    assert len(elements) == 1

    e = elements[0]
    assert e["element_type"] == "Beam"
    assert {"x", "y", "z"} == set(e["min"].keys())
    assert {"x", "y", "z"} == set(e["max"].keys())
    assert {"x", "y", "z"} == set(e["centroid"].keys())

    assert e["min"]["x"] <= e["max"]["x"]
    assert e["min"]["y"] <= e["max"]["y"]
    assert e["min"]["z"] <= e["max"]["z"]

    # test_slab1: (1000,0,3020) → (1000,6000,3020) - beam along Y axis
    assert e["max"]["y"] - e["min"]["y"] == pytest.approx(6000.0, abs=1.0)
    assert e["centroid"]["y"] == pytest.approx(3000.0, abs=1.0)


def test_get_elements_bounding_boxes_multiple(model_objects):
    """Tests bounding boxes for wall and slab selected together: two distinct results."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_slab1"]])
    result = get_elements_bounding_boxes()

    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 2
    assert result.structured_content["processed_count"] == 2

    elements = result.structured_content["elements"]
    assert len(elements) == 2

    for e in elements:
        assert "guid" in e
        assert e["element_type"] == "Beam"
        assert e["min"]["x"] <= e["max"]["x"]
        assert e["min"]["y"] <= e["max"]["y"]
        assert e["min"]["z"] <= e["max"]["z"]

    assert len({e["guid"] for e in elements}) == 2
