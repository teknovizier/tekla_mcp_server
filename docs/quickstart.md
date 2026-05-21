# Quickstart

Python 3.11+ required. Install dependencies:

```bash
uv pip install -r requirements.txt
```

For development:

```bash
uv pip install -r requirements-dev.txt
```

## Configuration

1. **settings.json**: Copy `config/settings.sample.json` to `config/settings.json`

| Property | Default | Description |
|----------|---------|-------------|
| `tekla_path` | `C:\Program Files\Tekla Structures\2022.0\bin` | Tekla Structures binary directory |
| `context_folder` | `context` | Path to the folder with markdown files. Their contents can be accessed by LLM via `project://context` MCP resource to provide context like project design requirements, element naming conventions, etc. |
| `excluded_tags` | `[]` | List of tool tags to hide from the LLM. For more information see [configuration guide](configuration.md#tool-visibility). |
| `embeddings.enabled` | `true` | Enable semantic attribute search |
| `embeddings.embedding_model` | `teknovizier/minilm-tekla-attr-embed-v1` | HuggingFace model or local path |
| `embeddings.embedding_spread_threshold` | `0.1` | Min stddev for auto-resolution (0-1) |
| `embeddings.embedding_minimum_threshold` | `0.8` | Min confidence score (0-1) |
| `tolerances.default` | `20.0` | Default spatial tolerance in mm |
| `tolerances.wall_pairing` | `50.0` | Tolerance used for wall pairing in mm |
| `tolerances.center_tolerance_factor` | `0.05` | Relative factor for center-point tolerance |

2. **element_types.json**: Copy `config/element_types.sample.json` to `config/element_types.json` and set Tekla classes and numbering prefixes.
3. **semantic_overrides.json**: Copy `config/semantic_overrides.sample.json` to `config/semantic_overrides.json` for attribute name overrides.
4. **base_components.json**: Copy `config/base_components.sample.json` to `config/base_components.json` and configure available components.
5. **report_properties.json**: Copy `config/report_properties.sample.json` to `config/report_properties.json`.

## Running the Server

Configure `mcp_server.py` as a custom server in your MCP client. For client-specific installation instructions see the [MCP Installation Guide](https://mcp-install-instructions.alpic.cloud/servers/tekla-mcp-server).

You will need to update the JSON configuration with your own paths. Replace all `C:\\path\\to\\...` placeholders with the actual locations on your machine:

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

## Troubleshooting

### Python Package Conflict
You may experience a naming conflict with the `clr` package. Solution: rename or delete `C:\Users\User\AppData\Local\Programs\Python\Python313\Lib\site-packages\clr`.

### Tekla Connection Issues
- Ensure Tekla Structures is running and a model is open before using MCP tools
- Check that `tekla_path` in `settings.json` points to the correct Tekla binary directory (e.g. `C:\Program Files\Tekla Structures\2022.0\bin`)
- For Tekla 2026, confirm that `<tekla_path>\Net48Runtime` exists and contains the Tekla libraries
- Ensure the Python process has read access to the Tekla installation directory

### Configuration Not Loading
- Check the log file for errors - all config failures are logged with details
- Ensure all required JSON files exist in the config directory: `settings.json`, `element_types.json`, `semantic_overrides.json`, `base_components.json`, `report_properties.json`
- Validate JSON syntax (trailing commas and comments are not valid JSON)
- Config files are **read once on startup**. Restart the MCP server after any changes

### Embedding Model Issues
- If semantic mapping fails, set `"embeddings": { "enabled": false }` in `settings.json` to fall back to LLM-only attribute resolution
- The embedding model downloads automatically on first use (~120 MB)
- If the download hangs, manually download `teknovizier/minilm-tekla-attr-embed-v1` from HuggingFace and set `embedding_model` to the local path
