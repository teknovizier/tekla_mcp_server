"""
Selection tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Annotated, Any

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import (
    ElementTypeModel,
    SelectionMode,
    NumericMatchType,
    StringFilterOption,
    StringMatchType,
    NumericFilterOption,
)
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects
from tekla_mcp_server.tekla.loader import (
    ArrayList,
    Part,
    BinaryFilterExpression,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    BinaryFilterOperatorType,
    NumericConstantFilterExpression,
    NumericOperatorType,
    ObjectFilterExpressions,
    PartFilterExpressions,
    StringConstantFilterExpression,
    TeklaStructuresDatabaseTypeEnum,
    TemplateFilterExpressions,
)
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.utils import (
    NUMERIC_MATCH_TYPE_MAPPING,
    STRING_MATCH_TYPE_MAPPING,
)


selection_provider = LocalProvider()
_FILTERING_API_AVAILABLE = all(
    item is not None
    for item in (
        BinaryFilterExpression,
        BinaryFilterExpressionCollection,
        BinaryFilterExpressionItem,
        BinaryFilterOperatorType,
        NumericConstantFilterExpression,
        NumericOperatorType,
        ObjectFilterExpressions,
        PartFilterExpressions,
        StringConstantFilterExpression,
        TemplateFilterExpressions,
    )
)


def _to_filter_option(val: Any, model_class: type[StringFilterOption] | type[NumericFilterOption]) -> StringFilterOption | NumericFilterOption:
    if isinstance(val, dict):
        return model_class.model_validate(val)
    return val


def add_filter(
    filter_collection: BinaryFilterExpressionCollection,
    filter_expression: Any,
    value: str | int | float,
    match_type: Any = None,
    operator: Any = None,
) -> ToolResult | None:
    if operator is None:
        operator = BinaryFilterOperatorType.BOOLEAN_AND
    if not isinstance(value, (str, int, float)):
        expr = BinaryFilterExpression(filter_expression, NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(value))
        filter_collection.Add(BinaryFilterExpressionItem(expr, operator))
        return None

    is_string_filter = False
    if match_type is not None:
        if isinstance(match_type, StringMatchType):
            is_string_filter = True
        elif isinstance(match_type, NumericMatchType):
            is_string_filter = False

    if isinstance(value, str) and not is_string_filter:
        try:
            if value.replace(".", "").replace("-", "").isdigit():
                value = float(value) if "." in value else int(value)
        except ValueError:
            pass

    if isinstance(value, str):
        if match_type is None:
            match_type = StringMatchType.IS_EQUAL
        op = STRING_MATCH_TYPE_MAPPING.get(match_type)
        expr = BinaryFilterExpression(filter_expression, op, StringConstantFilterExpression(value))
    elif isinstance(value, (int, float)):
        if match_type is None:
            match_type = NumericOperatorType.IS_EQUAL
        if isinstance(match_type, NumericOperatorType):
            op = match_type
        else:
            op = NUMERIC_MATCH_TYPE_MAPPING.get(match_type)
        expr = BinaryFilterExpression(filter_expression, op, NumericConstantFilterExpression(value))
    else:
        logger.error("Unsupported value type in filter: %s", type(value))
        return ToolResult(structured_content={"status": "error", "message": f"Unsupported value type: {type(value)}"})

    filter_collection.Add(BinaryFilterExpressionItem(expr, operator))
    return None


def _string_matches(actual: Any, expected: Any, match_type: str) -> bool:
    actual_value = "" if actual is None else str(actual)
    expected_value = "" if expected is None else str(expected)
    if match_type == StringMatchType.IS_EQUAL.value:
        return actual_value == expected_value
    if match_type == StringMatchType.IS_NOT_EQUAL.value:
        return actual_value != expected_value
    if match_type == StringMatchType.CONTAINS.value:
        return expected_value in actual_value
    if match_type == StringMatchType.NOT_CONTAINS.value:
        return expected_value not in actual_value
    if match_type == StringMatchType.STARTS_WITH.value:
        return actual_value.startswith(expected_value)
    if match_type == StringMatchType.NOT_STARTS_WITH.value:
        return not actual_value.startswith(expected_value)
    if match_type == StringMatchType.ENDS_WITH.value:
        return actual_value.endswith(expected_value)
    if match_type == StringMatchType.NOT_ENDS_WITH.value:
        return not actual_value.endswith(expected_value)
    return False


def _numeric_matches(actual: Any, expected: Any, match_type: str) -> bool:
    try:
        actual_value = float(actual)
        expected_value = float(expected)
    except (TypeError, ValueError):
        return False
    if match_type == NumericMatchType.IS_EQUAL.value:
        return actual_value == expected_value
    if match_type == NumericMatchType.IS_NOT_EQUAL.value:
        return actual_value != expected_value
    if match_type == NumericMatchType.SMALLER_THAN.value:
        return actual_value < expected_value
    if match_type == NumericMatchType.SMALLER_OR_EQUAL.value:
        return actual_value <= expected_value
    if match_type == NumericMatchType.GREATER_THAN.value:
        return actual_value > expected_value
    if match_type == NumericMatchType.GREATER_OR_EQUAL.value:
        return actual_value >= expected_value
    return False


def _conditions_match(actual: Any, filter_option: StringFilterOption | NumericFilterOption, is_numeric: bool = False) -> bool:
    conditions = filter_option.conditions
    if not isinstance(conditions, list):
        conditions = [conditions]
    matcher = _numeric_matches if is_numeric else _string_matches
    results = [matcher(actual, condition.value, condition.match_type) for condition in conditions]
    return all(results) if filter_option.logic == "AND" else any(results)


def _safe_custom_property(model_object: Any, property_name: str, is_numeric: bool) -> Any:
    if is_numeric:
        for default in (float(), int(), str()):
            try:
                is_ok, value = model_object.GetReportProperty(property_name, default)
                if is_ok:
                    return value
            except Exception:
                pass
    else:
        for default in (str(), float(), int()):
            try:
                is_ok, value = model_object.GetReportProperty(property_name, default)
                if is_ok:
                    return value
            except Exception:
                pass

    for default in (float(), int(), str()) if is_numeric else (str(), float(), int()):
        try:
            is_ok, value = model_object.GetUserProperty(property_name, default)
            if is_ok:
                return value
        except Exception:
            pass
    return None


def _resolve_custom_attrs(queries: list[str]) -> tuple[dict[str, str | None], list[dict[str, Any]]]:
    if not queries:
        return {}, []
    try:
        resolution = TemplateAttributeParser.resolve_attributes(queries)
    except Exception as e:
        logger.warning("Custom attribute resolution failed, using raw names: %s", e)
        return {query: query for query in queries}, []

    errors = resolution.get("errors", [])
    resolved: dict[str, str | None] = {}
    for query, attr in zip(queries, resolution.get("resolved", []), strict=False):
        resolved[query] = None if any(error.get("query") == query for error in errors) else attr
    for query in queries:
        resolved.setdefault(query, query)
    return resolved, errors


def _fallback_select_elements_by_filter(
    element_type: str | None = None,
    tekla_classes: int | list[int] | None = None,
    standard_string_filters: dict[str, Any] | None = None,
    standard_numeric_filters: dict[str, Any] | None = None,
    custom_string_filters: dict[str, Any] | None = None,
    custom_numeric_filters: dict[str, Any] | None = None,
    combine_with: str = "AND",
) -> ToolResult:
    if combine_with not in {"AND", "OR"}:
        return ToolResult(structured_content={"status": "error", "message": f"Invalid combine_with '{combine_with}'. Must be 'AND' or 'OR'."})

    if not any((element_type, tekla_classes, standard_string_filters, standard_numeric_filters, custom_string_filters, custom_numeric_filters)):
        return ToolResult(structured_content={"status": "error", "message": "At least one filter must be provided."})

    element_type_classes: list[int] = []
    if element_type:
        try:
            element_type_enum = ElementTypeModel(value=element_type).to_enum()
        except Exception as e:
            return ToolResult(structured_content={"status": "error", "message": f"Invalid element_type: {str(e)}"})

        for material_types in get_config().element_types.values():
            for type_name, config in material_types.items():
                if element_type_enum.name.replace(" ", "_").upper() in type_name.upper() or type_name.upper() in element_type_enum.name.upper():
                    element_type_classes.extend(config.get("tekla_classes", []))

    explicit_classes: list[int] = []
    if tekla_classes:
        explicit_classes = [tekla_classes] if isinstance(tekla_classes, int) else list(tekla_classes)

    standard_string_filters = standard_string_filters or {}
    standard_numeric_filters = standard_numeric_filters or {}
    custom_string_filters = custom_string_filters or {}
    custom_numeric_filters = custom_numeric_filters or {}

    valid_string_keys = {"name", "profile", "material", "finish", "phase", "part_prefix", "assembly_prefix"}
    valid_numeric_keys = {"part_start_number", "assembly_start_number"}
    invalid_string_keys = set(standard_string_filters) - valid_string_keys
    invalid_numeric_keys = set(standard_numeric_filters) - valid_numeric_keys
    if invalid_string_keys:
        return ToolResult(structured_content={"status": "error", "message": f"Invalid standard_string_filters key(s): {sorted(invalid_string_keys)}"})
    if invalid_numeric_keys:
        return ToolResult(structured_content={"status": "error", "message": f"Invalid standard_numeric_filters key(s): {sorted(invalid_numeric_keys)}"})

    resolved_string_attrs, string_resolution_errors = _resolve_custom_attrs(list(custom_string_filters.keys()))
    resolved_numeric_attrs, numeric_resolution_errors = _resolve_custom_attrs(list(custom_numeric_filters.keys()))

    def standard_value(part: Any, key: str) -> Any:
        if key == "name":
            return part.Name
        if key == "profile":
            return part.Profile.ProfileString
        if key == "material":
            return part.Material.MaterialString
        if key == "finish":
            return part.Finish
        if key == "phase":
            is_ok, phase = part.GetPhase()
            return phase.PhaseNumber if is_ok else None
        if key == "part_prefix":
            return part.PartNumber.Prefix
        if key == "assembly_prefix":
            return part.AssemblyNumber.Prefix
        if key == "part_start_number":
            return part.PartNumber.StartNumber
        if key == "assembly_start_number":
            return part.AssemblyNumber.StartNumber
        return None

    def part_matches(part: Any) -> bool:
        groups: list[bool] = []

        if element_type_classes:
            groups.append(int(part.Class) in element_type_classes)
        if explicit_classes:
            groups.append(int(part.Class) in explicit_classes)

        for key, raw_filter_option in standard_string_filters.items():
            filter_option = _to_filter_option(raw_filter_option, StringFilterOption)
            groups.append(_conditions_match(standard_value(part, key), filter_option))

        for key, raw_filter_option in standard_numeric_filters.items():
            filter_option = _to_filter_option(raw_filter_option, NumericFilterOption)
            groups.append(_conditions_match(standard_value(part, key), filter_option, is_numeric=True))

        for key, raw_filter_option in custom_string_filters.items():
            attr_name = resolved_string_attrs.get(key)
            if not attr_name:
                groups.append(False)
                continue
            filter_option = _to_filter_option(raw_filter_option, StringFilterOption)
            groups.append(_conditions_match(_safe_custom_property(part, attr_name, is_numeric=False), filter_option))

        for key, raw_filter_option in custom_numeric_filters.items():
            attr_name = resolved_numeric_attrs.get(key)
            if not attr_name:
                groups.append(False)
                continue
            filter_option = _to_filter_option(raw_filter_option, NumericFilterOption)
            groups.append(_conditions_match(_safe_custom_property(part, attr_name, is_numeric=True), filter_option, is_numeric=True))

        return all(groups) if combine_with == "AND" else any(groups)

    selected = ArrayList()
    all_objects = TeklaModel().get_all_objects()
    while all_objects.MoveNext():
        obj = all_objects.Current
        if isinstance(obj, Part) and part_matches(obj):
            selected.Add(obj)

    TeklaModel.select_objects(selected)
    has_resolution_errors = bool(string_resolution_errors or numeric_resolution_errors)
    return ToolResult(
        structured_content={
            "status": "partial" if has_resolution_errors else ("success" if selected.Count else "warning"),
            "selected_elements": selected.Count,
            "filtering_mode": "python_fallback",
            "string_resolution_errors": string_resolution_errors,
            "numeric_resolution_errors": numeric_resolution_errors,
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_filter(
    element_type: Annotated[str | None, Field(description="Named element type (e.g., 'Wall', 'Steel Beam')")] = None,
    tekla_classes: Annotated[int | list[int] | None, Field(description="Tekla class numbers")] = None,
    standard_string_filters: Annotated[dict[str, Any] | None, Field(description="Dict of standard string properties to filter options")] = None,
    standard_numeric_filters: Annotated[dict[str, Any] | None, Field(description="Dict of standard numeric properties to filter options")] = None,
    custom_string_filters: Annotated[dict[str, Any] | None, Field(description="Dict of custom attribute names to StringFilterOption")] = None,
    custom_numeric_filters: Annotated[dict[str, Any] | None, Field(description="Dict of custom property names to NumericFilterOption")] = None,
    combine_with: Annotated[str, Field(description="How to combine filter groups: 'AND' or 'OR'")] = "AND",
) -> ToolResult:
    """
    Selects elements in the Tekla model using standard properties, custom attributes and numeric ranges.

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
        "tekla_classes": 1,
        "standard_string_filters": {
            "name": {"conditions": {"match_type": "Ends With", "value": "1601"}}
        }
    }

    # Elements in class 1 (Wall) with height > 2m
    {
        "tekla_classes": 1,
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

    At least one filter must be provided.
    """
    if not _FILTERING_API_AVAILABLE:
        return _fallback_select_elements_by_filter(
            element_type=element_type,
            tekla_classes=tekla_classes,
            standard_string_filters=standard_string_filters,
            standard_numeric_filters=standard_numeric_filters,
            custom_string_filters=custom_string_filters,
            custom_numeric_filters=custom_numeric_filters,
            combine_with=combine_with,
        )

    # Validate combine_with and ensure at least one filter provided
    if combine_with not in {"AND", "OR"}:
        logger.error("select_elements_by_filter failed: Invalid combine_with '%s'. Must be 'AND' or 'OR'.", combine_with)
        return ToolResult(structured_content={"status": "error", "message": f"Invalid combine_with '{combine_with}'. Must be 'AND' or 'OR'."})

    if not any((element_type, tekla_classes, standard_string_filters, standard_numeric_filters, custom_string_filters, custom_numeric_filters)):
        logger.error("select_elements_by_filter failed: No filters provided")
        return ToolResult(structured_content={"status": "error", "message": "At least one filter must be provided."})

    if element_type:
        try:
            element_type_enum = ElementTypeModel(value=element_type).to_enum()
        except Exception as e:
            logger.error("select_elements_by_filter failed: Invalid element_type '%s': %s", element_type, str(e))
            return ToolResult(structured_content={"status": "error", "message": f"Invalid element_type: {str(e)}"})

    model = TeklaModel()

    # Base filter: always filter for parts only
    filter_collection = BinaryFilterExpressionCollection()
    filter_collection.Add(
        BinaryFilterExpressionItem(
            BinaryFilterExpression(
                ObjectFilterExpressions.Type(),
                NumericOperatorType.IS_EQUAL,
                NumericConstantFilterExpression(TeklaStructuresDatabaseTypeEnum.PART),
            )
        )
    )

    # Define expression maps
    _STANDARD_STRING_EXPRESSION_MAP = {
        "name": PartFilterExpressions.Name(),
        "profile": PartFilterExpressions.Profile(),
        "material": PartFilterExpressions.Material(),
        "finish": PartFilterExpressions.Finish(),
        "phase": TemplateFilterExpressions.CustomString("ASSEMBLY.PHASE"),
        "part_prefix": PartFilterExpressions.Prefix(),
        "assembly_prefix": TemplateFilterExpressions.CustomString("ASSEMBLY_PREFIX"),
    }

    _STANDARD_NUMERIC_EXPRESSION_MAP = {
        "part_start_number": PartFilterExpressions.StartNumber(),
        "assembly_start_number": TemplateFilterExpressions.CustomNumber("ASSEMBLY_START_NUMBER"),
    }

    # Derive valid keys from expression maps
    _VALID_STRING_KEYS = frozenset(_STANDARD_STRING_EXPRESSION_MAP.keys())
    _VALID_NUMERIC_KEYS = frozenset(_STANDARD_NUMERIC_EXPRESSION_MAP.keys())

    # Validate input keys
    if standard_string_filters:
        for key in standard_string_filters:
            if key not in _VALID_STRING_KEYS:
                logger.error("select_elements_by_filter failed: Invalid standard_string_filters key '%s'. Must be one of: %s", key, _VALID_STRING_KEYS)
                return ToolResult(structured_content={"status": "error", "message": f"Invalid standard_string_filters key '{key}'. Must be one of: {_VALID_STRING_KEYS}"})

    if standard_numeric_filters:
        for key in standard_numeric_filters:
            if key not in _VALID_NUMERIC_KEYS:
                logger.error("select_elements_by_filter failed: Invalid standard_numeric_filters key '%s'. Must be one of: %s", key, _VALID_NUMERIC_KEYS)
                return ToolResult(structured_content={"status": "error", "message": f"Invalid standard_numeric_filters key '{key}'. Must be one of: {_VALID_NUMERIC_KEYS}"})

    filter_groups: list[BinaryFilterExpressionCollection] = []

    def build_filter_group(expression: Any, filter_option: StringFilterOption | NumericFilterOption, is_numeric: bool = False) -> BinaryFilterExpressionCollection | ToolResult | None:
        """Build filter group from conditions. Returns None if empty (no valid conditions)."""
        sub = BinaryFilterExpressionCollection()
        conditions = filter_option.conditions
        logic = filter_option.logic
        if not isinstance(conditions, list):
            conditions = [conditions]
        if not conditions:
            return None
        operator = BinaryFilterOperatorType.BOOLEAN_OR if logic == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        for cond in conditions:
            value = cond.value
            match_type_str = cond.match_type
            match_type = NumericMatchType(match_type_str) if is_numeric else StringMatchType(match_type_str)
            result = add_filter(sub, expression, value, match_type, operator=operator)
            if result:
                return result  # Error: return early

        # Check if we actually added anything
        if sub.Count == 0:
            return None
        return sub

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
        if isinstance(tekla_classes, int):
            tekla_classes = [tekla_classes]
        type_sub = BinaryFilterExpressionCollection()
        for cls in tekla_classes:
            add_filter(type_sub, PartFilterExpressions.Class(), cls, NumericOperatorType.IS_EQUAL, operator=BinaryFilterOperatorType.BOOLEAN_OR)
        filter_groups.append(type_sub)

    # Add standard string filters (name, profile, material, finish, phase, part_prefix, assembly_prefix)
    if standard_string_filters:
        for key, filter_option in standard_string_filters.items():
            expression = _STANDARD_STRING_EXPRESSION_MAP[key]
            filter_option = _to_filter_option(filter_option, StringFilterOption)
            result = build_filter_group(expression, filter_option)
            if isinstance(result, ToolResult):
                return result
            if result is not None:
                filter_groups.append(result)

    # Add standard numeric filters (part_start_number, assembly_start_number)
    if standard_numeric_filters:
        for key, filter_option in standard_numeric_filters.items():
            expression = _STANDARD_NUMERIC_EXPRESSION_MAP[key]
            filter_option = _to_filter_option(filter_option, NumericFilterOption)
            result = build_filter_group(expression, filter_option, is_numeric=True)
            if isinstance(result, ToolResult):
                return result
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
            for query, resolved in zip(string_queries, resolution["resolved"]):
                if any(e["query"] == query for e in errors):
                    resolved_string_attrs[query] = None
                else:
                    resolved_string_attrs[query] = resolved

        for field_name, filter_option in custom_string_filters.items():
            resolved_name = resolved_string_attrs.get(field_name)
            if resolved_name:
                expression = TemplateFilterExpressions.CustomString(resolved_name)
                filter_option = _to_filter_option(filter_option, StringFilterOption)
                result = build_filter_group(expression, filter_option)
                if isinstance(result, ToolResult):
                    return result
                if result is not None:
                    filter_groups.append(result)

    # Same for numeric filters
    if custom_numeric_filters:
        numeric_queries = list(custom_numeric_filters.keys())
        if numeric_queries:
            resolution = TemplateAttributeParser.resolve_attributes(numeric_queries)
            errors = resolution.get("errors", [])
            numeric_resolution_errors = errors
            for query, resolved in zip(numeric_queries, resolution["resolved"]):
                if any(e["query"] == query for e in errors):
                    resolved_numeric_attrs[query] = None
                else:
                    resolved_numeric_attrs[query] = resolved

        for field_name, filter_option in custom_numeric_filters.items():
            resolved_name = resolved_numeric_attrs.get(field_name)
            if resolved_name:
                expression = TemplateFilterExpressions.CustomNumber(resolved_name)
                filter_option = _to_filter_option(filter_option, NumericFilterOption)
                result = build_filter_group(expression, filter_option, is_numeric=True)
                if isinstance(result, ToolResult):
                    return result
                if result is not None:
                    filter_groups.append(result)

    # Combine all filter groups into final filter
    if len(filter_groups) == 1:
        filter_collection.Add(BinaryFilterExpressionItem(filter_groups[0], BinaryFilterOperatorType.BOOLEAN_AND))
    elif len(filter_groups) > 1:
        combined = BinaryFilterExpressionCollection()
        group_operator = BinaryFilterOperatorType.BOOLEAN_OR if combine_with == "OR" else BinaryFilterOperatorType.BOOLEAN_AND
        logger.debug("Combining %d filter groups with %s", len(filter_groups), combine_with)
        for fg in filter_groups:
            if fg is not None:
                combined.Add(BinaryFilterExpressionItem(fg, group_operator))
        if combined.Count > 0:
            filter_collection.Add(BinaryFilterExpressionItem(combined, BinaryFilterOperatorType.BOOLEAN_AND))

    objects_to_select = model.get_objects_by_filter(filter_collection)
    TeklaModel.select_objects(objects_to_select)

    count = objects_to_select.GetSize()
    has_resolution_errors = bool(string_resolution_errors or numeric_resolution_errors)

    return ToolResult(
        structured_content={
            "status": "partial" if has_resolution_errors else ("success" if count else "warning"),
            "selected_elements": count,
            "string_resolution_errors": string_resolution_errors,
            "numeric_resolution_errors": numeric_resolution_errors,
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_filter_name(
    filter_name: Annotated[str, Field(description="Name of the Tekla filter to apply")],
) -> ToolResult:
    """
    Selects elements applying an existing Tekla filter.
    """
    model = TeklaModel()
    objects_to_select = model.get_objects_by_filter(filter_name)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by named filter", objects_to_select.GetSize())
    return ToolResult(
        structured_content={
            "status": "success" if objects_to_select.GetSize() else "warning",
            "selected_elements": objects_to_select.GetSize(),
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_by_guid(
    guids: Annotated[list[str], Field(description="List of GUIDs to select")],
) -> ToolResult:
    """
    Selects elements by their GUID.
    """
    model = TeklaModel()
    objects_to_select = model.get_objects_by_guid(guids)
    TeklaModel.select_objects(objects_to_select)
    logger.info("Selected %s elements by GUID", objects_to_select.Count)
    return ToolResult(
        structured_content={
            "status": "success" if objects_to_select.Count else "warning",
            "selected_elements": objects_to_select.Count,
        }
    )


@selection_provider.tool(tags={"selection"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def select_elements_assemblies_or_main_parts(
    mode: Annotated[SelectionMode, Field(description="Selection mode: 'Assembly' or 'Main Part'")],
) -> ToolResult:
    """
    Selects assemblies or main parts for the selected elements.
    """
    selected_objects = TeklaModel().get_selected_objects()

    processed_elements = 0
    selected_object_types = ""

    filtered_parts = ArrayList()
    for selected_object in wrap_model_objects(selected_objects):
        try:
            assembly = selected_object.get_top_level_assembly()
        except TypeError:
            logger.error("Failed to get top level assembly for the element %s", selected_object.guid)
            continue
        if mode == "Assembly":
            filtered_parts.Add(assembly.model_object)
            selected_object_types = "selected_assemblies"
        elif mode == "Main Part":
            filtered_parts.Add(assembly.main_part.model_object)
            selected_object_types = "selected_main_parts"
        processed_elements += 1

    TeklaModel.select_objects(filtered_parts)
    logger.info("Selected %s elements as '%s'", filtered_parts.Count, mode)
    return ToolResult(
        structured_content={
            "status": "success" if filtered_parts.Count else "warning",
            "selected_elements": selected_objects.GetSize(),
            "processed_elements": processed_elements,
            selected_object_types: filtered_parts.Count,
        }
    )
