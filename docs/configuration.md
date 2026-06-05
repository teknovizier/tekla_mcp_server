# Configuration

This guide covers all configuration files and environment variables.

## Settings (`settings.json`)

| Property | Default | Description |
|----------|---------|-------------|
| `tekla_path` | `C:\Program Files\Tekla Structures\2022.0\bin` | Tekla Structures binary directory |
| `context_folder` | `context` | Path to the folder with markdown files. Their contents can be accessed by LLM via `project://context` MCP resource to provide context like project design requirements, element naming conventions, etc. |
| `excluded_tags` | `[]` | List of tool tags to hide from the LLM. Leave empty to expose all tools. See [Tool Visibility](#tool-visibility) below. |
| `read_only` | `false` | When `true`, shows only tools marked as read-only. Query, selection, and view/navigation tools remain available, anything that writes the model is hidden. |

### Tool Visibility

Controls which tools are exposed to the LLM. All tools are enabled by default. Use `read_only` to expose only read-only tools at once or `excluded_tags` to opt out specific groups.

#### `read_only`

When set to `true`, exposes **only** tools annotated with `readOnlyHint=true` (any tool without that annotation is hidden). Query tools plus selection and view/navigation tools remain fully available - these are transient UI actions that write nothing to the model, so inspection workflows still work (e.g. select objects, then read their properties). Every tool that writes the model, additive or destructive, is hidden. Use this for inspection or review sessions where accidental model changes must be prevented.

#### `excluded_tags`

| Tag | Tools covered | Notes |
|-----|--------------|-------|
| `resources` | MCP resources (project context, component definitions, etc.) | |
| `selection` | Select, filter, and inspect model objects | |
| `view` | Camera, views, and visibility controls | |
| `properties` | Read and write element properties and UDAs | |
| `operations` | Numbering, clash detection, and other model operations | |
| `components` | Place and manage Tekla components | |
| `drawings` | Drawing creation and management | |
| `modeling` | Create and modify model objects | |
**Example:** hide modeling tools:
```json
{ "excluded_tags": ["modeling"] }
```

Both settings compose: `excluded_tags` and `read_only` can be active simultaneously.


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

### Tolerances

| Property | Default | Description |
|----------|---------|-------------|
| `tolerances.default` | `20.0` | Default spatial tolerance in mm, used for bounding-box searches |
| `tolerances.wall_pairing` | `50.0` | Tolerance used for wall pairing operations in mm |
| `tolerances.center_tolerance_factor` | `0.05` | Relative factor for center-point tolerance (fraction of element size) |
| `tolerances.comparison` | `0.01` | Numeric tolerance used in `compare_elements`. Values within this tolerance are treated as equal. |

### Reports

| Property | Default | Description |
|----------|---------|-------------|
| `reports.preview_max_chars` | `2000` | Max characters returned in `content_preview` of `create_report`. Set to `0` to disable the preview (the file is not read). |
| `reports.preview_timeout` | `30` | Max seconds `create_report` blocks waiting for the report file to appear on disk before returning a warning. |

## Element Types (`element_types.json`)

Map element type names to Tekla class numbers and numbering settings:

```json
{
    "MATERIAL_CONCRETE": {
        "CONCRETE_WALL": {
            "tekla_classes": [1],
            "name": "WALL",
            "assembly_prefix": "W",
            "assembly_start_number": 1
        },
        "CONCRETE_SANDWICH_WALL": {
            "tekla_classes": [2, 3],
            "name": "SANDWICH_WALL",
            "assembly_prefix": "SW",
            "assembly_start_number": 1
        }
    },
    "MATERIAL_STEEL": {
        "STEEL_BEAM": {
            "tekla_classes": [100],
            "name": "BEAM",
            "part_prefix": "SB",
            "part_start_number": 1,
            "assembly_prefix": "SBA",
            "assembly_start_number": 1
        }
    }
}
```

**Fields:**
- `tekla_classes`: Array of Tekla class numbers for this element type
- `assembly_prefix`: Prefix for assembly numbering (required for all materials)
- `assembly_start_number`: Starting number for assembly numbering (default: 1)
- `part_prefix`: Prefix for part numbering (steel only - concrete typically uses assembly-only)
- `part_start_number`: Starting number for part numbering (steel only)

## Report Properties (`report_properties.json`)

Controls which Tekla report properties are extracted for each object type when building element snapshots. Snapshots are used both for reporting element properties (`get_elements_properties`) and for element comparison (`compare_elements`).

```json
{
    "part": ["AREA", "PROFILE", "MATERIAL", "WEIGHT", "..."],
    "assembly": ["AREA", "NAME", "WEIGHT", "..."],
    "rebar_group": ["GRADE", "LENGTH", "SHAPE", "..."],
    "rebar_mesh": ["GRADE", "LENGTH", "SIZE", "..."],
    "rebar_strand": ["GRADE", "LENGTH", "SIZE", "..."],
    "weld": ["WELD_SIZE1", "WELD_TYPE1", "WELD_LENGTH1", "..."]
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

By default, settings for three Tekla components are included:

#### `Lifting Anchor`
No properties are supported. The placement of the component is performed by custom handlers (see below).

#### `Mesh Bars`
Only supports straight rebars with same properties on all sides.
Does not support splicing and setting custom UDA for reinforcing bars.

#### `Edge and Corner`
Supports all properties.

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
| `TEKLA_MCP_LOG_FILE_PATH` | Log file path | `C:\path\to\mcp_server.log` |
| `TEKLA_MCP_CONFIG_DIR` | Config directory | `C:\path\to\tekla_mcp_server\config` |

For example, in Claude Desktop:

```json
{
  "mcpServers": {
    "tekla-mcp": {
      "command": "python",
      "args": ["C:\\path\\to\\tekla_mcp_server\\src\\tekla_mcp_server\\mcp_server.py"],
      "env": {
        "TEKLA_MCP_LOG_LEVEL": "INFO",
        "TEKLA_MCP_LOG_FILE_PATH": "C:\\path\\to\\mcp_server.log",
        "TEKLA_MCP_CONFIG_DIR": "C:\\path\\to\\tekla_mcp_server\\config"
      }
    }
  }
}
```

**Note:** All path variables (`TEKLA_MCP_LOG_FILE_PATH`, `TEKLA_MCP_CONFIG_DIR`) should use absolute paths.

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
