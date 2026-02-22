"""
Template Attribute Parser for parsing Tekla template attributes.

This module provides functionality to:
1. Load attribute definitions from Tekla contentattributes file
2. Cache parsed attributes
3. Match user input to attributes using exact, normalized, and semantic matching
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tekla_mcp_server.init import logger
from tekla_mcp_server.config import get_config
from tekla_mcp_server.models import ReportProperty
from tekla_mcp_server.embeddings import get_embedding_model, get_embedding_threshold, semantic_match, is_embeddings_enabled
from tekla_mcp_server.utils import find_normalized_match

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class TemplateAttributeParser:
    """
    Lazily loads and parses Tekla attribute definitions from the template file.
    Supports semantic matching - tries exact match first, then falls back to semantic similarity.
    """

    _cache: dict[str, ReportProperty] = {}
    _loaded: bool = False
    _embeddings_cache: dict[str, list[float]] = {}
    _semantic_loaded: bool = False
    _model: "SentenceTransformer | None" = None

    @classmethod
    def _get_model(cls) -> "SentenceTransformer | None":
        if cls._model is None:
            cls._model = get_embedding_model()
        return cls._model

    @classmethod
    def _ensure_semantic_loaded(cls) -> None:
        if cls._semantic_loaded or not is_embeddings_enabled():
            return

        model = cls._get_model()
        if not model:
            return

        attribute_names = list(cls._cache.keys())
        if not attribute_names:
            return

        embeddings = model.encode(attribute_names)
        cls._embeddings_cache = {name: emb.tolist() for name, emb in zip(attribute_names, embeddings, strict=True)}
        cls._semantic_loaded = True
        logger.info("Generated embeddings for %d template attributes", len(attribute_names))

    @classmethod
    def _semantic_match(cls, user_input: str) -> str | None:
        cls._ensure_semantic_loaded()
        if not cls._embeddings_cache:
            return None

        model = cls._get_model()
        threshold = get_embedding_threshold()

        best_match, _ = semantic_match(user_input, cls._embeddings_cache, threshold, model)
        return best_match

    @classmethod
    def parse(cls, attribute_name: str) -> ReportProperty:
        """
        On first call, this function reads the Tekla template attributes file once,
        parses all attribute definitions, and caches them in memory. Subsequent calls
        return cached results instantly without re-reading the file.

        Tries exact match first, then falls back to semantic matching if exact fails.
        """
        if not cls._loaded:
            config = get_config()
            logger.debug("Loading Tekla attribute definitions from file '%s'", config.content_attributes_file_path)
            with open(config.content_attributes_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("//") or stripped.startswith("[") or stripped.lower().startswith("name"):
                        continue

                    first_split = re.split(r"\s", stripped, maxsplit=1)
                    if len(first_split) < 2:
                        continue

                    name = first_split[0].strip()
                    remainder = first_split[1].strip()
                    rest_parts = re.split(r"\s{2,}", remainder)
                    while len(rest_parts) < 8:
                        rest_parts.append(None)

                    dtype = rest_parts[0]
                    unit = rest_parts[6] if rest_parts[6] != "*" else None

                    cls._cache[name] = ReportProperty(name=name, data_type=ReportProperty.map_string_to_type(dtype), unit=unit)

            cls._loaded = True
            logger.info("Tekla attribute definitions loaded and cached")

        # Try normalized exact match
        matched_name = find_normalized_match(attribute_name, cls._cache)
        if matched_name:
            return cls._cache[matched_name]

        # Semantic matching only if embeddings are enabled
        if is_embeddings_enabled():
            matched_name = cls._semantic_match(attribute_name)
            if matched_name:
                return cls._cache[matched_name]

        raise ValueError(f"Attribute '{attribute_name}' not found.")
