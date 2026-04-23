"""
Resources provider for Tekla MCP server.

Provides read-only data resources for discovery and metadata.
"""

from fastmcp.resources import ResourceContent, ResourceResult
from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.config import get_config
from tekla_mcp_server.tekla.loader import Grid
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.utils import get_macros, get_filters
from tekla_mcp_server.utils import mcp_handler, parse_coordinate_string, parse_label_string


resources_provider = LocalProvider()


@resources_provider.resource("tekla://components")
@mcp_handler(scope="resource")
def get_component_list() -> ResourceResult:
    """
    Returns mapping of Tekla component names to config keys.

    Use this to find the config key for a component, then call
    `tekla://components/{component_key}` to get the property schema.
    """
    data = {comp.get("tekla_name"): key for key, comp in get_config().base_components.items() if comp.get("tekla_name")}
    return ResourceResult(contents=[ResourceContent(content=data, mime_type="application/json")])


@resources_provider.resource("tekla://components/{component_key}")
@mcp_handler(scope="resource")
def get_component_schema(component_key: str) -> ResourceResult:
    """
    Returns the custom_properties schema for a specific component.
    """
    component = get_config().base_components.get(component_key)
    if component:
        description = component.get("description", "")
        custom_props = component.get("custom_properties", {})
        schema = {"description": description, "custom_properties": custom_props}
        return ResourceResult(contents=[ResourceContent(content=schema, mime_type="application/json")])
    return ResourceResult(contents=[])


@resources_provider.resource("tekla://macros")
@mcp_handler(scope="resource")
def get_macro_list() -> ResourceResult:
    """
    Returns a list of available Tekla macros from configured directories.
    """
    return ResourceResult(contents=[ResourceContent(content=get_macros(), mime_type="application/json")])


@resources_provider.resource("tekla://element_types")
@mcp_handler(scope="resource")
def get_element_types() -> ResourceResult:
    """
    Returns a list of available Tekla element types and their corresponding class numbers.
    """
    return ResourceResult(contents=[ResourceContent(content=get_config().get_element_types_list(), mime_type="application/json")])


@resources_provider.resource("tekla://filters/selection")
@mcp_handler(scope="resource")
def get_selection_filter_list() -> ResourceResult:
    """
    Returns a list of available Tekla selection filter names from .SObjGrp files.
    """
    return ResourceResult(contents=[ResourceContent(content=get_filters(".SObjGrp"), mime_type="application/json")])


@resources_provider.resource("tekla://filters/view")
@mcp_handler(scope="resource")
def get_view_filter_list() -> ResourceResult:
    """
    Returns a list of available Tekla view filter names from .VObjGrp files.
    """
    return ResourceResult(contents=[ResourceContent(content=get_filters(".VObjGrp"), mime_type="application/json")])


@resources_provider.resource("tekla://phases")
@mcp_handler(scope="resource")
def get_phase_list() -> ResourceResult:
    """
    Returns a list of all phases in the current Tekla model.
    """
    tekla_model = TeklaModel()
    phases = tekla_model.model.GetPhases()

    phase_list = []
    current_phase = None
    for phase in phases:
        is_current = phase.IsCurrentPhase
        if is_current == 1:
            current_phase = phase.PhaseNumber
        phase_list.append(
            {
                "phase_number": phase.PhaseNumber,
                "phase_name": phase.PhaseName,
                "phase_comment": phase.PhaseComment,
            }
        )

    return ResourceResult(
        contents=[
            ResourceContent(
                content={"phases": phase_list, "current_phase": current_phase},
                mime_type="application/json",
            )
        ]
    )


@resources_provider.resource("tekla://grids")
@mcp_handler(scope="resource")
def get_grid_list() -> ResourceResult:
    """
    Returns rectangular grid data from the current Tekla model.
    """
    tekla_model = TeklaModel()
    enumerator = tekla_model.model.GetModelObjectSelector().GetAllObjectsWithType(Grid.ModelObjectEnum.GRID)
    grid_data = []
    while enumerator.MoveNext():
        grid = enumerator.Current

        # Tekla may have more labels than axis coordinates, extra labels are ignored
        x_coords = parse_coordinate_string(grid.CoordinateX)
        x_labels = parse_label_string(grid.LabelX)
        y_coords = parse_coordinate_string(grid.CoordinateY)
        y_labels = parse_label_string(grid.LabelY)
        z_coords = parse_coordinate_string(grid.CoordinateZ)
        z_labels = parse_label_string(grid.LabelZ)

        grid_data.append(
            {
                "guid": grid.Identifier.GUID.ToString(),
                "name": grid.Name,
                "axes": {
                    "x": {
                        "coords": list(x_coords)[: len(x_labels)],
                        "labels": list(x_labels)[: len(x_coords)],
                    },
                    "y": {
                        "coords": list(y_coords)[: len(y_labels)],
                        "labels": list(y_labels)[: len(y_coords)],
                    },
                    "z": {
                        "coords": list(z_coords)[: len(z_labels)],
                        "labels": list(z_labels)[: len(z_coords)],
                    },
                },
            }
        )
    return ResourceResult(
        contents=[
            ResourceContent(
                content={"grids": grid_data},
                mime_type="application/json",
            )
        ]
    )


@resources_provider.resource("tekla://connection_status")
@mcp_handler(scope="resource")
def get_connection_status() -> ResourceResult:
    """
    Returns the current Tekla connection status.
    """
    model = TeklaModel()
    return ResourceResult(
        contents=[
            ResourceContent(
                content={
                    "connected": True,
                    "model_path": model.model.GetInfo().ModelPath,
                    "message": "Connected to Tekla model",
                },
                mime_type="application/json",
            )
        ]
    )


@resources_provider.resource("project://requirements")
@mcp_handler(scope="resource")
def get_project_requirements() -> ResourceResult:
    """
    Provides the complete set of project requirements and conventions.

    This resource aggregates foundational rules, guidelines, and
    expected practices that should be followed throughout the project,
    helping the AI understand the project scope and design conventions.
    """
    content = get_config().load_requirements()
    return ResourceResult(contents=[ResourceContent(content=content, mime_type="text/markdown")])
