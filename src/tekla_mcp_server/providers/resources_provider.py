"""
Resources provider for Tekla MCP server.

Provides read-only data resources for discovery and metadata.
"""

from fastmcp.resources import ResourceContent, ResourceResult
from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.tekla.loader import Grid
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.utils import get_all_materials, get_all_rebar_items, get_macros, get_filters
from tekla_mcp_server.utils import json_resource, mcp_handler, parse_coordinate_string, parse_label_string


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
    logger.debug("Retrieved %d components", len(data))
    return json_resource(data)


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
        logger.debug("Retrieved schema for component '%s'", component_key)
        return json_resource(schema)
    logger.warning("Component schema not found for key '%s'", component_key)
    return ResourceResult(contents=[])


@resources_provider.resource("tekla://catalog/materials")
@mcp_handler(scope="resource")
def get_materials_resource() -> ResourceResult:
    """
    Returns all available materials from Tekla catalog.
    """
    materials = get_all_materials()
    logger.debug("Retrieved %d materials", len(materials))
    return json_resource(materials)


@resources_provider.resource("tekla://catalog/rebars")
@mcp_handler(scope="resource")
def get_rebars_resource() -> ResourceResult:
    """
    Returns all available rebar grades and sizes from Tekla catalog.
    """
    rebars = get_all_rebar_items()
    logger.debug("Retrieved %d rebars", len(rebars))
    return json_resource(rebars)


@resources_provider.resource("tekla://macros")
@mcp_handler(scope="resource")
def get_macro_list() -> ResourceResult:
    """
    Returns a list of available Tekla macros from configured directories.
    """
    macros = get_macros()
    logger.debug("Retrieved %d macros", len(macros))
    return json_resource(macros)


@resources_provider.resource("tekla://element_types")
@mcp_handler(scope="resource")
def get_element_types() -> ResourceResult:
    """
    Returns a list of available Tekla element types and their corresponding class numbers.
    """
    element_types = get_config().get_element_types_list()
    logger.debug("Retrieved %d element types", len(element_types))
    return json_resource(element_types)


@resources_provider.resource("tekla://filters/selection")
@mcp_handler(scope="resource")
def get_selection_filter_list() -> ResourceResult:
    """
    Returns a list of available Tekla selection filter names from .SObjGrp files.
    """
    filters = get_filters(".SObjGrp")
    logger.debug("Retrieved %d selection filters", len(filters))
    return json_resource(filters)


@resources_provider.resource("tekla://filters/view")
@mcp_handler(scope="resource")
def get_view_filter_list() -> ResourceResult:
    """
    Returns a list of available Tekla view filter names from .VObjGrp files.
    """
    filters = get_filters(".VObjGrp")
    logger.debug("Retrieved %d view filters", len(filters))
    return json_resource(filters)


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

    logger.debug("Retrieved %d phases, current: %s", len(phase_list), current_phase)
    return json_resource({"phases": phase_list, "current_phase": current_phase})


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

        # Coordinates and labels are trimmed to the same length (min of the two).
        # If Tekla has more labels than coordinates, the extra labels are dropped.
        # If there are more coordinates than labels, the unlabeled axis lines are
        # also dropped from the response.
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
    logger.debug("Retrieved %d grids", len(grid_data))
    return json_resource({"grids": grid_data})


@resources_provider.resource("tekla://connection_status")
@mcp_handler(scope="resource")
def check_connection_status() -> ResourceResult:
    """
    Returns the current Tekla connection status.
    """
    model = TeklaModel()
    model_path = model.model.GetInfo().ModelPath
    logger.debug("Connection status check: %s", model_path)
    return json_resource({"connected": True, "model_path": model_path, "message": "Connected to Tekla model"})


def _parse_context_meta(path) -> dict:
    """Extract name (# H1) and description (## H2) from a context file."""
    name = path.stem
    description = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and name == path.stem:
            name = line[2:].strip()
        elif line.startswith("## "):
            description = line[3:].strip()
            break
    return {"name": name, "description": description, "file": path.stem}


@resources_provider.resource("project://context")
@mcp_handler(scope="resource")
def get_context_index() -> ResourceResult:
    """
    Returns an index of available project context files.

    Each entry contains the context name, a short description,
    and the file key to use with `project://context/{file}`.
    """
    folder = get_config().context_folder
    index = [_parse_context_meta(f) for f in sorted(folder.glob("*.md"))] if folder.exists() else []
    logger.debug("Retrieved context index: %d files", len(index))
    return json_resource(index)


@resources_provider.resource("project://context/{file}")
@mcp_handler(scope="resource")
def get_context(file: str) -> ResourceResult:
    """
    Returns the full content of a specific project context file.

    Use `project://context` first to discover available file keys.
    """
    folder = get_config().context_folder.resolve()
    path = (folder / f"{file}.md").resolve()
    if not path.exists() or not path.is_relative_to(folder):
        logger.warning("Context file not found: %s", file)
        return ResourceResult(contents=[])
    content = path.read_text(encoding="utf-8")
    logger.debug("Retrieved context file '%s', %d chars", file, len(content))
    return ResourceResult(contents=[ResourceContent(content=content, mime_type="text/markdown")])
