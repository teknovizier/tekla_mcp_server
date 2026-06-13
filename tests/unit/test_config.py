"""
Unit tests for configuration management.
"""

from typing import Any

import pytest
from unittest.mock import patch

from tekla_mcp_server.config import Config, get_config, get_report_preview_max_chars, get_report_preview_timeout, _load_json, _load_settings
from tekla_mcp_server.models import ElementTypes


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all lru_cache decorators before each test."""
    _load_json.cache_clear()
    _load_settings.cache_clear()
    yield


class TestConfigDefaults:
    """Test default configuration loading."""

    def test_loads_element_types(self):
        """Test that element_types.json is loaded."""
        with patch("tekla_mcp_server.config._load_json") as mock_load:
            mock_load.return_value = {"key": {"type": [1, 2, 3]}}
            config = Config()
            _ = config.element_types
            assert mock_load.called

    def test_lazy_loading(self):
        """Test that config uses lazy loading via lru_cache."""

        def mock_load_json(filename):
            return {
                "tekla_path": "C:\\Tekla",
            }

        with patch("tekla_mcp_server.config._load_json", mock_load_json):
            config = Config()
            assert config.tekla_path == "C:\\Tekla"


class TestConfigAttributeMapper:
    """Test embeddings property."""

    def test_embeddings_defaults(self):
        """Test embeddings returns empty dict when not in settings."""
        with patch("tekla_mcp_server.config._load_json") as mock_load:
            mock_load.return_value = {
                "tekla_path": "C:\\Tekla",
            }
            config = Config()
            assert config.embeddings == {}

    def test_embeddings_from_settings(self):
        """Test embeddings returns values from settings."""
        with patch("tekla_mcp_server.config._load_json") as mock_load:
            mock_load.return_value = {
                "tekla_path": "C:\\Tekla",
                "embeddings": {
                    "embedding_model": "test-model",
                    "embedding_spread_threshold": 0.1,
                },
            }
            config = Config()
            assert config.embeddings == {"embedding_model": "test-model", "embedding_spread_threshold": 0.1}
            assert config.embedding_model == "test-model"
            assert config.embedding_spread_threshold == 0.1


class TestGetConfigSingleton:
    """Test get_config singleton pattern."""

    def test_returns_same_instance(self):
        """Test that get_config returns the same instance."""
        assert callable(get_config)


class TestReportPreviewConfig:
    """Test get_report_preview_max_chars and get_report_preview_timeout."""

    def test_preview_max_chars_default(self):
        """Returns default when reports section is absent."""
        with patch("tekla_mcp_server.config._load_settings") as mock_settings:
            mock_settings.return_value = {"tekla_path": "C:\\Tekla"}
            assert get_report_preview_max_chars() == 2000

    def test_preview_max_chars_from_config(self):
        """Reads value from reports.preview_max_chars."""
        with patch("tekla_mcp_server.config._load_settings") as mock_settings:
            mock_settings.return_value = {"tekla_path": "C:\\Tekla", "reports": {"preview_max_chars": 500}}
            assert get_report_preview_max_chars() == 500

    def test_preview_timeout_default(self):
        """Returns default when reports section is absent."""
        with patch("tekla_mcp_server.config._load_settings") as mock_settings:
            mock_settings.return_value = {"tekla_path": "C:\\Tekla"}
            assert get_report_preview_timeout() == 30.0

    def test_preview_timeout_from_config(self):
        """Reads value from reports.preview_timeout."""
        with patch("tekla_mcp_server.config._load_settings") as mock_settings:
            mock_settings.return_value = {"tekla_path": "C:\\Tekla", "reports": {"preview_timeout": 120}}
            assert get_report_preview_timeout() == 120.0


def _make_element_types() -> dict[str, Any]:
    """Return element_types data with a known duplicate class (13) across materials."""
    return {
        "MATERIAL_CONCRETE": {
            "COLUMN": {"tekla_classes": [13], "default_name": "ConcreteColumn"},
        },
        "MATERIAL_STEEL": {
            "BEAM": {"tekla_classes": [1, 2], "default_name": "SteelBeam"},
        },
        "MATERIAL_REINFORCEMENT": {
            "MESH": {"tekla_classes": [13], "default_name": "RebarMesh"},
        },
    }


def _mock_load_json_for_element_types(
    filename: str,
    et_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a mock _load_json that dispatches on filename."""
    if filename == "settings.json":
        return {"tekla_path": "C:\\TeklaStructures"}
    if filename == "element_types.json":
        return _make_element_types() if et_data is None else et_data
    return {}


class TestElementTypeClassMapping:
    """Tests for class-number collision handling in element-type resolution."""

    def test_get_element_types_flat_first_occurrence_wins(self):
        """When class 13 appears under CONCRETE and REINFORCEMENT, the concrete entry wins (first listed)."""
        with patch("tekla_mcp_server.config._load_json", side_effect=_mock_load_json_for_element_types):
            config = Config()
            flat = config.get_element_types_flat()
        assert 13 in flat
        assert flat[13]["default_name"] == "ConcreteColumn"

    def test_get_class_mapping_first_occurrence_wins(self):
        """When class 13 appears under CONCRETE and REINFORCEMENT, the concrete tuple wins."""
        with patch("tekla_mcp_server.config._load_json", side_effect=_mock_load_json_for_element_types):
            mapping = ElementTypes.get_class_mapping()
        assert 13 in mapping
        material, type_name = mapping[13]
        assert material == "MATERIAL_CONCRETE"
        assert type_name == "COLUMN"

    def test_get_element_type_by_class_returns_first(self):
        """get_element_type_by_class(13) returns the concrete column entry, not reinforcement mesh."""
        with patch("tekla_mcp_server.config._load_json", side_effect=_mock_load_json_for_element_types):
            result = ElementTypes.get_element_type_by_class(13)
        assert result == ("MATERIAL_CONCRETE", "COLUMN")

    def test_no_duplicate_classes_unchanged(self):
        """Classes that appear only once are not affected by the setdefault logic."""
        with patch("tekla_mcp_server.config._load_json", side_effect=_mock_load_json_for_element_types):
            config = Config()
            flat = config.get_element_types_flat()
        assert 1 in flat
        assert flat[1]["default_name"] == "SteelBeam"
        assert 2 in flat
        assert flat[2]["default_name"] == "SteelBeam"
