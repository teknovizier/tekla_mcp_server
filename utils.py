"""
Module for utility functions.
"""

from functools import wraps
from collections.abc import Callable
from typing import Any

from init import logger


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
        except Exception as e:
            logger.exception("[%s] failed:", func.__name__)
            return {"status": "error", "message": str(e)}

    return wrapper
