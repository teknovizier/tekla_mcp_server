"""
Template Attribute Parser for parsing Tekla template attributes.

This module provides functionality to:
1. Load attribute definitions from Tekla contentattributes file
2. Cache parsed attributes
3. Match user input to attributes using exact, normalized, and semantic matching
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from tekla_mcp_server.init import logger
from tekla_mcp_server.config import get_config
from tekla_mcp_server.models import ReportProperty
from tekla_mcp_server.embeddings import (
    get_embedding_model,
    get_embedding_threshold,
    get_embedding_name_weight,
    get_embedding_description_weight,
    is_embeddings_enabled,
)
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
    _description_embeddings_cache: dict[str, list[float]] = {}
    _semantic_loaded: bool = False
    _model: "SentenceTransformer | None" = None
    _descriptions_cache: dict[str, str] = {}
    _semantic_match_cache: dict[str, str | None] = {}
    _parse_cache: dict[str, ReportProperty] = {}

    @classmethod
    def _load_json_descriptions(cls) -> None:
        if cls._descriptions_cache:
            return

        config = get_config()
        json_path = config.template_attributes_json_path

        if not json_path:
            cls._descriptions_cache = {}
            return

        try:
            json_file = Path(json_path)
            if not json_file.exists():
                logger.warning("Template attributes JSON file not found: %s", json_path)
                cls._descriptions_cache = {}
                return

            with json_file.open(encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict) and "attributes" in data:
                items = data["attributes"]
            else:
                items = data

            for item in items:
                name = item.get("name", "")
                description = item.get("description", "")
                if name and description:
                    cleaned_name = name.strip().rstrip(".,")
                    cls._descriptions_cache[cleaned_name] = description

            logger.info("Loaded %d template attribute descriptions from JSON", len(cls._descriptions_cache))
        except Exception:
            cls._descriptions_cache = {}

    @classmethod
    def _get_model(cls) -> "SentenceTransformer | None":
        if cls._model is None:
            cls._model = get_embedding_model()
        return cls._model

    @classmethod
    def preload(cls) -> None:
        if cls._semantic_loaded or not is_embeddings_enabled():
            return

        cls._load_json_descriptions()

        model = cls._get_model()
        if not model:
            return

        attribute_names = list(cls._cache.keys())
        if not attribute_names:
            return

        embeddings = model.encode(attribute_names)
        cls._embeddings_cache = {name: emb.tolist() for name, emb in zip(attribute_names, embeddings, strict=True)}

        if cls._descriptions_cache:
            descriptions = [cls._descriptions_cache.get(name, "") for name in attribute_names]
            desc_embeddings = model.encode(descriptions)
            cls._description_embeddings_cache = {name: emb.tolist() for name, emb in zip(attribute_names, desc_embeddings, strict=True)}

        cls._semantic_loaded = True
        logger.info("Generated embeddings for %d template attributes", len(attribute_names))

    @classmethod
    def _semantic_match_weighted(cls, user_input: str) -> str | None:
        """
        Semantic match using weighted combination of name and description embeddings.

        Weights are configurable via config settings (default: name=0.7, description=0.3)
        """
        if user_input in cls._semantic_match_cache:
            return cls._semantic_match_cache[user_input]

        from sentence_transformers import util

        cls.preload()
        if not cls._embeddings_cache or not cls._description_embeddings_cache:
            logger.debug("Semantic match for '%s': no embeddings cache", user_input)
            return None

        model = cls._get_model()
        if not model:
            logger.debug("Semantic match for '%s': no model", user_input)
            return None

        logger.debug("Semantic match for '%s'", user_input)

        threshold = get_embedding_threshold()
        name_weight = get_embedding_name_weight()
        desc_weight = get_embedding_description_weight()

        user_embedding = model.encode(user_input)

        best_match = None
        best_score = 0.0
        top5 = []

        for name, name_emb in cls._embeddings_cache.items():
            name_score = util.cos_sim(user_embedding, name_emb).item()

            desc_emb = cls._description_embeddings_cache.get(name)
            desc_score = util.cos_sim(user_embedding, desc_emb).item() if desc_emb else 0.0

            weighted_score = name_weight * name_score + desc_weight * desc_score

            if weighted_score >= threshold and weighted_score > best_score:
                best_score = weighted_score
                best_match = name

            top5.append((name, weighted_score))

        top5.sort(key=lambda x: x[1], reverse=True)
        top5_str = ", ".join(f"{k} ({s:.2f})" for k, s in top5[:5])
        logger.debug("Weighted semantic match for '%s': top 5 = [%s]", user_input, top5_str)

        if best_match:
            logger.debug("Semantic match result: '%s' (score: %.2f)", best_match, best_score)
            cls._semantic_match_cache[user_input] = best_match
        else:
            logger.debug("Semantic match result: no match above threshold %.2f", threshold)
            cls._semantic_match_cache[user_input] = None

        return best_match

    @classmethod
    def parse(cls, attribute_name: str) -> ReportProperty:
        """
        On first call, this function reads the Tekla template attributes file once,
        parses all attribute definitions, and caches them in memory. Subsequent calls
        return cached results instantly without re-reading the file.

        Matching priority:
        1. Exact/normalized match on attribute names
        2. Weighted semantic match
        """
        if attribute_name in cls._parse_cache:
            return cls._parse_cache[attribute_name]

        logger.debug("Parsing attribute: '%s'", attribute_name)

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

        # 1. Try normalized exact match
        matched_name = find_normalized_match(attribute_name, cls._cache)
        if matched_name:
            logger.debug("Exact match found: '%s'", matched_name)
            result = cls._cache[matched_name]
            cls._parse_cache[attribute_name] = result
            return result

        logger.debug("No exact match, trying semantic matching")

        # 2. Semantic matching - use weighted approach
        if is_embeddings_enabled():
            weighted_match = cls._semantic_match_weighted(attribute_name)
            if weighted_match:
                logger.debug("Semantic match found: '%s'", weighted_match)
                result = cls._cache[weighted_match]
                cls._parse_cache[attribute_name] = result
                return result

        logger.warning("Attribute not found: '%s'", attribute_name)
        raise ValueError(f"Attribute '{attribute_name}' not found.")
