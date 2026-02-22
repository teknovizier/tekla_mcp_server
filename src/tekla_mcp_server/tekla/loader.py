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
from Tekla.Structures import Identifier, TeklaStructuresDatabaseTypeEnum, PositionTypeEnum, DetailTypeEnum, AutoDirectionTypeEnum
from Tekla.Structures.Geometry3d import AABB, Point, Vector
from Tekla.Structures.Model import (
    Model,
    ModelObject,
    ModelObjectEnumerator,
    ModelObjectSelector,
    Assembly,
    BaseWeld,
    Beam,
    Boolean,
    BooleanPart,
    Part,
    Position,
    Reinforcement,
    Solid,
    TransformationPlane,
    ComponentInput,
    Component,
    Detail,
    Seam,
    Reinforcement,
    BaseRebarGroup,
    RebarMesh,
    RebarStrand,
    SingleRebar
)
from Tekla.Structures.Model.Operations import Operation
from Tekla.Structures.Model.UI import Color, GraphicsDrawer, ModelObjectSelector as ModelObjectSelectorUI, ViewHandler, ModelObjectVisualization, TemporaryTransparency
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
    "Part",
    "Position",
    "Reinforcement",
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
]
