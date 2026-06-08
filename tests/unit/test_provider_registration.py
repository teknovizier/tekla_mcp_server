"""
Static guard that every provider is registered with the MCP server.

`mcp_server.py` must call `mcp.add_provider(...)` for each provider exported by the
`providers` package - a provider that is defined but never registered silently
exposes none of its tools or resources, and nothing else catches it. This test
parses both files with `ast` - no Tekla import required, so it runs in CI - and
asserts the registered set matches the package's `__all__` exactly.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "tekla_mcp_server"
SERVER_FILE = SRC / "mcp_server.py"
PROVIDERS_INIT = SRC / "providers" / "__init__.py"


def _exported_providers() -> set[str]:
    """Provider names listed in `providers/__init__.py`'s `__all__`."""
    tree = ast.parse(PROVIDERS_INIT.read_text(encoding="utf-8"), filename=str(PROVIDERS_INIT))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                    return {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)}
    return set()


def _registered_providers() -> set[str]:
    """Provider names passed to `mcp.add_provider(...)` in `mcp_server.py`."""
    tree = ast.parse(SERVER_FILE.read_text(encoding="utf-8"), filename=str(SERVER_FILE))
    registered: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_provider" and node.args and isinstance(node.args[0], ast.Name):
            registered.add(node.args[0].id)
    return registered


def test_at_least_one_provider_registered():
    """Guard against the AST walk silently matching nothing."""
    assert _registered_providers(), "No mcp.add_provider(...) calls found in mcp_server.py"


def test_every_exported_provider_is_registered():
    """Exported providers and registered providers must be the same set."""
    exported = _exported_providers()
    registered = _registered_providers()
    assert exported, "No providers found in providers/__init__.py __all__"

    not_registered = exported - registered
    not_exported = registered - exported

    errors: list[str] = []
    if not_registered:
        errors.append(f"Exported by providers package but NOT registered in mcp_server.py: {sorted(not_registered)}")
    if not_exported:
        errors.append(f"Registered in mcp_server.py but NOT exported by providers package: {sorted(not_exported)}")
    assert not errors, "\n".join(errors)
