"""
Module for utility functions.
"""

import re
from functools import wraps
from collections.abc import Callable
from typing import Any, Literal

from fastmcp.resources import ResourceContent, ResourceResult
from fastmcp.tools import ToolResult

from tekla_mcp_server.init import logger


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


def normalize_for_embedding(name: str) -> str:
    """
    Normalize attribute name for embeddings.

    Converts to lowercase, replaces underscores/hyphens with spaces,
    removes non-alphanumeric characters except spaces.

    Args:
        name: Attribute name to normalize

    Returns:
        Normalized attribute name (e.g., "ASSEMBLY_TOP_LEVEL" -> "assembly top level")
    """
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"[^a-zA-Z0-9 ]+", "", name)
    return name.lower().strip()


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
            return attr_name
    return None


def log_function_call(func: Callable) -> Callable:
    """
    Decorator that logs function calls.

    Args:
        func: The function to decorate

    Returns:
        Wrapped function that logs its arguments
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger.debug("[%s] called with args=%s, kwargs=%s", func.__name__, args, kwargs)
        return func(*args, **kwargs)

    return wrapper


def mcp_handler(scope: Literal["tool", "resource"] = "tool") -> Callable:
    """
    Decorator for MCP tools/resources that logs function calls and handles exceptions.

    Args:
        scope: "tool" for tools, "resource" for resources

    Returns:
        Decorated function with error handling
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.info("[%s] called with args=%s, kwargs=%s", func.__name__, args, kwargs)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.exception("[%s] failed:", func.__name__)
                if scope == "tool":
                    return ToolResult(structured_content={"status": "error", "message": str(e)})
                else:
                    return ResourceResult(contents=[ResourceContent(content={"error": str(e)}, mime_type="application/json")])

        return wrapper

    return decorator


def parse_coordinate_string(coord_str: str) -> list[float]:
    """Parse coordinate string like '0.0 4900.0 400.0 4900.0' into list of floats.

    First value is kept as-is. Second+ values are added to accumulated total.
    Supports 'N*VALUE' syntax to repeat a value N times.
    """
    if not coord_str:
        return []

    def expand_parts(coord_str: str) -> list[float]:
        parts = coord_str.strip().split()
        result = []
        for part in parts:
            if "*" in part:
                count_str, value_str = part.split("*", 1)
                count = int(count_str)
                value = float(value_str)
                result.extend([value] * count)
            else:
                result.append(float(part))
        return result

    expanded = expand_parts(coord_str)
    if not expanded:
        return []

    accumulated = expanded[0]
    result = [accumulated]
    for value in expanded[1:]:
        accumulated += value
        result.append(accumulated)
    return result


def parse_label_string(label_str: str) -> list[str]:
    """Parse label string like 'A B C D' into list of strings."""
    if not label_str:
        return []
    return [label.strip() for label in label_str.strip().split() if label.strip()]


def rects_intersect(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    margin: float = 0.0,
) -> bool:
    """
    Check if two rectangles intersect with margin.

    Args:
        a: Tuple of (x1, y1, x2, y2) defining first rectangle
        b: Tuple of (x1, y1, x2, y2) defining second rectangle
        margin: Optional margin to add to rectangles

    Returns:
        True if rectangles intersect, False otherwise
    """
    return not (a[2] < b[0] - margin or a[0] > b[2] + margin or a[3] < b[1] - margin or a[1] > b[3] + margin)


def lines_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
    margin: float = 0.0,
) -> bool:
    """
    Check if two line segments intersect with margin.

    Args:
        p1: First point of first line segment (x, y)
        p2: Second point of first line segment (x, y)
        p3: First point of second line segment (x, y)
        p4: Second point of second line segment (x, y)
        margin: Optional margin for intersection tolerance

    Returns:
        True if line segments intersect, False otherwise
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 0.0001:
        return False

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if 0 - margin <= t <= 1 + margin and 0 - margin <= u <= 1 + margin:
        return True
    return False


def line_rect_intersect(
    line_p1: tuple[float, float],
    line_p2: tuple[float, float],
    rect: tuple[float, float, float, float],
    margin: float = 0.0,
) -> bool:
    """
    Check if a line segment intersects a rectangle.

    Args:
        line_p1: First point of line segment (x, y)
        line_p2: Second point of line segment (x, y)
        rect: Tuple of (x1, y1, x2, y2) defining rectangle
        margin: Optional margin to add to rectangle

    Returns:
        True if line intersects rectangle, False otherwise
    """
    x1, y1 = line_p1
    x2, y2 = line_p2
    rx1, ry1, rx2, ry2 = rect

    left = min(rx1, rx2) - margin
    right = max(rx1, rx2) + margin
    bottom = min(ry1, ry2) - margin
    top = max(ry1, ry2) + margin

    if left <= x1 <= right and bottom <= y1 <= top:
        return True
    if left <= x2 <= right and bottom <= y2 <= top:
        return True

    if lines_intersect((x1, y1), (x2, y2), (left, bottom), (right, bottom), margin):
        return True
    if lines_intersect((x1, y1), (x2, y2), (right, bottom), (right, top), margin):
        return True
    if lines_intersect((x1, y1), (x2, y2), (right, top), (left, top), margin):
        return True
    if lines_intersect((x1, y1), (x2, y2), (left, top), (left, bottom), margin):
        return True

    return False
