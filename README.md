[![Python Tests](https://github.com/teknovizier/tekla_mcp_server/actions/workflows/python-tests.yml/badge.svg)](https://github.com/teknovizier/tekla_mcp_server/actions/workflows/python-tests.yml)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue?style=flat&logo=python)](https://github.com/teknovizier/tekla_mcp_server/blob/main/README.md#requirements)
[![License](https://img.shields.io/github/license/teknovizier/tekla_mcp_server?color=green)](https://github.com/teknovizier/tekla_mcp_server/blob/main/LICENSE)

![Tekla MCP Server](assets/tekla_mcp_server_logo_small.png)

# Tekla MCP Server

This server facilitates interaction with **Tekla Structures**, helping users speed up modeling processes. It acts as a bridge between users and Tekla, enabling automated workflows and improving efficiency.

> #### 📌 What is MCP?
>
> *MCP* stands for **Model Context Protocol**, and it is a communication protocol introduced by Anthropic to enable more efficient and secure interactions between large language models and other systems, such as human users or other AI agents.
>
> **Tekla MCP Server** uses AI-powered natural language processing to make interactions more human-readable, allowing you to work with a set of tools using plain text.

To use this server, users must first install and configure an MCP client.

### Tools
The server provides the following tools:
| Tool                             | Description                                                                 |
|----------------------------------|-----------------------------------------------------------------------------|
| `put_wall_lifting_anchors`       | Insert `Lifting Anchor (80)` Tekla components in the selected elements      |
| `remove_wall_lifting_anchors`    | Remove `Lifting Anchor (80)` Tekla components from the selected elements    |
| `put_custom_detail_components`   | Insert custom detail components with specified name to the selected elements|
| `select_elements_using_filter`   | Select elements in Tekla model based on their type or Tekla class and name or profile |
| `select_elements_using_filter_name`   | Select elements in Tekla model based on the predefined filter |
| `select_elements_using_guid`     | Select elements in Tekla model by their GUID                                |
| `select_elements_assemblies_or_main_parts` | Get assemblies or main parts for the elements selected in Tekla model and select them |
| `draw_elements_names`            | Draw the temporary names for the selected elements in Tekla in the currently active rendered view |
| `zoom_to_selection`            | Zooms the currently active rendered view to fit the currently selected elements |
| `convert_cut_parts_to_real_parts` | Convert all cut parts in the selected elements into real model parts       |
| `set_elements_udas`              | Set custom attributes on selected Tekla elements. You can choose to keep existing values or replace them with new ones |
| `get_elements_properties`       | Retrieve structured data about selected elements in the Tekla model, including key properties like position, GUID, main part details, weight, and any defined custom properties |

### Compatibility
The server was tested to work with **only Tekla 2022** and may not be compatible with other versions of Tekla Structures.

Verified to work correctly with [DeepChat](https://deepchat.thinkinai.xyz) and [chatmcp](https://github.com/daodao97/chatmcp) clients, along with the following language models:
- GPT-4o
- DeepSeek
- Gemini 2.0 Flash

## Requirements

Python 3.11 or newer, along with some libraries, is required. You can install all the necessary libraries by running:

    $ uv pip install -r requirements.txt

⚠️ *Note:* You may experience a naming conflict with the `clr` string styling package. A solution is to rename or delete the folder `C:\Users\User\AppData\Local\Programs\Python\Python313\Lib\site-packages\clr`.

## Setting up

* Rename `config/settings.sample.json` to `config/settings.json` and adjust the values:

| **Property**         | **Default**                                        | **Description**                                                                 |
|-----------------------|----------------------------------------------------|---------------------------------------------------------------------------------|
| `tekla_path`          | "C:\\Program Files\\Tekla Structures\\2022.0\\bin" | The path to the directory where Tekla Structures is located                      |
| `content_attributes_file_path`          | "C:\\Program Files\\Tekla Structures\\2022.0\\bin\\applications\\Tekla\\Tools\\TplEd\\settings\\contentattributes_global.lst" | The path to the `contentattributes_global.lst` file                      |

* Rename `config/lifting_anchor_types.sample.json` to `config/lifting_anchor_types.json`, and specify the components for the lifting anchors used in your projects along with their attributes
* Rename `config/element_types.sample.json` to `config/element_types.json`, and set the values of Tekla classes used in your model
* Configure `mcp_server.py` as a custom MCP server in your MCP client

## Distribution

A standalone binary file can be created using [PyInstaller](https://pyinstaller.org) for easier distribution. To do this, install PyInstaller:

    $ uv pip install pyinstaller

Then, generate an executable with:

    $ pyinstaller mcp_server.py

This will produce a binary file inside the `dist/mcp_server/` directory, which can be distributed without requiring Python installation. Ensure the `_internals` directory is included alongside the binary. 

Additionally, when using this option, configuration files should be copied to the `_internals/config` directory.

## License

This software is open-source and released under the **GPLv3 license**. You are free to use, modify, and distribute it, as long as all modifications remain open-source under the same license.

For full details, please refer to the [LICENSE](LICENSE) file included in this repository.

## Disclaimer

This software is provided *as is*, without any warranties or guarantees of functionality, reliability, or security. The developer assumes **no responsibility** for any damages, data loss, or other issues arising from its use. 

Use at your own risk.
