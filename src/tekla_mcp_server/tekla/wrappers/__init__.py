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
]
