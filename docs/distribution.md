# Distribution

Create a standalone binary for distribution using PyInstaller.

## Build

```bash
uv pip install pyinstaller
uv run pyinstaller src/tekla_mcp_server/mcp_server.py
```

This produces an executable in `dist/mcp_server/`.

## Notes

- The `_internals` directory must be distributed alongside the binary
- Copy configuration files to `_internals/config/` for portable deployment
- Python installation not required on target machine