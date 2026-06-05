# Testing

The project includes unit tests and functional tests.

## Test Structure

### Unit Tests (`tests/unit/`)
- `test_init.py`: DLL loading and error handling
- `test_config.py`: Configuration management
- `test_models.py`: Data model validation
- `test_utils.py`: Decorators and utilities
- `test_tekla_utils.py`: Tekla API wrapper tests
- `test_tekla_model.py`: TeklaModel connection wrapper (singleton, thread safety)
- `test_tekla_model_object.py`: Tekla ModelObject wrappers
- `test_tekla_view.py`: Tekla view wrapper
- `test_tekla_template_attrs_parser.py`: Template attribute parsing
- `test_component_handlers.py`: Component handler plugins
- `test_embeddings.py`: Semantic attribute resolution
- `test_modeling.py`: Modeling utilities
- `test_tool_annotations.py`: Guards that every tool declares `readOnlyHint`/`destructiveHint`
- `test_docs_reference_parity.py`: Guards that `docs/reference.md` matches the provider code

### Functional Tests (`tests/functional/`)
- `conftest.py`: Shared fixtures and utilities
- `test_components.py`: Component placement, removal, modification
- `test_selection.py`: Element selection by filter, GUID, assembly
- `test_view.py`: View operations (labels, zoom, filters)
- `test_operations.py`: Boolean cuts, cut part conversion, macros
- `test_properties.py`: Property get/set, UDAs, numbering, comparison, IFC property copy
- `test_drawings.py`: Drawing retrieval and properties
- `test_modeling.py`: Modeling operations (beams, columns, grids, etc.)

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
- `test_docs_reference_parity.py` and `test_tool_annotations.py` parse the provider source via AST, so they run in CI without Tekla. Update `docs/reference.md` whenever you add or remove a tool or resource, or these tests fail
