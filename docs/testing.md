# Testing

The project includes unit tests and functional tests.

## Test Structure

### Unit Tests (`tests/unit/`)
- `test_init.py`: DLL loading and error handling
- `test_config.py`: Configuration management
- `test_models.py`: Data model validation
- `test_utils.py`: Decorators and utilities
- `test_tekla_utils.py`: Tekla API wrapper tests
- `test_tekla_model_object.py`: Tekla ModelObject wrappers
- `test_tekla_template_attrs_parser.py`: Template attribute parsing
- `test_component_handlers.py`: Component handler plugins

### Functional Tests (`tests/functional/`)
- `test_mcp_server.py`: End-to-end MCP tool integration tests

## Running Tests

```bash
# Run all tests (functional tests skipped if Tekla not running)
uv run pytest tests/

# Run only unit tests
uv run pytest tests/unit/

# Run specific test file
uv run pytest tests/unit/test_models.py

# Run specific test function
uv run pytest tests/unit/test_models.py::test_get_element_type_by_class_valid
```

## Test Naming Conventions

All test object names (parts, assemblies, UDAs) must start with `MCP_TEST_` prefix to prevent conflicts and make cleanup easy.

## Notes

- Functional tests modify actual Tekla model - run only in test/development environment
- Unit tests do not require Tekla to be running
