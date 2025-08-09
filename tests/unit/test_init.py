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

import clr
import System

from init import CONFIG_FILE_PATH, read_config, load_dlls


def test_read_config_valid(monkeypatch):
    """
    Checks that valid config is loaded and validated.
    """
    valid_json = '{"tekla_path": "C:\\\\Tekla"}'
    mocked_open = mock_open(read_data=valid_json)
    monkeypatch.setattr(Path, "open", mocked_open)
    config = read_config()
    assert config["tekla_path"] == "C:\\Tekla"


def test_read_config_missing_file(monkeypatch):
    """
    Checks that missing config file triggers sys.exit.
    """

    def raise_file_not_found(*args, **kwargs):
        raise FileNotFoundError("not found")

    monkeypatch.setattr(type(CONFIG_FILE_PATH), "open", raise_file_not_found)
    with patch("init.logger.critical") as mock_critical, patch("init.sys.exit") as mock_exit:
        read_config()
        mock_critical.assert_called_once()
        mock_exit.assert_called_once_with(1)


def test_read_config_invalid_json(monkeypatch):
    """
    Checks that invalid JSON triggers sys.exit.
    """
    invalid_json = "{invalid json"
    mocked_open = mock_open(read_data=invalid_json)
    monkeypatch.setattr(type(CONFIG_FILE_PATH), "open", mocked_open)
    with patch("init.logger.critical") as mock_critical, patch("init.sys.exit") as mock_exit:
        read_config()
        mock_critical.assert_called_once()
        mock_exit.assert_called_once_with(1)


def test_read_config_missing_key(monkeypatch):
    """
    Checks that missing required key triggers sys.exit.
    """
    invalid_json = '{"wrong_key": "value"}'
    mocked_open = mock_open(read_data=invalid_json)
    monkeypatch.setattr(type(CONFIG_FILE_PATH), "open", mocked_open)
    with patch("init.logger.critical") as mock_critical, patch("init.sys.exit") as mock_exit:
        read_config()
        mock_critical.assert_called_once()
        mock_exit.assert_called_once_with(1)


def test_read_config_wrong_type(monkeypatch):
    """
    Checks that wrong type for key triggers sys.exit.
    """
    invalid_json = '{"tekla_path": 123}'
    mocked_open = mock_open(read_data=invalid_json)
    monkeypatch.setattr(type(CONFIG_FILE_PATH), "open", mocked_open)
    with patch("init.logger.critical") as mock_critical, patch("init.sys.exit") as mock_exit:
        read_config()


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
def test_load_dlls_success():
    """
    Checks that all DLLs are loaded and returns True.
    """
    fake_config = {"tekla_path": "C:\\Tekla"}
    with patch("init.read_config", return_value=fake_config), patch("init.clr.AddReference") as mock_add_ref:
        assert load_dlls() is True
        assert mock_add_ref.call_count == 9  # 9 DLLs


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
def test_load_dlls_file_not_found_triggers_critical_and_exit():
    """
    Checks error handling when DLL is missing.
    """
    fake_config = {"tekla_path": "C:\\Tekla"}
    with patch("init.read_config", return_value=fake_config), patch("init.clr.AddReference", side_effect=System.IO.FileNotFoundException), patch("init.logger.critical") as mock_critical, patch(
        "init.sys.exit"
    ) as mock_exit:
        load_dlls()
        mock_critical.assert_called_once()
        mock_exit.assert_called_once_with(1)
