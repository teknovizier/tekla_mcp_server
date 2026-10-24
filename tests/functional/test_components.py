"""
Functional tests for components_provider.

Tests component placement, removal, modification, and retrieval operations.

The attribute tests at the end guard the pythonnet type traps behind `get_components`
and `modify_components`: the .NET overload is picked from the Python value type, a
component ignores an attribute stored with the wrong type, and a Python int placeholder
reads the double overload. Each of them works on its own fresh wall.
"""

from typing import Any

import pytest

from tekla_mcp_server.config import get_config
from tekla_mcp_server.models import PanelInput, PointInput
from tekla_mcp_server.providers.components_provider import put_components, remove_components, get_components, modify_components, explode_components
from tekla_mcp_server.providers.modeling_provider import place_panels
from tekla_mcp_server.tekla.loader import Int32
from tekla_mcp_server.tekla.wrappers.model import TeklaModel

# Components with an attribute schema
SCHEMA_COMPONENTS = ["MeshBars", "Edge and Corner"]

# (schema type, value sent to `modify_components`, value the component must store and report).
# Non-ASCII text is left out: Tekla folds it to ASCII ('Å' -> 'A') on its own. Empty text is left out: Tekla drops the attribute
VALUE_CASES = [
    ("int", 0, 0),
    ("int", 1, 1),
    ("int", 2, 2),
    ("int", 7, 7),
    ("int", 999, 999),
    ("int", -1, -1),
    ("int", "3", 3),
    ("int", 4.0, 4),
    ("int", True, 1),
    ("float", 0.0, 0.0),
    ("float", 1.5, 1.5),
    ("float", 12.5, 12.5),
    ("float", 300.0, 300.0),
    ("float", 1234.567, 1234.567),
    ("float", -50.25, -50.25),
    ("float", 300, 300.0),
    ("float", "2.5", 2.5),
    ("str", "16", "16"),
    ("str", "B500B", "B500B"),
    ("str", "MCP TEST 1", "MCP TEST 1"),
    ("str", 12, "12"),
]


def test_put_lifting_anchors_walls(model_objects):
    """Tests put_components for lifting anchors on standard walls."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = put_components(component_name="Lifting Anchor")
    assert result.structured_content["status"] == "success"


def test_put_lifting_anchors_sandwich(model_objects):
    """Tests put_components for lifting anchors on sandwich walls."""
    TeklaModel.select_objects([model_objects["test_sw1"]])
    result = put_components(component_name="Lifting Anchor")
    assert result.structured_content["status"] == "success"


def test_remove_lifting_anchors(model_objects):
    """Tests remove_components for lifting anchors."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    put_components(component_name="Lifting Anchor")
    result = remove_components(component_names=["Lifting Anchor"])
    assert result.structured_content["status"] == "success"


def test_put_components_invalid_component(model_objects):
    """Tests put_components with an invalid component name, no work done."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = put_components(component_name="NonExistentComponent")
    assert result.structured_content["status"] == "warning"


def test_put_components_with_custom_properties(model_objects):
    """Tests put_components for Mesh Bars with custom properties."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    result = put_components(component_name="MeshBars", custom_properties={"TopAsBott": "0"})
    assert result.structured_content["status"] == "success"


def test_remove_components(model_objects):
    """Tests remove_components function."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    # Start clean: earlier tests in this module leave MeshBars on this wall
    remove_components(component_names=["MeshBars"])
    put_components(component_name="MeshBars")
    result = remove_components(component_names=["meshbars"])
    assert result.structured_content["status"] == "success"
    assert result.structured_content["removed"] == {"MeshBars": 1}
    assert result.structured_content["not_found"] == []


def test_remove_components_several_names(model_objects):
    """Several names in one call: found ones are removed, missing ones are reported, status is partial."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    remove_components(component_names=["MeshBars"])
    put_components(component_name="MeshBars")
    result = remove_components(component_names=["MeshBars", "NonExistentComponent"])
    assert result.structured_content["status"] == "partial"
    assert result.structured_content["removed"] == {"MeshBars": 1}
    assert result.structured_content["not_found"] == ["NonExistentComponent"]


def test_get_components_returns_components(model_objects):
    """Tests get_components returns component info for elements with components."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    put_components(component_name="MeshBars")
    result = get_components()
    assert result.structured_content["status"] == "success"
    assert result.structured_content["total_elements"] == 1
    assert result.structured_content["total_components"] >= 1
    # Earlier tests may leave other components on this wall
    comp = next(c for c in result.structured_content["elements"][0]["components"] if c["name"] == "MeshBars")
    assert comp["supported"] is True
    assert comp["config_key"] == "mesh_bars"
    assert "schema" not in comp
    assert result.structured_content["schemas"]["mesh_bars"]


def test_get_components_empty_selection(model_objects):
    """Tests get_components with no elements selected."""
    TeklaModel.select_objects([])
    result = get_components()
    assert result.structured_content["status"] == "error"


def test_get_components_supported_component(model_objects):
    """Tests get_components marks supported components correctly."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    put_components(component_name="MeshBars")
    result = get_components()
    assert result.structured_content["status"] == "success"
    assert result.structured_content["total_components"] >= 1
    comp_names = [c["name"] for c in result.structured_content["elements"][0]["components"]]
    if "MeshBars" in comp_names:
        comp = next(c for c in result.structured_content["elements"][0]["components"] if c["name"] == "MeshBars")
        assert comp["supported"] is True
        assert comp["config_key"] == "mesh_bars"
        assert result.structured_content["schemas"]["mesh_bars"]


def test_modify_components_success(model_objects):
    """Tests modify_components modifies attributes on existing components."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    # Start clean so the instance read back below is the only, modified one
    remove_components(component_names=["MeshBars"])
    put_components(component_name="MeshBars")
    result = modify_components(
        component_name="MeshBars",
        custom_properties={"TopAsBott": 1, "NumberBarsBottSec": 4, "SpacBarsBottSec": 300.0, "BottDiaSec": "12"},
    )
    assert result.structured_content["status"] == "success"
    assert result.structured_content["processed_components_count"] >= 1

    result = get_components()
    comp = next(c for c in result.structured_content["elements"][0]["components"] if c["name"] == "MeshBars")
    print(comp["attributes"])
    assert comp["attributes"]["TopAsBott"] == 1
    assert comp["attributes"]["NumberBarsBottSec"] == 4
    assert comp["attributes"]["SpacBarsBottSec"] == 300.0
    assert comp["attributes"]["BottDiaSec"] == "12"


def test_modify_components_no_matching_component(model_objects):
    """Tests modify_components returns warning when component not found, no work done."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    result = modify_components(
        component_name="NonExistingComponent",
        custom_properties={"RecessLength": 200.0},
    )
    assert result.structured_content["status"] == "warning"
    assert result.structured_content["processed_components_count"] == 0
    assert "commit_success" not in result.structured_content


def test_modify_components_invalid_properties(model_objects):
    """Tests modify_components returns error for invalid property names."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    put_components(component_name="MeshBars")
    result = modify_components(
        component_name="MeshBars",
        custom_properties={"NonExistentProperty": 123},
    )
    assert result.structured_content["status"] == "error"


def test_put_components_no_selection():
    """No selection: put_components returns an error."""
    TeklaModel.clear_selection()
    result = put_components(component_name="MeshBars")
    assert result.structured_content["status"] == "error"


def test_explode_components(model_objects):
    """Exploded component is gone from the element and is reported per name."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    remove_components(component_names=["MeshBars"])
    put_components(component_name="MeshBars")
    result = explode_components(component_names=["meshbars"])
    assert result.structured_content["status"] == "success"
    assert result.structured_content["exploded"] == {"MeshBars": 1}
    assert result.structured_content["not_found"] == []

    components = get_components().structured_content["elements"][0]["components"]
    assert "MeshBars" not in [c["name"] for c in components]


def test_explode_components_no_matching(model_objects):
    """No matching component: nothing is exploded, status is warning, no commit attempted."""
    TeklaModel.select_objects([model_objects["test_wall6"]])
    result = explode_components(component_names=["NonExistentComponent"])
    assert result.structured_content["status"] == "warning"
    assert result.structured_content["exploded"] == {}
    assert result.structured_content["not_found"] == ["NonExistentComponent"]
    assert "commit_success" not in result.structured_content


def test_remove_components_no_matching(model_objects):
    """Selected element with no matching component: nothing is removed, status is warning, no commit attempted."""
    TeklaModel.select_objects([model_objects["test_wall6"]])
    result = remove_components(component_names=["MeshBars"])
    assert result.structured_content["status"] == "warning"
    assert result.structured_content["removed"] == {}
    assert result.structured_content["not_found"] == ["MeshBars"]
    assert "commit_success" not in result.structured_content


@pytest.fixture
def wall():
    """A fresh wall far from the shared test objects, deleted after the test."""
    model = TeklaModel()
    res = place_panels(
        panels=[
            PanelInput(
                start_point=PointInput(x=180000, y=0, z=0), end_point=PointInput(x=182000, y=0, z=0), profile="3000*200", material="Concrete_Undefined", tekla_class=1, name="MCP_TEST_ATTR_WALL"
            )
        ]
    )
    guid = res.structured_content["results"][0]["guid"]
    yield model.get_object_by_guid(guid)
    obj = model.get_object_by_guid(guid)
    if obj is not None:
        obj.Delete()
        model.commit_changes()


def _schema(name: str) -> dict[str, Any]:
    return get_config().get_component_by_tekla_name(name)["custom_properties"]


def _insert(wall: Any, name: str) -> Any:
    """Insert the component with its standard settings and return the raw .NET component."""
    TeklaModel.select_objects([wall])
    assert put_components(component_name=name).structured_content["status"] == "success"
    fresh = TeklaModel().get_object_by_guid(wall.Identifier.GUID.ToString())
    return next(c for c in fresh.GetComponents() if c.Name == name)


def _reported(wall: Any, name: str) -> dict[str, Any]:
    """Attributes of the single `name` component as `get_components` reports them."""
    TeklaModel.select_objects([wall])
    comps = [c for c in get_components().structured_content["elements"][0]["components"] if c["name"] == name]
    assert len(comps) == 1
    return comps[0]["attributes"]


def _stored(comp: Any, key: str, declared: str) -> tuple[bool, Any]:
    """What the component really stores for `key`, as the declared type. (False, None) when not stored."""
    ok, value = comp.GetAttribute(key, {"int": Int32(0), "float": 0.0, "str": ""}[declared])
    if ok:
        return True, value
    if declared == "int":
        ok, text = comp.GetAttribute(key, "")
        if ok and text.strip().lstrip("-").isdigit():
            return True, int(text)
    return False, None


def _distinct(declared: str, current: Any) -> Any:
    """A value of the declared type that differs from the current one."""
    if declared == "int":
        return 1 if current in (None, 0) else 0
    if declared == "float":
        return round((current or 0.0) + 12.5, 1)
    if isinstance(current, str) and current.lstrip("-").isdigit():
        return str(int(current) + 1)
    return "MCP_TEST" if current != "MCP_TEST" else "MCP_TEST2"


@pytest.mark.parametrize("name", SCHEMA_COMPONENTS)
def test_fresh_component_reads_stored_values(wall, name):
    """`get_components` reports exactly what a freshly inserted component stores, with the schema type."""
    comp = _insert(wall, name)
    reported = _reported(wall, name)
    wrong = {}
    for key, prop in _schema(name).items():
        is_stored, value = _stored(comp, key, prop.get("type", "str"))
        if is_stored and (reported[key] != value or type(reported[key]) is not type(value)):
            wrong[key] = (value, reported[key])
    assert not wrong, f"stored vs reported: {wrong}"


@pytest.mark.parametrize("name", SCHEMA_COMPONENTS)
def test_stored_attributes_match_schema_types(wall, name):
    """Every attribute the component stores can be read with its schema type, so the schema type is right."""
    comp = _insert(wall, name)
    wrong = []
    for key, prop in _schema(name).items():
        found = [t for t, p in (("int", Int32(0)), ("float", 0.0), ("str", "")) if comp.GetAttribute(key, p)[0]]
        if found and not _stored(comp, key, prop.get("type", "str"))[0]:
            wrong.append(f"{key}: schema {prop.get('type', 'str')}, stored as {found}")
    assert not wrong, wrong


@pytest.mark.parametrize("name", SCHEMA_COMPONENTS)
def test_modify_round_trips_every_attribute(wall, name):
    """A distinct value written to every attribute through `modify_components` is read back unchanged and typed."""
    _insert(wall, name)
    current = _reported(wall, name)
    schema = _schema(name)
    to_write = {key: _distinct(prop.get("type", "str"), current[key]) for key, prop in schema.items()}

    TeklaModel.select_objects([wall])
    assert modify_components(component_name=name, custom_properties=to_write).structured_content["status"] == "success"

    after = _reported(wall, name)
    comp = next(c for c in TeklaModel().get_object_by_guid(wall.Identifier.GUID.ToString()).GetComponents() if c.Name == name)
    # Attributes the component does not store (it drops some on `Modify`) are ignored
    stored = {k: v for k, v in to_write.items() if _stored(comp, k, schema[k].get("type", "str"))[0]}
    assert stored
    wrong = {k: (v, after[k]) for k, v in stored.items() if after[k] != v or type(after[k]) is not type(v)}
    assert not wrong, f"written vs read: {wrong}"


@pytest.mark.parametrize("attr_type,value,expected", VALUE_CASES, ids=[f"{t}-{v!r}" for t, v, _ in VALUE_CASES])
@pytest.mark.parametrize("name", SCHEMA_COMPONENTS)
def test_modify_writes_and_reads_value_sets(wall, name, attr_type, value, expected):
    """The same value written to every attribute of one type is stored and reported as `expected`, with its type."""
    _insert(wall, name)
    keys = [key for key, prop in _schema(name).items() if prop.get("type", "str") == attr_type]

    TeklaModel.select_objects([wall])
    assert modify_components(component_name=name, custom_properties={key: value for key in keys}).structured_content["status"] == "success"

    reported = _reported(wall, name)
    comp = next(c for c in TeklaModel().get_object_by_guid(wall.Identifier.GUID.ToString()).GetComponents() if c.Name == name)
    # Attributes the component does not store (it drops some on `Modify`) are ignored
    stored = {key: _stored(comp, key, attr_type) for key in keys}
    stored = {key: stored_value for key, (is_stored, stored_value) in stored.items() if is_stored}
    assert stored

    wrong_stored = {key: v for key, v in stored.items() if v != expected or type(v) is not type(expected)}
    wrong_reported = {key: reported[key] for key in stored if reported[key] != expected or type(reported[key]) is not type(expected)}
    assert not wrong_stored, f"component stores instead of {expected!r}: {wrong_stored}"
    assert not wrong_reported, f"get_components reports instead of {expected!r}: {wrong_reported}"


def test_numbering_start_stored_as_text_is_read_as_int(wall):
    """The standard settings store MeshBars numbering starts as text '1', reported as the int 1."""
    _insert(wall, "MeshBars")
    reported = _reported(wall, "MeshBars")
    for key in ("BottPriStart", "TopPriStart", "BottSecStart", "TopSecStart"):
        assert reported[key] == 1 and type(reported[key]) is int, key


def test_int_attribute_written_by_modify_changes_rebars(wall):
    """MeshBars uses an int attribute only when it is written as int: 6 bars per group instead of the spacing-based count."""
    _insert(wall, "MeshBars")
    TeklaModel.select_objects([wall])
    result = modify_components(component_name="MeshBars", custom_properties={"NumberBarsBottPri": 6, "SpacTypBotPri": 1})
    assert result.structured_content["status"] == "success"

    rebars = list(TeklaModel().get_object_by_guid(wall.Identifier.GUID.ToString()).GetReinforcements())
    assert rebars
    assert [r.GetRebarGeometries(False).Count for r in rebars] == [6] * len(rebars)
