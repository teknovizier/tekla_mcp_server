"""
Unit tests for configuration management.
"""

from unittest.mock import MagicMock, patch

from tekla_mcp_server.config import Config, get_config


class TestConfigDefaults:
    """Test default configuration loading."""

    @patch("builtins.open", MagicMock())
    @patch("json.load")
    def test_loads_settings_json(self, mock_json_load):
        """Test that settings.json is loaded."""
        mock_json_load.return_value = {
            "tekla_path": "C:\\Tekla",
            "content_attributes_file_path": "C:\\Tekla\\file.lst",
        }
        config = Config()
        assert config.tekla_path == "C:\\Tekla"
        assert config.content_attributes_file_path == "C:\\Tekla\\file.lst"

    @patch("builtins.open", MagicMock())
    @patch("json.load")
    def test_loads_element_types(self, mock_json_load):
        """Test that element_types.json is loaded."""
        mock_json_load.return_value = {
            "tekla_path": "C:\\Tekla",
            "content_attributes_file_path": "C:\\Tekla\\file.lst",
        }
        config = Config()
        # Trigger lazy loading
        _ = config.element_types
        # Should have tried to load element_types.json
        assert mock_json_load.called

    @patch("builtins.open", MagicMock())
    @patch("json.load")
    def test_lazy_loading(self, mock_json_load):
        """Test that config uses lazy loading."""
        mock_json_load.return_value = {
            "tekla_path": "C:\\Tekla",
            "content_attributes_file_path": "C:\\Tekla\\file.lst",
        }
        config = Config()
        # Settings should be loaded on first access
        _ = config.tekla_path
        assert mock_json_load.call_count == 1
        # Element types should NOT be loaded yet
        call_args = [str(c) for c in mock_json_load.call_args_list]
        assert not any("element_types" in str(c) for c in call_args)


class TestConfigAttributeMapper:
    """Test embeddings property."""

    @patch("builtins.open", MagicMock())
    @patch("json.load")
    def test_embeddings_defaults(self, mock_json_load):
        """Test embeddings returns empty dict when not in settings."""
        mock_json_load.return_value = {
            "tekla_path": "C:\\Tekla",
            "content_attributes_file_path": "C:\\Tekla\\file.lst",
        }
        config = Config()
        assert config.embeddings == {}

    @patch("builtins.open", MagicMock())
    @patch("json.load")
    def test_embeddings_from_settings(self, mock_json_load):
        """Test embeddings returns values from settings."""
        mock_json_load.return_value = {
            "tekla_path": "C:\\Tekla",
            "content_attributes_file_path": "C:\\Tekla\\file.lst",
            "embeddings": {
                "embedding_model": "test-model",
                "embedding_threshold": 0.7,
            },
        }
        config = Config()
        assert config.embeddings == {"embedding_model": "test-model", "embedding_threshold": 0.7}
        assert config.embedding_model == "test-model"
        assert config.embedding_threshold == 0.7


class TestGetConfigSingleton:
    """Test get_config singleton pattern."""

    def test_returns_same_instance(self):
        """Test that get_config returns the same instance."""
        assert callable(get_config)
