"""
Selection tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Annotated, Any, Literal

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    ElementType,
    SelectionMode,
    StringFilterOption,
    NumericFilterOption,
)
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects
from tekla_mcp_server.tekla.filter_builder import add_filter, build_filter_group, to_filter_option
from tekla_mcp_server.tekla.loader import (
    ArrayList,
    BinaryFilterExpression,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    BinaryFilterOperatorType,
    BoltFilterExpressions,
    NumericConstantFilterExpression,
    NumericOperatorType,
    ObjectFilterExpressions,
    PartFilterExpressions,
    TeklaStructuresDatabaseTypeEnum,
    TemplateFilterExpressions,
)
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser


# Define expression maps
STANDARD_STRING_EXPRESSION_MAP = {
    "name": PartFilterExpressions.Name(),
    "profile": PartFilterExpressions.Profile(),
    "material": PartFilterExpressions.Material(),
    "finish": PartFilterExpressions.Finish(),
    "phase": TemplateFilterExpressions.CustomString("ASSEMBLY.PHASE"),
    "part_prefix": PartFilterExpressions.Prefix(),
    "assembly_prefix": TemplateFilterExpressions.CustomString("ASSEMBLY_PREFIX"),
}

STANDARD_NUMERIC_EXPRESSION_MAP = {
    "part_start_number": PartFilterExpressions.StartNumber(),
    "assembly_start_number": TemplateFilterExpressions.CustomNumber("ASSEMBLY_START_NUMBER"),
}

BOLT_STRING_EXPRESSION_MAP = {
    "bolt_standard": BoltFilterExpressions.Standard(),
    "bolt_type": BoltFilterExpressions.SiteWorkshop(),
}

# Tekla's site/workshop filter matches the `BoltTypeEnum` value as a string
BOLT_TYPE_FILTER_VALUES = {"site": "0", "workshop": "1"}

BOLT_NUMERIC_EXPRESSION_MAP = {
    "bolt_size": BoltFilterExpressions.Size(),
    "bolt_length": BoltFilterExpressions.Length(),
    "phase": BoltFilterExpressions.Phase(),
}

# Per object type: (database type, string map, numeric map, custom string factory, custom number factory)
OBJECT_TYPE_FILTERS: dict[str, tuple[Any, dict[str, Any], dict[str, Any], Any, Any]] = {
    "part": (
        TeklaStructuresDatabaseTypeEnum.PART,
        STANDARD_STRING_EXPRESSION_MAP,
        STANDARD_NUMERIC_EXPRESSION_MAP,
        TemplateFilterExpressions.CustomString,
        TemplateFilterExpressions.CustomNumber,
    ),
    "bolt": (
        TeklaStructuresDatabaseTypeEnum.BOLT,
        BOLT_STRING_EXPRESSION_MAP,
        BOLT_NUMERIC_EXPRESSION_MAP,
        BoltFilterExpressions.CustomString,
        BoltFilterExpressions.CustomNumber,
    ),
}


selection_provider = LocalProvider()


def _to_bolt_type_filter(filter_option: StringFilterOption) -> StringFilterOption:
    """
    Translate 'site' and 'workshop' in a `bolt_type` filter to the values Tekla matches.

    Args:
        filter_option: Filter option whose condition values are 'site' or 'workshop'

    Returns:
        A copy of the option with the values replaced

    Raises:
        ValueError: If a value is not 'site' or 'workshop'
    """
    conditions = filter_option.conditions if isinstance(filter_option.conditions, list) else [filter_option.conditions]
    mapped = []
    for condition in conditions:
        value = BOLT_TYPE_FILTER_VALUES.get(condition.value.strip().lower())
        if value is None:
            raise ValueError(f"Invalid bolt_type filter value '{condition.value}'. Must be one of: {sorted(BOLT_TYPE_FILTER_VALUES)}")
        mapped.append(condition.model_copy(update={"value": value}))
    return filter_option.model_copy(update={"conditions": mapped})


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_filter(
    element_type: Annotated[str | None, Field(description="Named element type (e.g. 'Wall', 'Steel Beam')")] = None,
    tekla_classes: Annotated[list[int], Field(description="Tekla class numbers")] = [],
    standard_string_filters: Annotated[dict[str, Any], Field(description="Dict of standard string properties to filter options")] = {},
    standard_numeric_filters: Annotated[dict[str, Any], Field(description="Dict of standard numeric properties to filter options")] = {},
    custom_string_filters: Annotated[dict[str, Any], Field(description="Dict of custom attribute names to StringFilterOption")] = {},
    custom_numeric_filters: Annotated[dict[str, Any], Field(description="Dict of custom property names to NumericFilterOption")] = {},
    combine_with: Annotated[str, Field(description="How to combine filter groups: 'AND' or 'OR'")] = "AND",
    object_type: Annotated[
        Literal["part", "bolt"],
        Field(
            description="Object type to select. 'bolt' accepts only `standard_string_filters` keys 'bolt_standard' and 'bolt_type' ('site' or 'workshop') and `standard_numeric_filters` keys 'bolt_size', 'bolt_length', 'phase'"
        ),
    ] = "part",
) -> ToolResult:
    """
    Selects elements in the Tekla model using standard properties, custom attributes and numeric ranges.

    Parts are selected by default. Set `object_type` to 'bolt' to select bolt groups instead.
    `element_type` and `tekla_classes` apply to parts only. Tekla cannot filter bolts by cut length, extra length
    or tolerance. To find bolts by those, read them with `get_elements_properties` and select the matching GUIDs
    with `select_elements_by_guid`.

    ### EXAMPLES
    # NAME = "Wall" OR PHASE = "2"
    {
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Is Equal", "value": "Wall"}},
            "phase": {"conditions": {"match_type": "Is Equal", "value": "2"}}
        },
        "combine_with": "OR"
    }

    # element_type = Wall AND (name = "beam" OR profile = "200*600")
    {
        "element_type": "Wall",
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Is Equal", "value": "beam"}},
            "profile": {"conditions": {"match_type": "Is Equal", "value": "200*600"}}
        },
        "combine_with": "OR"
    }

    # Elements in class 1 (Wall) with name ending in "1601"
    {
        "tekla_classes": [1],
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Ends With", "value": "1601"}}
        }
    }

    # Elements in class 1 (Wall) with height > 2m
    {
        "tekla_classes": [1],
        "custom_numeric_filters": {
            "HEIGHT": {"conditions": {"match_type": "Greater Than", "value": 2000}}
        }
    }

    # Combined: prefix starts with SB AND part_start_number > 50
    {
        "standard_string_filters": {
            "part_prefix": {"conditions": {"match_type": "Starts With", "value": "SB"}}
        },
        "standard_numeric_filters": {
            "part_start_number": {"conditions": {"match_type": "Greater Than", "value": 50}}
        },
        "combine_with": "AND"
    }

    # Bolts of standard '7990' with diameter 16
    {
        "object_type": "bolt",
        "standard_string_filters": {
            "bolt_standard": {"conditions": {"match_type": "Is Equal", "value": "7990"}}
        },
        "standard_numeric_filters": {
            "bolt_size": {"conditions": {"match_type": "Is Equal", "value": 16}}
        }
    }

    At least one filter must be provided.
    """
    # Validate combine_with and ensure at least one filter provided
    if combine_with not in {"AND", "OR"}:
        raise ValueError(f"Invalid combine_with '{combine_with}'. Must be 'AND' or 'OR'.")

    if not any((element_type, tekla_classes, standard_string_filters, standard_numeric_filters, custom_string_filters, custom_numeric_filters)):
        raise ValueError("At least one filter must be provided.")

    if object_type not in OBJECT_TYPE_FILTERS:
        raise ValueError(f"Invalid object_type '{object_type}'. Must be one of: {sorted(OBJECT_TYPE_FILTERS)}")
    database_type, string_expression_map, numeric_expression_map, custom_string_expression, custom_number_expression = OBJECT_TYPE_FILTERS[object_type]

    if object_type != "part" and (element_type or tekla_classes):
        raise ValueError("`element_type` and `tekla_classes` apply to parts only. Remove them or set `object_type` to 'part'.")

    if element_type:
        try:
            element_type_enum = ElementType(element_type.strip())
        except Exception as e:
            raise ValueError(f"Invalid element_type: {e}") from e

    model = TeklaModel()

    # Base filter: always filter for the requested object type only
    filter_collection = BinaryFilterExpressionCollection()
    filter_collection.Add(
        BinaryFilterExpressionItem(
            BinaryFilterExpression(
                ObjectFilterExpressions.Type(),
                NumericOperatorType.IS_EQUAL,
                NumericConstantFilterExpression(database_type),
            )
        )
    )

    # Derive valid keys from expression maps
    _VALID_STRING_KEYS = frozenset(string_expression_map.keys())
    _VALID_NUMERIC_KEYS = frozenset(numeric_expression_map.keys())

    # Validate input keys
    if standard_string_filters:
        for key in standard_string_filters:
            if key not in _VALID_STRING_KEYS:
                raise ValueError(f"Invalid standard_string_filters key '{key}'. Must be one of: {_VALID_STRING_KEYS}")

    if standard_numeric_filters:
        for key in standard_numeric_filters:
            if key not in _VALID_NUMERIC_KEYS:
                raise ValueError(f"Invalid standard_numeric_filters key '{key}'. Must be one of: {_VALID_NUMERIC_KEYS}")

    filter_groups: list[BinaryFilterExpressionCollection] = []

    # Resolve element_type to tekla class numbers
    if element_type:
        element_type_classes: list[int] = []
        for material_types in get_config().element_types.values():
            for type_name, config in material_types.items():
                logger.debug("Checking element type '%s' against '%s', classes=%s", element_type_enum.name, type_name, config.get("tekla_classes", []))
                if element_type_enum.name.replace(" ", "_").upper() in type_name.upper() or type_name.upper() in element_type_enum.name.upper():
                    element_type_classes.extend(config.get("tekla_classes", []))
        type_sub = BinaryFilterExpressionCollection()
        for cls in element_type_classes:
            add_filter(type_sub, PartFilterExpressions.Class(), cls, NumericOperatorType.IS_EQUAL, operator=BinaryFilterOperatorType.BOOLEAN_OR)
        filter_groups.append(type_sub)

    # Add explicit tekla_classes to filter
    if tekla_classes:
        type_sub = BinaryFilterExpressionCollection()
        for cls in tekla_classes:
            add_filter(type_sub, PartFilterExpressions.Class(), cls, NumericOperatorType.IS_EQUAL, operator=BinaryFilterOperatorType.BOOLEAN_OR)
        filter_groups.append(type_sub)

    # Add standard string filters (parts: name, profile, material, finish, phase, prefixes. Bolts: bolt_standard, bolt_type)
    if standard_string_filters:
        for key, filter_option in standard_string_filters.items():
            expression = string_expression_map[key]
            filter_option = to_filter_option(filter_option, StringFilterOption)
            if object_type == "bolt" and key == "bolt_type":
                filter_option = _to_bolt_type_filter(filter_option)
            result = build_filter_group(expression, filter_option)
            if result is not None:
                filter_groups.append(result)

    # Add standard numeric filters (parts: start numbers. Bolts: bolt_size, bolt_length, phase)
    if standard_numeric_filters:
        for key, filter_option in standard_numeric_filters.items():
            expression = numeric_expression_map[key]
            filter_option = to_filter_option(filter_option, NumericFilterOption)
            result = build_filter_group(expression, filter_option, is_numeric=True)
            if result is not None:
                filter_groups.append(result)

    string_resolution_errors: list[dict[str, Any]] = []
    numeric_resolution_errors: list[dict[str, Any]] = []
    resolved_string_attrs: dict[str, str | None] = {}
    resolved_numeric_attrs: dict[str, str | None] = {}

    # Resolve custom attribute names to Tekla names, then add string filters
    if custom_string_filters:
        string_queries = list(custom_string_filters.keys())
        if string_queries:
            resolution = TemplateAttributeParser.resolve_attributes(string_queries)
            errors = resolution.get("errors", [])
            string_resolution_errors = errors
            # `resolved` holds only the names that resolved, in the order their queries
            # succeeded. Align them to the non-failed queries - a positional zip against
            # all queries would shift names onto the wrong attributes once one query fails
            failed_queries = {e["query"] for e in errors}
            successful_queries = [q for q in string_queries if q not in failed_queries]
            resolved_map = dict(zip(successful_queries, resolution["resolved"]))
            for query in string_queries:
                resolved_string_attrs[query] = resolved_map.get(query)

        for field_name, filter_option in custom_string_filters.items():
            resolved_name = resolved_string_attrs.get(field_name)
            if resolved_name:
                expression = custom_string_expression(resolved_name)
                filter_option = to_filter_option(filter_option, StringFilterOption)
                result = build_filter_group(expression, filter_option)
                if result is not None:
                    filter_groups.append(result)

    # Same for numeric filters
    if custom_numeric_filters:
        numeric_queries = list(custom_numeric_filters.keys())
        if numeric_queries:
            resolution = TemplateAttributeParser.resolve_attributes(numeric_queries)
            errors = resolution.get("errors", [])
            numeric_resolution_errors = errors
            # See the string-filter block above: align resolved names to the non-failed
            # queries so a single failed query does not shift names onto wrong attributes
            failed_queries = {e["query"] for e in errors}
            successful_queries = [q for q in numeric_queries if q not in failed_queries]
            resolved_map = dict(zip(successful_queries, resolution["resolved"]))
            for query in numeric_queries:
                resolved_numeric_attrs[query] = resolved_map.get(query)

        for field_name, filter_option in custom_numeric_filters.items():
            resolved_name = resolved_numeric_attrs.get(field_name)
            if resolved_name:
                expression = custom_number_expression(resolved_name)
                filter_option = to_filter_option(filter_option, NumericFilterOption)
                result = build_filter_group(expression, filter_option, is_numeric=True)
                if result is not None:
                    filter_groups.append(result)

    # Drop empty groups - e.g. an element_type that matched no classes, or custom
    # attributes that all failed to resolve. If nothing meaningful remains, refuse
    # rather than silently selecting every object via the bare type filter.
    non_empty_groups = [fg for fg in filter_groups if fg is not None and fg.Count > 0]
    if not non_empty_groups:
        failed = [e.get("query") for e in (string_resolution_errors + numeric_resolution_errors)]
        detail = f" Unresolved custom attributes: {failed}." if failed else ""
        raise ValueError(f"No usable filter conditions were produced - nothing was selected to avoid selecting the entire model.{detail}")

    # Combine all filter groups into final filter
    if len(non_empty_groups) == 1:
        filter_collection.Add(BinaryFilterExpressionItem(non_empty_groups[0], BinaryFilterOperatorType.BOOLEAN_AND))
    else:
        combined = BinaryFilterExpressionCollection()
        group_operator = BinaryFilterOperatorType.BOOLEAN_OR if combine_with == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        logger.debug("Combining %d filter groups with %s", len(non_empty_groups), combine_with)
        for fg in non_empty_groups:
            combined.Add(BinaryFilterExpressionItem(fg, group_operator))
        filter_collection.Add(BinaryFilterExpressionItem(combined, BinaryFilterOperatorType.BOOLEAN_AND))

    objects_to_select = model.get_objects_by_filter(filter_collection)
    TeklaModel.select_objects(objects_to_select)

    count = objects_to_select.GetSize()
    has_resolution_errors = bool(string_resolution_errors or numeric_resolution_errors)

    return ToolResult(
        structured_content={
            "status": "partial" if has_resolution_errors else ("success" if count else "warning"),
            "selected_count": count,
            "string_resolution_errors": string_resolution_errors,
            "numeric_resolution_errors": numeric_resolution_errors,
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
