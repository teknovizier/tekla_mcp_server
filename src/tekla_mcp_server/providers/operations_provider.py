"""
Operations tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any, Annotated
from pydantic import Field

from fastmcp.server.providers import LocalProvider

from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import log_mcp_tool_call
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects
from tekla_mcp_server.tekla.loader import Operation
from tekla_mcp_server.tekla.utils import iterate_boolean_parts


operations_provider = LocalProvider()


@operations_provider.tool()
@log_mcp_tool_call
def cut_elements_with_zero_class_parts(delete_cutting_parts: Annotated[bool, Field(description="Remove cutting parts after cuts are applied")] = False) -> dict[str, Any]:
    """
    Performs boolean cuts on selected model objects using parts in class 0.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    processed_elements = 0
    performed_cuts = 0
    objects_to_select = model.get_objects_by_class(0)
    cutters = list(wrap_model_objects(objects_to_select))
    if cutters:
        for selected_object in wrap_model_objects(selected_objects):
            element_had_cut = False
            for cutter in cutters:
                if selected_object.add_cut(cutter, delete_cutting_parts):
                    performed_cuts += 1
                    element_had_cut = True
            if element_had_cut:
                processed_elements += 1
        if performed_cuts:
            model.commit_changes()
    logger.info("Performed %s cuts on %s elements", performed_cuts, processed_elements)
    return {
        "status": "success" if performed_cuts else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "performed_cuts": performed_cuts,
    }


@operations_provider.tool()
@log_mcp_tool_call
def convert_cut_parts_to_real_parts() -> dict[str, Any]:
    """
    Finds boolean parts and inserts them as real model objects.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    processed_elements = 0
    inserted_booleans = 0
    for selected_object in selected_objects:
        for boolean_part in iterate_boolean_parts(selected_object):
            if boolean_part.OperativePart.Insert():
                inserted_booleans += 1
        processed_elements += 1
    if inserted_booleans > 0:
        model.commit_changes()
    logger.info("Inserted %s boolean parts as real parts", inserted_booleans)
    return {
        "status": "success" if inserted_booleans else "error",
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "converted_booleans": inserted_booleans,
    }


@operations_provider.tool()
@log_mcp_tool_call
def run_macro(macro_name: Annotated[str, Field(description="Name of the macro file to run (e.g., 'MyMacro.cs'")]) -> dict[str, Any]:
    """
    Runs a Tekla macro with the specified name.

    ## AVAILABLE MACROS
    Use the `macro://list` resource to get a list of available macros.
    """
    if Operation.IsMacroRunning():
        logger.warning("Cannot run macro '%s': Tekla is busy running another macro", macro_name)
        return {
            "status": "error",
            "message": "Tekla is busy running another macro",
        }

    result = Operation.RunMacro(macro_name)

    logger.info("Ran macro '%s'", macro_name)
    return {
        "status": "success" if result else "error",
        "macro_name": macro_name,
    }
