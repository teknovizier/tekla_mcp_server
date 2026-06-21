# Agent Guidelines for Tekla MCP Server

This file defines basic rules for AI agents and human contributors working on the Tekla MCP Server.

**Sections:** [Agent Behavior Expectations](#agent-behavior-expectations) · [Critical Traps](#critical-traps) · [Quick Reference](#quick-reference) · [Code Style & Conventions](#code-style--conventions) · [Cookbook: Adding Things](#cookbook-adding-things) · [Architecture Notes](#architecture-notes) · [Testing Guidelines](#testing-guidelines)

## Agent Behavior Expectations

- Change only files directly related to the request
- Don't add new dependencies without approval
- Never use Tekla API in unit tests
- All `Tekla.*` type imports must go through `tekla/loader.py` - never use `import clr` or `from Tekla.*` directly anywhere else
- Keep existing style and structure unless told otherwise
- Make changes minimal, focused, and consistent
- Never remove existing comments, keep them as they are unless explicitly instructed otherwise
- Backwards compatibility is not required, changes can introduce breaking behavior for older versions

## Critical Traps

Failures CI cannot catch (silent, delayed or Tekla-behavioral):

- **Import-time DLL load**: importing any module that transitively imports `tekla/loader.py` loads the Tekla DLLs at import, so such modules cannot be imported where Tekla is absent (CI, pure unit tests). This is why Tekla-touching test modules carry a CI skip guard (see [Testing Guidelines](#testing-guidelines)).
- **pythonnet interop**: Python containers do not marshal to .NET. Use .NET collections at the Tekla boundary - `ArrayList()`, `List[ModelObject]()`, `SystemArray[SystemType](...)` - not a plain Python `list`. `out`-params come back as extra tuple elements (the first is the success bool), so always unpack: `is_ok, value = obj.GetReportProperty(name, str())`. The trailing placeholder's type selects the .NET overload.
- **Work plane**: to work in an object's local coordinates, save the current plane, set the local one, then restore it in a `finally` (`GetWorkPlaneHandler().GetCurrentTransformationPlane()` / `SetCurrentTransformationPlane(...)`). Leaving it changed corrupts later geometry.
- **CI-enforced invariants** (pure-AST unit tests that fail the PR): `test_tool_annotations.py` requires every `@<provider>.tool` to pass `annotations` with a boolean `readOnlyHint` (and a boolean `destructiveHint` when not read-only), `test_docs_reference_parity.py` requires `docs/reference.md` to list exactly the tools and resources in code. Both scan only `providers/*_provider.py` (resources: only `resources_provider.py`), so a tool or resource defined elsewhere evades both checks.
- **`readOnlyHint` is security-critical**: read-only mode (`ReadOnlyToolFilter`) only filters tool visibility - there is no runtime write-block, and CI checks the hint is present, not correct. A mutating tool mislabeled `readOnlyHint: True` will run in read-only mode. Only human review catches a wrong hint.
- **Python floor vs CI**: `requires-python>=3.11`, but CI tests only 3.13, so CI will not catch 3.11-incompatible syntax or stdlib (e.g. PEP 695 `type` aliases). Code to the 3.11 floor.
- **Logging uses lazy `%`-args**: in `logger.*` calls use `logger.info("x=%s", x)`, never f-strings (defers formatting, this is the one place f-strings are not used).

---

## Quick Reference

Lookup material - skim for the one fact you need, this section is not meant to be read linearly.

### Commands

**Package management**
- Install: `uv pip install -r requirements.txt`
- Add: `uv pip add <package>`
- Update: `uv pip compile requirements.txt --upgrade`

**Testing**
- All tests: `uv run pytest tests/`
- Unit only: `uv run pytest tests/unit/`
- Functional only: `uv run pytest tests/functional/`
- Single test: `uv run pytest tests/unit/test_utils.py::test_log_function_call -xvs`
- Single test class: `uv run pytest tests/unit/test_utils.py::TestLogFunctionCall -xvs`
- Verbose: `uv run pytest -xvs tests/`

> ⚠️ Functional tests modify Tekla models - run only in test environments.

**Quality checks** - run after **all non-trivial changes** (not only before committing - skip only for minor edits like typo fixes):
1. Check: `uv run ruff check .`
2. Fix: `uv run ruff check --fix .`
3. Format: `uv run ruff format .`
4. Type check: `uv run mypy .`
5. Run tests: `uv run pytest tests/unit/`

Or combined: `uv run ruff check . && uv run ruff format . && uv run mypy .`

**Run / build**
- Run server: `uv run python src/tekla_mcp_server/mcp_server.py`
- Build binary: `uv run pyinstaller src/tekla_mcp_server/mcp_server.py`

### MCP Resources (Read-Only Data)

Resources provide discovery/metadata, not actions:

| Resource | Purpose |
|----------|---------|
| `tekla://components` | List all available components |
| `tekla://components/{component_key}` | Get component details by key |
| `tekla://macros` | List available Tekla macros |
| `tekla://element_types` | List element types with class numbers |
| `tekla://phases` | List all phases in the model |
| `tekla://grids` | List all rectangular grids |
| `tekla://filters/selection` | List available selection filters |
| `tekla://filters/view` | List available view filters |
| `tekla://connection_status` | Connection status |
| `tekla://catalog/materials` | All available material names from the Tekla material catalog |
| `tekla://catalog/rebars` | All available rebar grades and sizes from the Tekla rebar catalog |
| `tekla://reports` | Available Tekla report template names (`.rpt` files) |
| `project://context` | Project context: design rules, naming conventions, etc. |
| `project://context/{file}` | Full content of a specific project context file |

### Directory Layout

```
tekla_mcp_server/
├── src/tekla_mcp_server/
│   ├── config.py                        # Configuration management
│   ├── dxf_operations.py                # DXF entity resolution and drawing collision checks
│   ├── embeddings.py                    # Semantic attribute resolution
│   ├── init.py                          # Logger and DLL loading
│   ├── mcp_server.py                    # Main server entrypoint
│   ├── models.py                        # Data models and enums
│   ├── utils.py                         # Shared decorators and utilities
│   ├── providers/
│   │   ├── components_provider.py       # put/get/modify/remove_components
│   │   ├── drawings_provider.py         # get_drawings, print_drawings, ...
│   │   ├── modeling_provider.py         # place_beams/columns/panels/slabs, move, grid
│   │   ├── operations_provider.py       # cut, orphans, clash_check, macro, ...
│   │   ├── properties_provider.py       # get/set_elements_properties, compare, copy_properties_from_ifc, ...
│   │   ├── resources_provider.py        # All MCP resources (tekla://, project://)
│   │   ├── selection_provider.py        # select_elements_by_filter/guid/name
│   │   └── view_provider.py             # color, zoom, hide, labels, filters
│   └── tekla/
│       ├── loader.py                    # Single source for all Tekla.* DLL imports
│       ├── clash_check.py               # Clash detection logic
│       ├── component_handlers.py        # Component handler registry and implementations
│       ├── drawing_utils.py             # Drawing helpers
│       ├── filter_builder.py            # Filter expression builder helpers
│       ├── snapshot_builder.py          # Part/Assembly snapshot construction
│       ├── template_attrs_parser.py     # Report property type resolution
│       ├── utils.py                     # Tekla-API-side helpers
│       └── wrappers/
│           ├── drawing.py               # TeklaDrawing
│           ├── drawing_handler.py       # TeklaDrawingHandler
│           ├── model.py                 # TeklaModel singleton
│           ├── model_object.py          # TeklaModelObject, TeklaPart, TeklaAssembly, ...
│           └── view.py                  # TeklaDrawingView
├── config/
│   ├── base_components.json             # Component definitions + handler config
│   ├── element_types.json               # Element type -> Tekla class mapping
│   ├── report_properties.json           # Report property definitions
│   ├── semantic_overrides.json          # Embedding search overrides
│   ├── settings.json                    # Server settings
│   └── context/                         # project://context markdown files
├── tests/
│   ├── unit/                            # Pure Python tests - no Tekla API
│   └── functional/                      # Live model tests - use MCP_TEST_ prefix
├── docs/
│   └── reference.md                     # Tool and resource reference (keep up to date)
└── pyproject.toml
```

### File Placement Rules

| File Type | Location |
|-----------|----------|
| MCP tool definition | `providers/*.py` |
| Pydantic model | `models.py` |
| Model wrapper | `tekla/wrappers/model.py`, `tekla/wrappers/model_object.py` |
| Drawing wrappers | `tekla/wrappers/drawing.py`, `tekla/wrappers/drawing_handler.py`, `tekla/wrappers/view.py` |
| Tekla-specific utility | `tekla/utils.py` |
| Pure-Python feature logic with no Tekla import (DLL-free, fully unit-testable in CI) | top-level module in `src/tekla_mcp_server/`, not `tekla/` |
| Configuration | `config/*.json` |
| General utility | `utils.py` |
| Documentation | `docs/*.md` |
| Unit test | `tests/unit/test_*.py` |
| Functional test | `tests/functional/test_*.py` |

### Test Naming Conventions
- All test object names (parts, assemblies, UDAs) MUST start with `MCP_TEST_` prefix
- This prevents conflicts with existing model objects and makes cleanup easy

### Debug Scripts
- Use `/debug` folder for temporary scripts, experiments, and test code
- These scripts are for development/debugging only
- Do not commit files from this folder to version control
- Production-ready code must be moved to proper locations

---

## Code Style & Conventions

### Core Principles
1. **Tekla API expertise** - Efficient interaction with Tekla Open API
2. **Simplicity** - Readable solutions over complex ones
3. **Pythonic** - Use built-ins and standard libraries
4. **Concise docs** - Focus on "what" and "why", not "how"

### Imports
Organize imports in this order:
1. Standard library
2. Third-party
3. Local application

Import only what is used in the file.

```python
# Standard library
from typing import Any

# Third-party
from pydantic import BaseModel, Field, PrivateAttr

# Local application
from tekla_mcp_server.init import logger
from tekla_mcp_server.tekla.filter_builder import add_filter
```

**Inline imports**
- **Avoid inline imports** (imports inside functions) where possible
- Use top-level imports for better readability and performance
- Exception: Lazy imports for expensive libraries (e.g., `sentence_transformers`) or to avoid circular dependencies

```python
# Good - top-level import
from tekla_mcp_server.tekla.loader import TeklaStructuresSettings

def function():
    return TeklaStructuresSettings.GetAdvancedOption(...)

# Acceptable - lazy import to avoid circular dependency
def function():
    from tekla_mcp_server.tekla.loader import SomeClass
    return SomeClass()
```

### Type Hints & Formatting
- **Always** use type hints for parameters and returns
- **Always** use f-strings: `f"Found {count} elements"` (except `logger.*` calls - see [Critical Traps](#critical-traps))
- Line length: 200 chars (configured in `pyproject.toml`)
- Indentation: 4 spaces
- Don't reformat existing code unless asked

### Strings & Punctuation
- Python string literals use **double quotes** `"..."`
- Inside docstring prose, use **single quotes** to quote values or names: `For 'MeshBars', use key 'SpacBarsBottPri'`
- Use **backticks** in docstrings/comments to mark tool names, parameters, and technical terms: `my_tool`, `view_key`, `TeklaModel`
- Use **hyphen** `-` only, never em dash `—`
- Never use `;` in docstrings - end the sentence with a period and start a new one instead
- Avoid overusing `-` in docstrings - prefer plain prose sentences

### Docstrings
All tool functions must use **Google-style** docstrings with:
- Summary line (imperative mood, max 79 chars)
- Concise and short - no more prose than needed to convey the "what" and "why"
- `Args:` section for parameters
- `Returns:` section for return values
- `Raises:` section for exceptions (where applicable)

For a multi-line docstring, the opening `"""` goes on its own line - never put the first line of text on the same line as the opening quotes.

```python
# Correct
def tool_example(param: str, count: int) -> dict[str, Any]:
    """
    Do something with the parameter.

    Args:
        param: Description of parameter
        count: Number of items to process

    Returns:
        dict with status and processed count

    Raises:
        ValueError: If count is negative
    """

# Wrong - first line shares the line with the opening quotes
def tool_example(param: str, count: int) -> dict[str, Any]:
    """Do something with the parameter.

    Args:
        param: Description of parameter
        count: Number of items to process
    """
```

### Code Comments
- Code must have comments, but not too many - comment where it genuinely helps, don't narrate every line
- Inline `#` comments must NOT end with a period
- Never use `;` in comments - end the sentence with a period and start a new one instead
- Keep comments concise and meaningful - explain the non-obvious "why", not the "what"

### Naming
- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private: prefix with `_` or use `PrivateAttr()`

### Error Handling
Use `@mcp_handler(scope="tool")` on every tool and `@mcp_handler(scope="resource")` on every resource. The decorator catches all exceptions and converts them into the correct error response automatically.

**Never return a `ToolResult` before the normal end of the function.** Raise an exception instead - let the `@mcp_handler` decorator catch it and convert it.

```python
# Correct - raise, don't return
if not items:
    raise ValueError("No items provided")

# Wrong: do not return early with a ToolResult
if not items:
    return ToolResult(structured_content={"status": "error", "message": "No items provided"})

# Wrong: do not return early before the single normal return at the end
result = compute(...)
if not result:
    return ToolResult(structured_content={"status": "error", "message": "computation failed"})
return ToolResult(structured_content={"status": "success", "result": result})
```

| Scope | Return Type | Error Format |
|-------|-------------|--------------|
| `tool` | `ToolResult` | `{"status": "error", "message": "..."}` |
| `resource` | `ResourceResult` | `{"error": "..."}` in content |

### Pydantic Models
- Inherit from `BaseModel`
- Use `Field()` for metadata
- `PrivateAttr` for non-serialized attributes
- `@field_validator` for custom validation
- `model_post_init()` for initialization logic

### Logging
- Use `logger` from `init.py`
- Levels: `debug()`, `info()`, `warning()`, `error()`
- Decorators: `@log_function_call`, `@mcp_handler`
- Configure via env vars: `TEKLA_MCP_LOG_LEVEL`, `TEKLA_MCP_LOG_FILE_PATH`

---

## Cookbook: Adding Things

### Add or Modify a Tool

**1. Add MCP Tool (`providers/*.py`)**

```python
from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from tekla_mcp_server.utils import mcp_handler

my_provider = LocalProvider()

@my_provider.tool(tags={"category"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def my_new_feature(
    param: Annotated[str, Field(description="Description visible to MCP clients")],
) -> ToolResult:
    """Tool description for MCP users."""
    # Implementation here
    return ToolResult(
        structured_content={
            "status": "success",  # success | warning | partial
            "result": param,
        }
    )
```

**2. Write tests**
- Unit tests in `tests/unit/test_<module>.py`: pure logic (no Tekla import) runs in CI, tests that import Tekla wrappers and mock the `Model` carry the CI skip guard and run locally (see [Testing Guidelines](#testing-guidelines))
- Functional tests in `tests/functional/` if Tekla model state must be touched (use the `MCP_TEST_` prefix; run against a scratch model, never production)

**3. Add to documentation** - add the new tool to `docs/reference.md` with tool name, description, parameters and types, and return value format.

### Add a Resource

Resources return discovery/metadata, not actions.

**1. Add MCP Resource (`providers/resources_provider.py`)**

```python
@resources_provider.resource("example://data")
@mcp_handler(scope="resource")
def get_example_data() -> ResourceResult:
    """Get example data."""
    return json_resource({"key": "value"})  # JSON - use json_resource() helper

# Non-JSON (e.g. markdown):
@resources_provider.resource("example://doc")
@mcp_handler(scope="resource")
def get_example_doc() -> ResourceResult:
    """Get markdown document."""
    return ResourceResult(contents=[ResourceContent(content="# Title\nText", mime_type="text/markdown")])
```

**2. Add to documentation** - add the new resource to `docs/reference.md` with resource name and description.

### Add a New Component Handler

1. Create handler class with `tekla_name` property:
```python
@register_handler
class MyComponentHandler:
    @property
    def tekla_name(self) -> str:
        return "My Component"
    
    def pre_process(self, component, selected_object) -> dict:
        # Called before component insertion
        return {"context": "data"}
    
    def post_process(self, component, selected_object, count, context) -> int:
        # Called after component insertion
        return count
```

2. Register in config:
```json
{
  "my_component": {
    "tekla_name": "My Component",
    "number": -1,
    "handler": {
      "name": "MyComponentHandler",
      "config": { "setting": "value" }
    }
  }
}
```

### Add a Helper Function

Use underscore prefix for reusable helper functions:

```python
def _helper_function(param: str) -> dict[str, Any]:
    """Helper description."""
    # Helper logic here
    return {"status": "success"}
```

---

## Architecture Notes

### MCP Server Architecture
- **Providers** (`providers/`) - MCP tool definitions with inline implementations
- Use `LocalProvider` for organizing tools into modules
- Tool functions accept model inputs and return dict[str, Any]
- Use `to_filter_option()` helper from `tekla/filter_builder.py` to convert dicts to Pydantic models

### When to Use Resources vs Tools
- Use **resources** for small, read-only data (lists, metadata) - see [MCP Resources table](#mcp-resources-read-only-data)
- Use **tools** for filtering, searching, or any non-trivial logic
- Never expose large datasets as resources

### Model Operations
- Use `TeklaModel` class from `tekla/wrappers/model.py` (singleton pattern)
- Always `model.commit_changes()` after modifications
- Use `wrap_model_objects()` from `tekla/wrappers/model_object.py` for conversion, silently skips unsupported object types
- `model.get_selected_objects()` raises `ValueError` if nothing is selected

### Drawing Operations
- Use `TeklaDrawingHandler` from `tekla/wrappers/drawing_handler.py` - **NOT a singleton**, create a fresh instance per operation: `handler = TeklaDrawingHandler()`
- Use `handler.require_active_drawing()` to get the active `TeklaDrawing` - raises `RuntimeError` if no drawing is open
- Always call `drawing.commit_changes()` after any drawing mutation (analogous to `model.commit_changes()`)
- Use `TeklaDrawingView` from `tekla/wrappers/view.py` for per-view operations (scale, origin, object enumeration)
- `view.view_key` is **not stable across Tekla sessions** - IDs are reassigned on model reopen, do not persist them

### Component Handler System
The component handler system provides a plugin-like architecture for specialized Tekla components.
- Handlers are defined in `tekla/component_handlers.py`
- Base handler class: None (duck typing with `tekla_name` property)
- Registry auto-discovers handlers from `config/base_components.json`
- See [Cookbook: Adding Things](#cookbook-adding-things) for how to add a new handler

---

## Testing Guidelines

The CI gate is the module-level skip guard, not the directory. Any test module that imports a Tekla-touching module triggers the import-time DLL load described in [Critical Traps](#critical-traps), so it MUST start with:

```python
if os.getenv("CI") == "true":
    pytest.skip(..., allow_module_level=True)
```

Pure-logic modules omit the guard and run in CI.

- Pure unit tests: no Tekla import, run in CI - test pure functions directly.
- Mock-based Tekla unit tests (e.g. `test_tekla_model.py`): import Tekla wrappers and mock the .NET `Model` with `unittest.mock.MagicMock`/`patch`. Mocking the Tekla API here is acceptable, the module carries the skip guard and runs locally. Reset singletons between tests (`TeklaModel._instance = None`).
- Use `unittest.mock.MagicMock` for external dependencies.
- Test files mirror module structure: `test_<module_name>.py`.
- Use `@pytest.mark.parametrize` for multiple test cases.

### Configuration
- Settings in `config/settings.json`
- Use `get_config()` from `config.py` for centralized access
- Config files are `@lru_cache` backed - changes do not take effect until the MCP server is restarted
- Environment variables: `TEKLA_MCP_LOG_LEVEL`, `TEKLA_MCP_LOG_FILE_PATH`, `TEKLA_MCP_CONFIG_DIR`

### Performance Guidelines
- Use `@lru_cache` for expensive Tekla queries
- Avoid repeated catalog access
- Never load large datasets in MCP responses
- Prefer filtered queries over full scans
