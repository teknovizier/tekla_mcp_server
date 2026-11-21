"""
Unit tests for selection provider helpers.

The provider imports the Tekla loader, which loads the Tekla DLLs, so these tests
are skipped in CI environments where Tekla is not available. The tool itself is
covered by the functional tests.
"""

import importlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import FilterCondition, FilterGroup

sp = importlib.import_module("tekla_mcp_server.providers.selection_provider")


def _condition(**data) -> FilterCondition:
    """Validate keyword arguments as a filter condition."""
    return FilterCondition.model_validate(data)


class TestExpandElementType:
    @pytest.fixture
    def wall_classes(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: [1, 8, 1])

    def test_is_equal_becomes_one_class_list(self, wall_classes):
        condition = sp._expand_element_type(_condition(field="part.element_type", op="Is Equal", value="Wall"))
        assert (condition.field, condition.op, condition.value) == ("part.class", "Is Equal", [1, 8])

    def test_is_not_equal_keeps_its_operator(self, wall_classes):
        assert sp._expand_element_type(_condition(field="part.element_type", op="Is Not Equal", value="Wall")).op == "Is Not Equal"

    def test_type_list_merges_classes(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: {"Wall": [1], "Sandwich Wall": [8, 52, 1]}[element_type])
        condition = sp._expand_element_type(_condition(field="part.element_type", op="Is Equal", value=["Wall", "Sandwich Wall"]))
        assert condition.value == [1, 8, 52]

    def test_type_without_classes_raises(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: [])
        with pytest.raises(ValueError, match="no Tekla classes configured"):
            sp._expand_element_type(_condition(field="part.element_type", op="Is Equal", value="Wall"))

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Invalid element_type"):
            sp._expand_element_type(_condition(field="part.element_type", op="Is Equal", value="NotAType"))


class TestResolveElementTypeClasses:
    @pytest.fixture
    def config(self, monkeypatch):
        element_types = {
            "MATERIAL_CONCRETE": {"CONCRETE_WALL": {"tekla_classes": [1]}, "CONCRETE_SANDWICH_WALL": {"tekla_classes": [8, 52]}},
            "MATERIAL_REINFORCEMENT": {"MESH": {"tekla_classes": [13]}},
        }
        monkeypatch.setattr(sp, "get_config", lambda: SimpleNamespace(element_types=element_types))

    @pytest.mark.parametrize("element_type", ["Mesh", "MESH"])
    def test_reinforcement_type_is_rejected(self, config, element_type):
        with pytest.raises(ValueError, match="reinforcement type, not a part type. Use 'rebar.class'"):
            sp._resolve_element_type_classes(element_type)

    def test_unknown_type_does_not_list_reinforcement_types(self, config):
        with pytest.raises(ValueError) as exc_info:
            sp._resolve_element_type_classes("FakeWall")
        assert "Mesh" not in str(exc_info.value)

    @pytest.mark.parametrize("element_type", ["Sandwich Wall", "sandwich wall", "SANDWICH WALL", "CONCRETE_SANDWICH_WALL", "concrete_sandwich_wall", " Concrete Sandwich Wall "])
    def test_name_and_key_spellings(self, config, element_type):
        assert sp._resolve_element_type_classes(element_type) == [8, 52]

    def test_wall_is_not_a_sandwich_wall(self, config):
        assert sp._resolve_element_type_classes("CONCRETE_WALL") == [1]

    def test_unknown_type_lists_the_valid_names(self, config):
        with pytest.raises(ValueError, match="Must be one of: \\['Wall', 'Sandwich Wall'"):
            sp._resolve_element_type_classes("FakeWall")


class FakeFilter:
    """Stand-in for Tekla's `Filter` that writes a small file the way `CreateFile` does."""

    mode = "write"
    calls: list[str] = []
    refreshes: list[bool] = []

    def __init__(self, expression: Any) -> None:
        self.expression = expression

    def CreateFile(self, file_type: Any, stem: str) -> str:  # noqa: N802
        """Write `stem` plus the extension of `file_type`, or fail the way the test asks."""
        FakeFilter.calls.append(stem)
        extension = ".VObjGrp" if file_type == sp.FilterExpressionFileType.OBJECT_GROUP_VIEW else ".SObjGrp"
        path = f"{stem}{extension}"
        if FakeFilter.mode == "raise":
            raise RuntimeError("Illegal characters in path.\nat Tekla")
        if FakeFilter.mode == "write":
            Path(path).write_text(f"new {Path(stem).name}", encoding="utf-8")
        return path


@pytest.fixture
def attributes(tmp_path, monkeypatch) -> Path:
    """A temporary model attributes folder with `TeklaModel`, `Filter` and the cache refresh replaced."""
    folder = tmp_path / "attributes"
    folder.mkdir()
    model = SimpleNamespace(model_path=str(tmp_path), get_objects_by_filter=lambda expression: SimpleNamespace(GetSize=lambda: 7))
    monkeypatch.setattr(sp, "TeklaModel", lambda: model)
    monkeypatch.setattr(sp, "Filter", FakeFilter)
    FakeFilter.mode = "write"
    FakeFilter.calls = []
    FakeFilter.refreshes = []
    monkeypatch.setattr(sp, "refresh_attribute_files", lambda: FakeFilter.refreshes.append(True))
    return folder


def _create(**kwargs: Any) -> dict[str, Any]:
    """Call `create_filter` with a simple part filter unless the test overrides arguments."""
    arguments = {"filter_name": "MCP_TEST_F", "filter_type": "selection", "filter": {"field": "part.class", "op": "Is Equal", "value": 1}, "object_types": ["part"], **kwargs}
    return sp.create_filter(**arguments).structured_content


class TestCreateFilter:
    def test_new_filter_is_written_without_leftovers(self, attributes):
        content = _create()
        assert content["status"] == "success", content
        assert (content["filter_name"], content["overwritten"], content["matching_objects"]) == ("MCP_TEST_F", False, 7)
        assert "reopen" in content["note"]
        assert sorted(f.name for f in attributes.iterdir()) == ["MCP_TEST_F.SObjGrp"]
        assert FakeFilter.refreshes == [True]
        # Tekla writes under the temporary name, never straight onto the target
        assert Path(FakeFilter.calls[0]).name == f"{sp.TEMPORARY_FILTER_PREFIX}MCP_TEST_F"

    def test_view_filter_gets_the_view_extension(self, attributes):
        assert Path(_create(filter_type="view")["path"]).name == "MCP_TEST_F.VObjGrp"

    def test_existing_filter_is_kept_without_overwrite(self, attributes):
        (attributes / "MCP_TEST_F.SObjGrp").write_text("old", encoding="utf-8")
        content = _create()
        assert content["status"] == "error" and "already exists" in content["message"]
        assert (attributes / "MCP_TEST_F.SObjGrp").read_text(encoding="utf-8") == "old"
        assert FakeFilter.calls == []

    def test_overwrite_replaces_the_file(self, attributes):
        (attributes / "MCP_TEST_F.SObjGrp").write_text("old", encoding="utf-8")
        content = _create(overwrite=True)
        assert content["overwritten"] is True
        assert sorted(f.name for f in attributes.iterdir()) == ["MCP_TEST_F.SObjGrp"]
        assert (attributes / "MCP_TEST_F.SObjGrp").read_text(encoding="utf-8").startswith("new")

    @pytest.mark.parametrize("mode,message", [("raise", "Tekla could not write the filter 'MCP_TEST_F': Illegal characters in path."), ("nothing", "Tekla did not write")])
    def test_failed_write_keeps_the_original(self, attributes, mode, message):
        (attributes / "MCP_TEST_F.SObjGrp").write_text("old", encoding="utf-8")
        FakeFilter.mode = mode
        content = _create(overwrite=True)
        assert content["status"] == "error"
        assert message in content["message"]
        assert sorted(f.name for f in attributes.iterdir()) == ["MCP_TEST_F.SObjGrp"]
        assert (attributes / "MCP_TEST_F.SObjGrp").read_text(encoding="utf-8") == "old"
        assert FakeFilter.refreshes == []

    def test_existing_spelling_is_kept(self, attributes):
        (attributes / "MCP_TEST_F.SObjGrp").write_text("old", encoding="utf-8")
        content = _create(filter_name="mcp_test_f", overwrite=True)
        assert content["filter_name"] == "MCP_TEST_F"
        assert sorted(f.name for f in attributes.iterdir()) == ["MCP_TEST_F.SObjGrp"]

    def test_existing_spelling_is_named_in_the_refusal(self, attributes):
        (attributes / "MCP_TEST_F.SObjGrp").write_text("old", encoding="utf-8")
        assert "'MCP_TEST_F' already exists" in _create(filter_name="mcp_test_f")["message"]

    @pytest.mark.parametrize(
        "kwargs,message",
        [
            ({"filter": {"field": "part.nope", "op": "Is Equal", "value": 1}}, "Unknown field"),
            ({"object_types": ["beam"]}, "Unknown object types"),
            ({"filter_name": "MCP_TEST_F.VObjGrp"}, "filter extension"),
            ({"filter_name": "sub/MCP_TEST_F"}, "without folders or a drive"),
        ],
    )
    def test_invalid_request_is_reported_before_the_existing_file(self, attributes, kwargs, message):
        (attributes / "MCP_TEST_F.SObjGrp").write_text("old", encoding="utf-8")
        content = _create(**kwargs)
        assert content["status"] == "error"
        assert message in content["message"]
        assert FakeFilter.calls == []

    def test_missing_attributes_folder_is_an_error(self, attributes):
        attributes.rmdir()
        assert "no attributes folder" in _create()["message"]


class TestPrepareTree:
    def test_element_type_is_expanded_in_nested_groups(self, monkeypatch):
        monkeypatch.setattr(sp, "_resolve_element_type_classes", lambda element_type: [1])
        tree = FilterGroup.model_validate({"any": [{"all": [{"field": "part.element_type", "op": "Is Equal", "value": "Wall"}]}, {"attribute": "comment", "op": "Is Equal", "value": "x"}]})
        prepared = sp._prepare_tree(tree)
        assert prepared.is_any
        expanded_group, attribute = prepared.items
        assert (expanded_group.items[0].field, expanded_group.items[0].value) == ("part.class", [1])
        # Attribute names are kept exactly, case included
        assert attribute.attribute == "comment"
        # The caller's tree is left as it was
        assert tree.items[0].items[0].field == "part.element_type"

    def test_plain_condition_is_kept(self):
        condition = _condition(field="part.name", op="Is Equal", value="A")
        assert sp._prepare_tree(condition) is condition
