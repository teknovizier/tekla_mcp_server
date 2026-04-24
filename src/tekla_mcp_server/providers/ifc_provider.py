"""
IFC reference tools provider for Tekla MCP server.

Uses LocalProvider for modular organization and callable decorator pattern.
"""

from typing import Any, Annotated

from fastmcp.server.providers import LocalProvider
from fastmcp.tools import ToolResult
from pydantic import Field

from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import mcp_handler
from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import TeklaModelObject, TeklaReferenceModelObject, wrap_model_objects

ifc_provider = LocalProvider()


@ifc_provider.tool(tags={"ifc", "properties"}, annotations={"readOnlyHint": False, "destructiveHint": True})
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
        # Use GUID from report properties: native Tekla objects may not have valid GUID
        guid = str(selected_object.get_report_property("GUID"))
        if selected_object is None:
            continue
        if isinstance(selected_object, TeklaReferenceModelObject):
            ifc_sources.append((guid, selected_object))
        else:
            tekla_targets.append((guid, selected_object))

    if not ifc_sources:
        logger.error("copy_properties_from_ifc failed: No IFC reference objects found in selection")
        return ToolResult(
            structured_content={
                "status": "error",
                "message": "No IFC reference objects found in selection. Please select IFC references and Tekla parts together.",
            }
        )
    if not tekla_targets:
        logger.error("copy_properties_from_ifc failed: No Tekla parts found in selection")
        return ToolResult(
            structured_content={
                "status": "error",
                "message": "No Tekla parts found in selection. Please select IFC references and Tekla parts together.",
            }
        )

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
