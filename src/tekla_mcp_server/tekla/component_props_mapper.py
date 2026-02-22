"""
Component Props Mapper for mapping user-provided keys to component config property names.

This module provides functionality to:
1. Load custom_properties schema from component configuration
2. Generate embeddings for property descriptions using sentence-transformers
3. Map user-provided keys to config property names using semantic similarity
4. Convert values to expected types from config
"""

from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.embeddings import get_embedding_model, get_embedding_threshold, semantic_match, is_embeddings_enabled
from tekla_mcp_server.models import get_custom_properties_schema
from tekla_mcp_server.utils import find_normalized_match


class ComponentPropsMapper:
    def __init__(self, threshold: float | None = None):
        self._model = None
        self.threshold = threshold
        self._semantic_enabled = is_embeddings_enabled()
        if self._semantic_enabled:
            self._model = get_embedding_model()
            if self.threshold is None:
                self.threshold = get_embedding_threshold()
        self._schema_cache: dict[str, dict] = {}

    def _load_schema(self, component_name: str) -> bool:
        if component_name in self._schema_cache:
            logger.debug("Using cached schema for component: %s", component_name)
            return True

        schema = get_custom_properties_schema(component_name)
        if not schema:
            logger.debug("No custom_properties schema found for component: %s", component_name)
            return False

        descriptions = [attr["description"] for attr in schema.values()]
        config_keys = list(schema.keys())

        if self._semantic_enabled and self._model:
            logger.debug("Generating embeddings for %d properties", len(descriptions))
            embeddings = self._model.encode(descriptions)
            desc_to_config = {desc: (key, emb.tolist()) for desc, key, emb in zip(descriptions, config_keys, embeddings, strict=True)}
        else:
            desc_to_config = {}

        self._schema_cache[component_name] = {
            "schema": schema,
            "config_keys": config_keys,
            "desc_to_config": desc_to_config,
        }

        logger.info("Loaded schema for component '%s' with %d properties", component_name, len(schema))
        return True

    def map_keys(self, user_dict: dict[str, Any], component_name: str) -> dict[str, Any]:
        """
        Map user-provided keys to config property names using semantic similarity.

        Args:
            user_dict: User-provided dict (e.g., {"rebar size": 10, "rebar grade": "B500B"})
            component_name: Name of the Tekla component

        Returns:
            Dict with mapped keys (e.g., {"SBSize_list": 10, "SBGrade_list": "B500B"})
        """
        if not self._load_schema(component_name):
            return {}

        cached = self._schema_cache[component_name]
        schema = cached["schema"]
        desc_to_config = cached["desc_to_config"]

        # Create embeddings dict with descriptions as keys for semantic matching
        desc_embeddings = {desc: emb for desc, (_, emb) in desc_to_config.items()}

        result = {}
        unmapped_keys = []
        for user_key, user_value in user_dict.items():
            # Try normalized exact match against schema keys
            best_match = find_normalized_match(user_key, schema)
            best_score = 1.0 if best_match else 0.0

            if not best_match and self._semantic_enabled and self._model and self.threshold is not None:
                # Try semantic match against descriptions if no exact match
                matched_desc, best_score = semantic_match(user_key, desc_embeddings, self.threshold, self._model)
                if matched_desc:
                    best_match = desc_to_config[matched_desc][0]  # Map description back to config key

            if best_match:
                expected_type = schema[best_match].get("type", "string")
                converted_value = self._convert_type(user_value, expected_type)
                result[best_match] = converted_value
                logger.debug("Mapped '%s' -> '%s' (score: %.2f)", user_key, best_match, best_score)
            else:
                logger.warning("No match found for key: %s", user_key)
                unmapped_keys.append(user_key)

        result["unmapped_keys"] = unmapped_keys
        logger.info("Mapped %d keys for component '%s', %d unmapped", len(result) - 1, component_name, len(unmapped_keys))
        return result

    @staticmethod
    def _convert_type(value: Any, expected_type: str) -> Any:
        """
        Converts a value to the expected type.

        Args:
            value: The value to convert
            expected_type: Expected type as string ("int", "float", "str")

        Returns:
            Value converted to the expected type, or string representation on failure
        """
        try:
            if expected_type == "int":
                return int(float(value))
            elif expected_type == "float":
                return float(value)
            else:
                return str(value)
        except (ValueError, TypeError):
            return str(value)


def map_properties(user_dict: dict[str, Any], component_name: str) -> dict[str, Any]:
    """
    Map user-provided custom_properties keys to config property names.

    Args:
        user_dict: User-provided dict (e.g., {"rebar size": 10, "rebar grade": "B500B"})
        component_name: The name of the Tekla component

    Returns:
        Dict with mapped keys (e.g., {"SBSize_list": 10, "SBGrade_list": "B500B"})
    """
    try:
        mapper = ComponentPropsMapper()
    except Exception as e:
        logger.warning("Component props mapper unavailable: %s", e)
        return {}

    result = mapper.map_keys(user_dict, component_name)
    if result:
        logger.info("Mapped custom properties: %s", result)
    else:
        logger.warning("No mapping found for custom properties: %s", user_dict)
    return result
