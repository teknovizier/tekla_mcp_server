"""
Module for initializing and exposing Tekla Structures OpenAPI namespaces.

This module ensures that Tekla's .NET assemblies are properly loaded before any
Tekla-related imports are accessed. It provides a centralized entry point for
DLL loading and exposes commonly used classes for use throughout the application.
"""

from tekla_mcp_server.init import load_dlls

load_dlls()
from System.Collections import ArrayList, Hashtable
from System.Collections.Generic import List
from Tekla.Structures import Identifier, TeklaStructuresDatabaseTypeEnum, PositionTypeEnum, DetailTypeEnum, AutoDirectionTypeEnum, TeklaStructuresInfo, TeklaStructuresSettings
from Tekla.Structures.Geometry3d import AABB, Point, Vector
from Tekla.Structures.Model import (
    Model,
    ModelObject,
    ModelObjectEnumerator,
    ModelObjectSelector,
    Phase,
    PhaseCollection,
    Assembly,
    BaseWeld,
    Beam,
    Boolean,
    BooleanPart,
    ContourPlate,
    ContourPoint,
    Offset,
    Part,
    Position,
    Reinforcement,
    Solid,
    TransformationPlane,
    ComponentInput,
    Component,
    Detail,
    Seam,
    BaseRebarGroup,
    RebarMesh,
    RebarStrand,
    SingleRebar,
    Grid,
    ReferenceModelObject,
)
from Tekla.Structures.Model.Operations import Operation
from Tekla.Structures.Model.UI import Color, GraphicsDrawer, ModelObjectSelector as ModelObjectSelectorUI, ViewHandler, ModelObjectVisualization, TemporaryTransparency, View
try:
    from Tekla.Structures.Filtering import (
        BinaryFilterOperatorType,
        BinaryFilterExpressionCollection,
        BinaryFilterExpressionItem,
        NumericOperatorType,
        NumericConstantFilterExpression,
        StringConstantFilterExpression,
        BinaryFilterExpression,
        StringOperatorType,
        FilterExpression,
    )
    from Tekla.Structures.Filtering.Categories import PartFilterExpressions, ObjectFilterExpressions, TemplateFilterExpressions
except ModuleNotFoundError:
    BinaryFilterOperatorType = None
    BinaryFilterExpressionCollection = None
    BinaryFilterExpressionItem = None
    NumericOperatorType = None
    NumericConstantFilterExpression = None
    StringConstantFilterExpression = None
    BinaryFilterExpression = None
    StringOperatorType = None
    FilterExpression = None
    PartFilterExpressions = None
    ObjectFilterExpressions = None
    TemplateFilterExpressions = None
from Tekla.Structures.Catalogs import CatalogHandler, MaterialItem, MaterialItemEnumerator, ProfileItem, ProfileItemEnumerator
from Tekla.Structures.Drawing import (
    Drawing,
    DrawingEnumerator,
    Mark,
    DrawingObject,
    DrawingObjectEnumerator,
    Frame,
    FrameTypes,
    DrawingColors,
    Polyline,
    PointList,
    DrawingHandler,
    LeaderLinePlacing,
    LeaderLine,
    DPMPrinterAttributes,
    DotPrintColor,
    DotPrintOrientationType,
    DotPrintOutputType,
    DotPrintPaperSize,
    DotPrintToMultipleSheet,
    DotPrintScalingType,
)


# Export everything
__all__ = [
    "ArrayList",
    "Hashtable",
    "List",
    "Identifier",
    "TeklaStructuresDatabaseTypeEnum",
    "PositionTypeEnum",
    "DetailTypeEnum",
    "AutoDirectionTypeEnum",
    "TeklaStructuresInfo",
    "TeklaStructuresSettings",
    "AABB",
    "Point",
    "Vector",
    "Model",
    "ModelObject",
    "ModelObjectEnumerator",
    "ModelObjectSelector",
    "Assembly",
    "BaseWeld",
    "Beam",
    "Boolean",
    "BooleanPart",
    "ContourPoint",
    "ContourPlate",
    "Part",
    "Phase",
    "PhaseCollection",
    "Position",
    "Solid",
    "TransformationPlane",
    "ComponentInput",
    "Component",
    "Detail",
    "Seam",
    "Reinforcement",
    "BaseRebarGroup",
    "RebarMesh",
    "RebarStrand",
    "SingleRebar",
    "Operation",
    "Color",
    "GraphicsDrawer",
    "ModelObjectSelectorUI",
    "ViewHandler",
    "ModelObjectVisualization",
    "TemporaryTransparency",
    "View",
    "BinaryFilterOperatorType",
    "BinaryFilterExpressionCollection",
    "BinaryFilterExpressionItem",
    "NumericOperatorType",
    "NumericConstantFilterExpression",
    "StringConstantFilterExpression",
    "BinaryFilterExpression",
    "StringOperatorType",
    "FilterExpression",
    "PartFilterExpressions",
    "ObjectFilterExpressions",
    "TemplateFilterExpressions",
    "CatalogHandler",
    "MaterialItem",
    "MaterialItemEnumerator",
    "ProfileItem",
    "ProfileItemEnumerator",
    "DrawingHandler",
    "Drawing",
    "DrawingEnumerator",
    "Mark",
    "DrawingObject",
    "DrawingObjectEnumerator",
    "Frame",
    "FrameTypes",
    "DrawingColors",
    "Polyline",
    "PointList",
    "LeaderLine",
    "LeaderLinePlacing",
    "Grid",
    "Offset",
    "ReferenceModelObject",
    "DPMPrinterAttributes",
    "DotPrintColor",
    "DotPrintOrientationType",
    "DotPrintOutputType",
    "DotPrintPaperSize",
    "DotPrintToMultipleSheet",
    "DotPrintScalingType",
]
