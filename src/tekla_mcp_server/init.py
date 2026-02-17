"""
This module handles the initialization of the application, including reading configuration
data and loading required Tekla Structures OpenAPI DLLs. It ensures that all necessary setup
steps are performed before the main application logic begins.
"""

import json
import logging
import os
import sys

from tekla_mcp_server.config import get_config
import clr
import System


# Constants
_log_level = os.getenv("TEKLA_MCP_LOG_LEVEL", "DEBUG")
_log_file_path = os.getenv("TEKLA_MCP_LOG_FILE_PATH", "mcp_server.log")

# Logging
logging.basicConfig(
    filename=_log_file_path,
    filemode="a",
    format="%(asctime)s: %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, _log_level))


def load_dlls() -> bool:
    """
    Loads Tekla Structures OpenAPI DLLs based on the configuration.

    This function reads the DLL path from the configuration file and loads the required
    libraries using the `clr` module. If any DLL is not found, an exception is raised,
    and the application exits.
    """
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
        sys.exit(1)

    tekla_path = config.tekla_path

    try:
        for dll in dlls:
            clr.AddReference(os.path.join(tekla_path, dll))

        logger.info("Successfully loaded all Tekla Structures DLLs")
        return True

    except System.IO.FileNotFoundException:
        logger.exception("Tekla Structures DLLs not found. Check the TEKLA_PATH environment variable or settings.json")
        sys.exit(1)
