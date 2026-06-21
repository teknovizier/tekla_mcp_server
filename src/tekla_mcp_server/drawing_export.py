"""
Python helpers for drawing export.

Owns the .dwgsetting XML patching used by the export tools.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def patch_dwgsetting_xml(base_xml: str, *, file_extension: str, file_version: str, output_dir: str) -> str:
    """
    Return a copy of a .dwgsetting XML with format/version/output-dir patched.

    Sets `FileAttributes/@FileExtension`, `FileAttributes/@FileVersion` and
    `Preferences/@OutputDirectory`. The base XML is never mutated. Other
    attributes (FilePrefix, FileSuffix, layer rules) are preserved.

    Args:
        base_xml: Source .dwgsetting XML text.
        file_extension: Output extension, e.g. '.dxf', '.dwg' or '.dgn'.
        file_version: Tekla DwgFileVersion token, e.g. 'Dwg.UI.DwgFileVersion.vAC24'.
        output_dir: Target export directory.

    Raises:
        ValueError: If the FileAttributes or Preferences element is missing.
    """
    root = ET.fromstring(base_xml)
    file_attributes = root.find(".//FileAttributes")
    preferences = root.find(".//Preferences")
    if file_attributes is None or preferences is None:
        raise ValueError("dwgsetting XML missing FileAttributes or Preferences element")

    file_attributes.set("FileExtension", file_extension)
    file_attributes.set("FileVersion", file_version)
    preferences.set("OutputDirectory", output_dir)

    # Tekla writes the declaration with utf-8, keep it on the patched copy
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def install_export_settings_content(model_path: str, setting_name: str, content: str) -> Path:
    """
    Write export-setting `content` to the model's attributes folder if changed.

    Mirrors `ensure_export_settings_installed` but takes ready content rather than
    copying a file, so a Python-patched .dwgsetting can be installed. Compares
    bytes and only rewrites on difference, keeping re-installs cheap.

    Returns:
        Path to the installed setting file.
    """
    destination = Path(model_path) / "attributes" / setting_name
    new_bytes = content.encode("utf-8")
    if not destination.exists() or destination.read_bytes() != new_bytes:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(new_bytes)
    return destination
