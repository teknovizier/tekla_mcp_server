# Configuration

This guide covers all configuration files and environment variables.

## Settings (`settings.json`)

| Property | Default | Description |
|----------|---------|-------------|
| `tekla_path` | `C:\Program Files\Tekla Structures\2022.0\bin` | Tekla Structures binary directory |
| `requirements_folder` | `requirements` | Path to the folder with markdown files. Their contents can be accessed by LLM via `project://requirements` MCP resource to provide context like project design requirements, element naming conventions, etc. |

### Embeddings

| Property | Default | Description |
|----------|---------|-------------|
| `embeddings.enabled` | `true` | Enable semantic search |
| `embeddings.embedding_model` | `teknovizier/minilm-tekla-attr-embed-v1` | HuggingFace model ID or local path |
| `embeddings.embedding_spread_threshold` | `0.1` | Min stddev for auto-resolution (0-1) |
| `embeddings.embedding_minimum_threshold` | `0.8` | Min confidence score (0-1) |

#### Semantic Attribute Mapping
The server uses **sentence-transformers** (MiniLM) to perform semantic attribute mapping for **template attributes**, converting user-friendly text into Tekla attribute names. By default, it loads **fine‑tuned Tekla‑specific model** published on HuggingFace: [teknovizier/minilm-tekla-attr-embed-v1](https://huggingface.co/teknovizier/minilm-tekla-attr-embed-v1).

##### How it works

- MiniLM returns top candidates for user input.
- If top candidate is confident (above threshold), auto-select.
- If uncertain, top candidates passed to LLM for final selection.


#### Using a Different Model

Set `embeddings.embedding_model` to HuggingFace ID or local path:

```json
{
  "embeddings": {
    "embedding_model": "your-username/tekla-attribute-model"
  }
}
```

## Element Types (`element_types.json`)

Map element type names to Tekla class numbers:

```json
{
    "Concrete": {
        "CONCRETE_WALL": [1],
        "CONCRETE_SANDWICH_WALL": [2, 3]
    },
    "Steel": {
        "STEEL_BEAM": [100]
    }
}
```

## Semantic Overrides (`semantic_overrides.json`)

Override common ambiguous attributes to bypass semantic model:

```json
{
    "concrete cover thickness at the first rebar end": "CONCRETE_COVER_START",
    "rebar grade": "GRADE"
}
```

## Base Components (`base_components.json`)

Define available Tekla components:

```json
{
  "component_key": {
    "tekla_name": "Component Name",
    "number": -100000,
    "description": "Description for AI",
    "custom_properties": {
      "PropertyName": {
        "description": "Property description",
        "type": "int|float|str"
      }
    }
  }
}
```

Both `tekla_name` and `number` are required.

### Component Handlers

For specialized components, add a handler:

```json
{
  "component_key": {
    "tekla_name": "Lifting Anchor",
    "number": 30000080,
    "handler": {
      "name": "LiftingAnchorsHandler",
      "config": {
        "safety_margin": 5,
        "anchor_types": {}
      }
    }
  }
}
```

Handlers are defined in `tekla/component_handlers.py` and use the `@register_handler` decorator.

There is one built-in handler for `Lifting Anchor` component (`LiftingAnchorsHandler`) that automatically calculates anchor positions.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TEKLA_MCP_LOG_LEVEL` | Logging level | `INFO` |
| `TEKLA_MCP_LOG_FILE_PATH` | Log file path | `mcp_server.log` |
| `TEKLA_MCP_CONFIG_DIR` | Config directory | `config` |

For local development, use `.env` file (copy from `.env.example`).
