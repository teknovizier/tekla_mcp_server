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

# Local application (use tekla_mcp_server prefix)
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import ReportProperty
from tekla_mcp_server.utils import log_function_call, log_mcp_tool_call
from tekla_mcp_server.embeddings import get_embedding_model, get_embedding_threshold, find_normalized_match
from tekla_mcp_server.config import get_config
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tekla.model_object import TeklaModelObject
from tekla_mcp_server.tekla.utils import wrap_model_objects
from tekla_mcp_server.tekla.loader import Point, Beam, Identifier, Model
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
- Use `TeklaModel` class from `tekla/model.py` (singleton pattern for connection reuse)
- Use `TeklaModelObject` from `tekla/model_object.py` for individual objects
- Always `model.commit_changes()` after modifications
- Use `wrap_model_objects()` from `tekla/utils.py` for conversion

### MCP Server
- Use `@mcp.tool()` decorator
- Return dict with `status` key
- Validate inputs in MCP tool layer
- Use `mcp_tools.py` for actual operations

## Project Structure
```
tekla_mcp_server/
├── src/tekla_mcp_server/     # Source code (package)
│   ├── __init__.py
│   ├── config.py              # Configuration management
│   ├── embeddings.py          # Embedding model loading and text normalization
│   ├── init.py                # Logging, DLL loading
│   ├── mcp_server.py          # Main server with MCP tools
│   ├── mcp_tools.py           # MCP tool implementations
│   ├── models.py              # Data models and enums
│   ├── utils.py               # Decorators and utilities
│   └── tekla/                 # Tekla-specific modules
│       ├── __init__.py
│       ├── loader.py          # Tekla DLL loading
│       ├── model.py           # Tekla Model wrapper (singleton pattern)
│       ├── model_object.py    # Tekla ModelObject wrappers
│       ├── utils.py           # Tekla API helpers
│       └── template_attrs_parser.py  # Template attribute parsing with semantic search
├── config/                    # Configuration JSON files
│   ├── settings.sample.json
│   ├── element_types.sample.json
│   ├── lifting_anchor_types.sample.json
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
│   │   └── test_tekla_utils.py
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

## Before Committing
1. Check: `uv run ruff check .`
2. Fix: `uv run ruff check --fix .`
3. Format: `uv run ruff format .`
4. Type check: `uv run mypy .`
5. Run tests: `uv run pytest tests/`
