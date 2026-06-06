"""
Unit tests for TeklaModel wrapper.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available.
"""

import os
import threading
from unittest.mock import MagicMock, patch

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

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


def _connected_instance(model_path: str | None = "C:\\Models\\TestModel") -> TeklaModel:
    """Build a TeklaModel backed by a connected mock Model."""
    with patch("tekla_mcp_server.tekla.wrappers.model.Model", return_value=_make_model(model_path)):
        return TeklaModel()


class TestModelPath:
    def test_reads_fresh_each_call(self):
        instance = _connected_instance()
        assert instance.model_path == "C:\\Models\\TestModel"
        assert instance.model_path == "C:\\Models\\TestModel"
        # No caching: the path is re-read from Tekla on every access.
        assert instance._model.GetInfo.call_count == 2

    def test_reflects_model_switch_without_reconnect(self):
        instance = _connected_instance("C:\\Models\\First")
        assert instance.model_path == "C:\\Models\\First"

        # User opens a different model in the same Tekla session; the connection
        # stays alive, so no reconnect happens, but the path must still update.
        instance._model.GetInfo.return_value = MagicMock(ModelPath="C:\\Models\\Second")
        assert instance.model_path == "C:\\Models\\Second"

    def test_returns_empty_string_when_model_path_is_none(self):
        instance = _connected_instance()
        instance._model.GetInfo.return_value = MagicMock(ModelPath=None)
        assert instance.model_path == ""

    def test_returns_empty_string_when_get_info_returns_none(self):
        instance = _connected_instance()
        instance._model.GetInfo.return_value = None
        assert instance.model_path == ""

    def test_raises_connection_error_when_not_connected(self):
        instance = TeklaModel.__new__(TeklaModel)
        instance._connect_lock = threading.RLock()
        instance._model = None
        instance._initialized = False
        TeklaModel._instance = instance

        with patch.object(instance, "ensure_connected", return_value=False):
            with pytest.raises(ConnectionError):
                _ = instance.model_path


class TestConnection:
    def test_ensure_connected_true_when_alive(self):
        instance = _connected_instance()
        assert instance.ensure_connected() is True

    def test_model_property_returns_live_handle(self):
        instance = _connected_instance()
        assert instance.model is instance._model

    def test_recovers_from_transient_loss(self):
        instance = _connected_instance()
        # The current handle reports the connection as lost...
        instance._model.GetConnectionStatus.return_value = False
        # ...but a fresh Model connects, so a single reconnect attempt succeeds.
        fresh = _make_model("C:\\Models\\Reconnected")
        with patch("tekla_mcp_server.tekla.wrappers.model.Model", return_value=fresh) as model_cls:
            assert instance.ensure_connected() is True
            model_cls.assert_called_once()  # a new handle was actually constructed
        assert instance._model is fresh

    def test_reconnect_failure_returns_false_and_preserves_old_handle(self):
        instance = _connected_instance()
        old_model = instance._model
        old_model.GetConnectionStatus.return_value = False  # connection lost

        disconnected = MagicMock()
        disconnected.GetConnectionStatus.return_value = False
        with patch("tekla_mcp_server.tekla.wrappers.model.Model", return_value=disconnected):
            assert instance.ensure_connected() is False

        # Failed reconnect must NOT destroy the old handle — it may still be valid.
        assert instance._model is old_model

    def test_model_property_raises_when_model_none(self):
        instance = _connected_instance()
        instance._model = None
        # ensure_connected reports healthy, but the handle raced to None: the
        # property must raise rather than hand back None typed as Model.
        with patch.object(instance, "ensure_connected", return_value=True):
            with pytest.raises(ConnectionError):
                _ = instance.model
