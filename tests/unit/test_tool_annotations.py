"""
Static guard for MCP tool annotations.

`ReadOnlyToolFilter` is fail-closed: in read-only mode it shows only tools whose
`readOnlyHint` is True, so a tool that is missing annotations (or missing
`readOnlyHint`) silently disappears from read-only mode. This test parses the
provider source with `ast` - no Tekla import required, so it runs in CI - and
asserts every `@<provider>.tool(...)` carries an explicit `readOnlyHint` bool,
plus an explicit `destructiveHint` bool whenever the tool is not read-only.
"""

import ast
from pathlib import Path

PROVIDERS_DIR = Path(__file__).resolve().parents[2] / "src" / "tekla_mcp_server" / "providers"


def _is_tool_decorator(decorator: ast.expr) -> bool:
    """True for `@<something>.tool(...)` decorator calls."""
    return isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "tool"


def _annotations_dict(decorator: ast.Call) -> ast.Dict | None:
    """Return the `annotations={...}` dict literal passed to the decorator, if any."""
    for kw in decorator.keywords:
        if kw.arg == "annotations" and isinstance(kw.value, ast.Dict):
            return kw.value
    return None


def _bool_hints(annotations: ast.Dict) -> dict[str, bool]:
    """Extract {hint_name: bool} pairs from the annotations dict literal."""
    hints: dict[str, bool] = {}
    for key, value in zip(annotations.keys, annotations.values):
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(value, ast.Constant) and isinstance(value.value, bool):
            hints[key.value] = value.value
    return hints


def _iter_tools():
    """Yield (file_name, func_name, annotations_dict_or_None) for every tool in every provider."""
    for path in sorted(PROVIDERS_DIR.glob("*_provider.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            tool_decorators = [d for d in node.decorator_list if _is_tool_decorator(d)]
            if not tool_decorators:
                continue
            yield path.name, node.name, _annotations_dict(tool_decorators[0])


def test_providers_dir_exists():
    assert PROVIDERS_DIR.is_dir(), f"providers dir not found: {PROVIDERS_DIR}"


def test_every_tool_has_readonly_hint():
    """Fail-closed invariant: every tool must declare an explicit `readOnlyHint` bool."""
    offenders = []
    for file_name, func_name, annotations in _iter_tools():
        if annotations is None:
            offenders.append(f"{file_name}::{func_name} has no annotations dict")
            continue
        if "readOnlyHint" not in _bool_hints(annotations):
            offenders.append(f"{file_name}::{func_name} is missing a boolean readOnlyHint")
    assert not offenders, "Tools missing readOnlyHint (would be hidden in read-only mode):\n" + "\n".join(offenders)


def test_non_readonly_tools_declare_destructive_hint():
    """Writing tools must say whether they are destructive (additive vs destructive)."""
    offenders = []
    for file_name, func_name, annotations in _iter_tools():
        if annotations is None:
            continue  # covered by test_every_tool_has_readonly_hint
        hints = _bool_hints(annotations)
        if hints.get("readOnlyHint") is False and "destructiveHint" not in hints:
            offenders.append(f"{file_name}::{func_name}")
    assert not offenders, "Non-read-only tools missing destructiveHint:\n" + "\n".join(offenders)


def test_at_least_one_tool_found():
    """Guards against the AST walk silently matching nothing."""
    assert any(True for _ in _iter_tools())
