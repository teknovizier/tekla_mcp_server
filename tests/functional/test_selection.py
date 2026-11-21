"""
Functional tests for selection_provider.

Tests element selection by filter, GUID, and assembly/main part modes.
"""

from pathlib import Path
from typing import Any

import pytest

from tekla_mcp_server.models import BeamInput, PanelInput, PointInput, SlabInput
from tekla_mcp_server.providers.components_provider import put_components
from tekla_mcp_server.providers.modeling_provider import place_beams, place_panels, place_slabs
from tekla_mcp_server.providers.selection_provider import (
    create_filter,
    select_elements_by_filter,
    select_elements_by_filter_name,
    select_elements_by_guid,
    select_related_elements,
)
from tekla_mcp_server.tekla.loader import BaseWeld, BoltArray, BoltGroup, CatalogHandler, Point, Polygon, SingleRebar, Weld
from tekla_mcp_server.tekla.utils import get_all_rebar_items, get_available_attribute_files, refresh_attribute_files
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


def test_select_elements_by_filter_name(model_objects):
    """Tests select_elements_by_filter_name function."""
    result = select_elements_by_filter_name(filter_name="non_standard")
    assert result.structured_content["status"] == "warning"

    result = select_elements_by_filter_name(filter_name="standard")
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"]


def _cond(field: str, op: str, value: Any) -> dict[str, Any]:
    """Build a filter condition dict."""
    return {"field": field, "op": op, "value": value}


def _attr(name: str, op: str, value: Any, category: str = "part") -> dict[str, Any]:
    """Build an attribute condition dict."""
    return {"attribute": name, "category": category, "op": op, "value": value}


@pytest.fixture(scope="module")
def filter_scene() -> Any:
    """
    A scene of every object kind the filter tree covers, far from the other test objects.

    Walls of classes 1 and 8 (one named with spaces), a beam, a plate with a MeshBars component,
    two single rebars, a site bolt group, a shop fillet weld and a site plug weld. Each test scopes
    its filter to the scene's object IDs, so the selection must equal the expected objects exactly.
    """
    model = TeklaModel()
    panel = {"material": "Concrete_Undefined"}
    placed = place_panels(
        panels=[
            PanelInput(start_point=PointInput(x=90000, y=0, z=0), end_point=PointInput(x=92000, y=0, z=0), profile="3000*200", tekla_class=1, name="MCP_TEST_FLT_W1", **panel),
            PanelInput(start_point=PointInput(x=93000, y=0, z=0), end_point=PointInput(x=95000, y=0, z=0), profile="2000*150", tekla_class=1, name="MCP_TEST_FLT_W2", **panel),
            PanelInput(start_point=PointInput(x=96000, y=0, z=0), end_point=PointInput(x=98000, y=0, z=0), profile="3000*200", tekla_class=8, name="MCP_TEST_FLT_SW", **panel),
            PanelInput(start_point=PointInput(x=99000, y=0, z=0), end_point=PointInput(x=101000, y=0, z=0), profile="2000*150", tekla_class=1, name="MCP_TEST_FLT LIGHT BLOCK", **panel),
        ]
    ).structured_content["results"]
    beam_result = place_beams(
        beams=[BeamInput(start_point=PointInput(x=91000, y=-500, z=1500), end_point=PointInput(x=91000, y=500, z=1500), profile="400*400", tekla_class=14, name="MCP_TEST_FLT_BEAM", **panel)]
    ).structured_content["results"]
    plate_result = place_slabs(
        slabs=[
            SlabInput(
                points=[PointInput(x=x, y=y, z=0) for x, y in [(103000, 0), (106000, 0), (106000, 3000), (103000, 3000)]],
                profile="200",
                tekla_class=4,
                name="MCP_TEST_FLT_PLATE",
                **panel,
            )
        ]
    ).structured_content["results"]
    w1, w2, sw, light = model.get_objects_by_guid([r["guid"] for r in placed])
    beam = model.get_objects_by_guid([beam_result[0]["guid"]])[0]
    plate = model.get_objects_by_guid([plate_result[0]["guid"]])[0]
    objects: dict[str, Any] = {"W1": w1, "W2": w2, "SW": sw, "LIGHT": light, "BEAM": beam, "PLATE": plate}

    w1.SetUserProperty("comment", "MCP_TEST_UDA_VALUE")
    w1.Modify()

    rebar_item = get_all_rebar_items()[0]
    for key, father, rebar_class, x in [("BAR_A", w1, 44, 90000), ("BAR_B", w2, 46, 93000)]:
        bar = SingleRebar()
        bar.Father = father
        bar.Name = f"MCP_TEST_FLT_{key}"
        bar.Class = rebar_class
        bar.Grade = rebar_item["grade"]
        bar.Size = rebar_item["size"]
        polygon = Polygon()
        polygon.Points.Add(Point(x + 200, 0, 500))
        polygon.Points.Add(Point(x + 1800, 0, 500))
        bar.Polygon = polygon
        assert bar.Insert(), f"Rebar {key} was not inserted"
        objects[key] = bar

    bolt_items = CatalogHandler().GetBoltItems()
    assert bolt_items.MoveNext(), "The bolt catalog is empty"
    bolt = BoltArray()
    bolt.PartToBoltTo = w1
    bolt.PartToBeBolted = beam
    bolt.FirstPosition = Point(91000, -300, 1500)
    bolt.SecondPosition = Point(91000, 300, 1500)
    bolt.BoltStandard = bolt_items.Current.Standard
    bolt.BoltSize = bolt_items.Current.Size
    bolt.Tolerance = 3.0
    bolt.BoltType = BoltGroup.BoltTypeEnum.BOLT_TYPE_SITE
    bolt.AddBoltDistX(0)
    bolt.AddBoltDistY(0)
    assert bolt.Insert(), "Bolt group was not inserted"
    objects["BOLT"] = bolt

    for key, main, secondary, shop, weld_type in [("WELD_SHOP", w1, beam, True, BaseWeld.WeldTypeEnum.WELD_TYPE_FILLET), ("WELD_SITE", w2, sw, False, BaseWeld.WeldTypeEnum.WELD_TYPE_PLUG)]:
        weld = Weld()
        weld.MainObject = main
        weld.SecondaryObject = secondary
        weld.ShopWeld = shop
        weld.TypeAbove = weld_type
        weld.SizeAbove = 6
        assert weld.Insert(), f"Weld {key} was not inserted"
        objects[key] = weld
    model.commit_changes()

    TeklaModel.select_objects([plate])
    assert put_components(component_name="MeshBars").structured_content["status"] == "success"
    reinforcements = plate.GetReinforcements()
    while reinforcements.MoveNext():
        component = reinforcements.Current.GetFatherComponent()
        if component is not None:
            objects["COMPONENT"] = component
            break

    # The shop weld joins the beam to the first wall's assembly, so assemblies are read after welding
    for key in ("W1", "W2", "SW", "LIGHT", "PLATE"):
        objects[f"ASM_{key}"] = objects[key].GetAssembly()

    ids = {key: o.Identifier.ID for key, o in objects.items()}
    yield {"objects": objects, "ids": ids, "names": {v: k for k, v in ids.items()}}

    for key in ("COMPONENT", "WELD_SHOP", "WELD_SITE", "BOLT", "BAR_A", "BAR_B", "BEAM", "W1", "W2", "SW", "LIGHT", "PLATE"):
        if key in objects:
            objects[key].Delete()
    model.commit_changes()


def _pick(scene: dict, tree: dict, object_types: list[str] | None = None) -> set[str]:
    """
    Select with a tree scoped to the scene and return the keys of the selected scene objects.

    Args:
        scene: The `filter_scene` fixture
        tree: Filter tree as a plain dict
        object_types: Object types, 'part' when omitted

    Returns:
        Keys of the selected objects. Anything selected outside the scene fails the test
    """
    scope = _cond("object.id_number", "Is Equal", sorted(scene["ids"].values()))
    result = select_elements_by_filter(filter={"all": [scope, tree]}, object_types=object_types or ["part"])
    assert result.structured_content["status"] in ("success", "warning"), result.structured_content
    if not result.structured_content["selected_count"]:
        return set()
    selected = {o.Identifier.ID for o in TeklaModel().get_selected_objects()}
    assert selected <= set(scene["names"]), f"Selected objects outside the scene: {selected - set(scene['names'])}"
    assert len(selected) == result.structured_content["selected_count"]
    return {scene["names"][i] for i in selected}


@pytest.mark.parametrize(
    "tree,object_types,expected",
    [
        # Plain fields, lists, quoting and wildcards
        (_cond("part.class", "Is Equal", [1, 8]), None, {"W1", "W2", "SW", "LIGHT"}),
        (_cond("part.class", "Is Not Equal", [1, 8]), None, {"BEAM", "PLATE"}),
        (_cond("part.name", "Is Equal", "MCP_TEST_FLT LIGHT BLOCK"), None, {"LIGHT"}),
        (_cond("part.name", "Is Equal", ["MCP_TEST_FLT LIGHT BLOCK", "MCP_TEST_FLT_W2"]), None, {"LIGHT", "W2"}),
        (_cond("part.name", "Is Equal", "MCP_TEST_FLT_W?"), None, {"W1", "W2"}),
        (_cond("part.name", "Contains", "LIGHT"), None, {"LIGHT"}),
        (_cond("part.profile", "Is Equal", ["3000*200", "400*400"]), None, {"W1", "SW", "BEAM"}),
        # Element types
        (_cond("part.element_type", "Is Equal", "Wall"), None, {"W1", "W2", "LIGHT"}),
        (_cond("part.element_type", "Is Equal", ["Wall", "Sandwich Wall"]), None, {"W1", "W2", "SW", "LIGHT"}),
        (_cond("part.element_type", "Is Not Equal", "Wall"), None, {"SW", "BEAM", "PLATE"}),
        (_cond("part.element_type", "Is Equal", "sandwich wall"), None, {"SW"}),
        (_cond("part.element_type", "Is Equal", ["CONCRETE_WALL", "concrete_sandwich_wall"]), None, {"W1", "W2", "SW", "LIGHT"}),
        # Nested groups up to Tekla's bracket limit
        ({"any": [{"all": [_cond("part.class", "Is Equal", 1), _cond("part.profile", "Is Equal", "3000*200")]}, _cond("part.class", "Is Equal", 14)]}, None, {"W1", "BEAM"}),
        (
            {
                "all": [
                    _cond("part.class", "Is Equal", 1),
                    {"any": [_cond("part.profile", "Is Equal", "2000*150"), {"all": [_cond("part.name", "Ends With", "W1"), _cond("part.profile", "Is Equal", "3000*200")]}]},
                ]
            },
            None,
            {"W1", "W2", "LIGHT"},
        ),
        # Rebars
        (_cond("rebar.class", "Is Equal", 44), ["rebar"], {"BAR_A"}),
        (_cond("rebar.class", "Is Not Equal", 44), ["rebar"], {"BAR_B"}),
        (_cond("rebar.name", "Is Equal", ["MCP_TEST_FLT_BAR_A", "MCP_TEST_FLT_BAR_B"]), ["rebar"], {"BAR_A", "BAR_B"}),
        # Several object types: each type is filtered by its own conditions only
        ({"all": [_cond("rebar.class", "Is Equal", 46), _cond("part.class", "Is Equal", 8)]}, ["rebar", "part"], {"BAR_B", "SW"}),
        ({"any": [_cond("part.name", "Is Equal", "MCP_TEST_FLT_W1"), _cond("bolt.site_workshop", "Is Equal", "site")]}, ["part", "bolt"], {"W1", "BOLT"}),
        (_cond("part.class", "Is Equal", 8), ["part", "bolt"], {"SW", "BOLT"}),
        ({"any": [_cond("object.type", "Is Equal", "weld"), _cond("part.class", "Is Equal", 14)]}, ["part", "weld"], {"WELD_SHOP", "WELD_SITE", "BEAM"}),
        (_cond("object.type", "Is Not Equal", "part"), ["part", "weld"], {"WELD_SHOP", "WELD_SITE"}),
        (_cond("object.type", "Is Equal", ["part", "weld"]), ["part", "bolt", "weld"], {"W1", "W2", "SW", "LIGHT", "BEAM", "PLATE", "WELD_SHOP", "WELD_SITE"}),
        # Welds and bolts with readable values
        (_cond("weld.welding_site", "Is Equal", "workshop"), ["weld"], {"WELD_SHOP"}),
        (_cond("weld.welding_site", "Is Equal", "site"), ["weld"], {"WELD_SITE"}),
        (_cond("weld.type_above", "Is Equal", "fillet"), ["weld"], {"WELD_SHOP"}),
        (_cond("weld.type_above", "Is Equal", ["fillet", "plug"]), ["weld"], {"WELD_SHOP", "WELD_SITE"}),
        (_cond("bolt.site_workshop", "Is Equal", "workshop"), ["bolt"], set()),
        # Report properties, UDAs and assembly conditions
        (_attr("MAINPART.CLASS_ATTR", "Is Equal", 8, "template"), ["assembly"], {"ASM_SW"}),
        (_attr("CLASS_ATTR", "Is Equal", [8, 14], "template"), None, {"SW", "BEAM"}),
        (_attr("comment", "Is Equal", "MCP_TEST_UDA_VALUE"), None, {"W1"}),
        (_attr("COMMENT", "Is Equal", "MCP_TEST_UDA_VALUE"), None, set()),
        # Components
        (_cond("component.name", "Is Equal", "MeshBars"), ["component"], {"COMPONENT"}),
        (_cond("component.name", "Is Equal", "MCP_TEST_NO_SUCH_COMPONENT"), ["component"], set()),
        # Heavy combinations: an 'any' over four object types, one condition each
        (
            {
                "any": [
                    _cond("part.name", "Is Equal", "MCP_TEST_FLT LIGHT BLOCK"),
                    _cond("rebar.class", "Is Equal", 44),
                    _cond("bolt.site_workshop", "Is Equal", "site"),
                    _cond("weld.type_above", "Is Equal", "plug"),
                ]
            },
            ["part", "rebar", "bolt", "weld"],
            {"LIGHT", "BAR_A", "BOLT", "WELD_SITE"},
        ),
        # Negative operators inside a nested group
        (
            {"all": [_cond("part.name", "Not Contains", "LIGHT"), {"any": [_cond("part.profile", "Is Not Equal", "3000*200"), _cond("part.class", "Is Not Equal", [1, 4])]}]},
            None,
            {"W2", "SW", "BEAM", "PLATE"},
        ),
        # Lists of wildcards in a group, one of them quoted because of its space
        ({"any": [_cond("part.name", "Is Equal", ["MCP_TEST_FLT_W?", "MCP_TEST_FLT LIGHT*"]), _cond("part.profile", "Is Equal", ["400*4??"])]}, None, {"W1", "W2", "LIGHT", "BEAM"}),
        # An object type excluded, and per type conditions in an 'any'
        (
            {"all": [_cond("object.type", "Is Not Equal", "weld"), {"any": [_cond("part.class", "Is Equal", 8), _cond("rebar.class", "Is Not Equal", 44)]}]},
            ["part", "rebar", "weld"],
            {"SW", "BAR_B"},
        ),
        # Report properties of assemblies, nested
        (
            {
                "any": [
                    _attr("MAINPART.CLASS_ATTR", "Is Equal", 8, "template"),
                    {"all": [_attr("MAINPART.CLASS_ATTR", "Is Equal", 1, "template"), _attr("MAINPART.PROFILE", "Is Equal", "2000*150", "template")]},
                ]
            },
            ["assembly"],
            {"ASM_SW", "ASM_W2", "ASM_LIGHT"},
        ),
        # Conditions of one type do not touch the others: bolts have none, so all bolts match
        ({"all": [_cond("part.class", "Is Equal", 1), _cond("weld.welding_site", "Is Equal", "workshop")]}, ["part", "bolt", "weld"], {"W1", "W2", "LIGHT", "BOLT", "WELD_SHOP"}),
        # A component and parts in one 'any'
        ({"any": [_cond("component.name", "Is Equal", "MeshBars"), _cond("part.class", "Is Equal", 4)]}, ["component", "part"], {"COMPONENT", "PLATE"}),
    ],
)
def test_select_elements_by_filter_scene(filter_scene, tree, object_types, expected):
    """Tests that a filter tree selects exactly the expected scene objects."""
    if any(key not in filter_scene["ids"] for key in expected):
        pytest.skip(f"Scene objects missing: {sorted(k for k in expected if k not in filter_scene['ids'])}")
    assert _pick(filter_scene, tree, object_types) == expected


def test_select_elements_by_filter_assembly_condition_applies_to_parts(filter_scene):
    """Tests that an assembly condition selects the parts of the matching assembly."""
    assembly = filter_scene["objects"]["ASM_W1"]
    assembly_parts = {filter_scene["names"][p.Identifier.ID] for p in [assembly.GetMainPart(), *assembly.GetSecondaries()] if p.Identifier.ID in filter_scene["names"]}
    assert _pick(filter_scene, _cond("assembly.name", "Is Equal", assembly.Name)) >= {"W1"}
    assert _pick(filter_scene, _cond("assembly.name", "Is Equal", assembly.Name)) == assembly_parts


def test_select_elements_by_filter_field_uda_report_property_and_assembly(filter_scene):
    """Tests one tree that mixes a field, a UDA, a report property and an assembly condition."""
    tree = {
        "all": [
            _cond("part.class", "Is Equal", [1, 14]),
            _cond("assembly.name", "Is Equal", filter_scene["objects"]["ASM_W1"].Name),
            {"any": [_attr("comment", "Is Equal", "MCP_TEST_UDA_VALUE"), _attr("CLASS_ATTR", "Is Equal", 14, "template")]},
        ]
    }
    # The shop weld puts the beam into the first wall's assembly
    assert _pick(filter_scene, tree) == {"W1", "BEAM"}


def test_select_elements_by_filter_matches_tekla_named_filter_semantics(filter_scene):
    """Tests that a mixed AND chain keeps the parts and rebars Tekla would keep."""
    tree = {"all": [_cond("rebar.class", "Is Equal", [44, 46]), _cond("part.class", "Is Not Equal", [8, 14, 4])]}
    assert _pick(filter_scene, tree, ["rebar", "part"]) == {"BAR_A", "BAR_B", "W1", "W2", "LIGHT"}


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"filter": {"all": []}}, "at least one item"),
        ({"filter": {"or": [_cond("part.class", "Is Equal", 1)]}}, "Extra inputs"),
        ({"filter": _cond("part.class", "Is Equal", 1), "object_types": []}, "At least one object type"),
        ({"filter": _cond("part.class", "Is Equal", 1), "object_types": ["beam"]}, "Unknown object types"),
        ({"filter": _cond("bolt.site_workshop", "Is Equal", "factory"), "object_types": ["bolt"]}, "Must be one of"),
        ({"filter": _cond("part.class", "Contains", 1)}, "does not apply"),
        ({"filter": _cond("part.nope", "Is Equal", 1)}, "Unknown field"),
        ({"filter": _cond("part.element_type", "Is Equal", "FakeWall")}, "Invalid element_type"),
        ({"filter": _cond("object.type", "Is Equal", "bolt")}, "can match this filter"),
        # Alternating 'all' and 'any' three times deep: every 'any' inside an 'all' needs brackets
        (
            {
                "filter": {
                    "all": [
                        _cond("part.class", "Is Equal", 1),
                        {
                            "any": [
                                _cond("part.class", "Is Equal", 2),
                                {
                                    "all": [
                                        _cond("part.name", "Is Equal", "A"),
                                        {
                                            "any": [
                                                _cond("part.name", "Is Equal", "B"),
                                                {"all": [_cond("part.name", "Is Equal", "C"), {"any": [_cond("part.class", "Is Equal", 3), _cond("part.class", "Is Equal", 4)]}]},
                                            ]
                                        },
                                    ]
                                },
                            ]
                        },
                    ]
                }
            },
            "nests 4 levels",
        ),
    ],
)
def test_select_elements_by_filter_invalid_input_returns_error(kwargs, message):
    """Tests invalid trees, object types, values, operators, fields and too deep nesting."""
    result = select_elements_by_filter(**kwargs)
    assert result.structured_content["status"] == "error"
    assert message in result.structured_content["message"]


@pytest.fixture
def filter_files() -> Any:
    """Collect the paths of filter files a test writes and delete them afterwards."""
    paths: list[Path] = []
    yield paths
    for path in paths:
        path.unlink(missing_ok=True)
    refresh_attribute_files()


def _scoped(scene: dict, tree: dict) -> dict:
    """Scope a tree to the scene's object IDs."""
    return {"all": [_cond("object.id_number", "Is Equal", sorted(scene["ids"].values())), tree]}


def _selected_keys(scene: dict, count: int) -> set[str]:
    """Return the keys of the selected scene objects, failing on anything outside the scene."""
    if not count:
        return set()
    selected = {o.Identifier.ID for o in TeklaModel().get_selected_objects()}
    assert selected <= set(scene["names"]), f"Selected objects outside the scene: {selected - set(scene['names'])}"
    return {scene["names"][i] for i in selected}


MIXED_TREE = {
    "any": [
        _cond("part.name", "Is Equal", "MCP_TEST_FLT LIGHT BLOCK"),
        {"all": [_cond("part.class", "Is Equal", 1), _cond("part.profile", "Is Equal", "3000*200")]},
        _cond("rebar.class", "Is Equal", 44),
        _cond("bolt.site_workshop", "Is Equal", "site"),
        _cond("weld.type_above", "Is Equal", "plug"),
    ]
}
MIXED_TYPES = ["part", "rebar", "bolt", "weld"]
MIXED_EXPECTED = {"LIGHT", "W1", "BAR_A", "BOLT", "WELD_SITE"}


def test_create_filter_selection_matches_the_tree(filter_scene, filter_files):
    """Tests that a saved selection filter selects exactly what the tree selects."""
    tree = _scoped(filter_scene, MIXED_TREE)
    result = create_filter(filter_name="MCP_TEST_FLT_SEL", filter_type="selection", filter=tree, object_types=MIXED_TYPES)
    content = result.structured_content
    filter_files.append(Path(content.get("path", "")))
    assert content["status"] == "success", content
    assert (content["filter_name"], content["filter_type"], content["overwritten"]) == ("MCP_TEST_FLT_SEL", "selection", False)
    assert Path(content["path"]).name == "MCP_TEST_FLT_SEL.SObjGrp"
    assert content["matching_objects"] == len(MIXED_EXPECTED)

    # The cached filter list sees the new file at once
    assert "MCP_TEST_FLT_SEL" in get_available_attribute_files(".SObjGrp")

    # Tekla evaluates the saved file the same way as the tree
    by_name = select_elements_by_filter_name(filter_name="MCP_TEST_FLT_SEL").structured_content
    assert _selected_keys(filter_scene, by_name["selected_count"]) == MIXED_EXPECTED
    by_tree = select_elements_by_filter(filter=tree, object_types=MIXED_TYPES).structured_content
    assert _selected_keys(filter_scene, by_tree["selected_count"]) == MIXED_EXPECTED


def test_create_filter_refuses_to_overwrite_unless_asked(filter_scene, filter_files):
    """Tests that an existing filter is kept unless `overwrite` is set, and replaced when it is."""
    first = create_filter(filter_name="MCP_TEST_FLT_OVERWRITE", filter_type="selection", filter=_scoped(filter_scene, _cond("part.class", "Is Equal", 8)))
    path = Path(first.structured_content["path"])
    filter_files.append(path)
    original = path.read_bytes()

    refused = create_filter(filter_name="MCP_TEST_FLT_OVERWRITE", filter_type="selection", filter=_scoped(filter_scene, _cond("part.class", "Is Equal", 14)))
    assert refused.structured_content["status"] == "error"
    assert "already exists" in refused.structured_content["message"]
    assert path.read_bytes() == original

    replaced = create_filter(filter_name="MCP_TEST_FLT_OVERWRITE.SObjGrp", filter_type="selection", filter=_scoped(filter_scene, _cond("part.class", "Is Equal", 14)), overwrite=True)
    assert replaced.structured_content["status"] == "success", replaced.structured_content
    assert replaced.structured_content["overwritten"] is True
    assert path.read_bytes() != original
    by_name = select_elements_by_filter_name(filter_name="MCP_TEST_FLT_OVERWRITE").structured_content
    assert _selected_keys(filter_scene, by_name["selected_count"]) == {"BEAM"}


def test_create_filter_with_a_real_style_name(filter_scene, filter_files):
    """Tests a name with '#', brackets, '~', '+' and spaces, like the model's own filters."""
    name = "#MCP_TEST_FLT [COLD BENDED] ~x+y"
    content = create_filter(filter_name=name, filter_type="selection", filter=_scoped(filter_scene, _cond("part.class", "Is Equal", 8))).structured_content
    filter_files.append(Path(content.get("path", "")))
    assert content["status"] == "success", content
    assert Path(content["path"]).name == f"{name}.SObjGrp"
    assert name in get_available_attribute_files(".SObjGrp")
    by_name = select_elements_by_filter_name(filter_name=name).structured_content
    assert _selected_keys(filter_scene, by_name["selected_count"]) == {"SW"}


def test_create_filter_overwrite_leaves_no_temporary_file(filter_scene, filter_files):
    """Tests that replacing a filter goes through a temporary file that is gone afterwards."""
    attributes = Path(TeklaModel().model_path) / "attributes"
    for value in (8, 14):
        content = create_filter(filter_name="MCP_TEST_FLT_TEMP", filter_type="view", filter=_scoped(filter_scene, _cond("part.class", "Is Equal", value)), overwrite=True).structured_content
        assert content["status"] == "success", content
    filter_files.append(Path(content["path"]))
    assert content["overwritten"] is True
    assert not list(attributes.glob("~mcp_tmp_*"))


def test_create_filter_view_has_the_selection_rows(filter_scene, filter_files):
    """Tests that a view filter holds the same rows as a selection filter of the same tree and selects the same objects."""
    tree = _scoped(filter_scene, MIXED_TREE)
    view = create_filter(filter_name="MCP_TEST_FLT_VIEW", filter_type="view", filter=tree, object_types=MIXED_TYPES).structured_content
    view_path = Path(view["path"])
    filter_files.append(view_path)
    assert view["status"] == "success", view
    assert view_path.name == "MCP_TEST_FLT_VIEW.VObjGrp"
    assert "MCP_TEST_FLT_VIEW" in get_available_attribute_files(".VObjGrp")

    selection = create_filter(filter_name="MCP_TEST_FLT_VIEW_AS_SEL", filter_type="selection", filter=tree, object_types=MIXED_TYPES).structured_content
    filter_files.append(Path(selection["path"]))
    assert view_path.read_bytes() == Path(selection["path"]).read_bytes()

    # Tekla cannot select by a view filter name, so evaluate the view file through a selection copy
    copy = view_path.with_name("MCP_TEST_FLT_VIEW_COPY.SObjGrp")
    copy.write_bytes(view_path.read_bytes())
    filter_files.append(copy)
    by_name = select_elements_by_filter_name(filter_name=copy.stem).structured_content
    assert _selected_keys(filter_scene, by_name["selected_count"]) == MIXED_EXPECTED


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"filter_name": "MCP_TEST/BAD"}, "without folders or a drive"),
        ({"filter_name": "  "}, "must not be empty"),
        ({"filter_name": "C:MCP_TEST_FLT_BAD"}, "without folders or a drive"),
        ({"filter_name": "MCP_TEST_FLT?BAD"}, "Tekla could not write the filter 'MCP_TEST_FLT?BAD'"),
        ({"filter_name": "MCP_TEST_FLT_BAD", "filter": _cond("part.nope", "Is Equal", 1)}, "Unknown field"),
        ({"filter_name": "MCP_TEST_FLT_BAD", "object_types": ["beam"]}, "Unknown object types"),
    ],
)
def test_create_filter_invalid_input_writes_nothing(kwargs, message):
    """Tests that invalid input is an error and leaves no file behind."""
    arguments = {"filter_type": "selection", "filter": _cond("part.class", "Is Equal", 1), **kwargs}
    result = create_filter(**arguments)
    assert result.structured_content["status"] == "error"
    assert message in result.structured_content["message"]
    assert not (Path(TeklaModel().model_path) / "attributes" / "MCP_TEST_FLT_BAD.SObjGrp").exists()


def test_select_elements_by_guid(model_objects):
    """Tests select_elements_by_guid function."""
    result = select_elements_by_guid(guids=[""])
    assert result.structured_content["status"] == "error"

    # Nothing found clears the previous selection so no later tool acts on it
    TeklaModel.select_objects([model_objects["test_wall1"]])
    nonexistent = "mcp_test_wall2"
    result = select_elements_by_guid(guids=[nonexistent])
    assert result.structured_content["status"] == "error"
    assert nonexistent in result.structured_content["message"]
    with pytest.raises(ValueError):
        TeklaModel().get_selected_objects()

    wall2_guid = model_objects["test_wall2"].Identifier.GUID.ToString()
    result = select_elements_by_guid(guids=[wall2_guid])
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["selected_guids"] == [wall2_guid]
    assert result.structured_content["missing_guids"] == []

    wall1_guid = model_objects["test_wall1"].Identifier.GUID.ToString()
    result = select_elements_by_guid(guids=[wall1_guid, wall2_guid])
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 2
    assert set(result.structured_content["selected_guids"]) == {wall1_guid, wall2_guid}
    assert result.structured_content["missing_guids"] == []

    # partial: one valid, one not found
    result = select_elements_by_guid(guids=[wall1_guid, nonexistent])
    assert result.structured_content["status"] == "partial"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["selected_guids"] == [wall1_guid]
    assert result.structured_content["missing_guids"] == [nonexistent]

    # Spelling variants of one GUID select it once and are reported in normalized form
    result = select_elements_by_guid(guids=[wall1_guid, f" {{{wall1_guid.upper()}}} "])
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == 1
    assert result.structured_content["selected_guids"] == [wall1_guid]


@pytest.mark.parametrize(
    "mode,mode_key,expected_count",
    [("Assembly", "selected_assemblies_count", 2), ("Main Part", "selected_main_parts_count", 2), ("Parts", "selected_parts_count", 2)],
)
def test_select_elements_assemblies(model_objects, mode, mode_key, expected_count):
    """Tests select_related_elements function."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = select_related_elements(mode=mode)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_count"] == expected_count
    assert result.structured_content[mode_key] == expected_count


def test_select_elements_parts_from_assembly(model_objects):
    """Tests 'Parts' mode: a selected assembly is replaced by its parts."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    select_related_elements(mode="Assembly")
    result = select_related_elements(mode="Parts")
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_parts_count"] == 1
