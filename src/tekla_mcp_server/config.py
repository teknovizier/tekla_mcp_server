"""
Centralized configuration manager for the Tekla MCP Server.

Loads configuration from JSON files in the config/ directory.
"""

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


@lru_cache
def _get_config_dir() -> Path:
    """
    Get the configuration directory path.

    Supports TEKLA_MCP_CONFIG_DIR environment variable override.

    Returns:
        Path to the configuration directory
    """
    env_dir = os.getenv("TEKLA_MCP_CONFIG_DIR", "config")
    return Path(env_dir)


@lru_cache(maxsize=8)
def _load_json(filename: str) -> dict[str, Any]:
    """
    Load a JSON config file with caching.

    Args:
        filename: Name of the JSON configuration file

    Returns:
        Dictionary containing the parsed JSON data

    Raises:
        FileNotFoundError: If the configuration file does not exist
        json.JSONDecodeError: If the file contains invalid JSON
    """
    config_dir = _get_config_dir()
    file_path = config_dir / filename
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Invalid JSON in {file_path}: {e}", e.doc, e.pos) from e


@lru_cache
def _load_settings() -> dict[str, Any]:
    """
    Load and validate settings.json configuration.

    Returns:
        Dictionary containing the validated settings

    Raises:
        ValueError: If required keys are missing from the settings
    """
    settings = _load_json("settings.json")
    required_keys = ["tekla_path"]
    for key in required_keys:
        if key not in settings:
            raise ValueError(f"Missing required key '{key}' in settings.json")
    return settings


@lru_cache
def _get_tekla_macro_directories() -> list[str]:
    """
    Get macro directories from Tekla's XS_MACRO_DIRECTORY advanced option.

    Returns:
        List of valid, existing directory paths from the macro directory setting
    """
    from tekla_mcp_server.tekla.loader import TeklaStructuresSettings

    _, option = TeklaStructuresSettings.GetAdvancedOption("XS_MACRO_DIRECTORY", str())
    if not option:
        return []

    paths: list[str] = []
    for path_str in option.split(";"):
        path = Path(path_str.strip())
        if path.is_dir():
            paths.append(str(path.resolve()))
    return paths


@lru_cache
def _get_contentattributes_file_paths() -> list[str]:
    """
    Get all contentattributes file paths from tpled.ini INCLUDE statements.

    Returns:
        List of paths to all .lst files referenced in the main contentattributes file
    """

    from tekla_mcp_server.tekla.loader import TeklaStructuresSettings
    from tekla_mcp_server.init import logger

    def resolve_path(raw_path: str, base: Path, tekla_base: Path) -> Path | None:
        """
        Resolve a raw path relative to base or tekla_base.

        Args:
            raw_path: The raw path string to resolve
            base: Base path for resolution
            tekla_base: Tekla base path for resolution

        Returns:
            Resolved Path object, or None if path escapes the base directory
        """
        try:
            if raw_path.startswith("@") and len(raw_path) > 1 and raw_path[1] in ("\\", "/"):
                resolved = base.parent / raw_path[2:]
            elif raw_path.startswith(".") and len(raw_path) > 1 and raw_path[1] in ("\\", "/"):
                resolved = tekla_base / raw_path[2:]
            else:
                resolved = base.parent / raw_path

            resolved = resolved.resolve()
            base_root = base.parent.resolve()
            tekla_root = tekla_base.resolve()

            if not (resolved.is_relative_to(base_root) or resolved.is_relative_to(tekla_root)):
                logger.warning("Rejected path traversal attempt: %s", raw_path)
                return None

            return resolved

        except Exception as e:
            logger.warning("Failed to resolve path %s: %s", raw_path, e)
            return None

    # Get tpled.ini location
    _, tpled_ini_path = TeklaStructuresSettings.GetAdvancedOption("XS_TPLED_INI", str())
    if not tpled_ini_path:
        return []

    ini_path = Path(tpled_ini_path)
    if ini_path.is_dir():
        ini_path = ini_path / "tpled.ini"
    if not ini_path.exists():
        return []

    tekla_base = Path(_load_settings()["tekla_path"]) / "applications" / "Tekla" / "Tools" / "TplEd"

    # Find main contentattributes.lst file
    content_attr_path: Path | None = None
    for line in ini_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "contentattributes.lst" in line.lower():
            content_attr_path = resolve_path(line.strip(), ini_path, tekla_base)
            break

    if not content_attr_path or not content_attr_path.exists():
        return []

    # Parse included files
    included_files: list[str] = []
    try:
        for line in content_attr_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("[BINDINGS]"):
                break
            if not stripped or stripped.startswith("//") or not stripped.startswith("[INCLUDE"):
                continue

            match = re.search(r"\[INCLUDE\s+(.+)\]", stripped, re.IGNORECASE)
            if match:
                resolved = resolve_path(match.group(1).strip(), content_attr_path, tekla_base)
                if resolved and resolved.exists():
                    included_files.append(str(resolved))
                elif resolved:
                    logger.warning("Included file not found: %s", resolved)
    except FileNotFoundError:
        logger.warning("contentattributes.lst not found at: %s", content_attr_path)
    except Exception as e:
        logger.warning("Failed to parse contentattributes file: %s", e)

    return included_files


class Config:
    """Centralized configuration manager - thin wrapper around cached functions."""

    @property
    def tekla_path(self) -> str:
        """Tekla Structures installation path."""
        return _load_settings()["tekla_path"]

    @property
    def content_attributes_file_paths(self) -> list[str]:
        """List of all Tekla contentattributes file paths from tpled.ini INCLUDE statements."""
        return _get_contentattributes_file_paths()

    @property
    def template_attributes_json_path(self) -> str | None:
        """Full path to template attributes JSON file."""
        name = _load_settings().get("template_attributes_json_name")
        if name:
            return str(_get_config_dir() / name)
        return None

    @property
    def embeddings(self) -> dict[str, Any]:
        """Embeddings configuration."""
        return _load_settings().get("embeddings", {})

    @property
    def embeddings_enabled(self) -> bool:
        """Whether embeddings/semantic search is enabled."""
        return self.embeddings.get("enabled", True)

    @property
    def embedding_model(self) -> str | None:
        """Embedding model name."""
        return self.embeddings.get("embedding_model")

    @property
    def embedding_spread_threshold(self) -> float:
        """Embedding spread threshold for confidence detection (default 0.1)."""
        return self.embeddings.get("embedding_spread_threshold", 0.1)

    @property
    def embedding_minimum_threshold(self) -> float:
        """Minimum embedding confidence to resolve directly (default 0.8)."""
        return self.embeddings.get("embedding_minimum_threshold", 0.8)

    @property
    def element_types(self) -> dict[str, Any]:
        """Element type mappings."""
        return _load_json("element_types.json")

    @property
    def base_components(self) -> dict[str, Any]:
        """Base component definitions."""
        return _load_json("base_components.json")

    @property
    def semantic_overrides(self) -> dict[str, Any]:
        """Semantic override configuration."""
        return _load_json("semantic_overrides.json")

    @property
    def tekla_macro_directories(self) -> list[str]:
        """List of directories to scan for Tekla macros."""
        return _get_tekla_macro_directories()

    @property
    def requirements_folder(self) -> Path:
        """Folder containing requirements markdown files."""
        folder = _load_settings().get("requirements_folder", "requirements")
        path = Path(folder)
        if not path.is_absolute():
            path = _get_config_dir() / folder
        if not path.is_dir():
            return _get_config_dir() / "requirements"
        return path

    @lru_cache
    def load_requirements(self) -> str:
        """Load and combine all markdown files from requirements folder."""
        folder = self.requirements_folder
        if not folder.exists():
            return "# Requirements\n\nRequirements folder not found."
        files = sorted(folder.glob("*.md"))
        if not files:
            return "# Requirements\n\nNo requirements files found."
        contents = []
        for f in files:
            contents.append(f.read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(contents)

    @lru_cache
    def get_element_types_list(self) -> list[dict[str, Any]]:
        """Returns element types as flat list."""
        return [{"material": material, "type": type_name, "tekla_classes": config.get("tekla_classes", [])} for material, types in self.element_types.items() for type_name, config in types.items()]

    @lru_cache
    def get_element_types_flat(self) -> dict[int, dict[str, Any]]:
        """Returns tekla_class -> full config mapping."""
        result: dict[int, dict[str, Any]] = {}
        for types in self.element_types.values():
            for config in types.values():
                for tekla_class in config.get("tekla_classes", []):
                    result[tekla_class] = config
        return result

    @lru_cache
    def get_custom_properties_schema(self, component_key: str) -> dict[str, dict[str, str]] | None:
        """Returns custom_properties schema for a component."""
        component = self.base_components.get(component_key)
        if component:
            return component.get("custom_properties")
        return None


def get_tolerance(name: str = "default") -> float:
    """
    Get a tolerance value from configuration.

    Args:
        name: Tolerance key

    Returns:
        Tolerance value in mm (or unitless for factor)
    """
    tolerances = _load_settings().get("tolerances", {})
    return tolerances.get(name, 20.0)


@lru_cache
def get_config() -> Config:
    """Get the singleton Config instance."""
    return Config()
