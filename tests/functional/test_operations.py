"""
Functional tests for operations_provider.

Tests operations like boolean cuts, cut part conversion, and macro execution.
"""

from tekla_mcp_server.providers.operations_provider import (
    cut_elements_with_zero_class_parts,
    convert_cut_parts_to_real_parts,
    run_macro,
)
from tekla_mcp_server.tekla.wrappers.model import TeklaModel


def test_cut_elements_with_zero_class_parts(model_objects):
    """Tests cut_elements_with_zero_class_parts tool."""
    TeklaModel.select_objects([model_objects["test_wall3"], model_objects["test_wall4"]])
    result = cut_elements_with_zero_class_parts(delete_cutting_parts=False)
    assert result.structured_content["status"] == "success"
    assert result.structured_content["selected_elements"] == 2


def test_convert_cut_parts_to_real_parts_without_cuts(model_objects):
    """Tests convert_cut_parts_to_real_parts when no cuts are present."""
    TeklaModel.select_objects([model_objects["test_wall1"], model_objects["test_wall2"]])
    result = convert_cut_parts_to_real_parts()
    assert result.structured_content["status"] == "error"


def test_convert_cut_parts_to_real_parts_with_cut(model_objects):
    """Tests convert_cut_parts_to_real_parts when a valid cut part exists."""
    TeklaModel.select_objects([model_objects["test_wall3"]])
    result = convert_cut_parts_to_real_parts()
    assert result.structured_content["status"] == "success"


def test_run_macro_nonexistent():
    """Tests that run_macro returns an error for non-existent macro."""
    result = run_macro(macro_name="NonExistentMacro.cs")
    assert result.structured_content["status"] == "error"
