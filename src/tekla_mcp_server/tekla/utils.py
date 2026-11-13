"""
Module for utility functions used for geometry manipulations.
"""

from __future__ import annotations

import filecmp
import re
import shutil
import time
from contextlib import contextmanager
from functools import wraps, lru_cache
from typing import Any, Literal
from collections.abc import Callable, Iterator
from pathlib import Path


from tekla_mcp_server.config import get_tolerance, get_advanced_option_directories, get_config_dir
from tekla_mcp_server.init import logger
from tekla_mcp_server.models import BaseComponent
from tekla_mcp_server.geometry import FloatArray, OrientedBox, smaller_box

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
    BoltItem,
    CatalogHandler,
    ProfileItem,
    MaterialItem,
    RebarItem,
    TeklaStructuresSettings,
    BooleanPart,
    Operation,
    Part,
)

from tekla_mcp_server.utils import log_function_call


from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import TeklaModelObject, TeklaAssembly, TeklaPart, TeklaReinforcement, wrap_model_object, wrap_model_objects


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
        """
        Run `func` in the first object's local plane.

        Args:
            model: Tekla model wrapper
            component: Component to pass through
            args: Target objects and extra args
            kwargs: Extra keyword args

        Returns:
            Result of `func`
        """
        # Determine the number of objects in args
        selected_object = args[0]  # Supports only the first element

        work_plane_handler = model.model.GetWorkPlaneHandler()
        current_plane = work_plane_handler.GetCurrentTransformationPlane()
        local_plane = TransformationPlane(selected_object.GetCoordinateSystem())

        try:
            work_plane_handler.SetCurrentTransformationPlane(local_plane)
            # Call the actual function
            result = func(model, component, *args, **kwargs)
        finally:
            # Reset transformation plane after execution
            work_plane_handler.SetCurrentTransformationPlane(current_plane)

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


def expand_to_parts(objects: list[TeklaModelObject], include_embeds: bool = True) -> tuple[list[TeklaPart], list[dict[str, str]]]:
    """
    Resolve wrapped objects to parts, replacing each assembly with all its parts.

    Directly given parts are always kept, `include_embeds` only filters parts reached through an assembly.
    Reinforcement and other non-part objects are dropped and reported back.
    A part reached twice (given directly and through its assembly) is returned once.

    Args:
        objects: Wrapped model objects, e.g. the current selection
        include_embeds: If False, embedded details inside assemblies are left out

    Returns:
        Unique parts in input order, and the dropped objects as `{"guid", "type"}` dicts
    """
    parts: dict[str, TeklaPart] = {}
    skipped: list[dict[str, str]] = []
    for obj in objects:
        if isinstance(obj, TeklaAssembly):
            candidates = obj.get_all_parts(include_embeds)
        elif isinstance(obj, TeklaPart):
            candidates = [obj]
        else:
            skipped.append({"guid": obj.guid, "type": type(obj).__name__})
            continue
        for part in candidates:
            parts.setdefault(part.guid, part)
    if skipped:
        logger.warning("expand_to_parts: skipped %d non-part objects: %s", len(skipped), [s["type"] for s in skipped])
    return list(parts.values()), skipped


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


def get_parts_in_extent(min_point: FloatArray, max_point: FloatArray, max_objects: int) -> list[TeklaPart]:
    """
    Find parts whose extent intersects an axis-aligned box in the current work plane.

    The search also returns rebars, cuts and welds. Loading every instance costs about
    ten times more than the search itself, so only the parts are loaded, and only when
    the search found no more than `max_objects` objects.

    Args:
        min_point: Box minimum corner
        max_point: Box maximum corner
        max_objects: Most objects of any type the search may return

    Returns:
        Wrapped parts

    Raises:
        ValueError: If the search found more than `max_objects` objects.
    """
    enumerator = ModelObjectSelector().GetObjectsByBoundingBox(Point(*min_point), Point(*max_point))
    if enumerator.GetSize() > max_objects:
        raise ValueError(f"Search area holds {enumerator.GetSize()} objects, more than the {max_objects} one search may load. Use a smaller `radius_mm` or a smaller source.")
    enumerator.SelectInstances = False
    parts: list[TeklaPart] = []
    while enumerator.MoveNext():
        obj = enumerator.Current
        if isinstance(obj, Part) and obj.Select():
            wrapped = wrap_model_object(obj)
            if isinstance(wrapped, TeklaPart):
                parts.append(wrapped)
    return parts


@contextmanager
def global_work_plane(model: TeklaModel) -> Iterator[Any]:
    """
    Run a block in the global work plane and restore the previous plane afterwards.

    Args:
        model: Tekla model wrapper

    Yields:
        The work plane handler, for temporary switches inside the block
    """
    handler = model.model.GetWorkPlaneHandler()
    saved_plane = handler.GetCurrentTransformationPlane()
    try:
        handler.SetCurrentTransformationPlane(TransformationPlane())
        yield handler
    finally:
        handler.SetCurrentTransformationPlane(saved_plane)


def get_oriented_box(part: TeklaPart, work_plane_handler: Any) -> OrientedBox | None:
    """
    Build the box of a part: the smaller of its extent in its own coordinate system and its global extent.

    Both boxes enclose the part. The own-axis box is tight for straight members at any
    angle, but a bent PolyBeam's coordinate system follows only its first segment, so
    its own-axis box can be metres too large. The global box is then the tighter one.

    Must run in the global work plane (`global_work_plane`). The part's plane is set
    only to read the solid and the global plane is set again before returning.

    Args:
        part: Part to measure
        work_plane_handler: Handler from `global_work_plane`

    Returns:
        The box in global coordinates, or None when the part has no solid
    """
    cs = part.model_object.GetCoordinateSystem()
    try:
        work_plane_handler.SetCurrentTransformationPlane(TransformationPlane(cs))
        solid = part.get_solid()
        if solid is None:
            return None
        mn, mx = solid.MinimumPoint, solid.MaximumPoint
    finally:
        work_plane_handler.SetCurrentTransformationPlane(TransformationPlane())
    own_box = OrientedBox.from_local_extent(
        (cs.Origin.X, cs.Origin.Y, cs.Origin.Z),
        (cs.AxisX.X, cs.AxisX.Y, cs.AxisX.Z),
        (cs.AxisY.X, cs.AxisY.Y, cs.AxisY.Z),
        (mn.X, mn.Y, mn.Z),
        (mx.X, mx.Y, mx.Z),
    )
    global_solid = part.get_solid()
    gmn, gmx = global_solid.MinimumPoint, global_solid.MaximumPoint
    global_box = OrientedBox.from_local_extent((0, 0, 0), (1, 0, 0), (0, 1, 0), (gmn.X, gmn.Y, gmn.Z), (gmx.X, gmx.Y, gmx.Z))
    return smaller_box(own_box, global_box)


def iterate_boolean_parts(model_object: ModelObject, types: tuple[type, ...] = (BooleanPart,)) -> list[ModelObject]:
    """
    Iterate over boolean parts attached to a model object.

    Args:
        model_object: The Tekla model object to get booleans from
        types: Boolean classes to keep, e.g. `(BooleanPart, Fitting, CutPlane, EdgeChamfer)`

    Returns:
        List of the booleans attached to the model object that match `types`
    """
    boolean_parts: list[ModelObject] = []
    boolean_enum = model_object.GetBooleans()
    while boolean_enum.MoveNext():
        boolean_part = boolean_enum.Current
        if isinstance(boolean_part, types):
            boolean_parts.append(boolean_part)
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
    """
    Read every profile from the catalog. Cached, assumes the catalog is connected.

    Returns:
        Profile dicts with 'name', 'type' and 'sub_type'
    """
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
    """
    Read every material from the catalog. Cached, assumes the catalog is connected.

    Returns:
        Material dicts with 'name' and 'type'
    """
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
    """
    Read every rebar item from the catalog. Cached, assumes the catalog is connected.

    Returns:
        Rebar dicts with 'grade' and 'size'
    """
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


def get_all_bolt_items() -> list[dict[str, Any]]:
    """
    Get all bolt standard/size combinations from the Tekla bolt catalog.

    The connection check stays outside the cache (see `get_all_profiles`) so a
    disconnected catalog is not cached as an empty list.

    Returns:
        List of bolt dicts with 'standard' and 'size' keys, or an empty list when the
        catalog is unavailable.
    """
    if not CatalogHandler().GetConnectionStatus():
        return []
    return _read_all_bolt_items()


@lru_cache
def _read_all_bolt_items() -> list[dict[str, Any]]:
    """
    Read every bolt item from the catalog. Cached, assumes the catalog is connected.

    Returns:
        Bolt dicts with 'standard' and 'size'
    """
    catalog = CatalogHandler()
    bolts = catalog.GetBoltItems()
    result = []
    while bolts.MoveNext():
        item = bolts.Current
        if isinstance(item, BoltItem):
            result.append({"standard": item.Standard, "size": item.Size})
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


def wait_for_macro(macro_name: str, poll_interval: float = 1.0) -> None:
    """
    Block until Tekla reports that no macro is running.

    `Operation.RunMacro` only starts the macro and returns, so a caller that relies on
    the macro's effect must wait before touching the selection or checking the model.

    Args:
        macro_name: Macro file name, used in the log message
        poll_interval: Seconds between `IsMacroRunning()` checks
    """
    while Operation.IsMacroRunning():
        time.sleep(poll_interval)
    logger.debug("Macro '%s' finished", macro_name)


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
        True if the macro was newly installed or its content changed (no previous
        copy existed at the destination, or the existing copy is outdated). Tekla
        only registers macro content at startup, so such a macro cannot be run
        until Tekla is restarted.

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
    macro_just_installed = not destination.exists() or not filecmp.cmp(source, destination, shallow=False)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        logger.info("Installed macro '%s' to '%s'", macro_name, destination)
    except Exception as e:
        logger.error("Failed to copy macro '%s' to '%s': %s", macro_name, destination, e)
        raise

    return macro_just_installed


def ensure_export_settings_installed(setting_name: str) -> None:
    """
    Ensure a DXF export setting is present in the model's attributes folder.

    The setting source is read from `config/attributes/{setting_name}` and copied
    to `{model_path}/attributes/{setting_name}`, overwriting any existing copy so
    that server updates reach users automatically.

    Args:
        setting_name: Export setting file name, e.g. 'TEKLA_MCP_COLLISION_LAYERS.dwgsetting'.

    Raises:
        FileNotFoundError: If the setting source or model path is unavailable.
        OSError: If the setting file cannot be copied.
    """
    source = get_config_dir() / "attributes" / setting_name
    if not source.exists():
        raise FileNotFoundError(f"Bundled export setting not found: {source}")

    model = TeklaModel()
    model_path = model.model_path
    if not model_path:
        raise FileNotFoundError("Cannot resolve model path.")

    destination = Path(model_path) / "attributes" / setting_name
    if not destination.exists() or not filecmp.cmp(source, destination, shallow=False):
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            logger.info("Installed export setting '%s' to '%s'", setting_name, destination)
        except Exception as e:
            logger.error("Failed to copy export setting '%s' to '%s': %s", setting_name, destination, e)
            raise


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


def get_available_attribute_files(file_extension: str) -> list[str]:
    """
    Get available Tekla attribute file names for the given extension.

    Searches in XS_FIRM, XS_PROJECT, and the model's attributes directory.

    Args:
        file_extension: File extension to search for (e.g. '.SObjGrp', '.VObjGrp', '.dwgsetting').

    Returns:
        Sorted list of file stems with the given extension.
    """

    if not file_extension.startswith("."):
        file_extension = f".{file_extension}"

    # The model's own attributes folder is one search location among several, so a
    # failure here must not kill the whole lookup. It must still be visible though -
    # silently returning a short list looks like "no such setting exists" to the caller.
    model_path = ""
    try:
        model_path = TeklaModel().model_path
    except Exception as e:
        logger.warning("Could not read the model's attributes folder while listing '%s' files, results are incomplete: %s", file_extension, e)
    return list(_attribute_files(file_extension, model_path))


@lru_cache
def _attribute_files(file_extension: str, model_path: str) -> tuple[str, ...]:
    """
    Scan the attribute folders for files with the given extension.

    Args:
        file_extension: File extension including the dot
        model_path: Model folder, empty when unknown. Part of the cache key

    Returns:
        Sorted file stems
    """
    paths: list[Path] = []

    for option_name in ("XS_FIRM", "XS_PROJECT"):
        _, option = TeklaStructuresSettings.GetAdvancedOption(option_name, str())
        if not option:
            continue
        for path_str in option.split(";"):
            path = Path(path_str.strip())
            if path.is_dir():
                paths.append(path.resolve())

    if model_path:
        attributes_dir = Path(model_path) / "attributes"
        if attributes_dir.is_dir():
            paths.append(attributes_dir.resolve())

    names: set[str] = set()
    for dir_path in paths:
        for file in dir_path.rglob(f"*{file_extension}"):
            names.add(file.stem)

    return tuple(sorted(names))


def require_selection_filter(filter_name: str) -> None:
    """
    Check that a saved Tekla selection filter with this name exists.

    Args:
        filter_name: Selection filter name

    Raises:
        ValueError: If no such filter is available.
    """
    available = get_available_attribute_files(".SObjGrp") + ["standard"]
    if filter_name not in available:
        # The list is cached, so a filter saved after it was read needs one fresh scan
        _attribute_files.cache_clear()
        available = get_available_attribute_files(".SObjGrp") + ["standard"]
    if filter_name not in available:
        raise ValueError(f"Filter '{filter_name}' not found. Available filters: {available}")
