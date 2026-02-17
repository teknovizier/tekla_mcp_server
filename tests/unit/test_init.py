"""
Unit tests for DLL loading logic.

This module verifies the robustness of the DLL loading mechanism
used to initialize Tekla Structures integrations.

Tests involving actual DLL loading are skipped in CI environments where Tekla is not available.

Tested modules:
- init.py
"""

import os
import pytest
from unittest.mock import MagicMock, patch

import clr  # noqa: F401
import System

from tekla_mcp_server.init import load_dlls


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
def test_load_dlls_success():
    """Checks that all DLLs are loaded and returns True."""
    mock_config = MagicMock()
    mock_config.tekla_path = "C:\\Tekla"
    with patch("tekla_mcp_server.init.get_config", return_value=mock_config), patch("tekla_mcp_server.init.clr.AddReference") as mock_add_ref:
        assert load_dlls() is True
        assert mock_add_ref.call_count == 9  # 9 DLLs


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
def test_load_dlls_file_not_found_triggers_exception_and_exit():
    """Checks error handling when DLL is missing."""
    mock_config = MagicMock()
    mock_config.tekla_path = "C:\\Tekla"
    with (
        patch("tekla_mcp_server.init.get_config", return_value=mock_config),
        patch("tekla_mcp_server.init.clr.AddReference", side_effect=System.IO.FileNotFoundException),
        patch("tekla_mcp_server.init.logger.exception") as mock_exception,
        patch("tekla_mcp_server.init.sys.exit") as mock_exit,
    ):
        load_dlls()
        mock_exception.assert_called_once()
        mock_exit.assert_called_once_with(1)
