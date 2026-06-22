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

# Name of the per-model runtime data directory
MCP_DATA_DIR_NAME = "TeklaMCPData"


# Config JSON files are read once and cached for the lifetime of the process.
# Changes to settings.json do not take effect until the MCP server is restarted
@lru_cache
def get_config_dir() -> Path:
    """
    Get the configuration directory path.

    Supports TEKLA_MCP_CONFIG_DIR environment variable override.

    Returns:
        Path to the configuration directory
    """
    env_dir = os.getenv("TEKLA_MCP_CONFIG_DIR", "config")
    return Path(env_dir)


# maxsize=None is safe here: config filenames are a small, fixed set, so
# the cache cannot grow without bound. It also removes any risk of a config file being
# silently evicted and re-read mid-session.
@lru_cache(maxsize=None)
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
    config_dir = get_config_dir()
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


def get_advanced_option_directories(option_name: str) -> list[str]:
    """
    Get existing directory paths from a semicolon-separated Tekla advanced option.

    Many Tekla advanced options (e.g. XS_MACRO_DIRECTORY, XS_TEMPLATE_DIRECTORY,
    XS_REPORT_OUTPUT_DIRECTORY) hold one or more semicolon-separated search paths.
    Relative paths (e.g. '.\\attributes') are resolved against the current model
    folder.

    Args:
        option_name: Advanced option name, e.g. 'XS_MACRO_DIRECTORY'.

    Returns:
        List of valid, existing directory paths from the setting,
        in declared order. Empty if the option is unset or no path exists.
    """
    from tekla_mcp_server.tekla.loader import TeklaStructuresSettings
    from tekla_mcp_server.tekla.wrappers.model import TeklaModel
    from tekla_mcp_server.init import logger

    _, option = TeklaStructuresSettings.GetAdvancedOption(option_name, str())
    if not option:
        return []

    # Relative paths in advanced options are relative to the model folder. If the
    # model folder cannot be read, log it - silently dropping relative entries would
    # otherwise surface to the caller as a misleading "option not set" error.
    try:
        model_path = TeklaModel().model_path
    except Exception as e:
        logger.warning("Could not read model folder while resolving '%s', relative paths will be skipped: %s", option_name, e)
        model_path = ""

    paths: list[str] = []
    skipped_relative = False
    for path_str in option.split(";"):
        raw = path_str.strip()
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            if not model_path:
                # Resolving a relative path against the process CWD is meaningless
                # here, so skip it rather than match an unrelated directory.
                skipped_relative = True
                continue
            path = Path(model_path) / path
        if path.is_dir():
            paths.append(str(path.resolve()))

    if skipped_relative and not paths:
        logger.warning("'%s' is set but only contains relative paths that could not be resolved (model folder unavailable)", option_name)
    return paths


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
            return str(get_config_dir() / name)
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
    def report_properties(self) -> dict[str, list[str]]:
        """Report property lists per object type."""
        return _load_json("report_properties.json")

    @property
    def read_only(self) -> bool:
        """When True, hide all tools marked as destructive from the LLM."""
        return bool(_load_settings().get("read_only", False))

    @property
    def excluded_tags(self) -> set[str]:
        """Set of tool tags to hide from the LLM."""
        tags = _load_settings().get("excluded_tags")
        if tags is None:
            return set()
        return set(tags)

    @property
    def context_folder(self) -> Path:
        """Folder containing project context markdown files."""
        folder = _load_settings().get("context_folder", "context")
        path = Path(folder)
        if not path.is_absolute():
            path = get_config_dir() / folder
        if not path.is_dir():
            return get_config_dir() / "context"
        return path

    @lru_cache
    def get_element_types_list(self) -> list[dict[str, Any]]:
        """Returns element types as flat list."""
        return [{"material": material, "type": type_name, "tekla_classes": config.get("tekla_classes", [])} for material, types in self.element_types.items() for type_name, config in types.items()]

    @lru_cache
    def get_element_types_flat(self) -> dict[int, dict[str, Any]]:
        """
        Returns tekla_class -> full config mapping.

        First occurrence wins when a class appears under multiple material groups,
        so a class shared between a structural type and a reinforcement/embedded
        type (e.g. 13 = concrete column and mesh) resolves to the structural entry,
        which element_types.json lists first.
        """
        result: dict[int, dict[str, Any]] = {}
        for types in self.element_types.values():
            for config in types.values():
                for tekla_class in config.get("tekla_classes", []):
                    result.setdefault(tekla_class, config)
        return result

    @lru_cache
    def get_custom_properties_schema(self, component_key: str) -> dict[str, dict[str, str]] | None:
        """Returns custom_properties schema for a component."""
        component = self.base_components.get(component_key)
        if component:
            return component.get("custom_properties")
        return None

    @lru_cache
    def get_component_by_tekla_name(self, tekla_name: str) -> dict[str, Any] | None:
        """Returns the component definition dict for the given tekla_name."""
        for comp in self.base_components.values():
            if comp.get("tekla_name") == tekla_name:
                return comp
        return None

    @lru_cache
    def get_report_props(self, key: str) -> list[str]:
        """Returns report property list for the given object type key."""
        return self.report_properties.get(key, [])


def get_report_preview_max_chars() -> int:
    """
    Get the maximum number of characters for report content preview.

    Returns:
        Max chars for preview (default 2000)
    """
    return int(_load_settings().get("reports", {}).get("preview_max_chars", 2000))


def get_report_preview_timeout() -> float:
    """
    Get the maximum time in seconds to wait for a report file to appear on disk.

    Returns:
        Timeout in seconds (default 30)
    """
    return float(_load_settings().get("reports", {}).get("preview_timeout", 30))


def get_export_timeout() -> float:
    """
    Get the maximum time in seconds to wait for exported files to appear on disk.

    Shared by `export_drawings`, `print_drawings` and `check_drawing_collisions`.

    Returns:
        Timeout in seconds (default 120)
    """
    return float(_load_settings().get("drawings", {}).get("timeout", 120))


def get_export_output_dir() -> str:
    """
    Get the configured drawing-export output directory.

    Shared by `export_drawings` and `print_drawings`. May be relative (resolved
    against the model folder at call time) or absolute. Defaults to './PlotFiles'.
    """
    return _load_settings().get("drawings", {}).get("output_dir", "./PlotFiles")


def get_default_export_settings() -> str:
    """
    Get the default customer export settings name for `export_drawings`.

    When non-empty, `export_drawings` uses these settings as-is by default.
    When empty (the default), exports run in on-the-go mode, patching the base
    settings with the chosen format/version.
    """
    return _load_settings().get("drawings", {}).get("export", {}).get("default_export_settings", "")


def get_default_print_settings() -> str:
    """
    Get the default customer print settings name for `print_drawings`.

    When non-empty, `print_drawings` uses these settings as-is by default.
    When empty (the default), prints run in on-the-go mode, patching the base
    settings with the auto-detected paper size and multi-sheet tiling.
    """
    return _load_settings().get("drawings", {}).get("print", {}).get("default_print_settings", "")


def get_mcp_data_dir(model_path: str) -> Path:
    """
    Return the TeklaMCPData directory for runtime data in the given model.

    Creates the directory if it doesn't exist.
    """
    data_dir = Path(model_path) / MCP_DATA_DIR_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_tolerance(name: str, default: float, group: str = "model") -> float:
    """
    Get a tolerance value from configuration.

    Tolerances are grouped by domain (`model` for model operations,
    `drawings` for drawing layout).

    Args:
        name: Tolerance key within the group.
        default: Fallback value if the key is missing. Required so every call
            site states a unit-appropriate fallback (mm for distances, a small
            fraction for factors) instead of silently inheriting a spatial
            default that is meaningless outside the `model` group.
        group: Tolerance group, "model" (default) or "drawings".

    Returns:
        Tolerance value in mm (or unitless for factor)
    """
    group_tolerances = _load_settings().get("tolerances", {}).get(group, {})
    return group_tolerances.get(name, default)


@lru_cache
def get_config() -> Config:
    """Get the singleton Config instance."""
    return Config()
