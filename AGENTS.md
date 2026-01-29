# Agent Guidelines for Tekla MCP Server

This file defines basic rules for AI agents and human contributors working on the Tekla MCP Server.

## Agent Behavior Expectations
- Change only files directly related to the request
- Don't add new dependencies without approval
- Never use Tekla API in unit tests
- Keep existing style and structure unless told otherwise
- Make changes minimal, focused, and consistent

## Essential Commands

### Package Management
- Install: `uv pip install -r requirements.txt`
- Add: `uv pip add <package>`
- Update: `uv pip compile requirements.txt --upgrade`

### Testing
- All tests: `uv run pytest tests/`
- Unit only: `uv run pytest tests/unit/`
- Functional only: `uv run pytest tests/functional/`
- Single test: `uv run pytest tests/unit/test_models.py::test_get_element_type_by_class_valid`
- Verbose: `uv run pytest -xvs tests/`

⚠️ Functional tests modify Tekla models - run only in test environments.

### Linting & Formatting
- Check: `uv run ruff check .`
- Fix: `uv run ruff check --fix .`
- Format: `uv run ruff format .`
- Type check: `uv run mypy .`

### Development
- Run server: `uv run python mcp_server.py`
- Build binary: `uv run pyinstaller mcp_server.py`

## Code Style

### Core Principles
1. **Tekla API expertise** - Efficient interaction with Tekla Open API
2. **Simplicity** - Readable solutions over complex ones
3. **Pythonic** - Use built-ins and standard libraries
4. **Concise docs** - Focus on "what" and "why", not "how"

### Imports (Order Matters)
```python
import json
import math
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field, PrivateAttr
from pydantic_core import PydanticCustomError

from init import logger
from utils import log_function_call
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
- Levels: `debug()`, `info()`, `warning()`, `error()`, `exception()`
- Decorators: `@log_function_call`, `@log_mcp_tool_call`

### Tekla API Patterns
- Use `TeklaModel` wrapper from `tekla_utils.py`
- Use `TeklaModelObject` for individual objects
- Always `model.commit_changes()` after modifications
- Use `wrap_model_objects()` for conversion

### MCP Server
- Use `@mcp.tool()` decorator
- Return dict with `status` key
- Validate inputs in MCP tool layer
- Use `tools.py` for actual operations

## Project Structure
- `mcp_server.py` - Main server with MCP tools
- `models.py` - Data models and enums
- `tools.py` - Tekla operations
- `tekla_utils.py` - Tekla API wrappers
- `tekla_loader.py` - Tekla DLL loading
- `utils.py` - Decorators
- `init.py` - Logging
- `config/` - JSON configs
- `tests/unit/` - Unit tests
- `tests/functional/` - Functional tests

## Before Committing
1. Check: `uv run ruff check .`
2. Fix: `uv run ruff check --fix .`
3. Format: `uv run ruff format .`
4. Type check: `uv run mypy .`
5. Run tests: `uv run pytest tests/`
