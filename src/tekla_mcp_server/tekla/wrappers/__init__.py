"""
Tekla wrapper classes.
"""

from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import (
    BoundingBox,
    TeklaModelObject,
    TeklaPart,
    TeklaAssembly,
    TeklaBeam,
    TeklaContourPlate,
    wrap_model_object,
    wrap_model_objects,
)
from tekla_mcp_server.tekla.wrappers.drawing import TeklaDrawing, wrap_drawings
from tekla_mcp_server.tekla.wrappers.drawing_handler import TeklaDrawingHandler
from tekla_mcp_server.tekla.wrappers.view import TeklaDrawingView

__all__ = [
    "TeklaModel",
    "TeklaModelObject",
    "TeklaPart",
    "TeklaAssembly",
    "wrap_model_object",
    "wrap_model_objects",
    "TeklaBeam",
    "TeklaContourPlate",
    "TeklaDrawing",
    "wrap_drawings",
    "BoundingBox",
    "TeklaDrawingView",
    "TeklaDrawingHandler",
]
