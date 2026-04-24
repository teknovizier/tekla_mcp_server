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
| `requirements_folder` | `requirements` | Path to the folder with markdown files. Their contents can be accessed by LLM via `project://requirements` MCP resource to provide context like project design requirements, element naming conventions, etc. |
| `embeddings.enabled` | `true` | Enable semantic search |
| `embeddings.embedding_model` | `teknovizier/minilm-tekla-attr-embed-v1` | HuggingFace model or local path |
| `embeddings.embedding_spread_threshold` | `0.1` | Min stddev for auto-resolution (0-1) |
| `embeddings.embedding_minimum_threshold` | `0.8` | Min confidence score (0-1) |

2. **element_types.json**: Copy `config/element_types.sample.json` to `config/element_types.json` and set Tekla classes and numbering prefixes.
3. **semantic_overrides.json**: Copy `config/semantic_overrides.sample.json` to `config/semantic_overrides.json` for attribute name overrides.
4. **base_components.json**: Copy `config/base_components.sample.json` to `config/base_components.json` and configure available components.

## Running the Server

Configure `mcp_server.py` as a custom server in your MCP client:

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
- Ensure Tekla Structures is running and model is open before using MCP tools
- Check `tekla_path` in `settings.json` points to correct Tekla binary directory

### Configuration Not Loading
- Check log file for configuration errors
- Ensure all required JSON files exist in config directory
- Validate JSON syntax

### Embedding Model Issues
- If semantic mapping fails, set `embeddings.enabled: false` in `settings.json`
- Model downloads automatically on first use (~120MB)
