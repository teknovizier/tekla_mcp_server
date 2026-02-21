"""
Module for utility functions.
"""

import re
from functools import wraps
from collections.abc import Callable
from typing import Any

import json

from tekla_mcp_server.init import logger


def serialize_to_json(data: Any) -> str:
    """
    Serializes data to a JSON string with consistent formatting.
    """
    return json.dumps(data, ensure_ascii=False, indent=2)


def normalize_attribute_name(name: str) -> str:
    """
    Normalize attribute name for comparison.

    Converts to uppercase, replaces spaces/hyphens with underscores,
    removes non-alphanumeric characters.

    Args:
        name: Attribute name to normalize

    Returns:
        Normalized attribute name (e.g., "assembly-top-level" -> "ASSEMBLY_TOP_LEVEL")
    """
    return re.sub(r"[_\W]+", "_", name.upper()).strip("_")


def find_normalized_match(input_name: str, candidates: dict[str, Any]) -> str | None:
    """
    Find a normalized exact match for input_name in candidates.

    Args:
        input_name: User-provided attribute name
        candidates: Dict of candidate attribute names to match against

    Returns:
        Matched key from candidates, or None if no match
    """
    input_normalized = normalize_attribute_name(input_name)
    for attr_name in candidates.keys():
        attr_normalized = normalize_attribute_name(attr_name)
        if input_normalized == attr_normalized:
            logger.debug("Normalized exact match for '%s': %s", input_name, attr_name)
            return attr_name
    return None


def log_function_call(func: Callable) -> Callable:
    """
    Decorator that logs function calls.

    Logs:
    - Function name
    - Positional and keyword arguments
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger.debug("[%s] called with args=%s, kwargs=%s", func.__name__, args, kwargs)
        return func(*args, **kwargs)

    return wrapper


def log_mcp_tool_call(func: Callable) -> Callable:
    """
    Decorator for MCP tools that logs function calls and handles exceptions.

    Logs:
    - Function name
    - Positional and keyword arguments
    - Exceptions with traceback

    Returns:
    - Original function result if successful
    - Standardized error dictionary if an exception occurs
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger.info("[%s] called with args=%s, kwargs=%s", func.__name__, args, kwargs)
        try:
            return func(*args, **kwargs)
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            logger.exception("[%s] failed:", func.__name__)
            return {"status": "error", "error_type": type(e).__name__, "message": str(e)}

    return wrapper
