"""
Selection tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Annotated

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field, TypeAdapter

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import ElementType, FilterCondition, FilterGroup, FilterNode, SelectionMode
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects
from tekla_mcp_server.tekla.filter_builder import build_filter_expression
from tekla_mcp_server.tekla.loader import ArrayList


selection_provider = LocalProvider()

_FILTER_ADAPTER: TypeAdapter[FilterNode] = TypeAdapter(FilterNode)


def _resolve_element_type_classes(element_type: str) -> list[int]:
    """
    Resolve a named element type to its Tekla class numbers from the config.

    Args:
        element_type: Named element type (e.g. 'Wall', 'Steel Beam')

    Returns:
        Tekla class numbers of the element type, empty when none is configured

    Raises:
        ValueError: If `element_type` is not a known element type
    """
    try:
        element_type_enum = ElementType(element_type.strip())
    except Exception as e:
        raise ValueError(f"Invalid element_type: {e}") from e

    element_type_classes: list[int] = []
    for material_types in get_config().element_types.values():
        for type_name, config in material_types.items():
            logger.debug("Checking element type '%s' against '%s', classes=%s", element_type_enum.name, type_name, config.get("tekla_classes", []))
            if element_type_enum.name.replace(" ", "_").upper() in type_name.upper() or type_name.upper() in element_type_enum.name.upper():
                element_type_classes.extend(config.get("tekla_classes", []))
    return element_type_classes


def _expand_element_type(condition: FilterCondition) -> FilterCondition:
    """
    Replace a `part.element_type` condition with one condition on its class numbers.

    Args:
        condition: Condition on 'part.element_type' with 'Is Equal' or 'Is Not Equal', one type or a list

    Returns:
        'part.class' condition with the same operator and the classes of all the types as a list

    Raises:
        ValueError: If an element type is unknown or has no configured classes
    """
    classes: list[str | int | float] = []
    for element_type in condition.values:
        type_classes = _resolve_element_type_classes(str(element_type))
        if not type_classes:
            raise ValueError(f"Element type '{element_type}' has no Tekla classes configured.")
        classes.extend(type_classes)
    return FilterCondition(field="part.class", op=condition.op, value=list(dict.fromkeys(classes)))


def _prepare_tree(node: FilterNode) -> FilterNode:
    """
    Expand element type conditions in a tree.

    Args:
        node: Validated filter group or condition

    Returns:
        A new tree ready for `build_filter_expression`
    """
    if isinstance(node, FilterGroup):
        items = [_prepare_tree(item) for item in node.items]
        return FilterGroup(any=items) if node.is_any else FilterGroup(all=items)
    if node.field == "part.element_type":
        return _expand_element_type(node)
    return node


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_filter(
    filter: Annotated[
        FilterGroup | FilterCondition,
        Field(description="Filter tree: a group with 'all' or 'any' (groups nest), or a single condition. Fields and object types are listed in `tekla://filters/fields`"),
    ],
    object_types: Annotated[list[str], Field(description="Object types to select, e.g. ['part'] or ['part', 'bolt']")] = ["part"],
) -> ToolResult:
    """
    Selects model objects matching a filter tree.

    A condition uses either `field` (e.g. 'part.profile', 'assembly.prefix', 'bolt.size') or `attribute` (a UDA
    of `category`, or a report property such as 'MAINPART.CLASS_ATTR' with category 'template'). A list value
    matches any of its values, or none of them for a negative operator. A condition on a category tied to one
    object type, such as 'part' or 'bolt', is ignored for the other object types: 'all' groups skip it and
    'any' groups do not match through it. So with several `object_types`, a type without conditions of its
    own is selected whole. 'object.type' conditions make groups depend on the type. Assembly conditions
    also apply to the parts of the assembly. 'part.element_type' takes element type names such as 'Wall'
    and matches their Tekla classes. Fields with readable values (e.g. 'bolt.site_workshop': 'site' or
    'workshop') accept only 'Is Equal' and 'Is Not Equal'. Text values may use Tekla wildcards '*' and '?'. Numeric fields take numbers only, so use a list or a range instead of a wildcard.
    Attribute names are used exactly as given and are case-sensitive, so read them first, e.g. with
    `get_elements_properties`. Tekla allows at most 3 levels of brackets, so prefer list values over
    'any' groups of single values.

    ### EXAMPLES
    # Walls with a profile starting with '200'
    {"filter": {"all": [
        {"field": "part.element_type", "op": "Is Equal", "value": "Wall"},
        {"field": "part.profile", "op": "Starts With", "value": "200"}
    ]}}

    # Parts in phase 2 whose assembly prefix is 'SB' or whose HEIGHT report property is over 2000
    {"filter": {"all": [
        {"field": "part.phase", "op": "Is Equal", "value": 2},
        {"any": [
            {"field": "assembly.prefix", "op": "Is Equal", "value": "SB"},
            {"attribute": "HEIGHT", "category": "template", "op": "Greater Than", "value": 2000}
        ]}
    ]}}

    # Assemblies whose main part class is 18, 23 or 31 (report property)
    {"object_types": ["assembly"], "filter":
        {"attribute": "MAINPART.CLASS_ATTR", "category": "template", "op": "Is Equal", "value": [18, 23, 31]}}

    # Site bolts of diameter 16
    {"object_types": ["bolt"], "filter": {"all": [
        {"field": "bolt.site_workshop", "op": "Is Equal", "value": "site"},
        {"field": "bolt.size", "op": "Is Equal", "value": 16}
    ]}}
    """
    tree = _FILTER_ADAPTER.validate_python(filter)
    expression = build_filter_expression(_prepare_tree(tree), object_types)

    model = TeklaModel()
    objects_to_select = model.get_objects_by_filter(expression)
    TeklaModel.select_objects(objects_to_select)

    count = objects_to_select.GetSize()
    logger.info("Selected %s objects by filter", count)
    return ToolResult(
        structured_content={
            "status": "success" if count else "warning",
            "selected_count": count,
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_filter_name(
    filter_name: Annotated[str, Field(description="Name of the Tekla filter to apply")],
) -> ToolResult:
    """
    Selects elements applying an existing Tekla filter.

    Use the `tekla://filters/selection` resource to discover available filters.
    """
    model = TeklaModel()
    objects_to_select = model.get_objects_by_filter(filter_name)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by named filter", objects_to_select.GetSize())
    return ToolResult(
        structured_content={
            "status": "success" if objects_to_select.GetSize() else "warning",
            "selected_count": objects_to_select.GetSize(),
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_guid(
    guids: Annotated[list[str], Field(description="List of GUIDs to select (e.g. from `get_elements_properties`)", min_length=1)],
) -> ToolResult:
    """
    Selects elements by their GUID.

    GUIDs not in the model are reported in `missing_guids`. If none is found, the selection is
    cleared so a later tool cannot act on a stale selection.
    """
    model = TeklaModel()
    objects_to_select, selected_guids, missing_guids = model.resolve_guids(guids)

    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by GUID (missing: %s)", len(selected_guids), missing_guids)
    if not selected_guids:
        raise ValueError(f"None of the GUIDs were found in the model: {missing_guids}")

    return ToolResult(
        structured_content={
            "status": "partial" if missing_guids else "success",
            "selected_count": len(selected_guids),
            "selected_guids": selected_guids,
            "missing_guids": missing_guids,
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_related_elements(
    mode: Annotated[SelectionMode, Field(description="Selection mode: 'Assembly', 'Main Part' or 'Parts'")],
    include_embeds: Annotated[bool, Field(description="Only for 'Parts' mode: also select embedded details inside the assembly")] = False,
) -> ToolResult:
    """
    Selects the top-level assemblies, their main parts or all their parts for the selected elements.

    'Parts' selects every part of the top-level assembly, including parts in subassemblies, without reinforcement.
    Embedded details are left out unless `include_embeds` is set. For example, selecting one layer or the
    assembly of a sandwich wall selects its inner layer, insulation and outer layer.
    """
    selected_objects = TeklaModel().get_selected_objects()

    processed_count = 0
    selected_object_types = {"Assembly": "selected_assemblies", "Main Part": "selected_main_parts", "Parts": "selected_parts"}[mode]

    filtered_parts = ArrayList()
    seen_part_guids: set[str] = set()
    for selected_object in wrap_model_objects(selected_objects):
        try:
            assembly = selected_object.get_top_level_assembly()
        except TypeError:
            logger.error("Failed to get top level assembly for the element %s", selected_object.guid)
            continue
        if assembly is None:
            logger.debug("No top-level assembly for %s, skipping", selected_object.guid)
            continue
        if mode == "Assembly":
            filtered_parts.Add(assembly.model_object)
        elif mode == "Main Part":
            try:
                filtered_parts.Add(assembly.main_part.model_object)
            except ValueError:
                logger.warning("Assembly %s has no main part, skipping", assembly.guid)
                continue
        elif mode == "Parts":
            # Several selected elements can share one assembly, so add each part once
            for part in assembly.get_all_parts(include_embeds):
                if part.guid not in seen_part_guids:
                    seen_part_guids.add(part.guid)
                    filtered_parts.Add(part.model_object)
        processed_count += 1

    TeklaModel.select_objects(filtered_parts)
    logger.info("Selected %s elements as '%s'", filtered_parts.Count, mode)
    return ToolResult(
        structured_content={
            "status": "success" if filtered_parts.Count else "warning",
            "selected_count": selected_objects.GetSize(),
            "processed_count": processed_count,
            f"{selected_object_types}_count": filtered_parts.Count,
        }
    )
