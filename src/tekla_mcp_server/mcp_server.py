"""
MCP Server for Tekla

This server facilitates interaction with Tekla Structures, allowing users to
speed-up modeling processes.
"""

import json

from fastmcp import FastMCP
from fastmcp.resources import ResourceResult, ResourceContent
from fastmcp.server.transforms import ResourcesAsTools

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import get_base_components, get_macros, get_filters
from tekla_mcp_server.providers import (
    selection_provider,
    view_provider,
    properties_provider,
    operations_provider,
    components_provider,
)


mcp = FastMCP("Tekla MCP Server")


@mcp.resource("tekla://components")
def get_component_list() -> ResourceResult:
    """
    Returns mapping of Tekla component names to config keys.

    Use this to find the config key for a component, then call
    tekla://components/{component_key} to get the property schema.
    """
    data = {comp.get("tekla_name"): key for key, comp in get_base_components().items() if comp.get("tekla_name")}
    return ResourceResult(contents=[ResourceContent(content=json.dumps(data), mime_type="application/json")])


@mcp.resource("tekla://components/{component_key}")
def get_component_schema(component_key: str) -> ResourceResult:
    """
    Returns the custom_properties schema for a specific component.
    """
    component = get_base_components().get(component_key)
    if component:
        description = component.get("description", "")
        custom_props = component.get("custom_properties", {})
        schema = {"description": description, "custom_properties": custom_props}
        return ResourceResult(contents=[ResourceContent(content=json.dumps(schema), mime_type="application/json")])
    return ResourceResult(contents=[])


@mcp.resource("tekla://macros")
def get_macro_list() -> ResourceResult:
    """
    Returns a list of available Tekla macros from configured directories.
    """
    return ResourceResult(contents=[ResourceContent(content=json.dumps(get_macros()), mime_type="application/json")])


@mcp.resource("tekla://filters/selection")
def get_selection_filter_list() -> ResourceResult:
    """
    Returns a list of available Tekla selection filter names from .SObjGrp files.
    """
    return ResourceResult(contents=[ResourceContent(content=json.dumps(get_filters(".SObjGrp")), mime_type="application/json")])


@mcp.resource("tekla://filters/view")
def get_view_filter_list() -> ResourceResult:
    """
    Returns a list of available Tekla view filter names from .VObjGrp files.
    """
    return ResourceResult(contents=[ResourceContent(content=json.dumps(get_filters(".VObjGrp")), mime_type="application/json")])


@mcp.resource("tekla://phases")
def get_phase_list() -> ResourceResult:
    """
    Returns a list of all phases in the current Tekla model.
    """
    from tekla_mcp_server.tekla.model import TeklaModel

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
                content=json.dumps({"phases": phase_list, "current_phase": current_phase}),
                mime_type="application/json",
            )
        ]
    )


@mcp.resource("tekla://connection_status")
def get_connection_status() -> ResourceResult:
    """
    Returns the current Tekla connection status.
    """
    from tekla_mcp_server.tekla.model import TeklaModel

    try:
        model = TeklaModel()
        return ResourceResult(
            contents=[
                ResourceContent(
                    content=json.dumps(
                        {
                            "connected": True,
                            "model_path": model.model.GetInfo().ModelPath,
                            "message": "Connected to Tekla model",
                        }
                    ),
                    mime_type="application/json",
                )
            ]
        )
    except ConnectionError as e:
        return ResourceResult(
            contents=[
                ResourceContent(
                    content=json.dumps({"connected": False, "model_path": None, "message": str(e)}),
                    mime_type="application/json",
                )
            ]
        )


@mcp.resource("project://requirements")
def get_project_requirements() -> ResourceResult:
    """
    Provides the complete set of project requirements and conventions.

    This resource aggregates foundational rules, guidelines, and
    expected practices that should be followed throughout the project,
    helping the AI understand the project scope and design conventions.
    """
    content = get_config()._load_requirements()
    return ResourceResult(contents=[ResourceContent(content=content, mime_type="text/markdown")])


# Add all providers to the MCP server
mcp.add_provider(selection_provider)
mcp.add_provider(view_provider)
mcp.add_provider(properties_provider)
mcp.add_provider(operations_provider)
mcp.add_provider(components_provider)


# Run the MCP server locally
if __name__ == "__main__":
    from tekla_mcp_server.embeddings import is_embeddings_enabled

    if is_embeddings_enabled():
        from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser

        logger.info("Pre-loading embeddings at startup...")
        TemplateAttributeParser.preload()
        logger.info("Embeddings ready")

    mcp.add_transform(ResourcesAsTools(mcp))

    mcp.run()
