"""
Module for utility functions.
"""

import json
import re
from functools import wraps
from pathlib import Path
from collections.abc import Callable
from typing import Any, Literal

from fastmcp.resources import ResourceContent, ResourceResult
from fastmcp.tools import ToolResult

import pathvalidate

from tekla_mcp_server.init import logger


def normalize_attribute_name(name: str) -> str:
    """
    Normalize attribute name for comparison.

    Converts to uppercase, replaces spaces/hyphens with underscores,
    removes non-alphanumeric characters.

    Args:
        name: Attribute name to normalize

    Returns:
        Normalized attribute name (e.g. 'assembly-top-level' -> 'ASSEMBLY_TOP_LEVEL')
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
        Normalized attribute name (e.g. 'ASSEMBLY_TOP_LEVEL' -> 'assembly top level')
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
                logger.exception("[%s] failed: %s", func.__name__, e)
                if scope == "tool":
                    return ToolResult(structured_content={"status": "error", "message": str(e)})
                else:
                    return ResourceResult(contents=[ResourceContent(content=json.dumps({"error": str(e)}), mime_type="application/json")])

        return wrapper

    return decorator


def json_resource(data: Any) -> ResourceResult:
    """
    Wrap JSON-serialisable data as a single-item ResourceResult.

    Args:
        data: JSON-serialisable payload

    Returns:
        ResourceResult containing the payload as 'application/json' content
    """
    return ResourceResult(contents=[ResourceContent(content=json.dumps(data), mime_type="application/json")])


def sanitize_filename(raw: str) -> str | None:
    """
    Replace characters that are invalid in Windows filenames.

    Args:
        raw: Filename to sanitize

    Returns:
        Sanitized filename, or None if nothing usable remains after sanitization
    """
    cleaned = pathvalidate.sanitize_filename(raw, replacement_text="_", platform="Windows").strip(" .")
    return cleaned or None


def resolve_model_relative_dir(folder: str, model_path: str) -> str:
    """
    Resolve a directory that may be relative to the model folder.

    Relative paths are resolved against `model_path` (the current model folder),
    matching how Tekla interprets relative advanced-option paths elsewhere in the
    codebase. Absolute paths are returned normalized.

    Args:
        folder: Directory path, absolute or model-relative.
        model_path: Current model folder, used as the base for relative paths.

    Returns:
        The resolved absolute path as a string.
    """
    path = Path(folder)
    if not path.is_absolute() and model_path:
        path = Path(model_path) / path
    return str(path.resolve())


def build_report_filename(template_name: str, output_filename: str | None) -> str:
    """
    Build a report file name from an optional caller-supplied name.

    Falls back to `template_name` when `output_filename` is empty, sanitizes the
    result for the filesystem, appends a default ".xsr" extension when none is
    present, and enforces Tekla's minimum stem length of three characters.

    Args:
        template_name: Report template name, used as the fallback file name.
        output_filename: Caller-supplied file name (may be None or empty).

    Returns:
        A sanitized report file name including an extension.

    Raises:
        ValueError: If no valid characters remain, or the stem is shorter than 3.
    """
    raw_name = output_filename or template_name
    safe_name = sanitize_filename(raw_name)
    if safe_name is None:
        raise ValueError(f"Output file name '{raw_name}' contains no valid filename characters")

    if not Path(safe_name).suffix:
        safe_name += ".xsr"

    if len(Path(safe_name).stem) < 3:
        raise ValueError(f"Report file name '{safe_name}' is too short: at least 3 characters are required (excluding the extension)")

    return safe_name


def parse_coordinate_string(coord_str: str) -> list[float]:
    """
    Parse a coordinate string like '0.0 4900.0 400.0 4900.0' into a list of floats.

    First value is kept as-is. Second+ values are added to the accumulated total.
    Supports 'N*VALUE' syntax to repeat a value N times.

    Args:
        coord_str: Whitespace-separated coordinate string

    Returns:
        List of accumulated float coordinates, or an empty list if input is empty
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


def format_coordinate_string(coords: list[float]) -> str:
    """
    Convert absolute coordinates to Tekla's incremental grid format.

    Args:
        coords: Absolute coordinate values

    Returns:
        Whitespace-separated incremental string, or an empty string if input is empty
    """
    if not coords:
        return ""
    values = [coords[0]] + [coords[i] - coords[i - 1] for i in range(1, len(coords))]
    return " ".join(str(int(v)) if v == int(v) else str(v) for v in values)


def parse_label_string(label_str: str) -> list[str]:
    """
    Parse a label string like 'A B C D' into a list of strings.

    Args:
        label_str: Whitespace-separated label string

    Returns:
        List of trimmed labels, or an empty list if input is empty
    """
    if not label_str:
        return []
    return [label.strip() for label in label_str.strip().split() if label.strip()]
