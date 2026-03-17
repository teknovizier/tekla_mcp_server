"""
Unit tests for embeddings module.
"""

from unittest.mock import patch, MagicMock

from tekla_mcp_server.embeddings import (
    get_compute_device,
    is_embeddings_enabled,
)


class TestGetComputeDevice:
    """Test get_compute_device function."""

    @patch("torch.cuda.is_available")
    def test_returns_cuda_when_available(self, mock_cuda):
        mock_cuda.return_value = True
        assert get_compute_device() == "cuda"

    @patch("torch.cuda.is_available")
    def test_returns_cpu_when_cuda_unavailable(self, mock_cuda):
        mock_cuda.return_value = False
        assert get_compute_device() == "cpu"

    @patch("tekla_mcp_server.init.logger")
    def test_returns_cpu_when_torch_not_installed(self, mock_logger):
        import importlib
        import tekla_mcp_server.embeddings as emb_module

        try:
            with patch.dict("sys.modules", {"torch": None}):
                importlib.reload(emb_module)
                result = emb_module.get_compute_device()

            assert result == "cpu"
            mock_logger.warning.assert_called_once()
        finally:
            importlib.reload(emb_module)


class TestIsEmbeddingsEnabled:
    """Test is_embeddings_enabled function."""

    @patch("tekla_mcp_server.embeddings.get_config")
    def test_returns_true_when_enabled(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.embeddings_enabled = True
        mock_get_config.return_value = mock_config

        assert is_embeddings_enabled() is True

    @patch("tekla_mcp_server.embeddings.get_config")
    def test_returns_false_when_disabled(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.embeddings_enabled = False
        mock_get_config.return_value = mock_config

        assert is_embeddings_enabled() is False
