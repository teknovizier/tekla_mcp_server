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
| `put_components`   | Insert Tekla components into the selected elements, using the given name and an optional custom property set. Supports intelligent components like `Lifting Anchor` with automatic placement calculations |
| `remove_components`   | Remove Tekla components with specified name from the selected elements |
| `select_elements_by_filter`   | Select elements in Tekla model based on type/Tekla class, name, profile, material, finish and phase |
| `select_elements_by_filter_name`   | Select elements in Tekla model based on the predefined filter |
| `select_elements_by_guid`     | Select elements in Tekla model by their GUID                                |
| `select_elements_assemblies_or_main_parts` | Get assemblies or main parts for the elements selected in Tekla model and select them |
| `draw_elements_labels`            | Draw the temporary labels (position, GUID, name, profile, material, finish, Tekla class, weight or any defined report property) for the selected elements in Tekla in the currently active rendered view  |
| `zoom_to_selection`            | Zooms the currently active rendered view to fit the currently selected elements |
| `show_only_selected`            | Show only the currently selected elements in the currently active rendered view  |
| `cut_elements_with_zero_class_parts` | Performs boolean cuts on selected elements using elements in class 0, with optional deletion of cutting parts       |
| `convert_cut_parts_to_real_parts` | Convert all cut parts in the selected elements into real model parts       |
| `set_elements_udas`              | Set custom attributes on selected Tekla elements. You can choose to keep existing values or replace them with new ones |
| `get_all_elements_udas`       | Retrieve structured data about all custom attributes for the selected Tekla elements |
| `get_elements_properties`       | Retrieve structured data about selected elements in the Tekla model, including key properties (position, GUID, name, profile, material, finish, Tekla class), weight, and any defined report properties |

### Compatibility
The server was tested to work with **only Tekla 2022** and may not be compatible with other versions of Tekla Structures.

Verified to work correctly with [DeepChat](https://deepchat.thinkinai.xyz) and [chatmcp](https://github.com/daodao97/chatmcp) clients, along with the following language models:
- GPT-4o
- DeepSeek
- Gemini 2.0 Flash

## Requirements

Python 3.11 or newer, along with some libraries, is required. You can install all the necessary libraries by running:

```bash
uv pip install -r requirements.txt
```

⚠️ *Note:* You may experience a naming conflict with the `clr` string styling package. A solution is to rename or delete the folder `C:\Users\User\AppData\Local\Programs\Python\Python313\Lib\site-packages\clr`.

## Setting up

* Rename `config/settings.sample.json` to `config/settings.json` and adjust the values:

| **Property**         | **Default**                                        | **Description**                                                                 |
|-----------------------|----------------------------------------------------|---------------------------------------------------------------------------------|
| `tekla_path`          | "C:\\Program Files\\Tekla Structures\\2022.0\\bin" | The path to the directory where Tekla Structures is located                      |
| `content_attributes_file_path`          | "C:\\Program Files\\Tekla Structures\\2022.0\\bin\\applications\\Tekla\\Tools\\TplEd\\settings\\contentattributes_global.lst" | The path to the `contentattributes_global.lst` file                      |

* Rename `config/lifting_anchor_types.sample.json` to `config/lifting_anchor_types.json`, and specify the components for the lifting anchors used in your projects along with their attributes
* Rename `config/element_types.sample.json` to `config/element_types.json`, and set the values of Tekla classes used in your model
* Rename `config/base_components.sample.json` to `config/base_components.json`, and specify the names and component numbers you'd like to make available to the MCP server
* Configure `mcp_server.py` as a custom MCP server in your MCP client

 ⚠️ *Note:* For the detailed steps, please see the [setup guide](https://www.notion.so/teknovizier/Tekla-MCP-Server-A-Tool-to-Improve-Your-Modeling-Workflows-264250689e1380f38a1be0b60477786b).

## Testing

The project includes a comprehensive test suite:

### Unit Tests (`tests/unit/`)
- `test_init.py`: Configuration loading, DLL initialization and error handling
- `test_models.py`: Data model validation
- `test_tekla_utils.py`: Tekla API wrapper tests

### Functional Tests (`tests/functional/`)
- `test_mcp_server.py`: End-to-end MCP tool integration tests

### Running Tests

```bash
# Run all tests (functional tests will be skipped if Tekla is not running)
uv run pytest tests/

# Run only unit tests
uv run pytest tests/unit/

# Run specific test file
uv run pytest tests/unit/test_models.py

# Run specific test function
uv run pytest tests/unit/test_models.py::test_get_element_type_by_class_valid
```

⚠️ *Note:* Functional tests modify actual Tekla model. Run them only in test/development environment.

## Distribution

A standalone binary file can be created using [PyInstaller](https://pyinstaller.org) for easier distribution. To do this, install PyInstaller:

```bash
uv pip install pyinstaller
```

Then, generate an executable with:

```bash
uv run pyinstaller mcp_server.py
```

This will produce a binary file inside the `dist/mcp_server/` directory, which can be distributed without requiring Python installation. Ensure the `_internals` directory is included alongside the binary. 

Additionally, when using this option, configuration files should be copied to the `_internals/config` directory.

## License

This software is open-source and released under the **GPLv3 license**. You are free to use, modify, and distribute it, as long as all modifications remain open-source under the same license.

For full details, please refer to the [LICENSE](LICENSE) file included in this repository.

## Disclaimer

This software is provided *as is*, without any warranties or guarantees of functionality, reliability, or security. The developer assumes **no responsibility** for any damages, data loss, or other issues arising from its use. 

Use at your own risk.
