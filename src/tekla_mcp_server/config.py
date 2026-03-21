"""
Centralized configuration manager for the Tekla MCP Server.

Loads configuration from JSON files in the config/ directory.
"""

import json
import os
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
    required_keys = ["tekla_path", "content_attributes_file_path"]
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
    """Get macro directories from Tekla's XS_MACRO_DIRECTORY advanced option.

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


class Config:
    """Centralized configuration manager - thin wrapper around cached functions."""

    @property
    def tekla_path(self) -> str:
        """Tekla Structures installation path."""
        return _load_settings()["tekla_path"]

    @property
    def content_attributes_file_path(self) -> str:
        """Path to Tekla content attributes file."""
        return _load_settings()["content_attributes_file_path"]

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
    def lifting_anchor_types(self) -> dict[str, Any]:
        """Lifting anchor type mappings."""
        return _load_json("lifting_anchor_types.json")

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
        """List of directories to scan for Tekla macros.

        Reads from Tekla's XS_MACRO_DIRECTORY advanced option.
        Returns only valid, existing directory paths.
        """
        return _get_tekla_macro_directories()

    @property
    def class_to_element(self) -> dict[int, tuple[str, str]]:
        """Returns class to element mapping."""
        return _get_class_to_element()


@lru_cache
def get_config() -> Config:
    """Get the singleton Config instance."""
    return Config()
