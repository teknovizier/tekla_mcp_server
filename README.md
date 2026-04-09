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

This server facilitates interaction with **Tekla Structures**, helping users automate and accelerate modeling workflows. It acts as a bridge between AI agents or MCP-compatible clients and Tekla, exposing resources and tools for selection, component insertion, property management and view operations.

> #### 📌 What is MCP?
>
> *MCP* stands for **Model Context Protocol**, and it is a communication protocol introduced by Anthropic to enable more efficient and secure interactions between large language models and other systems, such as human users or other AI agents.
>
> **Tekla MCP Server** uses AI-powered natural language processing to make interactions more intuitive, allowing user to work with tools using plain text.

To use this server, one must first install and configure an MCP client.

### Features

- **Modular Architecture**: Powered by FastMCP 3.0, with toolset organization through modular providers (Selection, View, Properties, Components, Operations, Drawing).

- **Resource Discovery**: Auto‑detection of available filters, macros, components, and custom requirements and instructions.

- **Component Handler Plugin System**: Flexible plugin model for Tekla components with lifecycle hooks, e.g., `Lifting Anchors` component select anchors based on element weight and auto‑calculates anchor placement according to center of gravity.

- **LLM‑Powered Component Property Understanding**: Natural language mapping like "concrete cover thickness" → actual Tekla component property.

- **Semantic Attribute Mapping**: Hybrid semantic system (MiniLM + LLM fallback) for mapping user‑friendly names to Tekla attributes.


See [Reference](docs/reference.md) for complete list of tools and resources.

### Compatibility

The server was tested to work with **only Tekla 2022** and may not be compatible with other versions of Tekla Structures.

Verified to work correctly with [DeepChat](https://deepchat.thinkinai.xyz) and [chatmcp](https://github.com/daodao97/chatmcp) clients, along with the following language models:
- GPT-4o
- DeepSeek
- Gemini 2.0 Flash
- Gemini 2.5 Flash
- Qwen3
- gpt-oss

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