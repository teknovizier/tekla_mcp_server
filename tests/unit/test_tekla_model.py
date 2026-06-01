"""
Unit tests for TeklaModel wrapper.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from tekla_mcp_server.tekla.wrappers.model import TeklaModel


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset TeklaModel singleton state between tests."""
    TeklaModel._instance = None
    yield
    TeklaModel._instance = None


def _make_model(model_path: str | None = "C:\\Models\\TestModel") -> MagicMock:
    """Return a connected mock Model with GetInfo().ModelPath set."""
    mock_model = MagicMock()
    mock_model.GetConnectionStatus.return_value = True
    mock_model.GetInfo.return_value = MagicMock(ModelPath=model_path)
    return mock_model


class TestModelPath:
    def _connected_instance(self, model_path: str | None = "C:\\Models\\TestModel") -> TeklaModel:
        with patch("tekla_mcp_server.tekla.wrappers.model.Model", return_value=_make_model(model_path)):
            return TeklaModel()

    def test_caches_result_after_first_call(self):
        instance = self._connected_instance()
        _ = instance.model_path
        _ = instance.model_path
        instance._model.GetInfo.assert_called_once()

    def test_cache_invalidated_on_reconnect(self):
        mock_model = _make_model("C:\\Models\\First")
        with patch("tekla_mcp_server.tekla.wrappers.model.Model", return_value=mock_model):
            instance = TeklaModel()

        assert instance.model_path == "C:\\Models\\First"

        mock_model.GetInfo.return_value = MagicMock(ModelPath="C:\\Models\\Second")
        with patch("tekla_mcp_server.tekla.wrappers.model.Model", return_value=mock_model):
            TeklaModel.reconnect()

        assert instance.model_path == "C:\\Models\\Second"
        assert instance._model.GetInfo.call_count == 2

    def test_raises_connection_error_when_not_connected(self):
        instance = TeklaModel.__new__(TeklaModel)
        instance._connect_lock = threading.RLock()
        instance._model = None
        instance._model_path = None
        instance._initialized = False
        TeklaModel._instance = instance

        with patch.object(instance, "ensure_connected", return_value=False):
            with pytest.raises(ConnectionError):
                _ = instance.model_path
