"""
Unit tests for configuration management.
"""

import pytest
from unittest.mock import patch

from tekla_mcp_server.config import Config, get_config, _load_json, _load_settings, _get_tekla_macro_directories


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all lru_cache decorators before each test."""
    _load_json.cache_clear()
    _load_settings.cache_clear()
    _get_tekla_macro_directories.cache_clear()
    yield


class TestConfigDefaults:
    """Test default configuration loading."""

    def test_loads_settings_json(self):
        """Test that settings.json is loaded."""
        with patch("tekla_mcp_server.config._load_json") as mock_load:
            mock_load.return_value = {
                "tekla_path": "C:\\Tekla",
            }
            config = Config()
            assert config.tekla_path == "C:\\Tekla"
            expected_path = "C:\\Tekla\\applications\\Tekla\\Tools\\TplEd\\settings\\contentattributes_global.lst"
            assert config.content_attributes_file_path == expected_path

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


class TestTeklaMacroDirectories:
    """Test tekla_macro_directories property."""

    def test_returns_empty_when_no_option(self):
        """Test returns empty list when GetAdvancedOption returns empty."""
        with patch("tekla_mcp_server.config._get_tekla_macro_directories", return_value=[]):
            config = Config()
            assert config.tekla_macro_directories == []

    def test_returns_cached_paths(self, tmp_path):
        """Test that paths from cached function are returned."""
        dir1 = tmp_path / "macros1"
        dir1.mkdir()
        cached_paths = [str(dir1.resolve())]

        with patch("tekla_mcp_server.config._get_tekla_macro_directories", return_value=cached_paths):
            config = Config()
            result = config.tekla_macro_directories
            assert result == cached_paths
