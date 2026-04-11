"""
Modeling tools provider for Tekla MCP server.

Provides tools for placing beams, columns, panels and managing elements.
"""

from typing import Any

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.models import (
    BeamInput,
    ColumnInput,
    PanelInput,
)
from tekla_mcp_server.tools.modeling import (
    tool_place_beams,
    tool_place_columns,
    tool_place_panels,
    tool_delete_selected,
)
from tekla_mcp_server.utils import log_mcp_tool_call


modeling_provider = LocalProvider()


@modeling_provider.tool()
@log_mcp_tool_call
def place_beams(beams: list[BeamInput] | None = None) -> dict[str, Any]:
    """
    Places multiple beams in the Tekla model.

    ## INPUT
    - `beams` [Required]: List of beam definitions, each containing:
        - `start` [Required]: Start point as {x, y, z}
        - `end` [Required]: End point as {x, y, z}
        - `profile` [Required]: Profile name (e.g., "300*600", "HEA200")
        - `material` [Required]: Material grade (e.g., "C30/37", "S235JR")
        - `class_number` [Required]: Tekla class number (e.g., 11, 100)
        Use tekla://filters/view to discover valid classes.
        - `name` [Optional]: Element name
        - `position` [Optional]: Position settings with keys:
            - `plane`: "LEFT", "MIDDLE", "RIGHT" (default: "MIDDLE")
            - `plane_offset`: Offset in mm along plane axis
            - `depth`: "FRONT", "MIDDLE", "BEHIND" (default: "MIDDLE")
            - `depth_offset`: Offset in mm along depth axis
            - `rotation`: "FRONT", "TOP", "BACK", "BOTTOM" (default: "FRONT")
            - `rotation_offset`: Rotation offset in degrees

    ## EXAMPLES
    ```json
    {
      "beams": [
        {"start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 5000, "y": 0, "z": 0}, "profile": "300*600", "material": "C30/37", "class_number": 11},
        {"start": {"x": 5000, "y": 0, "z": 0}, "end": {"x": 10000, "y": 0, "z": 0}, "profile": "300*600", "material": "C30/37", "class_number": 11}
      ]
    }
    ```
    """
    if not beams:
        return {"status": "error", "message": "No beams provided"}
    return tool_place_beams(beams)


@modeling_provider.tool()
@log_mcp_tool_call
def place_columns(columns: list[ColumnInput] | None = None) -> dict[str, Any]:
    """
    Places multiple columns (vertical beams) in the Tekla model.

    ## INPUT
    - `columns` [Required]: List of column definitions, each containing:
        - `base` [Required]: Base point as {x, y, z}
        - `height` [Required]: Column height in mm (must be > 0)
        - `profile` [Required]: Profile name (e.g., "300*300", "HEA300")
        - `material` [Required]: Material grade (e.g., "C30/37", "S235JR")
        - `class_number` [Required]: Tekla class number (e.g., 10, 101)
        Use tekla://filters/view to discover valid classes.
        - `name` [Optional]: Element name
        - `position` [Optional]: Position settings with keys:
            - `plane`: "LEFT", "MIDDLE", "RIGHT" (default: "MIDDLE")
            - `plane_offset`: Offset in mm along plane axis
            - `depth`: "FRONT", "MIDDLE", "BEHIND" (default: "MIDDLE")
            - `depth_offset`: Offset in mm along depth axis
            - `rotation`: "FRONT", "TOP", "BACK", "BOTTOM" (default: "FRONT")
            - `rotation_offset`: Rotation offset in degrees

    ## EXAMPLES
    ```json
    {
      "columns": [
        {"base": {"x": 0, "y": 0, "z": 0}, "height": 3000, "profile": "400*400", "material": "C30/37", "class_number": 10},
        {"base": {"x": 5000, "y": 0, "z": 0}, "height": 3000, "profile": "400*400", "material": "C30/37", "class_number": 10}
      ]
    }
    ```
    """
    if not columns:
        return {"status": "error", "message": "No columns provided"}
    return tool_place_columns(columns)


@modeling_provider.tool()
@log_mcp_tool_call
def place_panels(panels: list[PanelInput] | None = None) -> dict[str, Any]:
    """
    Places multiple wall panels in the Tekla model.

    ## INPUT
    - `panels` [Required]: List of panel definitions, each containing:
        - `start` [Required]: Start point as {x, y, z}
        - `end` [Required]: End point as {x, y, z}
        - `profile` [Required]: Profile name (e.g., "3000*200")
        - `material` [Required]: Material grade (e.g., "C30/37")
        - `class_number` [Required]: Tekla class number (e.g., 1)
        Use tekla://filters/view to discover valid classes.
        - `name` [Optional]: Element name
        - `position` [Optional]: Position settings with keys:
            - `plane`: "LEFT", "MIDDLE", "RIGHT" (default: "MIDDLE")
            - `plane_offset`: Offset in mm along plane axis
            - `depth`: "FRONT", "MIDDLE", "BEHIND" (default: "MIDDLE")
            - `depth_offset`: Offset in mm along depth axis
            - `rotation`: "FRONT", "TOP", "BACK", "BOTTOM" (default: "FRONT")
            - `rotation_offset`: Rotation offset in degrees

    ## EXAMPLES
    ```json
    {
      "panels": [
        {"start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 3000, "y": 0, "z": 0}, "profile": "3000*200", "material": "C30/37", "class_number": 1}
      ]
    }
    ```
    """
    if not panels:
        return {"status": "error", "message": "No panels provided"}
    return tool_place_panels(panels)


@modeling_provider.tool()
@log_mcp_tool_call
def delete_selected() -> dict[str, Any]:
    """
    Deletes all currently selected elements in Tekla.

    ## INPUT
    - No additional parameters required.
    """
    return tool_delete_selected()
