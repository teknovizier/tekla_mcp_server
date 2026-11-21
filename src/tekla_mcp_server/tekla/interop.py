"""
Helper functions for converting Python values into .NET types when using pythonnet.

Python lists, dictionaries, and other containers aren't automatically understood by
the Tekla .NET API. Before passing them to Tekla, they must be converted into
equivalent .NET collections.

This module contains those conversion functions. It only imports loader so that other
wrapper modules can use it without creating unnecessary dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tekla_mcp_server.tekla.loader import ArrayList, Int32, List, SystemDouble


def to_array_list(objects: Iterable[Any]) -> ArrayList:
    """
    Convert a Python iterable to a .NET ArrayList.

    Args:
        objects: Items to add

    Returns:
        .NET `ArrayList` with the items
    """
    array_list = ArrayList()
    for obj in objects:
        array_list.Add(obj)
    return array_list


def to_number_list(values: Iterable[int | float]) -> Any:
    """
    Convert Python numbers to a .NET `List<int>`, or `List<double>` when any is a float.

    Args:
        values: Numbers to add

    Returns:
        .NET `List[Int32]` or `List[Double]` with the values
    """
    numbers = list(values)
    result = List[Int32]() if all(isinstance(v, int) for v in numbers) else List[SystemDouble]()
    for value in numbers:
        result.Add(value)
    return result
