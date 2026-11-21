"""
Catalog of the Tekla filter fields that filter trees can use.

Pure data with no Tekla import, so the catalog and the tree validation run in CI.
Expression classes and enum members are named as strings and resolved to .NET
objects by `tekla/filter_builder.py`.
"""

from dataclasses import dataclass, field
from typing import Literal

FieldKind = Literal["string", "numeric", "boolean", "date"]

STRING_OPS = ("Is Equal", "Is Not Equal", "Contains", "Not Contains", "Starts With", "Not Starts With", "Ends With", "Not Ends With")
NUMERIC_OPS = ("Is Equal", "Is Not Equal", "Smaller Than", "Smaller Or Equal", "Greater Than", "Greater Or Equal")
BOOLEAN_OPS = ("Is Equal", "Is Not Equal")
DATE_OPS = ("Is Equal", "Is Not Equal", "Earlier Than", "Earlier Or Equal", "Later Than", "Later Or Equal")
# Fields with readable values accept only equality, because the words have no order
VALUE_OPS = ("Is Equal", "Is Not Equal")

OPS_BY_KIND: dict[str, tuple[str, ...]] = {"string": STRING_OPS, "numeric": NUMERIC_OPS, "boolean": BOOLEAN_OPS, "date": DATE_OPS}


@dataclass(frozen=True)
class FieldSpec:
    """One filterable field: the Tekla expression behind it, its value kind and readable values."""

    expression_class: str
    member: str
    kind: FieldKind
    description: str
    values: dict[str, str | int] = field(default_factory=dict)
    argument: str | None = None
    expanded: bool = False

    @property
    def ops(self) -> tuple[str, ...]:
        """Return the operators the field accepts."""
        return VALUE_OPS if self.values or self.expanded else OPS_BY_KIND[self.kind]


# Category key -> expression class, used for custom attribute (UDA and report property) conditions
CATEGORIES: dict[str, str] = {
    "part": "PartFilterExpressions",
    "assembly": "AssemblyFilterExpressions",
    "rebar": "ReinforcingBarFilterExpressions",
    "bolt": "BoltFilterExpressions",
    "weld": "WeldFilterExpressions",
    "component": "ComponentFilterExpressions",
    "reference_object": "ReferenceObjectFilterExpressions",
    "pour_object": "PourObjectFilterExpressions",
    "pour_break": "PourBreakFilterExpressions",
    "pour_unit": "PourUnitFilterExpressions",
    "surface": "SurfaceFilterExpressions",
    "object": "ObjectFilterExpressions",
    "logical_area": "LogicalAreaFilterExpressions",
    # Report properties such as 'MAINPART.CLASS_ATTR' or 'ASSEMBLY.USERDEFINED.x', for any object
    "template": "TemplateFilterExpressions",
}

# Custom attribute expression member per value kind
CUSTOM_MEMBERS: dict[str, str] = {"string": "CustomString", "numeric": "CustomNumber", "boolean": "CustomBoolean", "date": "CustomDateTime"}

# Readable object type -> `TeklaStructuresDatabaseTypeEnum` value compared by `ObjectFilterExpressions.Type`
# (PART, ASSEMBLY, REBAR, BOLT, WELDING, COMPONENT, FOREIGN_OBJECT, DB_POUR_OBJECT, DB_POUR_BREAK, DB_POUR_UNIT, SURFACE_OBJECT)
OBJECT_TYPES: dict[str, int] = {
    "part": 2,
    "assembly": 15,
    "rebar": 47,
    "bolt": 10,
    "weld": 13,
    "component": 4,
    "reference_object": 48,
    "pour_object": 90,
    "pour_break": 89,
    "pour_unit": 101,
    "surface": 97,
}

# Categories whose conditions apply to one object type only. For any other object type such a
# condition is ignored: it drops out of an 'all' group and out of an 'any' group. Assembly,
# object and report property conditions apply across types
CATEGORY_OBJECT_TYPES: dict[str, str] = {
    "part": "part",
    "rebar": "rebar",
    "bolt": "bolt",
    "weld": "weld",
    "component": "component",
    "reference_object": "reference_object",
    "pour_object": "pour_object",
    "pour_break": "pour_break",
    "pour_unit": "pour_unit",
    "surface": "surface",
}

# `BaseWeld.WeldTypeEnum` values, named like `get_elements_properties` reports them
WELD_TYPES: dict[str, str | int] = {
    "none": 0,
    "edge_flange": 1,
    "square_groove_square_butt": 2,
    "bevel_groove_single_v_butt": 3,
    "bevel_groove_single_bevel_butt": 4,
    "single_v_butt_with_broad_root_face": 5,
    "single_bevel_butt_with_broad_root_face": 6,
    "u_groove_single_u_butt": 7,
    "j_groove_j_butt": 8,
    "bevel_backing": 9,
    "fillet": 10,
    "plug": 11,
    "spot": 12,
    "seam": 13,
    "slot": 14,
    "flare_bevel_groove": 15,
    "flare_v_groove": 16,
    "corner_flange": 17,
    "partial_penetration_single_bevel_butt_plus_fillet": 18,
    "partial_penetration_square_groove_plus_fillet": 19,
    "melt_through": 20,
    "steep_flanked_bevel_groove_single_v_butt": 21,
    "steep_flanked_bevel_groove_single_bevel_butt": 22,
    "edge": 23,
    "iso_surfacing": 24,
    "fold": 25,
    "inclined": 26,
}

_PART = "PartFilterExpressions"
_ASSEMBLY = "AssemblyFilterExpressions"
_REBAR = "ReinforcingBarFilterExpressions"
_BOLT = "BoltFilterExpressions"
_WELD = "WeldFilterExpressions"
_COMPONENT = "ComponentFilterExpressions"
_POUR_OBJECT = "PourObjectFilterExpressions"
_POUR_UNIT = "PourUnitFilterExpressions"
_SURFACE = "SurfaceFilterExpressions"
_OBJECT = "ObjectFilterExpressions"
_LOGICAL_AREA = "LogicalAreaFilterExpressions"

FIELDS: dict[str, FieldSpec] = {
    # Part
    "part.name": FieldSpec(_PART, "Name", "string", "Part name"),
    "part.profile": FieldSpec(_PART, "Profile", "string", "Profile, e.g. 'HEA300' or '200*600'"),
    "part.material": FieldSpec(_PART, "Material", "string", "Material grade"),
    "part.finish": FieldSpec(_PART, "Finish", "string", "Finish"),
    "part.class": FieldSpec(_PART, "Class", "numeric", "Tekla class number"),
    "part.element_type": FieldSpec(_PART, "Class", "string", "Named element type from `tekla://element_types`, matched through its class numbers", expanded=True),
    "part.prefix": FieldSpec(_PART, "Prefix", "string", "Part position prefix"),
    "part.start_number": FieldSpec(_PART, "StartNumber", "numeric", "Part position start number"),
    "part.position_number": FieldSpec(_PART, "PositionNumber", "string", "Part position number"),
    "part.numbering_series": FieldSpec(_PART, "NumberingSeries", "string", "Part numbering series"),
    "part.phase": FieldSpec(_PART, "Phase", "numeric", "Phase number of the part"),
    "part.lot": FieldSpec(_PART, "Lot", "numeric", "Lot number"),
    "part.pour_phase": FieldSpec(_PART, "PourPhase", "numeric", "Pour phase"),
    "part.primary_part": FieldSpec(_PART, "PrimaryPart", "string", "Whether the part is the main part of its assembly", values={"yes": "1", "no": "0"}),
    # Assembly. Tekla's native start number and phase are text, so the numeric report properties are used
    "assembly.name": FieldSpec(_ASSEMBLY, "Name", "string", "Assembly name"),
    "assembly.prefix": FieldSpec(_ASSEMBLY, "Prefix", "string", "Assembly position prefix"),
    "assembly.start_number": FieldSpec("TemplateFilterExpressions", "CustomNumber", "numeric", "Assembly position start number", argument="ASSEMBLY_START_NUMBER"),
    "assembly.phase": FieldSpec("TemplateFilterExpressions", "CustomNumber", "numeric", "Phase number of the assembly", argument="ASSEMBLY.PHASE"),
    "assembly.position_number": FieldSpec(_ASSEMBLY, "PositionNumber", "string", "Assembly position number"),
    "assembly.series": FieldSpec(_ASSEMBLY, "Series", "string", "Assembly numbering series"),
    "assembly.level": FieldSpec(_ASSEMBLY, "Level", "string", "Assembly level"),
    "assembly.type": FieldSpec(_ASSEMBLY, "Type", "string", "Assembly type code as Tekla stores it"),
    "assembly.guid": FieldSpec(_ASSEMBLY, "Guid", "string", "Assembly GUID"),
    # Reinforcing bar
    "rebar.name": FieldSpec(_REBAR, "Name", "string", "Rebar name"),
    "rebar.material": FieldSpec(_REBAR, "Material", "string", "Rebar grade"),
    "rebar.size": FieldSpec(_REBAR, "Size", "string", "Bar size as in the rebar catalog"),
    "rebar.diameter": FieldSpec(_REBAR, "Diameter", "numeric", "Bar diameter (mm)"),
    "rebar.length": FieldSpec(_REBAR, "Length", "numeric", "Bar length (mm)"),
    "rebar.class": FieldSpec(_REBAR, "Class", "numeric", "Tekla class number"),
    "rebar.shape": FieldSpec(_REBAR, "Shape", "string", "Bending shape code"),
    "rebar.prefix": FieldSpec(_REBAR, "Prefix", "string", "Rebar position prefix"),
    "rebar.start_number": FieldSpec(_REBAR, "StartNumber", "numeric", "Rebar position start number"),
    "rebar.position_number": FieldSpec(_REBAR, "PositionNumber", "string", "Rebar position number"),
    "rebar.numbering_series": FieldSpec(_REBAR, "NumberingSeries", "string", "Rebar numbering series"),
    "rebar.position": FieldSpec(_REBAR, "Position", "string", "Rebar position"),
    "rebar.join_type": FieldSpec(_REBAR, "JoinType", "string", "Splice join type code as Tekla stores it"),
    "rebar.phase": FieldSpec(_REBAR, "Phase", "numeric", "Phase number"),
    # Bolt
    "bolt.standard": FieldSpec(_BOLT, "Standard", "string", "Bolt standard, e.g. '7990'"),
    "bolt.size": FieldSpec(_BOLT, "Size", "numeric", "Bolt diameter (mm)"),
    "bolt.length": FieldSpec(_BOLT, "Length", "numeric", "Bolt length (mm)"),
    "bolt.site_workshop": FieldSpec(_BOLT, "SiteWorkshop", "string", "Where the bolt is installed", values={"site": "0", "workshop": "1"}),
    "bolt.phase": FieldSpec(_BOLT, "Phase", "numeric", "Phase number"),
    # Weld
    "weld.type_above": FieldSpec(_WELD, "TypeAboveLine", "numeric", "Weld type above the line", values=WELD_TYPES),
    "weld.type_below": FieldSpec(_WELD, "TypeBelowLine", "numeric", "Weld type below the line", values=WELD_TYPES),
    "weld.size_above": FieldSpec(_WELD, "SizeAboveLine", "numeric", "Weld size above the line (mm)"),
    "weld.size_below": FieldSpec(_WELD, "SizeBelowLine", "numeric", "Weld size below the line (mm)"),
    "weld.welding_site": FieldSpec(_WELD, "WeldingSite", "numeric", "Where the weld is made", values={"site": 0, "workshop": 1}),
    "weld.reference_text": FieldSpec(_WELD, "ReferenceText", "string", "Weld reference text"),
    "weld.position_number": FieldSpec(_WELD, "PositionNumber", "string", "Weld position number"),
    "weld.phase": FieldSpec(_WELD, "Phase", "numeric", "Phase number"),
    # Component
    "component.name": FieldSpec(_COMPONENT, "Name", "string", "Component name"),
    "component.connection_code": FieldSpec(_COMPONENT, "ConnectionCode", "string", "Connection code"),
    "component.running_number": FieldSpec(_COMPONENT, "RunningNumber", "string", "Component running number"),
    "component.phase": FieldSpec(_COMPONENT, "Phase", "numeric", "Phase number"),
    # Pour object and pour unit
    "pour_object.concrete_mixture": FieldSpec(_POUR_OBJECT, "ConcreteMixture", "string", "Concrete mixture"),
    "pour_object.material": FieldSpec(_POUR_OBJECT, "Material", "string", "Concrete material"),
    "pour_object.pour_number": FieldSpec(_POUR_OBJECT, "PourNumber", "string", "Pour number"),
    "pour_object.pour_phase": FieldSpec(_POUR_OBJECT, "PourPhase", "string", "Pour phase"),
    "pour_object.pour_type": FieldSpec(_POUR_OBJECT, "PourType", "string", "Pour type code as Tekla stores it"),
    "pour_unit.name": FieldSpec(_POUR_UNIT, "Name", "string", "Pour unit name"),
    "pour_unit.guid": FieldSpec(_POUR_UNIT, "Guid", "string", "Pour unit GUID"),
    # Surface
    "surface.name": FieldSpec(_SURFACE, "Name", "string", "Surface name"),
    "surface.class": FieldSpec(_SURFACE, "Class", "numeric", "Tekla class number"),
    "surface.type": FieldSpec(_SURFACE, "Type", "string", "Surface type code as Tekla stores it"),
    # Any object
    "object.guid": FieldSpec(_OBJECT, "Guid", "string", "Object GUID"),
    "object.id_number": FieldSpec(_OBJECT, "IdNumber", "numeric", "Object ID number"),
    "object.phase": FieldSpec(_OBJECT, "Phase", "numeric", "Phase number of any object"),
    "object.type": FieldSpec(_OBJECT, "Type", "numeric", "Object type, for type conditions inside groups", values=dict(OBJECT_TYPES)),
    # Logical building areas (site, building, section, storey) of any object
    "logical_area.site": FieldSpec(_LOGICAL_AREA, "Site", "string", "Building site name"),
    "logical_area.building": FieldSpec(_LOGICAL_AREA, "Building", "string", "Building name"),
    "logical_area.section": FieldSpec(_LOGICAL_AREA, "Section", "string", "Section name"),
    "logical_area.story": FieldSpec(_LOGICAL_AREA, "Story", "string", "Storey name"),
}
