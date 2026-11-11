# Configuration

This guide covers all configuration files and environment variables.

## Settings (`settings.json`)

| Property | Default | Description |
|----------|---------|-------------|
| `tekla_path` | **required** | Tekla Structures binary directory, e.g. `C:\Program Files\Tekla Structures\2022.0\bin`. The server fails to start without it. |
| `context_folder` | `context` | Path to the folder with markdown files. Their contents can be accessed by LLM via `project://context` MCP resource to provide context like project design requirements, element naming conventions, etc. A relative path is resolved against the config directory, not the working directory. If the folder does not exist, `<config>/context` is used instead. |
| `excluded_tags` | `[]` | List of tool tags to hide from the LLM. Leave empty to expose all tools. See [Tool Visibility](#tool-visibility) below. |
| `read_only` | `false` | When `true`, shows only tools marked as read-only. Query, selection, and view/navigation tools remain available, anything that writes the model is hidden. |

### Tool Visibility

Controls which tools are exposed to the LLM. All tools are enabled by default. Use `read_only` to expose only read-only tools at once or `excluded_tags` to opt out specific groups.

#### `read_only`

When set to `true`, exposes **only** tools annotated with `readOnlyHint=true` (any tool without that annotation is hidden). Query tools plus selection and view/navigation tools remain fully available - these are transient UI actions that write nothing to the model, so inspection workflows still work (e.g. select objects, then read their properties). Every tool that writes the model, additive or destructive, is hidden. Use this for inspection or review sessions where accidental model changes must be prevented.

#### `excluded_tags`

| Tag | Tools covered |
|-----|--------------|
| `selection` | Select, filter, and inspect model objects |
| `view` | Camera, views, and visibility controls |
| `properties` | Read and write element properties and UDAs |
| `operations` | Cuts, clash checks, orphan and invalid-object checks, attaching, macros, reports, and other model operations |
| `components` | Place and manage Tekla components |
| `drawings` | Open, edit, print, export, and check existing drawings |
| `modeling` | Create and modify model objects |

MCP resources have no tags and cannot be hidden with `excluded_tags`.

**Example:** hide modeling tools:
```json
{ "excluded_tags": ["modeling"] }
```

Both settings compose: `excluded_tags` and `read_only` can be active simultaneously.


### Embeddings

| Property | Default | Description |
|----------|---------|-------------|
| `embeddings.enabled` | `false` | Enable semantic search |
| `embeddings.embedding_model` | none, **required** when `enabled` | HuggingFace model ID or local path. The sample settings use `teknovizier/minilm-tekla-attr-embed-v1`. |
| `embeddings.embedding_spread_threshold` | `0.1` | Min stddev for auto-resolution (0-1) |
| `embeddings.embedding_minimum_threshold` | `0.8` | Min confidence score (0-1) |

#### Semantic Attribute Mapping
The server uses **sentence-transformers** (MiniLM) to perform semantic attribute mapping for **template attributes**, converting user-friendly text into Tekla attribute names. It is disabled by default - without it, attribute names are resolved by exact and override matching only. When enabled, it loads **fine-tuned Tekla-specific model** published on HuggingFace: [teknovizier/minilm-tekla-attr-embed-v1](https://huggingface.co/teknovizier/minilm-tekla-attr-embed-v1).

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

Tolerances are grouped by domain: `model` for model operations and `drawings` for drawing layout.

| Property | Default | Description |
|----------|---------|-------------|
| `tolerances.model.default` | `20.0` | Default spatial tolerance in mm, used for bounding-box searches |
| `tolerances.model.wall_pairing` | `50.0` | Tolerance used for wall pairing operations in mm |
| `tolerances.model.center_tolerance_factor` | `0.05` | Relative factor for center-point tolerance (fraction of element size) |
| `tolerances.model.comparison` | `0.01` | Numeric tolerance used in `compare_elements`. Values within this tolerance are treated as equal. |
| `tolerances.drawings.snap_tolerance` | `0.1` | Snap tolerance in mm for `align_section_views`. Section views already within this distance of their projection are treated as aligned and left untouched. |
| `tolerances.drawings.sheet_size` | `1.0` | Tolerance in mm for matching sheet dimensions to standard paper sizes and multi-sheet tilings in `get_drawing_views`. |
| `tolerances.drawings.dimension_snap` | `0.5` | Tolerance in sheet mm for `check_for_unattached_dimensions`. A dimension point within this distance of a part corner or edge midpoint, bolt/hole centre, or grid/centre line is treated as attached/snapped. |

### Reports

| Property | Default | Description |
|----------|---------|-------------|
| `reports.preview_max_chars` | `2000` | Max characters returned in `content_preview` of `create_report`. Set to `0` to disable the preview (the file is not read). |
| `reports.preview_timeout` | `30` | Max seconds `create_report` blocks waiting for the report file to appear on disk before returning a warning. |

### Drawings

| Property | Default | Description |
|----------|---------|-------------|
| `drawings.timeout` | `120` | Max seconds `export_drawings`, `print_drawings` and `check_drawing_collisions` wait for exported files to appear in the output folder before raising an error. |
| `drawings.output_dir` | `".\PlotFiles"` | Output directory shared by `export_drawings` and `print_drawings`. Relative paths are resolved against the model folder. |
| `drawings.export.default_export_settings` | `""` (empty) | Customer `.dwgsetting` export setting name used by `export_drawings` by default. When non-empty, exports run in named mode using this setting as-is (format/version args are ignored). When empty, on-the-go mode patches the base setting with the chosen format and version. |
| `drawings.print.default_print_settings` | `""` (empty) | Customer `.PdfPrintOptions.xml` print setting name used by `print_drawings` by default. When non-empty, prints run in named mode using this setting as-is (size auto-detection is skipped). When empty, on-the-go mode patches the base setting with the auto-detected paper size and multi-sheet tiling. |

The base export settings are stored in `config/attributes/TEKLA_MCP_EXPORT_BASE.dwgsetting`, and the base print settings in `config/attributes/TEKLA_MCP_PDF_BASE.PdfPrintOptions.xml`. On every export or print call the server reads the base file, patches a copy with the chosen/detected values and writes that copy to the model's `attributes` folder. The files in `config/attributes` are never modified. You can adjust them directly, and the change applies from the next call without a restart.

Exported file names follow Tekla's `XS_DRAWING_PLOT_FILE_NAME_A/W/G/M/C` advanced options (one per drawing type). To change the output naming, set these values via Tekla's Advanced Options dialog and restart Tekla.

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
- `tekla_classes`: Array of Tekla class numbers for this element type (required)
- `name`: Default name given to new elements of this type by the `place_*` tools (optional)
- `assembly_prefix`: Prefix for assembly numbering (optional)
- `assembly_start_number`: Starting number for assembly numbering (required when `assembly_prefix` is set)
- `part_prefix`: Prefix for part numbering (optional, typically steel only - concrete usually uses assembly numbering only)
- `part_start_number`: Starting number for part numbering (required when `part_prefix` is set)

Besides `MATERIAL_CONCRETE` and `MATERIAL_STEEL`, the sample defines two groups whose entries only need `tekla_classes`: `MATERIAL_EMBEDDED` (classes treated as embedded details) and `MATERIAL_REINFORCEMENT` (classes treated as reinforcement).

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

#### `MeshBars`
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
| `TEKLA_MCP_LOG_FILE_PATH` | Log file path | `mcp_server.log` in the current working directory |
| `TEKLA_MCP_CONFIG_DIR` | Config directory, used as given even if it does not exist | First existing of: `config` next to the executable (PyInstaller build), `config` at the repository root, `config` in the current working directory |

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

### Config Directory Contents

`TEKLA_MCP_CONFIG_DIR` must point to a full copy of the repository's `config` folder, not only the JSON files:

| Path | Purpose |
|------|---------|
| `*.json` | Settings and the files described above, copied from the `*.sample.json` files |
| `context/` | Default `project://context` folder |
| `attributes/` | Base export, print and collision-layer settings installed into the model by the drawing tools |
| `macros/modeling/` | Macros installed into `XS_MACRO_DIRECTORY` by `print_drawings`, `export_drawings`, `explode_components`, `select_model_objects_from_drawings` and the drawing checks |

Without `attributes/` and `macros/`, the tools that depend on them fail with a "Bundled ... not found" error.

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
