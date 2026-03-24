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
    "tekla_name": "Component name",
    "number": -1,
    "description": "Component description for LLM",
    "custom_properties": {
      "PropertyName": {
        "description": "Property description for LLM",
        "type": "int|float|str"
      }
    }
  }
}
```
### Component Key Naming
The `component_key` is the internal identifier for a component. Use lowercase name without spaces:
```json
{
  "lifting_anchor": { ... },      // ✓ lowercase, no spaces
  "mesh_bars": { ... },           // ✓ lowercase, no spaces  
  "My Component": { ... }         // ✗ avoid - spaces, capital letters
}
```

### Required Fields
- `tekla_name`: The name of the component.
- `number`: The number of the component. For custom components the number is -1, for plug-ins the number is -100000. Tekla system components have specific numbers.

### Optional Fields
The `description` and `custom_properties` fields are optional and contain data for the LLM to understand component capabilities and available properties. These are exposed via the `tekla://components/{component_key}` MCP resource.

By default, settings for two Tekla components are included:

#### `Lifting Anchor`
No custom properties are supported. The placement of the component is performed by custom handlers (see below).

#### `Mesh Bars`
Only supports straight rebars with same properties on all sides.
Does not support splicing and setting custom UDA for reinforcing bars.

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
        "anchor_types": { ... }
      }
    }
  }
}
```

Handlers are defined in `tekla/component_handlers.py` and use the `@register_handler` decorator.

#### Built-in Handlers

##### `LiftingAnchorsHandler`
Automatically selects lifting anchors based on element weight, calculates anchor positions and places them with recesses according to predefined settings.

**Configuration:**
```json
{
  "safety_margin": 5,
  "anchor_types": {
    "P1": {
      "active": true,
      "type": "long",
      "element_type": ["CONCRETE_WALL"],
      "capacity": 1.0,
      "min_edge_distance": 300.0,
      "attributes": {
        "RecessLength": 130.0,
        "RecessHeight": 110.0,
        "RecessInnerLength": 25.0,
        "DistOutOfBeam": -30.0
      }
    }
  }
}
```

## Environment Variables

MCP servers receive environment variables from the client. The Tekla MCP Server supports the following:

| Variable | Description | Default |
|----------|-------------|---------|
| `TEKLA_MCP_LOG_LEVEL` | Logging level | `INFO` |
| `TEKLA_MCP_LOG_FILE_PATH` | Log file path | `mcp_server.log` |
| `TEKLA_MCP_CONFIG_DIR` | Config directory | `config` |

For example, in Claude Desktop:

```json
{
  "mcpServers": {
    "tekla-mcp": {
      "command": "python",
      "args": ["src/tekla_mcp_server/mcp_server.py"],
      "env": {
        "TEKLA_MCP_LOG_LEVEL": "DEBUG",
        "TEKLA_MCP_LOG_FILE_PATH": "mcp_server.log",
        "TEKLA_MCP_CONFIG_DIR": "config"
      }
    }
  }
}
```

### Logging Levels

| Level | Use Case |
|-------|----------|
| `DEBUG` | Detailed diagnostic information, development |
| `INFO` | General operational events, default for production |
| `WARNING` | Potential issues that don't prevent operation |
| `ERROR` | Serious problems affecting functionality |
| `CRITICAL` | Critical errors causing shutdown |


### Local Development

For local development, copy `.env.example` to `.env` and configure values there. The server reads these at startup.
