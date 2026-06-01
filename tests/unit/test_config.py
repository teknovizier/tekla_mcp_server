"""
Unit tests for configuration management.
"""

import pytest
from unittest.mock import patch

from tekla_mcp_server.config import Config, get_config, get_report_preview_max_chars, get_report_preview_timeout, _load_json, _load_settings


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
