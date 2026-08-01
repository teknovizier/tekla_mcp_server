"""
This module handles the initialization of the application, including reading configuration
data and loading required Tekla Structures OpenAPI DLLs. It ensures that all necessary setup
steps are performed before the main application logic begins.
"""

import json
import logging
import os
import sys
import threading

from pathlib import Path

from tekla_mcp_server.config import get_config

import clr
import System


# Cached load outcome and lock to prevent re-loading DLLs. None means "not attempted
# yet". A failed attempt is cached too, so a partial load is not silently retried on
# every later call - which would repeat the sys.path and Console.SetOut side effects
_load_result: bool | None = None
_dlls_loaded_lock = threading.Lock()

# Constants
_log_level = os.getenv("TEKLA_MCP_LOG_LEVEL", "INFO")
_log_file_path = os.getenv("TEKLA_MCP_LOG_FILE_PATH", "mcp_server.log")

# Logging
logging.basicConfig(
    filename=_log_file_path,
    filemode="a",
    format="%(asctime)s: %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, _log_level.upper(), logging.INFO))


def load_dlls() -> bool:
    """
    Loads Tekla Structures OpenAPI DLLs based on the configuration.

    This function reads the DLL path from the configuration file and loads the required
    libraries using the `clr` module. If any DLL is not found, an exception is raised,
    and the application exits.

    Side effect: redirects .NET Console.Out to Console.Error for the lifetime of the
    process, so Tekla API output does not corrupt the MCP stdio transport.

    The outcome of the first attempt is cached, so later calls report the same
    result without repeating the load and its process-wide side effects.

    Returns:
        True if all DLLs were loaded successfully, False if only some were.

    Raises:
        FileNotFoundError: If Tekla DLLs are not found at the configured path.
        System.IO.FileNotFoundException: If a specific DLL cannot be loaded.
        json.JSONDecodeError: If configuration file is invalid.
    """
    global _load_result

    with _dlls_loaded_lock:
        if _load_result is not None:
            return _load_result

        dlls = [
            "Tekla.Structures.dll",
            "Tekla.Structures.Plugins.dll",
            "Tekla.Structures.Model.dll",
            "Tekla.Structures.DataType.dll",
            "Tekla.Structures.Geometry3d.Compatibility.dll",
            "Tekla.Structures.Dialog.dll",
            "Tekla.Structures.Analysis.dll",
            "Tekla.Structures.Catalogs.dll",
            "Tekla.Structures.Drawing.dll",
        ]

        # Read configuration data
        try:
            config = get_config()
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
            logger.exception("Failed to load configuration: %s", e)
            raise

        tekla_path = Path(config.tekla_path)

        # Include Tekla 2026 runtime folder
        tekla_paths = [
            tekla_path,
            tekla_path / "Net48Runtime",
        ]

        # Python.NET uses sys.path to resolve dependent Tekla assemblies
        for path in tekla_paths:
            sys.path.append(str(path))

        loaded_dlls: set[str] = set()

        # Redirect .NET Console.Out to stderr before loading DLLs so that any
        # .NET console output during assembly initialization does not corrupt
        # the MCP stdio transport.
        try:
            System.Console.SetOut(System.Console.Error)
        except Exception:
            logger.warning("Failed to redirect .NET Console.Out to stderr")

        try:
            for path in tekla_paths:
                if path.is_dir():
                    for dll in dlls:
                        dll_path = path / dll
                        if dll_path.exists():
                            clr.AddReference(str(dll_path))
                            loaded_dlls.add(dll)

            if len(loaded_dlls) != len(dlls):
                logger.error("Only %d out of %d Tekla Structures DLLs were loaded", len(loaded_dlls), len(dlls))
                _load_result = False
                return False

            _load_result = True
            logger.info("Successfully loaded %d out of %d Tekla Structures DLLs", len(loaded_dlls), len(dlls))
            return True

        except System.IO.FileNotFoundException:
            logger.exception("Tekla Structures DLLs not found. Check the TEKLA_PATH environment variable or settings.json")
            raise
