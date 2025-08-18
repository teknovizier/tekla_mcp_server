"""
This module handles the initialization of the application, including reading configuration
data and loading required Tekla Structures OpenAPI DLLs. It ensures that all necessary setup
steps are performed before the main application logic begins.
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any
import clr
import System


# Constants
CONFIG_FILE_PATH = Path(__file__).parent.joinpath("config", "settings.json")  # Path to the configuration file
LOG_FILE_PATH = Path(__file__).parent.joinpath("app.log")  # Path to the log file

# Logging
logging.basicConfig(
    filename=str(LOG_FILE_PATH),  # Log file name
    filemode="a",  # Append mode
    format="%(asctime)s: %(levelname)s: %(message)s",  # Format for log messages
    datefmt="%Y-%m-%d %H:%M:%S",  # Date format
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Set logging level to DEBUG for detailed output


# Functions
def read_config() -> dict[str, Any]:
    """
    Reads and validates the configuration data from `config.json`.

    The configuration file is expected to be located in the same directory as the script.
    This function ensures that all required keys are present and have the correct data types.
    Missing or invalid keys result in an exception, and the application exits.
    """

    def validate_config(config) -> dict[str, Any]:
        """
        Validates the structure of the configuration data.

        Checks that all required keys are present and have the correct types.
        """

        required_keys = {"tekla_path": str, "content_attributes_file_path": str}

        # Check for required keys and types at the top level
        for key, expected_type in required_keys.items():
            if key not in config:
                raise ValueError(f"Missing required key: '{key}'")
            elif not isinstance(config[key], expected_type):
                raise ValueError(f"Key `{key}` must be of type {expected_type.__name__}, but got {type(config[key]).__name__}")

    try:
        with CONFIG_FILE_PATH.open("r", encoding="utf-8") as f:
            config = json.load(f)
            validate_config(config)
            logger.info("Successfully read config file")
            return config
    except FileNotFoundError as e:
        logger.exception("Configuration file not found: %s", e)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.exception("Invalid JSON format in configuration file: %s", e)
        sys.exit(1)
    except ValueError as e:
        logger.exception("Invalid configuration file structure: %s", e)
        sys.exit(1)


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
    config = read_config()
    tekla_path = config["tekla_path"]

    try:
        for dll in dlls:
            clr.AddReference(os.path.join(tekla_path, dll))

        logger.info("Successfully loaded all Tekla Structures DLLs")
        return True

    except System.IO.FileNotFoundException:
        logger.exception("Tekla Structures DLLs not found. Check the `tekla_path` parameter in configuration file: '%s'", CONFIG_FILE_PATH)
        sys.exit(1)
