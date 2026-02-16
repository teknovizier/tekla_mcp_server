"""
Attribute Mapper for mapping user-provided keys to config attribute names.

This module provides functionality to:
1. Load custom_attributes schema from component configuration
2. Generate embeddings for attribute descriptions using sentence-transformers
3. Map user-provided keys to config attribute names using semantic similarity
4. Convert values to expected types from config
"""

import re
import threading

from typing import Any

from init import logger, read_config
from models import get_custom_attributes_schema

try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence-transformers not installed. Attribute mapping will be disabled.")


class AttributeMapper:
    def __init__(self, model_name: str | None = None, threshold: float | None = None):
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError("sentence-transformers is required for attribute mapping.")

        config = read_config()
        mapper_settings = config.get("attribute_mapper", {})

        self.model_name = model_name or mapper_settings.get("embedding_model")
        self.threshold = threshold or mapper_settings.get("embedding_threshold")

        if not self.model_name or not self.threshold:
            raise ImportError("Attribute mapper configuration missing. Add 'attribute_mapper' section to config with 'embedding_model' and 'embedding_threshold'.")

        self._model: SentenceTransformer | None = None
        self._schema_cache: dict[str, dict] = {}

    def _ensure_model_loaded(self) -> None:
        if self._model is None:
            logger.info("Loading embedding model: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            logger.info("Embedding model loaded")

    def _load_schema(self, component_name: str) -> bool:
        if component_name in self._schema_cache:
            logger.debug("Using cached schema for component: %s", component_name)
            return True

        self._ensure_model_loaded()
        assert self._model is not None

        schema = get_custom_attributes_schema(component_name)
        if not schema:
            logger.debug("No custom_attributes schema found for component: %s", component_name)
            return False

        descriptions = [attr["description"] for attr in schema.values()]
        config_keys = list(schema.keys())

        logger.debug("Generating embeddings for %d attributes", len(descriptions))
        embeddings = self._model.encode(descriptions)

        self._schema_cache[component_name] = {
            "schema": schema,
            "config_keys": config_keys,
            "embeddings": {key: emb.tolist() for key, emb in zip(config_keys, embeddings)},
        }

        logger.info("Loaded schema for component '%s' with %d attributes", component_name, len(schema))
        return True

    def map_keys(self, user_dict: dict[str, Any], component_name: str) -> dict[str, Any]:
        """
        Map user-provided keys to config attribute names using semantic similarity.

        Args:
            user_dict: User-provided dict (e.g., {"rebar size": 10, "rebar grade": "B500B"})
            component_name: Name of the Tekla component

        Returns:
            Dict with mapped keys (e.g., {"SBSize_list": 10, "SBGrade_list": "B500B"})
        """
        if not self._load_schema(component_name):
            logger.debug("No custom_attributes schema for component: %s", component_name)
            return {}

        cached = self._schema_cache[component_name]
        schema = cached["schema"]
        embeddings_dict = cached["embeddings"]

        result = {}
        for user_key, user_value in user_dict.items():
            best_match = None
            best_score = 0.0

            self._ensure_model_loaded()
            assert self._model is not None

            # Try normalized exact match
            user_key_normalized = re.sub(r"[_\W]+", "_", user_key.upper()).strip("_")
            for attr_name in schema.keys():
                attr_normalized = re.sub(r"[_\W]+", "_", attr_name.upper()).strip("_")
                if user_key_normalized == attr_normalized:
                    logger.debug("Normalized exact match for '%s': %s", user_key, attr_name)
                    best_match = attr_name
                    break

            user_embedding = self._model.encode(user_key)
            for config_key, config_embedding in embeddings_dict.items():
                score = self._cosine_similarity(user_embedding, config_embedding)
                if score >= self.threshold and score > best_score:
                    best_score = score
                    best_match = config_key

            if best_match:
                expected_type = schema[best_match].get("type", "string")
                converted_value = self._convert_type(user_value, expected_type)
                result[best_match] = converted_value
                logger.debug("Mapped '%s' -> '%s' (score: %.2f)", user_key, best_match, best_score)
            else:
                logger.warning("No match found for key: %s", user_key)

        logger.info("Mapped %d keys for component '%s'", len(result), component_name)
        return result

    @staticmethod
    def _cosine_similarity(a: Any, b: Any) -> float:
        a = a.tolist() if hasattr(a, "tolist") else list(a)  # type: ignore[union-attr]
        b = b.tolist() if hasattr(b, "tolist") else list(b)  # type: ignore[union-attr]
        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = sum(x * x for x in a) ** 0.5
        magnitude_b = sum(x * x for x in b) ** 0.5
        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0
        return dot_product / (magnitude_a * magnitude_b)

    @staticmethod
    def _convert_type(value: Any, expected_type: str) -> Any:
        try:
            if expected_type == "int":
                return int(float(value))
            elif expected_type == "float":
                return float(value)
            else:
                return str(value)
        except (ValueError, TypeError):
            return str(value)


_attribute_mapper_instance: AttributeMapper | None = None
_lock = threading.Lock()


def get_attribute_mapper() -> AttributeMapper | None:
    global _attribute_mapper_instance
    if _attribute_mapper_instance is None:
        with _lock:
            if _attribute_mapper_instance is None:
                try:
                    _attribute_mapper_instance = AttributeMapper()
                except ImportError as e:
                    logger.warning("Attribute mapper unavailable: %s", e)
                    return None
    return _attribute_mapper_instance


def map_attributes(user_dict: dict[str, Any], component_name: str) -> dict[str, Any]:
    """
    Map user-provided custom_attributes keys to config attribute names.

    Args:
        user_dict: User-provided dict (e.g., {"rebar size": 10, "rebar grade": "B500B"})
        component_name: The name of the Tekla component

    Returns:
        Dict with mapped keys (e.g., {"SBSize_list": 10, "SBGrade_list": "B500B"})
    """
    mapper = get_attribute_mapper()
    if not mapper:
        logger.warning("Attribute mapper not available")
        return {}

    result = mapper.map_keys(user_dict, component_name)
    if result:
        logger.info("Mapped custom attributes: %s", result)
    else:
        logger.warning("No mapping found for custom attributes: %s", user_dict)
    return result
