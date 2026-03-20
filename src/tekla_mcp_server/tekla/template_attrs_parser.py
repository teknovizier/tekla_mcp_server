"""
Template Attribute Parser for parsing Tekla template attributes.

This module provides functionality to:
1. Load attribute definitions from Tekla contentattributes file
2. Resolve attributes with spread-based confidence detection
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np

from tekla_mcp_server.init import logger
from tekla_mcp_server.config import get_config
from tekla_mcp_server.models import ReportProperty
from tekla_mcp_server.embeddings import (
    get_compute_device,
    get_embedding_model,
    is_embeddings_enabled,
)
from tekla_mcp_server.utils import find_normalized_match, normalize_for_embedding

if TYPE_CHECKING:
    import torch


class TemplateAttributeParser:
    """Parse Tekla template attributes and resolve queries with optional embeddings."""

    _cache: dict[str, ReportProperty] = {}
    _loaded: bool = False
    _embeddings_cache: dict[str, "torch.Tensor"] = {}
    _semantic_loaded: bool = False

    @classmethod
    def preload(cls) -> None:
        """Load attributes and embeddings if not already loaded."""
        cls._load_attributes()
        if cls._semantic_loaded or not is_embeddings_enabled():
            return

        model = get_embedding_model()
        device = get_compute_device()
        names = list(cls._cache.keys())
        if not names:
            return

        normalized_labels = [normalize_for_embedding(n) for n in names]
        embeddings = model.encode(normalized_labels, convert_to_tensor=True, device=device)
        cls._embeddings_cache = {n: e for n, e in zip(names, embeddings, strict=True)}
        cls._semantic_loaded = True
        logger.info("Generated embeddings for %d template attributes", len(names))

    @classmethod
    def _load_attributes(cls) -> None:
        """Load attribute definitions from Tekla contentattributes file into cache."""
        if cls._loaded:
            return

        config = get_config()
        logger.debug("Loading Tekla attribute definitions from '%s'", config.content_attributes_file_path)

        with open(config.content_attributes_file_path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("[BINDINGS]"):
                    break
                if not s or s.startswith("//") or s.startswith("["):
                    continue

                parts = re.split(r"\s", s, maxsplit=1)
                if len(parts) < 2:
                    continue

                name, remainder = parts[0].strip(), parts[1].strip()
                rest_parts = re.split(r"\s{2,}", remainder)
                while len(rest_parts) < 8:
                    rest_parts.append(None)

                dtype = rest_parts[0]
                unit = rest_parts[6] if rest_parts[6] != "*" else None
                cls._cache[name] = ReportProperty(name=name, data_type=ReportProperty.map_string_to_type(dtype), unit=unit)

        cls._loaded = True
        logger.info("Tekla attribute definitions loaded and cached")

    @classmethod
    def resolve_attributes(cls, queries: list[str]) -> dict:
        """
        Resolve attribute queries to Tekla attribute names.

        Resolution order:
        1. Exact/normalized match against attribute cache
        2. Semantic overrides
        3. MiniLM embeddings with spread-based confidence and minimum threshold

        Returns resolved names and ambiguous queries with candidates for LLM.
        """
        cls.preload()
        spread_threshold = get_config().embedding_spread_threshold
        min_threshold = get_config().embedding_minimum_threshold
        top_k = 10

        resolved, errors = [], []

        for query in queries:
            name = find_normalized_match(query, cls._cache)
            if not name:
                name = cls._override_match(query)
            if not name and cls._embeddings_cache:
                result = cls._get_candidates(query, spread_threshold=spread_threshold, min_threshold=min_threshold, top_k=top_k)
                if isinstance(result, str):
                    resolved.append(result)
                else:
                    errors.append({"query": query, "candidates": result})
            elif name:
                resolved.append(name)
            else:
                errors.append({"query": query, "candidates": []})

        return {"resolved": resolved, "errors": errors}

    @classmethod
    def _override_match(cls, user_input: str) -> str | None:
        """Match user input against configured semantic overrides."""
        overrides = get_config().semantic_overrides
        query = user_input.lower().strip()
        query_tokens = set(re.findall(r"\w+", query))

        if query in overrides:
            return overrides[query]

        for key in sorted(overrides, key=len, reverse=True):
            key_tokens = set(re.findall(r"\w+", key))
            if len(key_tokens) >= 2 and key_tokens.issubset(query_tokens):
                return overrides[key]

        return None

    @classmethod
    def _compute_similarity(cls, query: str) -> tuple[list[str], list[float]]:
        """Compute cosine similarity between query and all cached attributes."""
        if not cls._embeddings_cache:
            return [], []

        model = get_embedding_model()
        device = get_compute_device()
        normalized_query = normalize_for_embedding(query)
        user_embedding = model.encode(normalized_query, convert_to_tensor=True, device=device)

        from sentence_transformers import util
        import torch

        names = list(cls._embeddings_cache.keys())
        embeddings = torch.stack(list(cls._embeddings_cache.values()))
        scores = util.cos_sim(user_embedding, embeddings)[0]

        return names, scores.tolist()

    @classmethod
    def _get_candidates(cls, query: str, spread_threshold: float, min_threshold: float, top_k: int = 10) -> str | list[str]:
        """
        Compute top-k candidates using MiniLM embeddings.
        If spread of top-k scores exceeds threshold AND top score >= min_threshold,
        returns top candidate (string). Otherwise, returns list of candidates for LLM fallback.
        """
        names, scores = cls._compute_similarity(query)
        if not names:
            return []

        top_indices = np.argsort(scores)[-top_k:][::-1]
        top_scores = [scores[i] for i in top_indices]
        top_candidates = [names[i] for i in top_indices]

        top_score = top_scores[0] if top_scores else 0.0
        spread = np.std(top_scores) if len(top_scores) > 1 else 1.0
        if spread > spread_threshold and top_score >= min_threshold:
            return top_candidates[0]

        return top_candidates

    @classmethod
    def get_attribute(cls, attribute_name: str) -> ReportProperty:
        """
        Return attribute metadata by exact name.

        Args:
            attribute_name: Exact Tekla attribute name (e.g., "AREA_NET")

        Returns:
            ReportProperty with type, unit, etc.

        Raises:
            KeyError: If attribute not found
        """
        cls.preload()
        return cls._cache[attribute_name]
