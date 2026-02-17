"""
Centralized configuration manager for the Tekla MCP Server.

Loads configuration from JSON files in the config/ directory.
"""

import json
import os
from functools import cached_property
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def _get_config_dir() -> Path:
    """Get config directory, supporting TEKLA_MCP_CONFIG_DIR env var."""
    env_dir = os.getenv("TEKLA_MCP_CONFIG_DIR", "config")
    return Path(env_dir)


class Config:
    """Centralized configuration manager with lazy loading."""

    _config_dir: Path = _get_config_dir()

    @cached_property
    def _settings(self) -> dict[str, Any]:
        """Load settings.json with env var overrides."""
        settings = self._load_json("settings.json")

        # Validate required keys
        required_keys = ["tekla_path", "content_attributes_file_path"]
        for key in required_keys:
            if key not in settings:
                raise ValueError(f"Missing required key '{key}' in settings.json")

        return settings

    @cached_property
    def _element_types(self) -> dict[str, Any]:
        """Load element types configuration."""
        return self._load_json("element_types.json")

    @cached_property
    def _lifting_anchor_types(self) -> dict[str, Any]:
        """Load lifting anchor types configuration."""
        return self._load_json("lifting_anchor_types.json")

    @cached_property
    def _base_components(self) -> dict[str, Any]:
        """Load base components configuration."""
        return self._load_json("base_components.json")

    def _load_json(self, filename: str) -> dict[str, Any]:
        """Load a JSON config file."""
        file_path = self._config_dir.joinpath(filename)
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Invalid JSON in {file_path}: {e}", e.doc, e.pos)

    @property
    def tekla_path(self) -> str:
        """Tekla Structures installation path."""
        return self._settings["tekla_path"]

    @property
    def content_attributes_file_path(self) -> str:
        """Path to Tekla content attributes file."""
        return self._settings["content_attributes_file_path"]

    @property
    def attribute_mapper(self) -> dict[str, Any]:
        """Attribute mapper configuration."""
        return self._settings.get("attribute_mapper", {})

    @property
    def embedding_model(self) -> str | None:
        """Embedding model name."""
        return self.attribute_mapper.get("embedding_model")

    @property
    def embedding_threshold(self) -> float | None:
        """Embedding threshold."""
        return self.attribute_mapper.get("embedding_threshold")

    @property
    def element_types(self) -> dict[str, Any]:
        """Element type mappings."""
        return self._element_types

    @property
    def lifting_anchor_types(self) -> dict[str, Any]:
        """Lifting anchor type mappings."""
        return self._lifting_anchor_types

    @property
    def base_components(self) -> dict[str, Any]:
        """Base component definitions."""
        return self._base_components


_config: Config | None = None


def get_config() -> Config:
    """Get the singleton Config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
