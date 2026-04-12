# Agent Guidelines for Tekla MCP Server

This file defines basic rules for AI agents and human contributors working on the Tekla MCP Server.

## Agent Behavior Expectations

- Change only files directly related to the request
- Don't add new dependencies without approval
- Never use Tekla API in unit tests
- Keep existing style and structure unless told otherwise
- Make changes minimal, focused, and consistent
- Never remove existing comments, keep them as they are unless explicitly instructed otherwise
- Backwards compatibility is not required, changes can introduce breaking behavior for older versions

---

# Part 1: Commands & Tools

## Essential Commands

### Package Management
- Install: `uv pip install -r requirements.txt`
- Add: `uv pip add <package>`
- Update: `uv pip compile requirements.txt --upgrade`

### Testing
- All tests: `uv run pytest tests/`
- Unit only: `uv run pytest tests/unit/`
- Functional only: `uv run pytest tests/functional/`
- Single test: `uv run pytest tests/unit/test_utils.py::test_log_function_call -xvs`
- Single test class: `uv run pytest tests/unit/test_utils.py::TestLogFunctionCall -xvs`
- Verbose: `uv run pytest -xvs tests/`

> ⚠️ Functional tests modify Tekla models - run only in test environments.

### Test Naming Conventions
- All test object names (parts, assemblies, UDAs) MUST start with `MCP_TEST_` prefix
- This prevents conflicts with existing model objects and makes cleanup easy

### Debug Scripts
- Use `/debug` folder for temporary scripts, experiments, and test code
- These scripts are for development/debugging only
- Do not commit files from this folder to version control
- Production-ready code must be moved to proper locations

### Before Committing
1. Check: `uv run ruff check .`
2. Fix: `uv run ruff check --fix .`
3. Format: `uv run ruff format .`
4. Type check: `uv run mypy .`
5. Run tests: `uv run pytest tests/`

---

# Part 2: Code Style & Patterns

## Core Principles
1. **Tekla API expertise** - Efficient interaction with Tekla Open API
2. **Simplicity** - Readable solutions over complex ones
3. **Pythonic** - Use built-ins and standard libraries
4. **Concise docs** - Focus on "what" and "why", not "how"

## Imports
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
from tekla_mcp_server.tools.selection import tool_select_elements_by_filter
```

### Inline Imports
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

## Type Hints & Formatting
- **Always** use type hints for parameters and returns
- **Always** use f-strings: `f"Found {count} elements"`
- Line length: 200 chars (configured in `pyproject.toml`)
- Indentation: 4 spaces
- Don't reformat existing code unless asked

## Docstrings
All tool functions must use **Google-style** docstrings with:
- Summary line (imperative mood, max 79 chars)
- `Args:` section for parameters
- `Returns:` section for return values
- `Raises:` section for exceptions (where applicable)

```python
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
```

## Naming
- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private: prefix with `_` or use `PrivateAttr()`

## Error Handling
```python
@log_mcp_tool_call
def tool_function(...):
    try:
        return {"status": "success", ...}
    except Exception as e:
        logger.exception("Operation failed")
        return {"status": "error", "message": str(e)}
```

## Pydantic Models
- Inherit from `BaseModel`
- Use `Field()` for metadata
- `PrivateAttr` for non-serialized attributes
- `@field_validator` for custom validation
- `model_post_init()` for initialization logic

## Logging
- Use `logger` from `init.py`
- Levels: `debug()`, `info()`, `warning()`, `error()`
- Decorators: `@log_function_call`, `@log_mcp_tool_call`
- Configure via env vars: `TEKLA_MCP_LOG_LEVEL`, `TEKLA_MCP_LOG_FILE_PATH`

---

# Part 3: MCP Architecture

## MCP Server Architecture
- **Providers** (`providers/`) - MCP tool definitions and resources with docstrings
- **Tools** (`tools/`) - Actual implementation logic
- Use `LocalProvider` for organizing tools into modules
- Tool functions accept `dict[str, Any]` inputs (MCP sends JSON)
- Use `_to_filter_option()` helper to convert dicts to Pydantic models

## MCP Resources (Read-Only Data)
Resources provide discovery/metadata, not actions:
| Resource | Purpose |
|----------|---------|
| `tekla://components` | List all available components |
| `tekla://macros` | List available Tekla macros |
| `tekla://element_types` | List element types with class numbers |
| `tekla://phases` | List all phases in the model |
| `tekla://grids` | List all rectangular grids |
| `tekla://filters/selection` | List available selection filters |
| `tekla://filters/view` | List available view filters |
| `tekla://connection_status` | Connection status |

## When to Use Resources vs Tools

- Use **resources** for small, read-only data (lists, metadata)
- Use **tools** for filtering, searching, or any non-trivial logic
- Never expose large datasets as resources

## How to Add a Tool

### 1. Add Implementation (tools/*.py)

```python
from tekla_mcp_server.utils import log_function_call

@log_function_call
def tool_my_new_feature(param: str) -> dict[str, Any]:
    """
    Description of what the tool does.

    Args:
        param: Description of parameter

    Returns:
        dict with status and result
    """
    # Implementation here
    return {"status": "success", "result": param}
```

### 2. Add MCP Interface (providers/*.py)

```python
from fastmcp.server.providers import LocalProvider
from tekla_mcp_server.models import MyInputModel
from tekla_mcp_server.tools.my_module import tool_my_new_feature
from tekla_mcp_server.utils import log_mcp_tool_call

my_provider = LocalProvider()

@my_provider.tool()
@log_mcp_tool_call
def my_new_feature(input: MyInputModel) -> dict[str, Any]:
    """Tool description for MCP users."""
    return tool_my_new_feature(input.param)
```

### 3. Add to Documentation

Add the new tool to `docs/reference.md` with:
- Tool name and description
- Parameters and their types
- Return value format

---

# Part 4: Tekla API Patterns

## Tekla API Patterns
- Use `TeklaModel` class from `tekla/wrappers/model.py` (singleton pattern via `lru_cache`)
- Always `model.commit_changes()` after modifications
- Use `wrap_model_objects()` from `tekla/wrappers/model_object.py` for conversion

## Component Handler System
The component handler system provides a plugin-like architecture for specialized Tekla components.

### Handler Structure
- Handlers are defined in `tekla/component_handlers.py`
- Base handler class: None (duck typing with `tekla_name` property)
- Registry auto-discovers handlers from `config/base_components.json`

### Adding a New Handler
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

---

# Part 5: Configuration & Testing

## Configuration
- Settings in `config/settings.json`
- Use `get_config()` from `config.py` for centralized access
- Environment variables: `TEKLA_MCP_LOG_LEVEL`, `TEKLA_MCP_LOG_FILE_PATH`, `TEKLA_MCP_CONFIG_DIR`

## Performance Guidelines
- Use `@lru_cache` for expensive Tekla queries
- Avoid repeated catalog access
- Never load large datasets in MCP responses
- Prefer filtered queries over full scans

## Unit Test Guidelines
- Never mock Tekla API - use pure functions when possible
- Use `unittest.mock.MagicMock` for external dependencies
- Test files mirror module structure: `test_<module_name>.py`
- Use `@pytest.mark.parametrize` for multiple test cases
- Avoid Tekla imports in unit tests - use mocks

## Development
- Run server: `uv run python src/tekla_mcp_server/mcp_server.py`
- Build binary: `uv run pyinstaller src/tekla_mcp_server/mcp_server.py`
- Check: `uv run ruff check .`
- Fix: `uv run ruff check --fix .`
- Format: `uv run ruff format .`
- Type check: `uv run mypy .`
- Linting: `uv run ruff check . && uv run ruff format . && uv run mypy .`

---

# Part 6: Project Structure

## Directory Layout

```
tekla_mcp_server/
├── src/tekla_mcp_server/     # Source code
│   ├── __init__.py
│   ├── config.py              # Configuration management
│   ├── embeddings.py          # Embedding model loading
│   ├── init.py                # Logging, DLL loading
│   ├── mcp_server.py          # Main server
│   ├── models.py              # Data models, enums
│   ├── utils.py               # Decorators and utilities
│   ├── providers/             # MCP tool definitions
│   ├── tools/                 # Tool implementations
│   └── tekla/                 # Tekla-specific modules
│       ├── loader.py          # DLL loading (pythonnet)
│       ├── wrappers/       # Tekla wrapper classes
│       ├── utils.py           # Tekla API helpers
│       ├── template_attrs_parser.py  # Template attribute parsing
│       └── component_handlers.py   # Component handlers
├── config/                    # Configuration JSON files
├── tests/
│   ├── unit/                  # Unit tests
│   └── functional/            # Functional tests
├── docs/                      # Documentation
└── pyproject.toml
```

## File Placement Rules

| File Type | Location |
|-----------|----------|
| MCP tool definition | `providers/*.py` |
| Tool implementation | `tools/*.py` |
| Pydantic model | `models.py` |
| Tekla wrapper | `tekla/wrappers/*.py` |
| Tekla-specific utility | `tekla/utils.py` |
| Configuration | `config/*.json` |
| General decorator | `utils.py` |
| Documentation | `docs/*.md` |
| Unit test | `tests/unit/test_*.py` |
| Functional test | `tests/functional/test_*.py` |