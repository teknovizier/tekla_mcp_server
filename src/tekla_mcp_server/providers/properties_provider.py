"""
Properties tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from collections import Counter
from typing import Any, Annotated

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.config import get_tolerance
from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import TeklaAssembly, TeklaBeam, TeklaContourPlate, TeklaModelObject, TeklaPart, TeklaReferenceModelObject, wrap_model_object, wrap_model_objects
from tekla_mcp_server.tekla.loader import Part, BooleanPart, Operation
from tekla_mcp_server.tekla.template_attrs_parser import TemplateAttributeParser
from tekla_mcp_server.tekla.utils import iterate_boolean_parts

properties_provider = LocalProvider()


def _validate_at_least_two_selected(count: int) -> None:
    if count == 0:
        raise ValueError("No elements selected. Please select at least two elements.")
    if count == 1:
        raise ValueError("Only one element selected. Please select at least two elements.")


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def set_elements_properties(
    name: Annotated[str | None, Field(description="Part name")] = None,
    profile: Annotated[str | None, Field(description="Profile string (e.g., '3000*200', 'HEA200')")] = None,
    material: Annotated[str | None, Field(description="Material string (e.g., 'C25/30', 'S355J2')")] = None,
    tekla_class: Annotated[int | None, Field(description="Tekla class (e.g., 1, 100 etc.)")] = None,
    finish: Annotated[str | None, Field(description="Finish type")] = None,
    part_prefix: Annotated[str | None, Field(description="Part numbering prefix")] = None,
    part_start_number: Annotated[int | None, Field(description="Part start number")] = None,
    assembly_prefix: Annotated[str | None, Field(description="Assembly numbering prefix")] = None,
    assembly_start_number: Annotated[int | None, Field(description="Assembly start number")] = None,
    phase: Annotated[int | None, Field(description="Phase number (1, 2, 3, etc.)")] = None,
    user_properties: Annotated[dict[str, Any] | None, Field(description="Dictionary of user-defined attribute names and values")] = None,
) -> ToolResult:
    """
    Sets properties and user-defined attributes (UDAs) on selected Tekla elements (assemblies or parts).

    Assemblies do not have `profile`, `material`, `finish`, `tekla_class`, `part_prefix`, `part_start_number`.
    These properties will only affect parts, not assemblies.
    """
    selected_objects = TeklaModel().get_selected_objects()

    total_changes: dict[str, int] = {
        "name": 0,
        "profile": 0,
        "material": 0,
        "tekla_class": 0,
        "finish": 0,
        "part_prefix": 0,
        "part_start_number": 0,
        "assembly_prefix": 0,
        "assembly_start_number": 0,
        "phase": 0,
        "udas": 0,
    }
    processed_elements = 0
    modified_elements = 0
    property_errors: list[dict] = []

    for selected_object in wrap_model_objects(selected_objects):
        try:
            if isinstance(selected_object, TeklaAssembly):
                changes = selected_object.set_properties(
                    name=name,
                    assembly_prefix=assembly_prefix,
                    assembly_start_number=assembly_start_number,
                    phase=phase,
                    user_properties=user_properties,
                )
            elif isinstance(selected_object, TeklaPart):
                changes = selected_object.set_properties(
                    name=name,
                    profile=profile,
                    material=material,
                    tekla_class=tekla_class,
                    finish=finish,
                    part_prefix=part_prefix,
                    part_start_number=part_start_number,
                    assembly_prefix=assembly_prefix,
                    assembly_start_number=assembly_start_number,
                    phase=phase,
                    user_properties=user_properties,
                )
            else:
                logger.error("set_elements_properties: Unsupported object type: %s", type(selected_object).__name__)
                continue

            elem_errors: list[dict] = changes.pop("errors", [])
            for key, value in changes.items():
                if key in total_changes:
                    total_changes[key] += value
            if any(v > 0 for v in changes.values()):
                modified_elements += 1
            if elem_errors:
                logger.warning("Property errors on %s: %s", selected_object.guid, elem_errors)
                property_errors.append({"guid": selected_object.guid, "errors": elem_errors})
        except Exception:
            logger.exception("Failed to set properties on %s", selected_object.guid)
        processed_elements += 1

    commit_success: bool | None = None
    if modified_elements > 0:
        commit_success = TeklaModel().commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after modifying %s elements", modified_elements)

    if commit_success is False:
        status = "error"
        message = "Changes were not persisted. Commit failed (possible constraint violation or locked objects)."
    elif modified_elements > 0 and property_errors:
        status = "partial"
        message = f"Modified {modified_elements} elements with some errors"
    elif modified_elements > 0:
        status = "success"
        message = f"Successfully modified {modified_elements} elements"
    else:
        status = "warning"
        message = "No elements were modified"

    logger.info("Set properties result: %s — %s", status, message)
    result: dict = {
        "status": status,
        "message": message,
        "selected_elements": selected_objects.GetSize(),
        "processed_elements": processed_elements,
        "modified_elements": modified_elements,
        "changes_applied": total_changes,
        "property_errors": property_errors,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_elements_properties(
    report_props_definitions: Annotated[list[str] | None, Field(description="Additional report property names")] = None,
    snapshot_mode: Annotated[bool, Field(description="Return full element snapshots")] = False,
) -> ToolResult:
    """
    Retrieve properties for selected Tekla elements (assemblies, parts, or IFC reference objects).

    ## MODES

    ### Default mode (`snapshot_mode=False`)
    Returns a flat table of key element properties. Optionally request extra columns via `report_props_definitions`.
    - Extract properties not in default columns; split multi-property phrases into separate items.
    - Example: ["gross weight", "assembly top and bottom level", "length"] → ["gross weight", "assembly top level", "assembly bottom level", "length"]
    - Return the result table in Markdown format EXACTLY as provided. DO NOT reformat, truncate, or modify anything. ALWAYS show the full table.

    ### Snapshot mode (`snapshot_mode=True`)
    Returns full element snapshots for convention and QA checks, including basic element properties, UDAs, cutparts, welds and reinforcement.
    """
    selected_objects = TeklaModel().get_selected_objects()

    processed_elements = 0

    # Snapshot mode
    if snapshot_mode:
        parts: list[dict[str, Any]] = []
        assemblies: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for obj in wrap_model_objects(selected_objects):
            try:
                if isinstance(obj, TeklaPart):
                    parts.append(obj.to_snapshot().model_dump())
                elif isinstance(obj, TeklaAssembly):
                    assemblies.append(obj.to_snapshot().model_dump())
                processed_elements += 1
            except Exception as e:
                logger.exception("Failed to build snapshot for %s: %s", obj.guid, str(e))
                errors.append({"guid": obj.guid, "error": str(e)})

        total = len(parts) + len(assemblies)
        logger.info("Snapshot mode: built snapshots for %d parts and %d assemblies", len(parts), len(assemblies))
        return ToolResult(
            structured_content={
                "status": "success" if total > 0 else "warning",
                "selected_elements": selected_objects.GetSize(),
                "processed_elements": processed_elements,
                "parts": parts,
                "assemblies": assemblies,
                "errors": errors,
            }
        )

    # Default mode: flat property table
    resolution_errors: list[dict[str, Any]] = []
    extraction_errors: list[dict[str, Any]] = []
    resolved_props: list[str] = []

    if report_props_definitions:
        resolution = TemplateAttributeParser.resolve_attributes(report_props_definitions)
        resolution_errors = resolution.get("errors", [])
        resolved_props = resolution.get("resolved", [])

        if resolved_props:
            logger.debug("Resolved %d property names: %s", len(resolved_props), resolved_props)
        if resolution_errors:
            logger.warning("Failed to resolve %d properties: %s", len(resolution_errors), [e.get("query") for e in resolution_errors])

    flat_assemblies: list[dict[str, Any]] = []
    flat_parts: list[dict[str, Any]] = []
    reference_objects: list[dict[str, Any]] = []

    for selected_object in wrap_model_objects(selected_objects):
        try:
            props = selected_object.get_properties(resolved_props if resolved_props else None)
        except Exception as e:
            extraction_errors.append({"guid": selected_object.guid, "error": str(e)})
            props = selected_object.get_properties(None)

        if isinstance(selected_object, TeklaReferenceModelObject):
            reference_objects.append(props)
        elif isinstance(selected_object, TeklaAssembly):
            flat_assemblies.append(props)
        elif isinstance(selected_object, TeklaPart):
            flat_parts.append(props)
        processed_elements += 1

    logger.info("Retrieved properties for %s elements", processed_elements)
    status = "success" if flat_assemblies or flat_parts or reference_objects else "error"
    if resolution_errors or extraction_errors:
        status = "partial"
        if extraction_errors:
            logger.warning("Failed to extract properties for %d elements: %s", len(extraction_errors), [e.get("guid") for e in extraction_errors])

    def _flatten_props(props: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        result["GUID"] = props.get("guid", "")
        standard_fields = ["position", "name", "profile", "material", "finish", "tekla_class", "part_prefix", "part_start_number", "assembly_prefix", "assembly_start_number"]
        for field in standard_fields:
            if field in props:
                result[field.replace("_", " ").title()] = props[field]
        result["Phase"] = props.get("phase", "")
        return result

    def _flatten(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return []
        flat_items = []
        for i, item in enumerate(items):
            row = _flatten_props(item)
            if user_props := item.get("user_properties"):
                row.update(user_props)
            if report_props := item.get("report_properties"):
                for rp in report_props:
                    name = rp.get("name", "")
                    value = rp.get("value")
                    unit = rp.get("unit", "")
                    header = f"{name} ({unit})" if unit else name
                    if value is not None:
                        row[header] = round(value, 3) if isinstance(value, float) else value
                    else:
                        row[header] = "N/A"
            flat_items.append({"No": i + 1, **row})
        return flat_items

    content_json = {k: v for k, v in (("assemblies", _flatten(flat_assemblies)), ("parts", _flatten(flat_parts)), ("reference_objects", _flatten(reference_objects))) if v}

    return ToolResult(
        content=content_json,
        structured_content={
            "status": status,
            "selected_elements": selected_objects.GetSize(),
            "processed_elements": processed_elements,
            "assemblies": flat_assemblies,
            "parts": flat_parts,
            "reference_objects": reference_objects,
            "resolution_errors": resolution_errors,
            "extraction_errors": extraction_errors,
        },
    )


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_elements_cut_parts() -> ToolResult:
    """
    Find all cut parts in the selected Tekla elements and return a summary grouped by profile.

    ## OUTPUT
    - Return the result table in Markdown format EXACTLY as provided by the tool.
    - DO NOT reformat, truncate, or modify anything, including spacing, columns, or headers.
    - ALWAYS show the full table. DO NOT remove any rows or columns.
    """
    selected_objects = TeklaModel().get_selected_objects()

    processed_elements = 0
    cut_parts_by_profile: Counter[str] = Counter()

    for selected_object in selected_objects:
        if not isinstance(selected_object, Part):
            logger.error("get_cut_parts failed: Skipping non-part object: %s", selected_object.GetType())
            continue
        for boolean_part in iterate_boolean_parts(selected_object):
            if boolean_part.Type == BooleanPart.BooleanTypeEnum.BOOLEAN_CUT:
                profile = boolean_part.OperativePart.Profile.ProfileString
                cut_parts_by_profile[profile] += 1
        processed_elements += 1

    cut_parts_sorted_by_profile = sorted(cut_parts_by_profile.items(), key=lambda x: x[0])

    content_json = [{"No": i + 1, "Profile": profile, "Count": count} for i, (profile, count) in enumerate(cut_parts_sorted_by_profile)]

    total_cut_parts = sum(cut_parts_by_profile.values())
    logger.info("Found %s cut parts across %s profiles in %s elements", total_cut_parts, len(cut_parts_sorted_by_profile), processed_elements)
    return ToolResult(
        content=content_json,
        structured_content={
            "status": "success" if cut_parts_sorted_by_profile else "warning",
            "selected_elements": selected_objects.GetSize(),
            "processed_elements": processed_elements,
            "total_cut_parts": total_cut_parts,
            "cut_parts_list": cut_parts_sorted_by_profile,
        },
    )


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def compare_elements(
    ignore_numbering: Annotated[bool, Field(description="Skip numbering check")] = False,
) -> ToolResult:
    """
    Compares all selected Tekla parts or assemblies with each other.
    Requires at least two elements to be selected.

    ## RULES
    - Only use information explicitly present in the diff. Do not infer or assume changes.
    - Ignore `id` and `guid` fields - they are ALWAYS different (not actual differences).
    - Ignore order of items in lists (cutparts, reinforcements, welds).
    """
    selected_objects = TeklaModel().get_selected_objects()

    tolerance = get_tolerance("comparison", default=0.01)

    _validate_at_least_two_selected(selected_objects.GetSize())

    parts = list(selected_objects)
    logger.debug("Comparing %d elements", len(parts))
    if not ignore_numbering:
        if not all(Operation.IsNumberingUpToDate(part) for part in parts):
            raise ValueError("Numbering is not up-to-date for selected elements.")

    valid_types = (TeklaPart, TeklaAssembly)

    IGNORED_KEYS = {"id", "guid"}

    def _canonical(value: Any) -> Any:
        if isinstance(value, dict):
            return tuple((k, _canonical(v)) for k, v in sorted(value.items()) if k.lower() not in IGNORED_KEYS)
        if isinstance(value, list):
            return tuple(_canonical(v) for v in value)
        return value

    def _strip_ignored(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _strip_ignored(v) for k, v in value.items() if k.lower() not in IGNORED_KEYS}
        if isinstance(value, list):
            return [_strip_ignored(v) for v in value]
        return value

    def _diff_values(values: list[Any]) -> Any:
        """
        Recursively compute a diff across N per-element values, stripping identical sub-values.

        Returns None when all values are identical.
        """
        if len({_canonical(v) for v in values}) == 1:
            return None  # all identical - strip entirely

        if all(isinstance(v, dict) for v in values):
            all_keys: set[str] = set()
            for v in values:
                all_keys.update(v.keys())
            result: dict[str, Any] = {}
            for key in sorted(all_keys):
                child = _diff_values([v.get(key) for v in values])
                if child is not None:
                    result[key] = child
            return result or None

        if all(isinstance(v, list) for v in values):
            lengths = {len(v) for v in values}
            if len(lengths) == 1:  # same length - recurse positionally
                n = next(iter(lengths))
                items = [_diff_values([v[i] for v in values]) for i in range(n)]
                return [item for item in items if item is not None]

        return values  # primitives or mismatched shapes - show raw values per element

    def _compute_multi_diff(snap_views: list[dict]) -> dict[str, Any] | None:
        """Top-level diff: for each field that differs across any element, recurse into it."""
        all_keys: set[str] = set()
        for snap in snap_views:
            all_keys.update(snap.keys())
        diff: dict[str, Any] = {}
        for key in sorted(all_keys):
            d = _diff_values([snap.get(key) for snap in snap_views])
            if d is not None:
                diff[key] = d
        return diff if diff else None

    guids: list[str] = []
    snap_views: list[dict] = []
    raws: list[dict] = []

    for part in parts:
        obj = wrap_model_object(part)
        if not isinstance(obj, valid_types):
            raise TypeError(f"Element must be a part or assembly, got {type(obj).__name__}")
        snapshot = obj.to_snapshot().normalize(tolerance)
        guids.append(obj.guid)
        snap_views.append(_strip_ignored(snapshot.to_diff_view()))
        raws.append(snapshot.model_dump())

    diff = _compute_multi_diff(snap_views)
    identical = diff is None

    logger.info("compare_elements: %d elements, identical=%s", len(guids), identical)

    # When not identical: guids for alignment + the diff (only fields that vary)
    # When identical: minimal confirmation, no diff key.
    if identical:
        content_out: dict[str, Any] = {"guids": guids, "identical": True}
    else:
        content_out = {"guids": guids, "identical": False, "diff": diff}

    sc_out: dict[str, Any] = {"status": "success", "guids": guids, "identical": identical, "raws": raws}
    if diff is not None:
        sc_out["diff"] = diff
    return ToolResult(content=content_out, structured_content=sc_out)


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def clear_elements_udas(
    uda_names: Annotated[list[str] | None, Field(description="List of specific UDA names to clear")] = None,
) -> ToolResult:
    """
    Clears user-defined attributes (UDAs) from selected Tekla parts and assemblies.

    If the list of specific UDA names is not provided, clears all UDAs.

    ## EXAMPLES
    # Clear all UDAs from selected elements
    clear_elements_udas()

    # Clear only specific UDAs
    clear_elements_udas(uda_names=["STATUS", "APPROVED_BY"])
    """
    selected_objects = TeklaModel().get_selected_objects()

    cleared_udas = 0
    modified_parts = 0
    modified_assemblies = 0

    for selected_object in wrap_model_objects(selected_objects):
        try:
            user_props = selected_object.get_all_user_properties()
            if not user_props:
                continue

            target_keys = [k for k in uda_names if k in user_props] if uda_names else list(user_props.keys())
            if not target_keys:
                continue

            for key in target_keys:
                value = user_props[key]
                if isinstance(value, str):
                    selected_object.set_user_property(key, "")
                elif isinstance(value, int):
                    selected_object.set_user_property(key, -2147483648)
                elif isinstance(value, float):
                    selected_object.set_user_property(key, float(-2147483648))
                cleared_udas += 1

            selected_object.modify()

            if isinstance(selected_object, TeklaPart):
                modified_parts += 1
            elif isinstance(selected_object, TeklaAssembly):
                modified_assemblies += 1
        except Exception:
            logger.exception("Failed to clear UDAs on %s", selected_object.guid)

    commit_success: bool | None = None
    if cleared_udas > 0:
        commit_success = TeklaModel().commit_changes()
        if not commit_success:
            logger.error("commit_changes() failed after clearing %d UDAs", cleared_udas)

    if commit_success is False:
        status = "error"
    elif cleared_udas > 0:
        status = "success"
    else:
        status = "warning"
    logger.info("Cleared %s UDAs from %s parts and %s assemblies", cleared_udas, modified_parts, modified_assemblies)
    result: dict = {
        "status": status,
        "cleared_udas": cleared_udas,
        "modified_parts": modified_parts,
        "modified_assemblies": modified_assemblies,
    }
    if commit_success is not None:
        result["commit_success"] = commit_success
    return ToolResult(structured_content=result)


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": True, "destructiveHint": False})
@mcp_handler(scope="tool")
def get_elements_coordinates() -> ToolResult:
    """
    Get coordinates of selected Tekla elements.

    ## OUTPUT
    - Beams: start_point, end_point (x, y, z) and start_point_offset, end_point_offset (dx, dy, dz)
    - Slabs: contour_points list of {x, y, z}
    """
    selected_objects = TeklaModel().get_selected_objects()

    elements: list[dict[str, Any]] = []

    for obj in wrap_model_objects(selected_objects):
        if isinstance(obj, TeklaBeam):
            start_pt = obj.start_point
            end_pt = obj.end_point
            start_offset = obj.start_point_offset
            end_offset = obj.end_point_offset

            elements.append(
                {
                    "guid": obj.guid,
                    "type": "Beam",
                    "start_point": {"x": start_pt.X, "y": start_pt.Y, "z": start_pt.Z},
                    "end_point": {"x": end_pt.X, "y": end_pt.Y, "z": end_pt.Z},
                    "start_point_offset": {"dx": start_offset.Dx, "dy": start_offset.Dy, "dz": start_offset.Dz},
                    "end_point_offset": {"dx": end_offset.Dx, "dy": end_offset.Dy, "dz": end_offset.Dz},
                }
            )
        elif isinstance(obj, TeklaContourPlate):
            contour_pts = obj.contour_points
            elements.append(
                {
                    "guid": obj.guid,
                    "type": "Slab",
                    "contour_points": [{"x": pt.X, "y": pt.Y, "z": pt.Z} for pt in contour_pts],
                }
            )

    logger.info("Retrieved coordinates for %s elements", len(elements))
    return ToolResult(
        structured_content={
            "status": "success" if elements else "warning",
            "elements": elements,
        }
    )


@properties_provider.tool(tags={"properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
@mcp_handler(scope="tool")
def copy_properties_from_ifc(
    user_properties: Annotated[dict[str, str], Field(description="Mapping of IFC property names to Tekla UDA names.")],
) -> ToolResult:
    """
    Copy user-defined properties from IFC reference objects to matching Tekla model elements.

    Use when both IFC references and Tekla parts are selected. The tool matches objects by geometry
    and transfers specified properties from IFC to Tekla elements UDAs.
    """
    selected_objects = TeklaModel().get_selected_objects()

    # Separate IFC references from Tekla parts
    ifc_sources: list[tuple[str, TeklaReferenceModelObject]] = []
    tekla_targets: list[tuple[str, TeklaModelObject]] = []

    for selected_object in wrap_model_objects(selected_objects):
        if selected_object is None:
            continue
        # Use GUID from report properties: native Tekla objects may not have valid GUID
        guid = str(selected_object.get_report_property("GUID"))
        if isinstance(selected_object, TeklaReferenceModelObject):
            ifc_sources.append((guid, selected_object))
        else:
            tekla_targets.append((guid, selected_object))

    if not ifc_sources:
        raise ValueError("No IFC reference objects found in selection. Please select IFC references and Tekla parts together.")
    if not tekla_targets:
        raise ValueError("No Tekla parts found in selection. Please select IFC references and Tekla parts together.")

    # Collect bounding boxes for matching
    ifc_bboxes: dict[str, Any] = {}
    for guid, obj in ifc_sources:
        bbox = obj.bounding_box
        if bbox is not None:
            ifc_bboxes[guid] = bbox

    tekla_bboxes: dict[str, Any] = {}
    for guid, obj in tekla_targets:
        bbox = obj.bounding_box
        if bbox is not None:
            tekla_bboxes[guid] = bbox

    errors: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    matched_tekla_guids: set[str] = set()
    properties_copied = 0
    matches_made = 0

    # Match IFC to Tekla elements by bounding box and copy properties
    for i, (ifc_guid, ifc_object) in enumerate(ifc_sources):
        if ifc_guid not in ifc_bboxes:
            logger.debug("Skipping IFC %s: no bounding box", ifc_guid)
            continue

        logger.debug("Processing IFC source %d/%d: %s", i + 1, len(ifc_sources), ifc_guid)
        ifc_bbox = ifc_bboxes[ifc_guid]
        found_match = False

        for tekla_guid, tekla_object in tekla_targets:
            if tekla_guid in matched_tekla_guids:
                continue
            if tekla_guid not in tekla_bboxes:
                continue

            tekla_bbox = tekla_bboxes[tekla_guid]
            if ifc_bbox.matches(tekla_bbox):
                for ifc_prop, uda_name in user_properties.items():
                    try:
                        value = ifc_object.get_report_property(ifc_prop)
                        if value is not None:
                            set_ok = tekla_object.set_user_property(uda_name, value)
                            if set_ok:
                                properties_copied += 1
                            else:
                                errors.append(
                                    {
                                        "ifc_object": ifc_guid,
                                        "tekla_object": tekla_guid,
                                        "ifc_property": ifc_prop,
                                        "uda": uda_name,
                                        "reason": "Failed to set property",
                                    }
                                )
                    except Exception as e:
                        errors.append(
                            {
                                "ifc_object": ifc_guid,
                                "tekla_object": tekla_guid,
                                "ifc_property": ifc_prop,
                                "uda": uda_name,
                                "reason": str(e),
                            }
                        )

                matched_tekla_guids.add(tekla_guid)
                matches_made += 1
                found_match = True
                logger.debug("Matched IFC %s -> Tekla %s", ifc_guid, tekla_guid)
                break

        if not found_match:
            unmatched.append({"ifc_object": ifc_guid, "reason": "No matching Tekla element found"})

    # Track unmatched Tekla elements
    for tekla_guid, _ in tekla_targets:
        if tekla_guid not in matched_tekla_guids:
            unmatched.append({"tekla_object": tekla_guid, "reason": "No matching IFC reference found"})

    if matches_made == 0:
        logger.error("copy_properties_from_ifc failed: No matches made between IFC and Tekla elements")
        status = "error"
    elif errors:
        status = "partial"
    elif unmatched:
        status = "partial"
    else:
        status = "success"

    logger.info("IFC copy complete: %d matches, %d properties copied, %d errors, %d unmatched", matches_made, properties_copied, len(errors), len(unmatched))
    return ToolResult(
        structured_content={
            "status": status,
            "ifc_sources": len(ifc_sources),
            "tekla_targets": len(tekla_targets),
            "matches_made": matches_made,
            "properties_copied": properties_copied,
            "errors": errors,
            "unmatched": unmatched,
        }
    )
