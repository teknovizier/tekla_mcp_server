"""
Unit tests for DLL loading and configuration parsing logic.

This module verifies the robustness of the DLL loading mechanism and configuration file handling
used to initialize Tekla Structures integrations. It ensures proper error reporting and graceful
exit behavior when configuration issues or missing DLLs are encountered.

Tests involving actual DLL loading are skipped in CI environments where Tekla is not available.

Tested modules:
- init.py
"""

import os
import pytest

from pathlib import Path
from unittest.mock import patch, mock_open

import clr  # noqa: F401
import System

from init import CONFIG_FILE_PATH, read_config, read_json_config, load_dlls


@pytest.fixture(autouse=True)
def clear_cache():
    import init

    init._config_cache = None
    yield


def test_read_config_valid(monkeypatch):
    """Checks that valid config is loaded and validated."""
    valid_json = '{"tekla_path": "C:\\\\Tekla", "content_attributes_file_path": "C:\\\\Tekla\\\\file.lst"}'

    def mock_exists(self):
        return True

    mocked_open = mock_open(read_data=valid_json)
    monkeypatch.setattr(Path, "open", mocked_open)
    monkeypatch.setattr(Path, "exists", mock_exists)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    config = read_config()
    assert config["tekla_path"] == "C:\\Tekla"


def test_read_config_missing_file(monkeypatch):
    """Checks that missing config file triggers sys.exit."""
    monkeypatch.setattr(type(CONFIG_FILE_PATH), "open", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("not found")))
    with patch("init.sys.exit") as mock_exit:
        read_config()
        mock_exit.assert_called_once_with(1)


def test_read_config_invalid_json(monkeypatch):
    """Checks that invalid JSON triggers sys.exit."""
    mocked_open = mock_open(read_data="{invalid")
    monkeypatch.setattr(Path, "open", mocked_open)
    with patch("init.sys.exit") as mock_exit:
        read_config()
        mock_exit.assert_called_once_with(1)


def test_read_config_missing_key(monkeypatch):
    """Checks that missing required key triggers sys.exit."""
    mocked_open = mock_open(read_data='{"wrong_key": "value"}')
    monkeypatch.setattr(Path, "open", mocked_open)
    with patch("init.sys.exit") as mock_exit:
        read_config()
        mock_exit.assert_called_once_with(1)


def test_read_config_wrong_type(monkeypatch):
    """Checks that wrong type for key triggers sys.exit."""
    mocked_open = mock_open(read_data='{"tekla_path": 123}')
    monkeypatch.setattr(Path, "open", mocked_open)
    with patch("init.sys.exit") as mock_exit:
        read_config()
        mock_exit.assert_called_once_with(1)


def test_read_config_path_not_exist(monkeypatch):
    """Checks that non-existent path triggers sys.exit."""
    valid_json = '{"tekla_path": "C:\\\\NonExistent", "content_attributes_file_path": "C:\\\\Tekla\\\\file.lst"}'

    def mock_exists(self):
        return False

    mocked_open = mock_open(read_data=valid_json)
    monkeypatch.setattr(Path, "open", mocked_open)
    monkeypatch.setattr(Path, "exists", mock_exists)
    with patch("init.sys.exit") as mock_exit:
        read_config()
        mock_exit.assert_called_once_with(1)


def test_read_json_config(monkeypatch):
    """Checks that valid JSON file is read correctly."""

    def mock_open_func(*args, **kwargs):
        return mock_open(read_data='{"key": "value"}')()

    monkeypatch.setattr("builtins.open", mock_open_func)
    monkeypatch.setattr("init.Path", lambda *args: Path("test.json"))

    result = read_json_config("test.json")
    assert result == {"key": "value"}


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
def test_load_dlls_success():
    """Checks that all DLLs are loaded and returns True."""
    fake_config = {"tekla_path": "C:\\Tekla"}
    with patch("init.read_config", return_value=fake_config), patch("init.clr.AddReference") as mock_add_ref:
        assert load_dlls() is True
        assert mock_add_ref.call_count == 9  # 9 DLLs


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
def test_load_dlls_file_not_found_triggers_exception_and_exit():
    """Checks error handling when DLL is missing."""
    fake_config = {"tekla_path": "C:\\Tekla"}
    with (
        patch("init.read_config", return_value=fake_config),
        patch("init.clr.AddReference", side_effect=System.IO.FileNotFoundException),
        patch("init.logger.exception") as mock_exception,
        patch("init.sys.exit") as mock_exit,
    ):
        load_dlls()
        mock_exception.assert_called_once()
        mock_exit.assert_called_once_with(1)
