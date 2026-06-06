<p align="center">
  <a href="https://github.com/teknovizier/tekla_mcp_server">
    <img src="https://github.com/teknovizier/tekla_mcp_server/raw/main/assets/tekla_mcp_server_logo_small.png" alt="Tekla MCP Server">
  </a>
</p>

<p align="center">
  <strong>
    Tekla and AI. Made Easy.
  </strong>
</p>

<p align="center">
  <a href="https://github.com/teknovizier/tekla_mcp_server/actions/workflows/python-tests.yml"><img
    src="https://github.com/teknovizier/tekla_mcp_server/actions/workflows/python-tests.yml/badge.svg"
    alt="Python Tests"
  /></a>
  <a href="https://github.com/teknovizier/tekla_mcp_server/blob/main/docs/quickstart.md"><img
    src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue?style=flat&logo=python"
    alt="Python versions"
  /></a>
  <a href="https://github.com/teknovizier/tekla_mcp_server/blob/main/LICENSE"><img
    src="https://img.shields.io/github/license/teknovizier/tekla_mcp_server?color=green"
    alt="License"
  /></a>
</p>

# Tekla MCP Server

This server enables interaction with **Tekla Structures**, helping users automate and accelerate modeling workflows. It acts as a bridge between AI agents or MCP-compatible clients and Tekla, exposing resources and tools for selection, component insertion, property management, modeling and view operations. A **read-only mode** is available for safe query-only access.

> #### 📌 What is MCP?
>
> *MCP* stands for **Model Context Protocol**, a communication protocol introduced by Anthropic to enable efficient and secure interactions between large language models and external systems.
>
> **Tekla MCP Server** uses AI-powered natural language processing to translate human intent into Tekla operations, allowing users to interact with tools using plain text.

To use this server, one must first install and configure an MCP client.

### Features

- **Modular Architecture**: Powered by FastMCP 3.0, with toolset organization through modular providers (Selection, View, Properties, Components, Operations, Drawings, Modeling).

- **Resource Discovery**: Auto‑detection of available filters, macros, components, Tekla phases, grids, material and rebar catalogs and project context files.

- **Component Handler Plugin System**: Flexible plugin model for Tekla components with lifecycle hooks, e.g., `Lifting Anchors` component selects anchors based on element weight and auto‑calculates anchor placement according to center of gravity.

- **LLM‑Powered Component Property Understanding**: Natural language mapping like "concrete cover thickness" → actual Tekla component property.

- **Semantic Attribute Mapping**: Hybrid semantic system (MiniLM embedding model + LLM fallback) for mapping user‑friendly names to Tekla attributes.

- **Flexible Access Control**: Possibility to run in read-only mode for safe query-only access and to hide specific tool categories based on project or workflow needs.

See [Reference](docs/reference.md) for complete list of tools and resources.

### Compatibility

Tested with **Tekla 2022** and **Tekla 2026**. See [Compatibility](docs/compatibility.md) for the full list of verified MCP clients and language models.

## Installation

For complete setup instructions, see [Quickstart Guide](docs/quickstart.md).


## Documentation

| Guide | Description |
|-------|-------------|
| [Reference](docs/reference.md) | Tools and resources reference |
| [Quickstart](docs/quickstart.md) | Setup and first steps |
| [Configuration](docs/configuration.md) | Config files and environment variables |
| [Testing](docs/testing.md) | Running tests |
| [Distribution](docs/distribution.md) | Building portable binary |

## License

This software is open-source and released under the **GPLv3 license**. You are free to use, modify, and distribute it, as long as all modifications remain open-source under the same license.

For full details, please refer to the [LICENSE](LICENSE) file included in this repository.

## Disclaimer

This software is provided *as is*, without any warranties or guarantees of functionality, reliability, or security. The developer assumes **no responsibility** for any damages, data loss, or other issues arising from its use.

Use at your own risk.