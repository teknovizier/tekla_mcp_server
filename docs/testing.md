# Testing

The project includes unit tests and functional tests.

## Test Structure

### Unit Tests (`tests/unit/`)

Pure Python, no Tekla needed, run in CI:
- `test_init.py`: DLL loading and error handling
- `test_config.py`: Configuration management
- `test_models.py`: Data model validation
- `test_utils.py`: Decorators and utilities
- `test_base_components_schema.py`: `base_components.json` schema
- `test_component_handlers.py`: Component handler plugins
- `test_drawing_export.py`: Export and print settings XML patching
- `test_dxf_operations.py`: DXF collision and attachment checks
- `test_embeddings.py`: Semantic attribute resolution
- `test_modeling.py`: Modeling utilities
- `test_provider_registration.py`: Provider and tool registration
- `test_tekla_template_attrs_index.py`: Template attribute index
- `test_tool_annotations.py`: Guards that every tool declares `readOnlyHint`/`destructiveHint`
- `test_docs_reference_parity.py`: Guards that `docs/reference.md` matches the provider code

Mock the Tekla API but import Tekla wrappers, so they need a local Tekla install and are skipped in CI:
- `test_tekla_utils.py`: Tekla API helpers
- `test_tekla_model.py`: TeklaModel connection wrapper (singleton, thread safety)
- `test_tekla_model_object.py`: Tekla ModelObject wrappers
- `test_tekla_view.py`: Tekla view wrapper
- `test_tekla_drawing_handler.py`: Drawing handler wrapper
- `test_tekla_template_attrs_parser.py`: Template attribute parsing
- `test_filter_builder.py`: Tekla filter expression builder
- `test_snapshot_builder.py`: Part and assembly snapshots
- `test_drawing_utils.py`: Drawing helpers
- `test_components_provider.py`, `test_drawings_provider_helpers.py`, `test_modeling_provider.py`, `test_properties_provider.py`, `test_selection_provider.py`: Provider helpers

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
# Run all tests (needs Tekla running with a test model open, see Notes)
uv run pytest tests/

# Run only the tests that need no Tekla, as CI does
CI=true uv run pytest tests/

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
- Functional tests are skipped only when `CI=true`. Otherwise they connect to the running Tekla instance and fail if it is not available
- Unit tests do not require Tekla to be running, but the mock-based ones need Tekla installed because importing the wrappers loads its DLLs
- `test_docs_reference_parity.py` and `test_tool_annotations.py` parse the provider source via AST, so they run in CI without Tekla. Update `docs/reference.md` whenever you add or remove a tool or resource, or these tests fail
