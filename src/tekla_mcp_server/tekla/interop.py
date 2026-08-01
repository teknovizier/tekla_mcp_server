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

from tekla_mcp_server.tekla.loader import ArrayList


def to_array_list(objects: Iterable[Any]) -> ArrayList:
    """Convert a Python iterable to a .NET ArrayList."""
    array_list = ArrayList()
    for obj in objects:
        array_list.Add(obj)
    return array_list
