"""
Components tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any, Annotated
from pydantic import Field

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import BaseComponent, ComponentType, TYPE_DEFAULTS
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_objects
from tekla_mcp_server.tekla.component_handlers import HandlerRegistry
from tekla_mcp_server.tekla.loader import Beam, CustomPart, Part
from tekla_mcp_server.tekla.utils import ensure_transformation_plane, get_wall_pairs, insert_component, insert_detail


components_provider = LocalProvider()


def _manage_components_on_selected_objects(
    callback: Any,
    component: BaseComponent,
    custom_properties_errors: list[str] | None = None,
    *args: Any,
    **kwargs: Any,
) -> ToolResult:
    model = TeklaModel()
    selected_objects = model.get_selected_objects()
    if component.component_type in [ComponentType.DETAIL, ComponentType.COMPONENT]:
        return _process_detail_or_component(selected_objects, callback, model, component, custom_properties_errors, *args, **kwargs)
    elif component.component_type in [ComponentType.SEAM, ComponentType.CONNECTION]:
        return _process_seam_or_connection(selected_objects, callback, model, component, custom_properties_errors, *args, **kwargs)
    raise ValueError(f"Unsupported component type: {component.component_type}")


def _process_detail_or_component(
    selected_objects: Any,
    callback: Any,
    model: TeklaModel,
    component: BaseComponent,
    custom_properties_errors: list[str] | None = None,
    *args: Any,
    **kwargs: Any,
) -> ToolResult:
    processed_count = 0
    processed_components_count = 0
    errors: list[dict[str, Any]] = []
    for selected_object in selected_objects:
        if isinstance(selected_object, Beam):
            # Isolate per-object failures so one bad element (e.g. a non-concrete
            # beam rejected by a handler) does not abort the whole batch and discard
            # the components already inserted for earlier elements.
            try:
                success = callback(model, component, selected_object, *args, **kwargs)
                if success:
                    processed_components_count += success
            except Exception as e:
                guid = selected_object.Identifier.GUID.ToString()
                logger.exception("Failed to process component on %s", guid)
                errors.append({"guid": guid, "error": str(e)})
            processed_count += 1

    commit_success: bool | None = None
    if processed_components_count > 0:
        commit_success = model.commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after processing %s components", processed_components_count)

    if commit_success is False:
        status = "error"
    elif processed_components_count and errors:
        status = "partial"
    elif processed_components_count:
        status = "success"
    else:
        status = "warning"

    logger.info("Processed %s elements, %s components", processed_count, processed_components_count)
    result: dict = {
        "status": status,
        "selected_count": selected_objects.GetSize(),
        "processed_count": processed_count,
        "processed_components_count": processed_components_count,
        "errors": errors,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


def _process_seam_or_connection(
    selected_objects: Any,
    callback: Any,
    model: TeklaModel,
    component: BaseComponent,
    custom_properties_errors: list[str] | None = None,
    *args: Any,
    **kwargs: Any,
) -> ToolResult:
    count = selected_objects.GetSize()
    if count == 1:
        raise ValueError("Only one element selected. Please select two elements.")
    if count > 2:
        raise ValueError(f"More than two elements selected. Expected 2, got {count}.")

    processed_pairs_count = 0
    processed_components_count = 0
    errors: list[dict[str, Any]] = []

    wall_pairs = get_wall_pairs(selected_objects)
    for pair in wall_pairs:
        # Isolate per-pair failures so one bad pair does not abort the whole batch.
        try:
            success = callback(model, component, pair[1], pair[0], *args, **kwargs)
            if success:
                processed_components_count += success
        except Exception as e:
            logger.exception("Failed to process seam/connection on a wall pair")
            errors.append({"error": str(e)})
        processed_pairs_count += 1

    commit_success: bool | None = None
    if processed_components_count > 0:
        commit_success = model.commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after processing %s component pairs", processed_components_count)

    if commit_success is False:
        status = "error"
    elif processed_components_count and errors:
        status = "partial"
    elif processed_components_count:
        status = "success"
    else:
        status = "warning"

    logger.info("Processed %s element pairs, %s components", processed_pairs_count, processed_components_count)
    result: dict = {
        "status": status,
        "selected_count": selected_objects.GetSize(),
        "processed_pairs_count": processed_pairs_count,
        "processed_components_count": processed_components_count,
        "errors": errors,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@ensure_transformation_plane
def _put_single_component(model: TeklaModel, component: BaseComponent, selected_object: Any, *args: Any) -> int:
    handler = HandlerRegistry.get(component.name)

    context = {}
    if handler and hasattr(handler, "pre_process"):
        context = handler.pre_process(component, selected_object)

    if component.number == -1:
        counter = int(insert_detail(selected_object, component, selected_object.GetCoordinateSystem().Origin))
        logger.debug("Inserted %s custom detail components", counter)
    else:
        counter = int(insert_component(selected_object, component))
        logger.debug("Inserted %s components", counter)

    if handler and hasattr(handler, "post_process"):
        counter = handler.post_process(component, selected_object, counter, context)

    return counter


@ensure_transformation_plane
def _modify_single_component(model: TeklaModel, component: BaseComponent, selected_object: Any, *args: Any) -> int:
    counter = 0

    comp_enum = selected_object.GetComponents()
    while comp_enum.MoveNext():
        comp = comp_enum.Current
        if comp.Name == component.name:
            if component.properties:
                for key, value in component.properties.items():
                    if isinstance(value, int):
                        value = float(value)
                    comp.SetAttribute(key, value)
            if comp.Modify():
                counter += 1

    logger.info("Modified %s '%s' components", counter, component.name)
    return counter


@components_provider.tool(tags={"components"}, annotations={"readOnlyHint": False, "destructiveHint": False})
@mcp_handler(scope="tool")
def put_components(
    component_name: Annotated[str, Field(description="The Tekla name of the component (e.g. 'Lifting Anchor', 'MeshBars')")],
    properties_set: Annotated[str, Field(description="The name of the Tekla component properties set to use")] = "standard",
    custom_properties: Annotated[dict[str, Any] | None, Field(description="Custom properties to apply to the component")] = None,
) -> ToolResult:
    """
    Inserts Tekla components into the selected objects.

    ## INSTRUCTIONS
    - First read `component://schema` to discover available components.
    - Then read `component://schema/{component_key}` to get custom properties for a specific component.
    - Use Tekla config keys (e.g. `SpacBarsBottPri`, `BottGradePri`) as property names, NOT user-friendly descriptions.
    - Example: For 'MeshBars', read the schema to get: `SpacBarsBottPri` for 'bottom primary bars spacing', `BottGradePri` for 'bottom primary bars reinforcement grade'.
    """
    component = BaseComponent(name=component_name, properties_set=properties_set, custom_properties=custom_properties)

    result = _manage_components_on_selected_objects(_put_single_component, component)
    return result


@components_provider.tool(tags={"components"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def remove_components(component_name: Annotated[str, Field(description="The Tekla name of the component (e.g. 'Lifting Anchor', 'MeshBars')")]) -> ToolResult:
    """
    Removes Tekla components from selected objects.
    """
    component = BaseComponent(name=component_name)
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    handler = HandlerRegistry.get(component.name)

    counter = 0
    objects_list = list(selected_objects)
    if handler and hasattr(handler, "pre_remove"):
        counter += handler.pre_remove(objects_list)

    for obj in objects_list:
        # Only Part and CustomPart support GetComponents()
        if not isinstance(obj, (Part, CustomPart)):
            continue
        # Collect matches before deleting
        to_delete = [comp for comp in obj.GetComponents() if comp.Number == component.number and comp.Name == component.name]
        for comp in to_delete:
            if comp.Delete():
                counter += 1
    commit_success: bool | None = None
    if counter > 0:
        commit_success = model.commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after removing %s components", counter)

    if commit_success is False:
        status = "error"
    elif counter > 0:
        status = "success"
    else:
        status = "warning"
    logger.info("Total components removed: %s", counter)
    result: dict = {
        "status": status,
        "selected_count": selected_objects.GetSize(),
        "removed_components_count": counter,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@components_provider.tool(tags={"components"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_components() -> ToolResult:
    """
    Gets all components attached to the currently selected elements.

    Returns component information including:
    - Component name and number.
    - Whether the component is supported by config.
    - Full schema with descriptions and types (if supported).
    - Actual attribute values from the component instance.
    """
    model = TeklaModel()
    selected_objects = model.get_selected_objects()

    base_components = get_config().base_components

    components_by_tekla_name: dict[str, dict[str, Any]] = {}
    for config_key, comp_def in base_components.items():
        tekla_name = comp_def.get("tekla_name")
        if tekla_name:
            components_by_tekla_name[tekla_name] = {
                "config_key": config_key,
                "number": comp_def.get("number", -1),
                "schema": comp_def.get("custom_properties", {}),
            }

    elements_data: list[dict[str, Any]] = []
    total_components = 0

    for selected_object in wrap_model_objects(selected_objects):
        # Only Part and CustomPart support GetComponents()
        if not isinstance(selected_object.model_object, (Part, CustomPart)):
            continue
        object_components: list[dict[str, Any]] = []
        comp_enum = selected_object.model_object.GetComponents()

        while comp_enum.MoveNext():
            comp = comp_enum.Current
            comp_name = comp.Name
            comp_number = comp.Number

            config_match = components_by_tekla_name.get(comp_name)
            if config_match:
                supported = True
                config_key = config_match["config_key"]
                schema = config_match["schema"]
            else:
                supported = False
                config_key = None
                schema = None

            attributes: dict[str, Any] = {}
            if schema:
                for attr_key, attr_def in schema.items():
                    attr_type = attr_def.get("type", "str")
                    default = TYPE_DEFAULTS.get(attr_type, str())
                    is_ok, attr_value = comp.GetAttribute(attr_key, default)
                    attributes[attr_key] = attr_value if is_ok else default

            object_components.append(
                {
                    "name": comp_name,
                    "number": comp_number,
                    "supported": supported,
                    "config_key": config_key,
                    "schema": schema,
                    "attributes": attributes,
                }
            )
            total_components += 1

        elements_data.append(
            {
                "guid": selected_object.guid,
                "components": object_components,
            }
        )

    logger.info("Found %s components across %s elements", total_components, len(elements_data))

    return ToolResult(
        structured_content={
            "status": "success",
            "total_elements": len(elements_data),
            "total_components": total_components,
            "elements": elements_data,
        }
    )


@components_provider.tool(tags={"components"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def modify_components(
    component_name: Annotated[str, Field(description="The Tekla name of the component (e.g. 'Lifting Anchor', 'MeshBars')")],
    custom_properties: Annotated[dict[str, Any], Field(description="Custom properties to update")],
) -> ToolResult:
    """
    Modifies attributes of existing components on selected elements.

    ## INSTRUCTIONS
    - First call `get_components` to see current component values
    - Then call this tool with only the properties the user wants to change
    - Use Tekla config keys (e.g. `RecessLength`, `RecessHeight`), NOT user-friendly descriptions
    - Only properties in `custom_properties` will be modified; all others remain unchanged
    """
    component = BaseComponent(name=component_name, custom_properties=custom_properties)

    result = _manage_components_on_selected_objects(_modify_single_component, component)
    return result
