"""
Module for utility functions used for geometry manipulations.
"""

from __future__ import annotations

import re
import shutil
from functools import wraps, lru_cache
from typing import Any, Literal
from collections.abc import Callable
from pathlib import Path


from tekla_mcp_server.config import get_tolerance, get_advanced_option_directories, get_config_dir
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import BaseComponent

from tekla_mcp_server.tekla.loader import (
    Point,
    Vector,
    ModelObject,
    ModelObjectEnumerator,
    ModelObjectSelector,
    Beam,
    TransformationPlane,
    ComponentInput,
    Component,
    Detail,
    Seam,
    PositionTypeEnum,
    AutoDirectionTypeEnum,
    DetailTypeEnum,
    ViewHandler,
    View,
    TeklaStructuresInfo,
    List,
    CatalogHandler,
    ProfileItem,
    MaterialItem,
    RebarItem,
    TeklaStructuresSettings,
    BooleanPart,
)

from tekla_mcp_server.utils import log_function_call


from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import TeklaModelObject, TeklaAssembly, TeklaPart, TeklaReinforcement, wrap_model_objects


def ensure_transformation_plane(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that sets the transformation plane before execution and restores it after.

    Args:
        func: The function to decorate

    Returns:
        Wrapped function that handles transformation plane context
    """

    @wraps(func)
    def wrapper(model: TeklaModel, component: Any, *args: Any, **kwargs: Any) -> Any:
        # Determine the number of objects in args
        selected_object = args[0]  # Supports only the first element

        current_plane = model.model.GetWorkPlaneHandler().GetCurrentTransformationPlane()
        local_plane = TransformationPlane(selected_object.GetCoordinateSystem())

        try:
            model.model.GetWorkPlaneHandler().SetCurrentTransformationPlane(local_plane)
            # Call the actual function
            result = func(model, component, *args, **kwargs)
        finally:
            # Reset transformation plane after execution
            model.model.GetWorkPlaneHandler().SetCurrentTransformationPlane(current_plane)

        return result

    return wrapper


def insert_detail(selected_object: ModelObject, component: BaseComponent, point: Point, reverse: bool = False) -> bool:
    """
    Inserts a custom detail component into a Tekla model at a specified point.

    Args:
        selected_object: The primary object to attach the detail to
        component: The component to insert
        point: The reference point for the detail
        reverse: If True, inserts detail in reverse direction (default False)

    Returns:
        True if insertion was successful, False otherwise
    """
    d = Detail()
    d.Name = component.name
    d.Number = component.number
    d.LoadAttributesFromFile(component.properties_set)
    d.UpVector = Vector(0, 0, 0)
    d.PositionType = PositionTypeEnum.MIDDLE_PLANE
    d.AutoDirectionType = AutoDirectionTypeEnum.AUTODIR_DETAIL
    d.DetailType = DetailTypeEnum.INTERMEDIATE_REVERSE if reverse else DetailTypeEnum.INTERMEDIATE
    d.SetPrimaryObject(selected_object)
    if component.properties:
        for key, value in component.properties.items():
            d.SetAttribute(key, value)
    d.SetReferencePoint(point)

    return d.Insert()


def insert_seam(primary_object: ModelObject, secondary_object: ModelObject, component: BaseComponent, point1: Point, point2: Point) -> bool:
    """
    Inserts a custom seam component into a Tekla model.

    Args:
        primary_object: The primary object for the seam
        secondary_object: The secondary object for the seam
        component: The component to insert
        point1: First input position
        point2: Second input position

    Returns:
        True if insertion was successful, False otherwise
    """
    s = Seam()
    s.Name = component.name
    s.Number = component.number
    s.LoadAttributesFromFile(component.properties_set)
    s.UpVector = Vector(0, 0, 0)
    s.AutoDirectionType = AutoDirectionTypeEnum.AUTODIR_DETAIL
    s.AutoPosition = True

    s.SetPrimaryObject(primary_object)
    s.SetSecondaryObject(secondary_object)
    if component.properties:
        for key, value in component.properties.items():
            s.SetAttribute(key, value)
    s.SetInputPositions(point1, point2)

    return s.Insert()


def insert_component(selected_object: ModelObject, component: BaseComponent) -> bool:
    """
    Inserts a component into a Tekla model to the specified object.

    Args:
        selected_object: The object to attach the component to
        component: The component to insert

    Returns:
        True if insertion was successful, False otherwise
    """
    c = Component()
    c.Name = component.name
    c.Number = component.number
    c.LoadAttributesFromFile(component.properties_set)
    if component.properties:
        for key, value in component.properties.items():
            c.SetAttribute(key, value)
    ci = ComponentInput()
    ci.AddInputObject(selected_object)
    c.SetComponentInput(ci)
    return c.Insert()


@log_function_call
def get_wall_pairs(selected_objects: ModelObjectEnumerator) -> list[tuple[ModelObject, ModelObject]]:
    """
    Identifies and pairs walls based on their (X, Y) coordinates and Z-levels within a specified tolerance.

    The function filters out non-wall objects, validates that there are exactly two floors,
    sorts the walls based on (X, Y, Z) coordinates, and pairs walls into (bottom_wall, top_wall)
    if their X and Y coordinates match within precision.

    Args:
        selected_objects: Enumerator of selected model objects (Beams expected)

    Returns:
        List of tuples containing (bottom_wall, top_wall) pairs

    Raises:
        ValueError: If fewer than two elements are selected
        ValueError: If more than two floors are detected
    """

    def is_within_tolerance(value1: float, value2: float, tolerance: float | None = None) -> bool:
        """
        Check if two values are within the defined tolerance range.

        Args:
            value1: First value to compare
            value2: Second value to compare
            tolerance: Maximum allowed difference

        Returns:
            True if absolute difference <= tolerance, False otherwise
        """
        if tolerance is None:
            tolerance = get_tolerance("wall_pairing", 50.0)
        return abs(value1 - value2) <= tolerance

    selected_walls = []
    for selected_object in selected_objects:
        if isinstance(selected_object, Beam):
            selected_walls.append(selected_object)

    if len(selected_walls) < 2:
        raise ValueError("Less than two elements selected. Please select two elements.")

    # Step 1. Validate number of floors
    floor_set: set[float] = set()
    for wall in selected_walls:
        if round(wall.StartPoint.Z, 2) != round(wall.EndPoint.Z, 2):
            raise ValueError(f"Z-coordinate mismatch for the start point and end point in the wall {wall.Name}.")

        # Check if this Z-value is close to an existing one
        close_match_found = False
        for existing_z in floor_set:
            if is_within_tolerance(existing_z, wall.StartPoint.Z):
                # No need to check further
                close_match_found = True
                break

        # Add Z only if no close match is found
        if not close_match_found:
            floor_set.add(wall.StartPoint.Z)

    if len(floor_set) > 2:
        raise ValueError("More than two floors detected.")

    # Step 2. Sort walls by (X, Y) and Z-coordinates
    selected_walls.sort(key=lambda w: (w.StartPoint.X, w.StartPoint.Y, w.StartPoint.Z))

    # Step 3. Pair bottom_wall with top_wall
    wall_pairs: Any = []
    wall_dict: Any = {}

    for wall in selected_walls:
        xy_key = ((round(wall.StartPoint.X, 2), round(wall.StartPoint.Y, 2)), (round(wall.EndPoint.X, 2), round(wall.EndPoint.Y, 2)))

        # Find a matching wall within allowed tolerance
        matched_key = None
        for key in wall_dict:
            if (
                is_within_tolerance(xy_key[0][0], key[0][0])
                and is_within_tolerance(xy_key[0][1], key[0][1])
                and is_within_tolerance(xy_key[1][0], key[1][0])
                and is_within_tolerance(xy_key[1][1], key[1][1])
            ):
                matched_key = key
                break

        if matched_key:
            bottom_wall = wall_dict[matched_key]
            top_wall = wall

            # Only pair walls on different floors. Two walls with matching footprints
            # at the same Z level are co-planar, not a vertical bottom/top stack, and a
            # seam between them would be meaningless geometry
            if bottom_wall != top_wall and not is_within_tolerance(bottom_wall.StartPoint.Z, top_wall.StartPoint.Z):
                # List of tuples as output
                wall_pairs.append((bottom_wall, top_wall))
                del wall_dict[matched_key]  # Remove matched pair from storage
        else:
            wall_dict[xy_key] = wall  # Store as potential bottom wall

    logger.debug("Wall pairs identified: %s", wall_pairs)
    return wall_pairs


def get_tekla_major_version() -> int:
    """
    Get the Tekla Structures major version from the current program version.

    Returns:
        Major version number (e.g. 2022, 2024).
        Defaults to 2022 if parsing fails.
    """
    version = TeklaStructuresInfo.GetCurrentProgramVersion()
    match = re.match(r"(\d{4})", version)
    if match:
        return int(match.group(1))
    return 2022


def get_active_views() -> list[View]:
    """
    Get the currently active views in the model.

    Uses ViewHandler.GetActiveView() for Tekla 2024+,
    falls back to ViewHandler.GetVisibleViews() for earlier versions.

    Returns:
        List of View objects that are currently active/visible
    """
    views: list[View] = []

    if get_tekla_major_version() >= 2024:
        active_view = ViewHandler.GetActiveView()
        if active_view is not None:
            views.append(active_view)
    else:
        view_enum = ViewHandler.GetVisibleViews()
        while view_enum.MoveNext():
            views.append(view_enum.Current)

    return views


def collect_children(selected_objects: ModelObjectEnumerator) -> List[ModelObject]:
    """
    Collect child objects from selected parts/assemblies into a Tekla List.

    Args:
        selected_objects: Enumerator of selected objects

    Returns:
        List of ModelObjects containing all children from assemblies and parts
    """
    children: list[ModelObject] = []
    for obj in wrap_model_objects(selected_objects):
        if isinstance(obj, TeklaAssembly):
            children.extend(obj.get_all_children())
        elif isinstance(obj, TeklaPart):
            children.extend(obj.get_all_children(include_all=False))
        elif isinstance(obj, TeklaReinforcement):
            children.extend([obj.model_object])

    tekla_list = List[ModelObject]()
    for child in children:
        tekla_list.Add(child)
    return tekla_list


def get_candidates_in_bounding_box(element: TeklaModelObject, tolerance: float) -> list[TeklaModelObject]:
    """
    Find objects within element's bounding box.

    Args:
        element: The element to get bounding box from.
        tolerance: Extra distance to expand the bounding box in all directions.

    Returns:
        List of model objects found within the expanded bounding box.
    """
    aabb = element.bounding_box
    if not aabb:
        return []

    # Expand box by tolerance to catch objects near boundaries
    min_point = Point(aabb.min_x - tolerance, aabb.min_y - tolerance, aabb.min_z - tolerance)
    max_point = Point(aabb.max_x + tolerance, aabb.max_y + tolerance, aabb.max_z + tolerance)
    selector = ModelObjectSelector()
    candidates = list(wrap_model_objects(selector.GetObjectsByBoundingBox(min_point, max_point)))
    logger.debug("Bounding box search for %s: found %d candidates", element.guid, len(candidates))
    return candidates


def iterate_boolean_parts(model_object: ModelObject) -> list[ModelObject]:
    """
    Iterate over boolean parts attached to a model object.

    Args:
        model_object: The Tekla model object to get booleans from

    Returns:
        List of BooleanPart objects attached to the model object
    """
    boolean_parts: list[ModelObject] = []
    boolean_enum = model_object.GetBooleans()
    while boolean_enum.MoveNext():
        if isinstance(boolean_enum.Current, BooleanPart):
            boolean_parts.append(boolean_enum.Current)
    return boolean_parts


def get_all_profiles() -> list[dict[str, str]]:
    """
    Get all profiles from the Tekla catalog. Lazy loaded on first access.

    The connection check stays outside the cache so a disconnected catalog returns []
    without caching it - a cached empty list would otherwise stick for the whole
    session, even after Tekla reconnects.

    Returns:
        List of profile dicts with 'name', 'type' and 'sub_type' keys, or an empty
        list when the catalog is unavailable.
    """
    if not CatalogHandler().GetConnectionStatus():
        return []
    return _read_all_profiles()


@lru_cache
def _read_all_profiles() -> list[dict[str, str]]:
    """Read every profile from the catalog. Cached, assumes the catalog is connected."""
    catalog = CatalogHandler()
    profiles = catalog.GetLibraryProfileItems()
    result = []
    while profiles.MoveNext():
        prof = profiles.Current
        if isinstance(prof, ProfileItem):
            prof_type = getattr(prof, "ProfileItemType", None)
            prof_subtype = getattr(prof, "ProfileItemSubType", None)
            result.append(
                {
                    "name": prof.ProfileName,
                    "type": prof_type.ToString() if prof_type else "UNKNOWN",
                    "sub_type": prof_subtype.ToString() if prof_subtype else "UNKNOWN",
                }
            )
    return result


def get_all_materials() -> list[dict[str, str]]:
    """
    Get all materials from the Tekla catalog. Lazy loaded on first access.

    The connection check stays outside the cache (see `get_all_profiles`) so a
    disconnected catalog is not cached as an empty list.

    Returns:
        List of material dicts with 'name' and 'type' keys, or an empty list when the
        catalog is unavailable.
    """
    if not CatalogHandler().GetConnectionStatus():
        return []
    return _read_all_materials()


@lru_cache
def _read_all_materials() -> list[dict[str, str]]:
    """Read every material from the catalog. Cached, assumes the catalog is connected."""
    catalog = CatalogHandler()
    materials = catalog.GetMaterialItems()
    result = []
    while materials.MoveNext():
        mat = materials.Current
        if isinstance(mat, MaterialItem):
            mat_type = getattr(mat, "Type", None)
            result.append(
                {
                    "name": mat.MaterialName,
                    "type": mat_type.ToString() if mat_type else "UNKNOWN",
                }
            )
    return result


def get_all_rebar_items() -> list[dict[str, str]]:
    """
    Get all available rebar items from the Tekla catalog. Lazy loaded on first access.

    The connection check stays outside the cache (see `get_all_profiles`) so a
    disconnected catalog is not cached as an empty list.

    Returns:
        List of rebar dicts with 'grade' and 'size' keys, or an empty list when the
        catalog is unavailable.
    """
    if not CatalogHandler().GetConnectionStatus():
        return []
    return _read_all_rebar_items()


@lru_cache
def _read_all_rebar_items() -> list[dict[str, str]]:
    """Read every rebar item from the catalog. Cached, assumes the catalog is connected."""
    catalog = CatalogHandler()
    rebars = catalog.GetRebarItems()
    result = []
    while rebars.MoveNext():
        item = rebars.Current
        if isinstance(item, RebarItem):
            result.append(
                {
                    "grade": item.Grade,
                    "size": item.Size,
                }
            )

    return result


@lru_cache
def get_macros() -> list[str]:
    """
    Get the available Tekla macro file names from XS_MACRO_DIRECTORY.

    Modeling macros are returned as plain filenames (e.g. ``'MyMacro.cs'``).
    Drawing macros found in the `drawings` subdirectory are
    prefixed with ``drawings\\`` (e.g. ``..\\drawings\\MyDrawingMacro.cs``).

    Returns:
        Sorted list of macro file names with path prefixes where needed.
    """

    directories = get_advanced_option_directories("XS_MACRO_DIRECTORY")
    logger.debug("Searching for macros in XS_MACRO_DIRECTORY: %s", directories)

    macro_names: list[str] = []
    seen: set[str] = set()
    for directory in directories:
        mac_dir = Path(directory)
        for subdir, prefix in (("modeling", ""), ("drawings", "..\\drawings\\")):
            scan_dir = mac_dir / subdir
            if scan_dir.is_dir():
                for file in scan_dir.glob("*.cs"):
                    key = f"{prefix}{file.name}"
                    if key not in seen:
                        macro_names.append(key)
                        seen.add(key)

    return sorted(macro_names)


def ensure_macro_installed(macro_name: str, category: Literal["modeling", "drawings"]) -> bool:
    """
    Ensure a macro is present in XS_MACRO_DIRECTORY, installing it if needed.

    The macro source is read from `config/macros/{category}/{macro_name}` and copied to
    the first directory in XS_MACRO_DIRECTORY, overwriting any existing copy so that
    server updates to the macro reach users automatically.

    Args:
        macro_name: Macro file name, e.g. 'TeklaMCPArrangeMarks.cs'.
        category: Macro subfolder, either 'modeling' or 'drawings'.

    Returns:
        True if the macro was newly installed (no previous copy existed at the
        destination). A macro that was just installed cannot be run until Tekla
        is restarted.

    Raises:
        FileNotFoundError: If the macro source or XS_MACRO_DIRECTORY is unavailable.
        OSError: If the macro file cannot be copied.
    """
    source = get_config_dir() / "macros" / category / macro_name
    if not source.exists():
        raise FileNotFoundError(f"Bundled macro not found: {source}")

    directories = get_advanced_option_directories("XS_MACRO_DIRECTORY")
    if not directories:
        raise FileNotFoundError("XS_MACRO_DIRECTORY is not configured or has no valid directories.")

    destination = Path(directories[0]) / category / macro_name
    macro_just_installed = not destination.exists()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        logger.info("Installed macro '%s' to '%s'", macro_name, destination)
    except Exception as e:
        logger.error("Failed to copy macro '%s' to '%s': %s", macro_name, destination, e)
        raise

    return macro_just_installed


@lru_cache
def get_report_templates() -> list[str]:
    """
    Get the available Tekla report template names from .rpt files.

    Searches in:
    - XS_TEMPLATE_DIRECTORY
    - XS_SYSTEM

    Returns:
        Sorted list of report template names (file stems, without the '.rpt' extension).
    """
    # Build a fresh list - the helper returns lru_cache'd lists that must not be mutated.
    search_dirs = [*get_advanced_option_directories("XS_TEMPLATE_DIRECTORY"), *get_advanced_option_directories("XS_SYSTEM")]
    logger.debug("Searching for report templates in XS_TEMPLATE_DIRECTORY and XS_SYSTEM: %s", search_dirs)

    template_names: set[str] = set()
    for directory in search_dirs:
        for file in Path(directory).rglob("*.rpt"):
            template_names.add(file.stem)

    return sorted(template_names)


@lru_cache
def get_filters(file_extension: str) -> list[str]:
    """
    Get the available Tekla filter names for files with the given extension.

    Searches in:
    - XS_FIRM
    - XS_PROJECT
    - ModelPath/attributes directory

    Args:
        file_extension: File extension to search for (e.g. '.SObjGrp', '.VObjGrp')

    Returns:
        Sorted list of filter names without the extension, always including 'standard'.
    """

    if not file_extension.startswith("."):
        file_extension = f".{file_extension}"

    paths: list[Path] = []

    for option_name in ("XS_FIRM", "XS_PROJECT"):
        _, option = TeklaStructuresSettings.GetAdvancedOption(option_name, str())
        if not option:
            continue
        for path_str in option.split(";"):
            path = Path(path_str.strip())
            if path.is_dir():
                paths.append(path.resolve())

    try:
        model = TeklaModel()
        model_path = model.model_path
        if model_path:
            attributes_dir = Path(model_path) / "attributes"
            if attributes_dir.is_dir():
                paths.append(attributes_dir.resolve())
    except Exception:
        pass

    filter_names: set[str] = {"standard"}
    for dir_path in paths:
        for file in dir_path.rglob(f"*{file_extension}"):
            filter_names.add(file.stem)

    return sorted(filter_names)
