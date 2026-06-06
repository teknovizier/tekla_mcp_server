"""
Unit tests for DLL loading logic.

Tests that require DLL loading are skipped in CI environments where Tekla is not available.
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
    import tekla_mcp_server.init as init_module

    init_module._dlls_loaded = False

    mock_config = MagicMock()
    mock_config.tekla_path = "C:\\Tekla"
    with (
        patch("tekla_mcp_server.init.get_config", return_value=mock_config),
        patch("pathlib.Path.is_dir", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
        patch("tekla_mcp_server.init.clr.AddReference") as mock_add_ref,
    ):
        assert load_dlls() is True
        assert mock_add_ref.call_count == 18  # 9 DLLs * 2 paths


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
def test_load_dlls_file_not_found_triggers_exception_and_exit():
    """Checks error handling when DLL is missing."""
    import tekla_mcp_server.init as init_module

    init_module._dlls_loaded = False

    mock_config = MagicMock()
    mock_config.tekla_path = "C:\\Tekla"
    with (
        patch("tekla_mcp_server.init.get_config", return_value=mock_config),
        patch("pathlib.Path.is_dir", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
        patch(
            "tekla_mcp_server.init.clr.AddReference",
            side_effect=System.IO.FileNotFoundException,
        ),
        patch("tekla_mcp_server.init.logger.exception") as mock_exception,
    ):
        with pytest.raises(System.IO.FileNotFoundException):
            load_dlls()

        mock_exception.assert_called_once()
