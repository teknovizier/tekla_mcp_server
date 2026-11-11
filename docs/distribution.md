# Distribution

Create a standalone binary for distribution using PyInstaller.

## Build

```bash
uv pip install pyinstaller
uv run pyinstaller src/tekla_mcp_server/mcp_server.py
```

This produces an executable in `dist/mcp_server/`.

## Notes

- The `_internal` directory must be distributed alongside the binary
- Copy the whole `config` folder (including `attributes/` and `macros/`) to `dist/mcp_server/config/`, next to the executable. Settings stay editable there after install. See [Config Directory Contents](configuration.md#config-directory-contents)
- Python installation not required on target machine
