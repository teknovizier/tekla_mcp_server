"""
Component tools for Tekla model operations.
"""

from collections.abc import Callable
from typing import Any

from tekla_mcp_server.tekla.component_handlers import HandlerRegistry
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import BaseComponent, ComponentType, get_base_components, TYPE_DEFAULTS
from tekla_mcp_server.tekla.loader import ModelObjectEnumerator
from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.tekla.model_object import wrap_model_objects
from tekla_mcp_server.tekla.utils import ensure_transformation_plane, get_wall_pairs, insert_component, insert_detail
from tekla_mcp_server.utils import log_function_call


@log_function_call
def manage_components_on_selected_objects(
    callback: Callable[..., int],
    component: BaseComponent,
    custom_properties_errors: list[str] | None = None,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Applies a component operation to selected objects in the Tekla model using a specified callback function.

    Args:
        callback: Callback function to apply to each object
        component: Component to apply
        custom_properties_errors: List to collect custom property errors
        *args: Additional positional arguments for callback
        **kwargs: Additional keyword arguments for callback
    """
    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    if component.component_type in [ComponentType.DETAIL, ComponentType.COMPONENT]:
        return process_detail_or_component(selected_objects, callback, tekla_model, component, custom_properties_errors, *args, **kwargs)
    elif component.component_type in [ComponentType.SEAM, ComponentType.CONNECTION]:
        return process_seam_or_connection(selected_objects, callback, tekla_model, component, custom_properties_errors, *args, **kwargs)
    logger.warning("Unsupported component type: %s", component.component_type)
    return {"status": "error", "message": f"Unsupported component type: {component.component_type}"}


@log_function_call
def process_detail_or_component(
    selected_objects: ModelObjectEnumerator,
    callback: Callable[..., int],
    model: TeklaModel,
    component: BaseComponent,
    custom_properties_errors: list[str] | None = None,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Processes a list of selected objects, applying a callback to each object that is an instance of Beam.
    Used for components that require only one primary object.

    Args:
        selected_objects: Enumerator of selected model objects
        callback: Callback function to apply to each object
        model: Tekla model instance
        component: Component to apply
        custom_properties_errors: List to collect custom property errors
        *args: Additional positional arguments for callback
        **kwargs: Additional keyword arguments for callback
    """
    from tekla_mcp_server.tekla.loader import Beam

    processed_elements = 0
    processed_components = 0
    for selected_object in selected_objects:
        if isinstance(selected_object, Beam):
            success = callback(model, component, selected_object, *args, **kwargs)
            if success:
                processed_components += success
            processed_elements += 1
    model.commit_changes()
    logger.info("Processed %s elements, %s components", processed_elements, processed_components)
    errors = custom_properties_errors or []
    status = "success" if processed_components else "error"
    if errors:
        status = "warning"
    return {
        "status": status,
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "processed_components": processed_components,
        "custom_properties_errors": errors,
    }


@log_function_call
def process_seam_or_connection(
    selected_objects: ModelObjectEnumerator,
    callback: Callable[..., int],
    model: TeklaModel,
    component: BaseComponent,
    custom_properties_errors: list[str] | None = None,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Processes seams or connections between selected objects in the model.
    This function is intended for use with components that require two objects, such as wall joints.
    It validates the number of selected objects, ensuring that exactly two are selected.

    Args:
        selected_objects: Enumerator of selected model objects
        callback: Callback function to apply to each object
        model: Tekla model instance
        component: Component to apply
        custom_properties_errors: List to collect custom property errors
        *args: Additional positional arguments for callback
        **kwargs: Additional keyword arguments for callback
    """
    from tekla_mcp_server.tools.selection import validate_exactly_two_selected

    validate_exactly_two_selected(selected_objects.GetSize())

    processed_elements = 0
    processed_components = 0

    wall_pairs = get_wall_pairs(selected_objects)
    for pair in wall_pairs:
        success = callback(model, component, pair[1], pair[0], *args, **kwargs)
        if success:
            processed_components += success
    model.commit_changes()
    logger.info("Processed %s elements, %s components", processed_elements, processed_components)
    errors = custom_properties_errors or []
    status = "success" if processed_components else "error"
    if errors:
        status = "warning"
    return {
        "status": status,
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "inserted_components": processed_components,
        "custom_properties_errors": errors,
    }


@ensure_transformation_plane
@log_function_call
def tool_put_components(model: TeklaModel, component: BaseComponent, selected_object: Any) -> int:
    """
    Inserts a component to the specified object in the Tekla model.
    Delegates specialized handling to registered handlers.

    Args:
        model: Tekla model instance
        component: Component to insert
        selected_object: Target object for the component
    """
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


@log_function_call
def tool_remove_components(model: TeklaModel, component: BaseComponent, *selected_objects: Any) -> int:
    """
    Removes components with the specified number and name from the specified object in the Tekla model.
    Delegates specialized cleanup to registered handlers.

    Args:
        model: Tekla model instance
        component: Component to remove
        *selected_objects: Objects to remove component from
    """
    if not selected_objects:
        raise ValueError("No elements selected. Please select at least one element.")

    handler = HandlerRegistry.get(component.name)

    counter = 0
    if handler and hasattr(handler, "pre_remove"):
        counter += handler.pre_remove(selected_objects)

    for comp in selected_objects[0].GetComponents():
        if comp.Number == component.number and comp.Name == component.name:
            if comp.Delete():
                counter += 1
    logger.info("Total components removed: %s", counter)
    return counter


@log_function_call
def tool_get_components() -> dict[str, Any]:
    """
    Gets all components attached to selected elements in the Tekla model.

    Returns component info including whether each component is supported by config,
    its schema (if supported), and actual attribute values from the component instance.

    Returns:
        Dictionary with status and component details per element
    """
    tekla_model = TeklaModel()
    selected_objects = tekla_model.get_selected_objects()
    base_components = get_base_components()

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

    return {
        "status": "success",
        "total_elements": len(elements_data),
        "total_components": total_components,
        "elements": elements_data,
    }


@ensure_transformation_plane
@log_function_call
def tool_modify_components(model: TeklaModel, component: BaseComponent, selected_object: Any) -> int:
    """
    Modifies attributes of existing components attached to a selected object.

    Args:
        model: Tekla model instance
        component: Component definition with name and properties to modify
        selected_object: Target Tekla object to find and modify components on

    Returns:
        Number of components modified
    """
    counter = 0

    comp_enum = selected_object.GetComponents()
    while comp_enum.MoveNext():
        comp = comp_enum.Current
        if comp.Name == component.name:
            if component.properties:
                for key, value in component.properties.items():
                    # Tekla API workaround: convert int to float to allow modifications
                    if isinstance(value, int):
                        value = float(value)
                    comp.SetAttribute(key, value)
            if comp.Modify():
                counter += 1

    logger.info("Modified %s '%s' components", counter, component.name)
    return counter
