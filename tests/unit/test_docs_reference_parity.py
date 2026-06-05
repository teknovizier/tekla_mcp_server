"""
Validate that `docs/reference.md` stays in sync with the actual provider code.

Parses the Markdown tables (tools + resources) and the provider source files
via AST - no Tekla import required, so it runs in CI.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_FILE = REPO_ROOT / "docs" / "reference.md"
PROVIDERS_DIR = REPO_ROOT / "src" / "tekla_mcp_server" / "providers"


def _tool_names_from_markdown(text: str) -> set[str]:
    """Extract tool function names from the Tools table in `reference.md`.

    Expected row format:
        | Category | 🔒 `tool_name` | Description | Parameters |
    """
    names: set[str] = set()
    in_tools = False
    for line in text.splitlines():
        if line.startswith("## Tools"):
            in_tools = True
            continue
        if line.startswith("## "):
            in_tools = False
        if not in_tools:
            continue
        # Table rows start with |
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        # parts[0] is empty, parts[1] = Category, parts[2] = tool column
        if len(parts) < 4:
            continue
        tool_cell = parts[2]
        # Match emoji + backticked name: "🔒 `tool_name`"
        m = re.search(r"[✏️⚠️🔒]\s+`(\w+)`", tool_cell)
        if m:
            names.add(m.group(1))
    return names


def _resource_uris_from_markdown(text: str) -> set[str]:
    """Extract resource URIs from the Resources table in `reference.md`.

    Expected row format:
        | `resource://uri` | Description |
    """
    uris: set[str] = set()
    in_resources = False
    for line in text.splitlines():
        if line.startswith("## Resources"):
            in_resources = True
            continue
        if line.startswith("## "):
            in_resources = False
        if not in_resources:
            continue
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        resource_cell = parts[1]
        m = re.match(r"`([^`]+)`", resource_cell)
        if m and ("://" in m.group(1) or m.group(1).startswith("tekla://") or m.group(1).startswith("project://")):
            uris.add(m.group(1))
    return uris


def _resource_uris_from_ast() -> set[str]:
    """Extract resource URIs from `@<provider>.resource(...)` decorators."""
    uris: set[str] = set()
    rsrc_file = PROVIDERS_DIR / "resources_provider.py"
    tree = ast.parse(rsrc_file.read_text(encoding="utf-8"), filename=str(rsrc_file))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "resource":
                if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                    uris.add(decorator.args[0].value)
    return uris


def _tool_names_from_ast() -> set[str]:
    """Extract tool function names from `@<provider>.tool(...)` decorators."""
    names: set[str] = set()
    for path in sorted(PROVIDERS_DIR.glob("*_provider.py")):
        if path.name == "resources_provider.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "tool":
                    names.add(node.name)
    return names


def test_tools_table_matches_providers():
    """Every documented tool exists in code, and every coded tool is documented."""
    text = DOCS_FILE.read_text(encoding="utf-8")
    doc_tools = _tool_names_from_markdown(text)
    code_tools = _tool_names_from_ast()

    only_in_docs = doc_tools - code_tools
    only_in_code = code_tools - doc_tools

    errors: list[str] = []
    if only_in_docs:
        errors.append(f"Documented but NOT in code: {sorted(only_in_docs)}")
    if only_in_code:
        errors.append(f"In code but NOT documented: {sorted(only_in_code)}")
    assert not errors, "\n".join(errors)


def test_resources_table_matches_code():
    """Every documented resource exists in code, and every coded resource is documented."""
    text = DOCS_FILE.read_text(encoding="utf-8")
    doc_resources = _resource_uris_from_markdown(text)
    code_resources = _resource_uris_from_ast()

    only_in_docs = doc_resources - code_resources
    only_in_code = code_resources - doc_resources

    errors: list[str] = []
    if only_in_docs:
        errors.append(f"Documented but NOT in code: {sorted(only_in_docs)}")
    if only_in_code:
        errors.append(f"In code but NOT documented: {sorted(only_in_code)}")
    assert not errors, "\n".join(errors)


def test_docs_file_exists():
    """Guard: the reference doc must exist."""
    assert DOCS_FILE.is_file(), f"Not found: {DOCS_FILE}"


def test_at_least_one_tool_found():
    """Guard against the Markdown parser silently matching nothing."""
    text = DOCS_FILE.read_text(encoding="utf-8")
    assert len(_tool_names_from_markdown(text)) > 0


def test_at_least_one_resource_found():
    """Guard against the Markdown parser silently matching nothing."""
    text = DOCS_FILE.read_text(encoding="utf-8")
    assert len(_resource_uris_from_markdown(text)) > 0
