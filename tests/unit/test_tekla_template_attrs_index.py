"""
Unit tests for `TemplateAttributeParser` exact matching through its normalized-name index.

Pure logic with embeddings switched off, so these run in CI and without embeddings enabled.
`template_attrs_parser` does not import `tekla/loader.py`, so no Tekla skip guard is needed.
"""

import pytest

from tekla_mcp_server.tekla import template_attrs_parser
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser

_LST = (
    "// header comment\n"
    "ASSEMBLY_TOP_LEVEL              CHARACTER   LEFT     TRUE      10        *\n"
    "ASSEMBLY-TOP-LEVEL              CHARACTER   LEFT     TRUE      10        *\n"
    "AREA_NET                        FLOAT       RIGHT    TRUE      10        m2\n"
)


class _Cfg:
    """Minimal config stand-in for `resolve_attributes`."""

    def __init__(self, path: str):
        self.content_attributes_file_paths = [path]
        self.embedding_spread_threshold = 0.0
        self.embedding_minimum_threshold = 0.0
        self.semantic_overrides: dict[str, str] = {}


@pytest.fixture(autouse=True)
def parser(tmp_path, monkeypatch):
    """Point the parser at a small attributes file with embeddings disabled."""
    lst = tmp_path / "contentattributes.lst"
    lst.write_text(_LST, encoding="utf-8")
    monkeypatch.setattr(template_attrs_parser, "get_config", lambda: _Cfg(str(lst)))
    monkeypatch.setattr(template_attrs_parser, "is_embeddings_enabled", lambda: False)
    monkeypatch.setattr(TemplateAttributeParser, "_cache", {})
    monkeypatch.setattr(TemplateAttributeParser, "_normalized_index", {})
    monkeypatch.setattr(TemplateAttributeParser, "_loaded", False)
    monkeypatch.setattr(TemplateAttributeParser, "_embedding_names", [])
    monkeypatch.setattr(TemplateAttributeParser, "_embedding_matrix", None)
    monkeypatch.setattr(TemplateAttributeParser, "_semantic_loaded", False)
    return lst


def test_index_first_loaded_name_wins():
    TemplateAttributeParser._load_attributes()
    assert TemplateAttributeParser._normalized_index == {"ASSEMBLY_TOP_LEVEL": "ASSEMBLY_TOP_LEVEL", "AREA_NET": "AREA_NET"}


def test_index_updated_when_loading_a_single_file(parser):
    """Loading a file directly must keep the index in step with the cache."""
    TemplateAttributeParser._load_attributes_from_file(str(parser))
    assert TemplateAttributeParser._normalized_index == {"ASSEMBLY_TOP_LEVEL": "ASSEMBLY_TOP_LEVEL", "AREA_NET": "AREA_NET"}


@pytest.mark.parametrize(
    "query,expected",
    [
        ("assembly top level", "ASSEMBLY_TOP_LEVEL"),
        ("Assembly-Top-Level", "ASSEMBLY_TOP_LEVEL"),
        ("area_net", "AREA_NET"),
    ],
)
def test_resolve_attributes_exact_match(query, expected):
    result = TemplateAttributeParser.resolve_attributes([query])
    assert result == {"resolved": [expected], "errors": []}


def test_resolve_attributes_no_match_without_embeddings():
    result = TemplateAttributeParser.resolve_attributes(["nope"])
    assert result["resolved"] == []
    assert result["errors"] == [{"query": "nope", "candidates": [], "reason": "no_match"}]
