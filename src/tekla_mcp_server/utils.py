"""
Module for utility functions.
"""

from __future__ import annotations

import json
import math
import re
from functools import wraps
from pathlib import Path
from collections.abc import Callable, Iterable
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


def normalize_guid(guid: str) -> str:
    """
    Normalize a GUID string to the lowercase form Tekla reports.

    Tekla resolves a GUID regardless of surrounding spaces, case and braces, so
    these spelling variants must compare equal to be recognised as duplicates.

    Args:
        guid: GUID string as given by the caller

    Returns:
        Normalized GUID (e.g. ' {C0CA35EE-...} ' -> 'c0ca35ee-...')
    """
    return guid.strip().strip("{}").strip().lower()


def dedupe_guids(guids: Iterable[str]) -> list[str]:
    """
    Normalize GUIDs and drop repeats, keeping the first-seen order.

    Args:
        guids: GUID strings as given by the caller

    Returns:
        Unique normalized GUIDs
    """
    return list(dict.fromkeys(normalize_guid(guid) for guid in guids))


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
        """
        Log the call and invoke the wrapped function.

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Wrapped function result
        """
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
        """
        Wrap `func` with logging and error handling.

        Args:
            func: Tool or resource function

        Returns:
            Wrapped function
        """

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """
            Invoke `func` and convert exceptions to error results.

            Args:
                *args: Positional arguments
                **kwargs: Keyword arguments

            Returns:
                Function result or error result
            """
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
        """
        Expand 'N*value' shorthand into a list of floats.

        Args:
            coord_str: Space-separated coordinate values

        Returns:
            Expanded values
        """
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


def build_grid_axis(coord_str: str, label_str: str) -> dict[str, list]:
    """
    Pair the coordinates of one grid axis with their labels.

    Every grid line is kept, since dropping unlabeled lines would return wrong geometry.
    Lines without a label get None. Labels beyond the last line have no line to name
    and are dropped.

    Args:
        coord_str: Tekla coordinate string of the axis
        label_str: Tekla label string of the axis

    Returns:
        dict with `coords` (all line positions) and `labels` (one entry per coordinate)
    """
    coords = parse_coordinate_string(coord_str)
    labels: list[str | None] = list(parse_label_string(label_str)[: len(coords)])
    labels.extend([None] * (len(coords) - len(labels)))
    return {"coords": coords, "labels": labels}


def find_bolt_catalog_error(standard: str, size: float, catalog: list[dict[str, Any]]) -> str | None:
    """
    Check a bolt standard and size combination against the bolt catalog.

    Tekla accepts any standard and size on `Modify()` without complaint, so an
    unknown combination has to be caught before it is written.

    Args:
        standard: Bolt standard (catalog identifier)
        size: Bolt diameter in mm
        catalog: Catalog items with 'standard' and 'size' keys, as returned by `get_all_bolt_items`

    Returns:
        An error message if the combination is not in the catalog, else None
    """
    sizes = sorted({float(item["size"]) for item in catalog if item["standard"] == standard})
    if not sizes:
        standards = sorted({item["standard"] for item in catalog})
        return f"Bolt standard '{standard}' is not in the bolt catalog. Available standards: {standards}"
    # Catalog sizes are single precision, e.g. 15.869999885559082 for a 5/8 inch bolt
    if not any(math.isclose(size, s, abs_tol=0.01) for s in sizes):
        return f"Bolt size {size} is not available for standard '{standard}'. Available sizes: {[round(s, 2) for s in sizes]}"
    return None


def validate_property_type(property_type: type) -> None:
    """
    Validates that the given type is one of the supported types: str, int, or float.

    Args:
        property_type: Type to validate

    Raises:
        TypeError: If the type is not supported.
    """
    if property_type not in (str, int, float):
        raise TypeError("Property type must be one of: str, int, float.")
