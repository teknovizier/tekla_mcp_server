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
    """Get config directory, supporting TEKLA_MCP_CONFIG_DIR env var."""
    env_dir = os.getenv("TEKLA_MCP_CONFIG_DIR", "config")
    return Path(env_dir)


@lru_cache(maxsize=8)
def _load_json(filename: str) -> dict[str, Any]:
    """Load a JSON config file with caching."""
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
    """Load settings.json with validation."""
    settings = _load_json("settings.json")
    required_keys = ["tekla_path"]
    for key in required_keys:
        if key not in settings:
            raise ValueError(f"Missing required key '{key}' in settings.json")
    return settings


@lru_cache
def _get_class_to_element() -> dict[int, tuple[str, str]]:
    """Lazy-loaded class to element mapping."""
    element_types = _load_json("element_types.json")
    result: dict[int, tuple[str, str]] = {}
    for material, types in element_types.items():
        for element_type, class_numbers in types.items():
            for cn in class_numbers:
                result[cn] = (material, element_type)
    return result


@lru_cache
def _get_tekla_macro_directories() -> list[str]:
    """
    Get macro directories from Tekla's XS_MACRO_DIRECTORY advanced option.
    Returns only valid, existing directory paths.
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
    """Get all contentattributes file paths from tpled.ini INCLUDE statements.
    Returns list of paths to all .lst files referenced in the main contentattributes file.
    """

    def resolve_path(raw_path: str, base: Path, tekla_base: Path) -> Path:
        """Resolve a raw path relative to base or tekla_base."""
        if raw_path.startswith("@") and len(raw_path) > 1 and raw_path[1] in ("\\", "/"):
            return base.parent / raw_path[2:]
        if raw_path.startswith(".") and len(raw_path) > 1 and raw_path[1] in ("\\", "/"):
            return tekla_base / raw_path[2:]
        return base.parent / raw_path

    from tekla_mcp_server.tekla.loader import TeklaStructuresSettings

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
                if resolved.exists():
                    included_files.append(str(resolved))
    except FileNotFoundError:
        return []

    return included_files


class Config:
    """Centralized configuration manager - thin wrapper around cached functions."""

    @property
    def tekla_path(self) -> str:
        """Tekla Structures installation path."""
        return _load_settings()["tekla_path"]

    @property
    def content_attributes_file_path(self) -> str:
        """Path to main Tekla content attributes file (deprecated, use content_attributes_file_paths)."""
        return str(Path(self.tekla_path) / "applications" / "Tekla" / "Tools" / "TplEd" / "settings" / "contentattributes_global.lst")

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
    def class_to_element(self) -> dict[int, tuple[str, str]]:
        """Returns class to element mapping."""
        return _get_class_to_element()

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
    def _load_requirements(self) -> str:
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
def get_config() -> Config:
    """Get the singleton Config instance."""
    return Config()
