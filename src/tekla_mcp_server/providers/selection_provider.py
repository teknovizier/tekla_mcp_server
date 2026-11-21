"""
Selection tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

import os
from pathlib import Path
from typing import Annotated, Literal

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field, TypeAdapter

from tekla_mcp_server.config import get_config
from tekla_mcp_server.filter_fields import FILTER_FILE_EXTENSIONS, normalize_filter_name
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import FilterCondition, FilterGroup, FilterNode, SelectionMode, element_type_name
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects
from tekla_mcp_server.tekla.filter_builder import build_filter_expression
from tekla_mcp_server.tekla.loader import ArrayList, Filter, FilterExpressionFileType
from tekla_mcp_server.tekla.utils import refresh_attribute_files


selection_provider = LocalProvider()

# Prefix of the file `create_filter` writes before moving it into place
TEMPORARY_FILTER_PREFIX = "~mcp_tmp_"

_FILTER_ADAPTER: TypeAdapter[FilterNode] = TypeAdapter(FilterNode)


def _resolve_element_type_classes(element_type: str) -> list[int]:
    """
    Resolve an element type to its Tekla class numbers from `element_types.json`.

    Args:
        element_type: Name or key from `tekla://element_types`, e.g. 'Wall' or 'CONCRETE_WALL', in any case

    Returns:
        Tekla class numbers of the element type, empty when none is configured

    Raises:
        ValueError: If `element_type` is not a configured element type
    """
    text = element_type.strip()
    wanted = text.upper().replace(" ", "_")
    for material_types in get_config().element_types.values():
        for type_key, config in material_types.items():
            if wanted in (type_key.upper(), element_type_name(type_key).upper().replace(" ", "_")):
                logger.debug("Element type '%s' is '%s' with classes %s", text, type_key, config.get("tekla_classes", []))
                return list(config.get("tekla_classes", []))
    names = [element_type_name(type_key) for material_types in get_config().element_types.values() for type_key in material_types]
    raise ValueError(f"Invalid element_type '{text}'. Must be one of: {names}")


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
    or their keys such as 'CONCRETE_WALL', in any case, and matches their Tekla classes. Fields with readable values (e.g. 'bolt.site_workshop': 'site' or
    'workshop') accept only 'Is Equal' and 'Is Not Equal'. '*' and '?' in a text value are always Tekla wildcards, so 'Is Equal 400*400' also matches a profile '400*1400'. Numeric fields take numbers only, so use a list or a range instead of a wildcard.
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


@selection_provider.tool(tags={"selection", "filters"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def create_filter(
    filter_name: Annotated[str, Field(description="Name of the filter file, without extension")],
    filter_type: Annotated[Literal["selection", "view"], Field(description="'selection' writes a selection filter (.SObjGrp), 'view' a view filter (.VObjGrp)")],
    filter: Annotated[
        FilterGroup | FilterCondition,
        Field(description="Filter tree, the same as for `select_elements_by_filter`. Fields and object types are listed in `tekla://filters/fields`"),
    ],
    object_types: Annotated[list[str], Field(description="Object types the filter matches, e.g. ['part'] or ['part', 'bolt']")] = ["part"],
    overwrite: Annotated[bool, Field(description="Replace a filter of the same name and type in the model's attributes folder")] = False,
) -> ToolResult:
    """
    Saves a filter as a Tekla selection filter or view filter.

    An existing filter is replaced only when `overwrite` is set. A model
    filter hides a firm or project filter of the same name. The result reports how many objects of the
    model match now.
    """
    # Check the whole request before touching any file
    stem = normalize_filter_name(filter_name, filter_type)
    tree = _FILTER_ADAPTER.validate_python(filter)
    expression = build_filter_expression(_prepare_tree(tree), object_types)

    model = TeklaModel()
    attributes = Path(model.model_path) / "attributes"
    if not attributes.is_dir():
        raise RuntimeError(f"The model has no attributes folder at '{attributes}'")
    file_name = f"{stem}{FILTER_FILE_EXTENSIONS[filter_type]}"
    # Windows file names ignore case, so an existing filter keeps its own spelling
    path = next((f for f in attributes.iterdir() if f.name.lower() == file_name.lower()), attributes / file_name)
    existed = path.exists()
    if existed and not overwrite:
        raise ValueError(f"A {filter_type} filter named '{path.stem}' already exists in the model. Set `overwrite` to replace it.")

    # Tekla writes a temporary file first, so a failed write never damages the filter it replaces
    file_type = FilterExpressionFileType.OBJECT_GROUP_SELECTION if filter_type == "selection" else FilterExpressionFileType.OBJECT_GROUP_VIEW
    temporary_stem = attributes / f"{TEMPORARY_FILTER_PREFIX}{path.stem}"
    try:
        # Tekla appends the extension and returns the path it wrote
        written = Path(str(Filter(expression).CreateFile(file_type, str(temporary_stem))))
    except Exception as e:
        raise ValueError(f"Tekla could not write the filter '{stem}': {str(e).splitlines()[0]}") from e
    try:
        if not written.is_file():
            raise RuntimeError(f"Tekla did not write the filter file '{written}'")
        os.replace(written, path)
    finally:
        written.unlink(missing_ok=True)

    # The filter lists behind `tekla://filters/*` and `apply_view_filter` are cached
    refresh_attribute_files()
    matching = model.get_objects_by_filter(expression).GetSize()
    logger.info("Created %s filter '%s' matching %d objects", filter_type, path, matching)
    return ToolResult(
        structured_content={
            "status": "success",
            "filter_name": path.stem,
            "filter_type": filter_type,
            "path": str(path),
            "overwritten": existed,
            "matching_objects": matching,
            "note": "Tekla reads its filter lists when a dialog opens, so reopen the view properties or filter dialog to see this filter there.",
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
