"""
Schema guard for `base_components*.json`.

The config drives component lookup (by `tekla_name`), numbering, custom-property
coercion, and handler dispatch - a malformed entry only fails at runtime. This test
validates structure with plain JSON parsing, and cross-checks `handler.name` against
the `@register_handler` classes in `component_handlers.py` via `ast`. No Tekla import
is required, so it runs in CI.

Every `base_components*.json` present in the config dir is checked: the tracked
`*.sample.json` always, plus a local untracked `base_components.json` if present.
"""

import ast
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
HANDLERS_FILE = REPO_ROOT / "src" / "tekla_mcp_server" / "tekla" / "component_handlers.py"

# Mirrors models.TYPE_MAP - the only types BaseComponent can coerce custom_properties to.
VALID_PROPERTY_TYPES = {"str", "int", "float"}


def _base_component_files() -> list[Path]:
    """All base_components config files present (sample + optional local)."""
    return sorted(CONFIG_DIR.glob("base_components*.json"))


def _registered_handler_names() -> set[str]:
    """Class names decorated with `@register_handler` in component_handlers.py."""
    tree = ast.parse(HANDLERS_FILE.read_text(encoding="utf-8"), filename=str(HANDLERS_FILE))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "register_handler":
                    names.add(node.name)
    return names


def test_base_components_sample_exists():
    """The tracked sample must exist - it is the canonical schema reference."""
    assert (CONFIG_DIR / "base_components.sample.json").is_file(), "config/base_components.sample.json is missing"


def test_register_handler_classes_found():
    """Guard against the AST walk silently matching no handlers."""
    assert _registered_handler_names(), "No @register_handler classes found in component_handlers.py"


@pytest.mark.parametrize("path", _base_component_files(), ids=lambda p: p.name)
def test_base_components_schema(path: Path):
    """Each component entry conforms to the schema the code relies on."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name}: root must be a JSON object"

    handler_names = _registered_handler_names()
    seen_tekla_names: dict[str, str] = {}
    errors: list[str] = []

    for key, comp in data.items():
        if not isinstance(comp, dict):
            errors.append(f"{key}: component definition must be an object")
            continue

        # tekla_name is the lookup key and must be unique: get_component_by_tekla_name
        # returns the first match, so a duplicate silently shadows another component.
        tekla_name = comp.get("tekla_name")
        if not isinstance(tekla_name, str) or not tekla_name:
            errors.append(f"{key}: 'tekla_name' must be a non-empty string")
        elif tekla_name in seen_tekla_names:
            errors.append(f"{key}: duplicate tekla_name '{tekla_name}' (also defined by '{seen_tekla_names[tekla_name]}')")
        else:
            seen_tekla_names[tekla_name] = key

        if "number" in comp and not isinstance(comp["number"], int):
            errors.append(f"{key}: 'number' must be an int")

        if "description" in comp and not isinstance(comp["description"], str):
            errors.append(f"{key}: 'description' must be a string")

        custom_properties = comp.get("custom_properties")
        if custom_properties is not None:
            if not isinstance(custom_properties, dict):
                errors.append(f"{key}: 'custom_properties' must be an object")
            else:
                for prop_key, prop_def in custom_properties.items():
                    if not isinstance(prop_def, dict):
                        errors.append(f"{key}.custom_properties.{prop_key}: must be an object")
                        continue
                    prop_type = prop_def.get("type")
                    if prop_type is not None and prop_type not in VALID_PROPERTY_TYPES:
                        errors.append(f"{key}.custom_properties.{prop_key}: type '{prop_type}' must be one of {sorted(VALID_PROPERTY_TYPES)}")

        handler = comp.get("handler")
        if handler is not None:
            if not isinstance(handler, dict):
                errors.append(f"{key}: 'handler' must be an object")
            else:
                handler_name = handler.get("name")
                if not isinstance(handler_name, str) or not handler_name:
                    errors.append(f"{key}: 'handler.name' must be a non-empty string")
                elif handler_name not in handler_names:
                    errors.append(f"{key}: handler '{handler_name}' is not a @register_handler class (known: {sorted(handler_names)})")
                if "config" in handler and not isinstance(handler["config"], dict):
                    errors.append(f"{key}: 'handler.config' must be an object")

    assert not errors, f"{path.name} schema violations:\n" + "\n".join(errors)
