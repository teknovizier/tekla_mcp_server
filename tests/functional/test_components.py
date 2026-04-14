"""
Functional tests for components_provider.

Tests component placement, removal, modification, and retrieval operations.
"""

from tekla_mcp_server.providers.components_provider import put_components, remove_components, get_components, modify_components
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


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
    result = remove_components(component_name="Lifting Anchor")
    assert result.structured_content["status"] == "success"


def test_put_components_invalid_component(model_objects):
    """Tests put_components with an invalid component name."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    result = put_components(component_name="NonExistentComponent")
    assert result.structured_content["status"] == "error"


def test_put_components_with_custom_properties(model_objects):
    """Tests put_components for Mesh Bars with custom properties."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    result = put_components(component_name="MeshBars", custom_properties={"TopAsBott": "0"})
    assert result.structured_content["status"] == "success"


def test_remove_components(model_objects):
    """Tests remove_components function."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    put_components(component_name="MeshBars")
    result = remove_components(component_name="MeshBars")
    assert result.structured_content["status"] == "success"


def test_get_components_returns_components(model_objects):
    """Tests get_components returns component info for elements with components."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    put_components(component_name="MeshBars")
    result = get_components()
    assert result.structured_content["status"] == "success"
    assert result.structured_content["total_elements"] == 1
    assert result.structured_content["total_components"] >= 1
    comp = result.structured_content["elements"][0]["components"][0]
    assert comp["name"] == "MeshBars"
    assert comp["supported"] is True
    assert comp["config_key"] == "mesh_bars"
    assert comp["schema"] is not None


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
        assert comp["schema"] is not None


def test_modify_components_success(model_objects):
    """Tests modify_components modifies attributes on existing components."""
    TeklaModel.select_objects([model_objects["test_wall1"]])
    put_components(component_name="MeshBars")
    result = modify_components(
        component_name="MeshBars",
        custom_properties={"TopAsBott": 1, "NumberBarsBottSec": 4, "SpacBarsBottSec": 300.0, "BottDiaSec": "12"},
    )
    assert result.structured_content["status"] == "success"
    assert result.structured_content["processed_components"] >= 1

    result = get_components()
    comp = next(c for c in result.structured_content["elements"][0]["components"] if c["name"] == "MeshBars")
    print(comp["attributes"])
    assert comp["attributes"]["TopAsBott"] == 1
    assert comp["attributes"]["NumberBarsBottSec"] == 4
    assert comp["attributes"]["SpacBarsBottSec"] == 300.0
    assert comp["attributes"]["BottDiaSec"] == "12"


def test_modify_components_no_matching_component(model_objects):
    """Tests modify_components returns error when component not found."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    result = modify_components(
        component_name="NonExistingComponent",
        custom_properties={"RecessLength": 200.0},
    )
    assert result.structured_content["status"] == "error"
    assert result.structured_content["processed_components"] == 0


def test_modify_components_invalid_properties(model_objects):
    """Tests modify_components returns error for invalid property names."""
    TeklaModel.select_objects([model_objects["test_wall8"]])
    put_components(component_name="MeshBars")
    result = modify_components(
        component_name="MeshBars",
        custom_properties={"NonExistentProperty": 123},
    )
    assert result.structured_content["status"] == "error"
