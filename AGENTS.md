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

⚠️ Functional tests modify Tekla models - run only in test environments.

### Test Naming Conventions
- All test object names (parts, assemblies, UDAs) MUST start with `MCP_TEST_` prefix
- This prevents conflicts with existing model objects and makes cleanup easy

## Debug Scripts
- Use `/debug` folder for temporary scripts, experiments, and test code
- These scripts are for development/debugging only
- Do not commit files from this folder to version control
- Production-ready code must be moved to proper locations

### Linting & Formatting
- Check: `uv run ruff check .`
- Fix: `uv run ruff check --fix .`
- Format: `uv run ruff format .`
- Type check: `uv run mypy .`

### Development
- Run server: `uv run python src/tekla_mcp_server/mcp_server.py`
- Build binary: `uv run pyinstaller src/tekla_mcp_server/mcp_server.py`

## Code Style

### Core Principles
1. **Tekla API expertise** - Efficient interaction with Tekla Open API
2. **Simplicity** - Readable solutions over complex ones
3. **Pythonic** - Use built-ins and standard libraries
4. **Concise docs** - Focus on "what" and "why", not "how"

### Imports (Order Matters)
```python
# Standard library
import json
import math
import re
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar
from collections.abc import Callable

# Third-party
from pydantic import BaseModel, Field, PrivateAttr
from pydantic_core import PydanticCustomError

# Local application
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import ReportProperty
from tekla_mcp_server.utils import log_function_call, log_mcp_tool_call
from tekla_mcp_server.embeddings import get_embedding_model, find_normalized_match
from tekla_mcp_server.config import get_config
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tekla.model_object import TeklaModelObject
from tekla_mcp_server.tekla.utils import wrap_model_objects
from tekla_mcp_server.tekla.loader import Point, Beam, Identifier, Model
from tekla_mcp_server.tekla.component_handlers import HandlerRegistry, LiftingAnchorsHandler

# Providers (MCP tool definitions)
from tekla_mcp_server.providers.selection_provider import select_elements_by_filter
from tekla_mcp_server.providers.view_provider import draw_elements_labels
from tekla_mcp_server.providers.properties_provider import get_elements_properties
from tekla_mcp_server.providers.components_provider import put_components
from tekla_mcp_server.providers.operations_provider import cut_elements_with_zero_class_parts

# Tools modules (actual implementations)
from tekla_mcp_server.tools.selection import tool_select_elements_by_filter
from tekla_mcp_server.tools.components import tool_put_components
from tekla_mcp_server.tools.view import tool_draw_elements_labels
from tekla_mcp_server.tools.properties import tool_get_elements_properties
from tekla_mcp_server.tools.operations import tool_cut_elements_with_zero_class_parts
```

### Type Hints & Formatting
- **Always** use type hints for parameters and returns
- **Always** use f-strings: `f"Found {count} elements"`
- Line length: 200 chars (configured in `pyproject.toml`)
- Indentation: 4 spaces
- Don't reformat existing code unless asked

### Naming
- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private: prefix with `_` or use `PrivateAttr()`

### Error Handling
```python
@log_mcp_tool_call
def tool_function(...):
    try:
        return {"status": "success", ...}
    except Exception as e:
        logger.exception("Operation failed")
        return {"status": "error", "message": str(e)}
```

### Pydantic Models
- Inherit from `BaseModel`
- Use `Field()` for metadata
- `PrivateAttr` for non-serialized attributes
- `@field_validator` for custom validation
- `model_post_init()` for initialization logic

### Logging
- Use `logger` from `init.py`
- Levels: `debug()`, `info()`, `warning()`, `error()`
- Decorators: `@log_function_call`, `@log_mcp_tool_call`
- Configure via env vars: `TEKLA_MCP_LOG_LEVEL`, `TEKLA_MCP_LOG_FILE_PATH`

### Tekla API Patterns
- Use `TeklaModel` class from `tekla/model.py` (singleton pattern via `lru_cache`)
- Use `TeklaModelObject` from `tekla/model_object.py` for individual objects
- Always `model.commit_changes()` after modifications
- Use `wrap_model_objects()` from `tekla/utils.py` for conversion

### MCP Server Architecture
- **Providers** (`providers/`) - MCP tool definitions with docstrings
- **Tools** (`tools/`) - Actual implementation logic
- Use `LocalProvider` for organizing tools into modules
- Tool functions accept `dict[str, Any]` inputs (MCP sends JSON)
- Use `_to_filter_option()` helper to convert dicts to Pydantic models

### MCP Resources (Read-Only Data)
Resources provide discovery/metadata, not actions:
| Resource | Purpose |
|----------|---------|
| `component://schema` | List all available components |
| `component://schema/{key}` | Get properties for a component |
| `macro://list` | List available Tekla macros |
| `info://connection_status` | Current Tekla connection status |

### MCP Tools (Actions)
Tools perform operations that may mutate state:
| Provider | Tools |
|----------|-------|
| `selection_provider` | `select_elements_by_filter`, `select_elements_by_guid`, etc. |
| `view_provider` | `draw_elements_labels`, `zoom_to_selection`, etc. |
| `properties_provider` | `get_elements_properties`, `set_elements_properties`, etc. |
| `components_provider` | `put_components`, `remove_components` |
| `operations_provider` | `cut_elements_with_zero_class_parts`, `run_macro` |

## Project Structure
```
tekla_mcp_server/
├── src/tekla_mcp_server/     # Source code (package)
│   ├── __init__.py
│   ├── config.py              # Configuration management (lru_cache for caching)
│   ├── embeddings.py          # Embedding model loading and text normalization
│   ├── init.py                # Logging, DLL loading
│   ├── mcp_server.py          # Main server (registers providers and resources)
│   ├── models.py              # Data models, enums, filter options
│   ├── utils.py               # Decorators and utilities (response helpers)
│   ├── providers/             # MCP tool definitions (docstrings + orchestration)
│   │   ├── __init__.py
│   │   ├── selection_provider.py
│   │   ├── view_provider.py
│   │   ├── properties_provider.py
│   │   ├── components_provider.py
│   │   └── operations_provider.py
│   ├── tools/                 # Tool implementations (business logic)
│   │   ├── selection.py       # Selection logic
│   │   ├── components.py      # Component operations
│   │   ├── properties.py      # Property operations
│   │   ├── view.py           # View operations
│   │   └── operations.py     # Boolean cuts, macros
│   └── tekla/                 # Tekla-specific modules
│       ├── __init__.py
│       ├── loader.py          # Tekla DLL loading (pythonnet)
│       ├── model.py           # Tekla Model wrapper (singleton via lru_cache)
│       ├── model_object.py    # Tekla ModelObject wrappers
│       ├── utils.py           # Tekla API helpers
│       ├── template_attrs_parser.py  # Template attribute parsing with semantic search
│       └── component_handlers.py     # Component handler plugins (LiftingAnchorsHandler, etc.)
├── config/                    # Configuration JSON files
│   ├── settings.sample.json
│   ├── element_types.sample.json
│   ├── semantic_overrides.sample.json
│   └── base_components.sample.json
├── tests/
│   ├── unit/                  # Unit tests
│   │   ├── __init__.py
│   │   ├── test_config.py
│   │   ├── test_init.py
│   │   ├── test_models.py
│   │   ├── test_utils.py
│   │   ├── test_tekla_model_object.py
│   │   ├── test_tekla_template_attrs_parser.py
│   │   ├── test_tekla_utils.py
│   │   └── test_component_handlers.py
│   └── functional/            # Functional tests
│       ├── __init__.py
│       └── test_mcp_server.py
├── .env.example               # Environment variables template
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

## Configuration
- Settings in `config/settings.json`
- Use `get_config()` from `config.py` for centralized access
- Environment variables: `TEKLA_MCP_LOG_LEVEL`, `TEKLA_MCP_LOG_FILE_PATH`, `TEKLA_MCP_CONFIG_DIR`

## Unit Test Guidelines
- Never mock Tekla API - use pure functions when possible
- Use `unittest.mock.MagicMock` for external dependencies
- Test files mirror module structure: `test_<module_name>.py`
- Use `@pytest.mark.parametrize` for multiple test cases
- Avoid Tekla imports in unit tests - use mocks

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

## Before Committing
1. Check: `uv run ruff check .`
2. Fix: `uv run ruff check --fix .`
3. Format: `uv run ruff format .`
4. Type check: `uv run mypy .`
5. Run tests: `uv run pytest tests/`
