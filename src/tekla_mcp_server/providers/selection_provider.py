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
from tekla_mcp_server.models import ElementType, NumericFilterOption, SelectionMode
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects
from tekla_mcp_server.tekla.filter_builder import build_filter_expression
from tekla_mcp_server.tekla.loader import ArrayList
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser


selection_provider = LocalProvider()


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


def _resolve_class_criteria(element_type: str | None, tekla_classes: list[int], combine_with: str) -> list[int]:
    """
    Merge `element_type` and `tekla_classes` into one list of Tekla class numbers.

    They used to be two separate filter groups, so the merge follows `combine_with`. AND keeps
    the classes in both lists, OR keeps the classes in either.

    Args:
        element_type: Named element type, or None
        tekla_classes: Tekla class numbers, may be empty
        combine_with: How the filter groups are combined, 'AND' or 'OR'

    Returns:
        Class numbers without duplicates, empty when neither criterion is given

    Raises:
        ValueError: If the element type has no configured classes, or AND leaves no class
    """
    class_lists: list[list[int]] = []
    if element_type:
        element_type_classes = _resolve_element_type_classes(element_type)
        if not element_type_classes:
            raise ValueError(f"Element type '{element_type}' has no Tekla classes configured.")
        class_lists.append(element_type_classes)
    if tekla_classes:
        class_lists.append(tekla_classes)

    if len(class_lists) < 2:
        return list(dict.fromkeys(class_lists[0])) if class_lists else []

    first, second = class_lists
    if combine_with == "AND":
        merged = [cls for cls in dict.fromkeys(first) if cls in second]
        if not merged:
            raise ValueError(f"`element_type` classes {first} and `tekla_classes` {second} have no class in common, so combining them with AND matches nothing.")
        return merged
    return list(dict.fromkeys(first + second))


def _class_filter_option(tekla_classes: list[int]) -> NumericFilterOption:
    """
    Build a 'class' filter option matching any of the given Tekla classes.

    Args:
        tekla_classes: Tekla class numbers, at least one

    Returns:
        Filter option with one 'Is Equal' condition per class, joined by OR
    """
    return NumericFilterOption.model_validate({"conditions": [{"match_type": "Is Equal", "value": cls} for cls in tekla_classes], "logic": "OR"})


def _resolve_custom_filters(custom_filters: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Replace custom attribute names given by the caller with the Tekla attribute names.

    Args:
        custom_filters: Attribute names as given by the caller to filter options

    Returns:
        Tuple of the filters keyed by Tekla attribute name, without the names that failed, and the resolution errors
    """
    if not custom_filters:
        return {}, []
    queries = list(custom_filters.keys())
    resolution = TemplateAttributeParser.resolve_attributes(queries)
    errors = resolution.get("errors", [])
    # `resolved` holds only the names that resolved, in the order their queries
    # succeeded. Align them to the non-failed queries - a positional zip against
    # all queries would shift names onto the wrong attributes once one query fails
    failed_queries = {e["query"] for e in errors}
    successful_queries = [q for q in queries if q not in failed_queries]
    resolved_map = dict(zip(successful_queries, resolution["resolved"]))
    return {resolved_map[q]: custom_filters[q] for q in successful_queries if resolved_map.get(q)}, errors


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
    `element_type`, `tekla_classes` and the `standard_numeric_filters` key 'class' apply to parts only. Tekla cannot filter bolts by cut length, extra length
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
    if object_type != "part" and (element_type or tekla_classes):
        raise ValueError("`element_type` and `tekla_classes` apply to parts only. Remove them or set `object_type` to 'part'.")

    # `element_type` and `tekla_classes` become the 'class' filter
    standard_numeric_filters = dict(standard_numeric_filters)
    class_numbers = _resolve_class_criteria(element_type, tekla_classes, combine_with)
    if class_numbers:
        if "class" in standard_numeric_filters:
            raise ValueError("Use either the 'class' key in `standard_numeric_filters` or `element_type` and `tekla_classes`, not both.")
        standard_numeric_filters["class"] = _class_filter_option(class_numbers)

    resolved_string_filters, string_resolution_errors = _resolve_custom_filters(custom_string_filters)
    resolved_numeric_filters, numeric_resolution_errors = _resolve_custom_filters(custom_numeric_filters)
    if (custom_string_filters or custom_numeric_filters) and not any((standard_string_filters, standard_numeric_filters, resolved_string_filters, resolved_numeric_filters)):
        failed = [e.get("query") for e in (string_resolution_errors + numeric_resolution_errors)]
        raise ValueError(f"No usable filter conditions were produced - nothing was selected to avoid selecting the entire model. Unresolved custom attributes: {failed}.")

    expression = build_filter_expression(
        object_type=object_type,
        standard_string_filters=standard_string_filters,
        standard_numeric_filters=standard_numeric_filters,
        custom_string_filters=resolved_string_filters,
        custom_numeric_filters=resolved_numeric_filters,
        combine_with=combine_with,
    )

    model = TeklaModel()
    objects_to_select = model.get_objects_by_filter(expression)
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
