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
from tekla_mcp_server.embeddings import (
    get_compute_device,
    get_embedding_model,
    get_embedding_threshold,
    is_embeddings_enabled,
)
from tekla_mcp_server.utils import find_normalized_match, normalize_for_embedding

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer
    import torch


class TemplateAttributeParser:
    """
    Lazily loads and parses Tekla attribute definitions from the template file.
    Supports semantic matching - tries exact match first, then falls back to semantic similarity.
    """

    _cache: dict[str, ReportProperty] = {}
    _loaded: bool = False
    _embeddings_cache: dict[str, "torch.Tensor"] = {}
    _semantic_loaded: bool = False
    _model: "SentenceTransformer | None" = None
    _semantic_match_cache: dict[str, str | None] = {}
    _parse_cache: dict[str, ReportProperty] = {}

    @classmethod
    def _load_attributes(cls) -> None:
        """Load Tekla attribute definitions from file."""
        if cls._loaded:
            return

        config = get_config()
        logger.debug("Loading Tekla attribute definitions from file '%s'", config.content_attributes_file_path)
        with open(config.content_attributes_file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("[BINDINGS]"):
                    break
                if not stripped or stripped.startswith("//") or stripped.startswith("["):
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

    @classmethod
    def _get_model(cls) -> "SentenceTransformer | None":
        if cls._model is None:
            cls._model = get_embedding_model()
        return cls._model

    @classmethod
    def preload(cls) -> None:
        cls._load_attributes()

        if cls._semantic_loaded or not is_embeddings_enabled():
            return

        model = cls._get_model()
        if not model:
            return

        attribute_names = list(cls._cache.keys())
        if not attribute_names:
            return

        device = get_compute_device()
        attribute_names = list(cls._cache.keys())
        normalized_labels = [normalize_for_embedding(name) for name in attribute_names]

        embeddings = model.encode(normalized_labels, convert_to_tensor=True, device=device)
        cls._embeddings_cache = {name: emb for name, emb in zip(attribute_names, embeddings, strict=True)}

        cls._semantic_loaded = True
        logger.info("Generated embeddings for %d template attributes", len(attribute_names))

    @classmethod
    def _override_match(cls, user_input: str) -> str | None:
        """
        Override match.

        Overrides resolve known ambiguous phrases before semantic
        embedding matching is executed.
        """
        overrides = get_config().semantic_overrides

        query = user_input.lower().strip()
        query_tokens = set(re.findall(r"\w+", query))

        # Exact match
        if query in overrides:
            return overrides[query]

        for key in sorted(overrides, key=len, reverse=True):
            key_tokens = set(re.findall(r"\w+", key))

            if len(key_tokens) < 2:
                continue

            if key_tokens.issubset(query_tokens):
                return overrides[key]

        return None

    @classmethod
    def _semantic_match(cls, user_input: str) -> str | None:
        """
        Semantic match.
        Returns the attribute name of the best match above threshold.
        """
        if not cls._embeddings_cache:
            logger.debug("Semantic match for '%s': no embeddings cache", user_input)
            return None

        model = cls._get_model()
        if not model:
            logger.debug("Semantic match for '%s': no model", user_input)
            return None

        # Check cache
        if user_input in cls._semantic_match_cache:
            return cls._semantic_match_cache[user_input]

        from sentence_transformers import util
        import torch

        logger.debug("Semantic match for '%s'", user_input)

        # Encode user input, convert to tensor
        device = get_compute_device()
        normalized_query = normalize_for_embedding(user_input)
        user_embedding = model.encode(normalized_query, convert_to_tensor=True, device=device)

        # Stack all attribute name embeddings for batch similarity
        attribute_names = list(cls._embeddings_cache.keys())
        all_name_embeddings = torch.stack(list(cls._embeddings_cache.values()))
        scores = util.cos_sim(user_embedding, all_name_embeddings)[0]

        # Find best match above threshold
        threshold = get_embedding_threshold()
        best_score, best_idx = torch.max(scores, dim=0)
        best_score_val = best_score.item()
        attribute = attribute_names[best_idx]

        # Log top 5 matches for debugging
        top5_scores, top5_indices = torch.topk(scores, k=5)
        top5_log = ", ".join(f"{attribute_names[idx]} ({score:.2f})" for score, idx in zip(top5_scores.tolist(), top5_indices.tolist()))
        logger.debug("Top 5 semantic matches for '%s': %s", user_input, top5_log)

        if best_score_val >= threshold:
            cls._semantic_match_cache[user_input] = attribute
            logger.debug("Semantic match result: '%s' (score: %.2f)", attribute, best_score_val)
            return attribute
        else:
            cls._semantic_match_cache[user_input] = None
            logger.debug("Semantic match result: no match above threshold %.2f", threshold)
            return None

    @classmethod
    def parse(cls, attribute_name: str) -> ReportProperty:
        """
        On first call, this function reads the Tekla template attributes file once,
        parses all attribute definitions, and caches them in memory. Subsequent calls
        return cached results instantly without re-reading the file.

        Matching priority:
        1. Exact/normalized match on attribute names
        2. Override match
        3. Semantic match
        """
        if attribute_name in cls._parse_cache:
            return cls._parse_cache[attribute_name]

        logger.debug("Parsing attribute: '%s'", attribute_name)

        # Ensure attributes and embeddings are loaded
        cls.preload()

        # 1. Try normalized exact match
        matched_name = find_normalized_match(attribute_name, cls._cache)
        if matched_name:
            logger.debug("Exact match found: '%s'", matched_name)
            result = cls._cache[matched_name]
            cls._parse_cache[attribute_name] = result
            return result

        logger.debug("No exact match, trying semantic matching")

        # 2. Override match
        override_match = cls._override_match(attribute_name)
        if override_match:
            logger.debug("Override match found: '%s'", override_match)
            result = cls._cache[override_match]
            cls._parse_cache[attribute_name] = result
            return result

        # 3. Semantic matching if enabled
        if is_embeddings_enabled():
            logger.debug("No exact match, trying semantic matching")

            semantic_match = cls._semantic_match(attribute_name)
            if semantic_match:
                logger.debug("Semantic match found: '%s'", semantic_match)
                result = cls._cache[semantic_match]
                cls._parse_cache[attribute_name] = result
                return result

        logger.warning("Attribute not found: '%s'", attribute_name)
        raise ValueError(f"Attribute '{attribute_name}' not found.")
