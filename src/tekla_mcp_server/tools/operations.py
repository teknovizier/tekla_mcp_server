"""
Operations tools for Tekla model operations.
"""

from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.tekla.loader import Operation
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tekla.model_object import wrap_model_objects
from tekla_mcp_server.tekla.utils import iterate_boolean_parts
from tekla_mcp_server.utils import log_function_call


@log_function_call
def tool_cut_elements_with_zero_class_parts(model: TeklaModel, selected_objects: Any, delete_cutting_parts: bool = False, tekla_class: int = 0) -> dict[str, Any]:
    """
    Applies boolean cuts to selected elements in the Tekla model using parts of a specified class as cutting objects.

    Args:
        model: Tekla model instance
        selected_objects: Enumerator of objects to cut
        delete_cutting_parts: Whether to delete cutting parts after operation (default False)
        tekla_class: Tekla class number for cutting parts (default 0)
    """
    processed_elements = 0
    performed_cuts = 0
    objects_to_select = model.get_objects_by_class(tekla_class)
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


@log_function_call
def tool_convert_cut_parts_to_real_parts(model: TeklaModel, selected_objects: Any) -> dict[str, Any]:
    """
    Inserts operative parts from boolean parts as real model objects.

    Args:
        model: Tekla model instance
        selected_objects: Enumerator of selected objects
    """
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


@log_function_call
def tool_run_macro(macro_name: str) -> dict[str, Any]:
    """
    Runs a Tekla macro with the specified name.

    Args:
        macro_name: Name of the macro to run (e.g., "MyMacro.cs")
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
