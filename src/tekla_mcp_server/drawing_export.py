"""
Python helpers for drawing export.

Owns the .dwgsetting and .PdfPrintOptions XML patching used by the export and
print tools.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

DWGSETTING_EXTENSION = ".dwgsetting"
PDF_PRINT_OPTIONS_EXTENSION = ".PdfPrintOptions.xml"


def _require_element(parent: ET.Element, path: str, *, file_kind: str) -> ET.Element:
    """Find `path` under `parent`, raising ValueError with a clear message if missing."""
    element = parent.find(path)
    if element is None:
        raise ValueError(f"{file_kind} XML missing {path} element")
    return element


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
    file_attributes = _require_element(root, ".//FileAttributes", file_kind="dwgsetting")
    preferences = _require_element(root, ".//Preferences", file_kind="dwgsetting")

    file_attributes.set("FileExtension", file_extension)
    file_attributes.set("FileVersion", file_version)
    preferences.set("OutputDirectory", output_dir)

    # Tekla writes the declaration with utf-8, keep it on the patched copy
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def patch_pdf_print_options_xml(base_xml: str, *, paper_size: str, orientation: str, multi_sheet: bool, multi_sheet_order: str, output_dir: str) -> str:
    """
    Return a copy of a .PdfPrintOptions XML with paper size, orientation,
    multi-sheet tiling and output-dir patched.

    Sets `PaperSize`, `Orientation`, `PrintOnMultipleSheets`, `MultipleSheetOrder`
    and `PDFAndPlotFileLocation` under `Options`. The base XML is never mutated.
    Other settings (color mode, scaling, line colors) are preserved.

    Args:
        base_xml: Source .PdfPrintOptions.xml text.
        paper_size: Tekla paper size token, e.g. 'A3', 'A0'.
        orientation: 'Landscape' or 'Portrait'.
        multi_sheet: Whether to tile the drawing across multiple sheets.
        multi_sheet_order: Tekla multi-sheet order token, e.g. 'LeftToRightTopToBottom'.
        output_dir: Target export directory.

    Raises:
        ValueError: If the Options element or one of the patched children is missing.
    """
    root = ET.fromstring(base_xml)
    options = _require_element(root, "Options", file_kind="PdfPrintOptions")

    def _set_text(tag: str, value: str) -> None:
        _require_element(options, tag, file_kind="PdfPrintOptions").text = value

    _set_text("PaperSize", paper_size)
    _set_text("Orientation", orientation)
    _set_text("PrintOnMultipleSheets", "true" if multi_sheet else "false")
    _set_text("MultipleSheetOrder", multi_sheet_order)
    _set_text("PDFAndPlotFileLocation", output_dir)

    # Tekla writes the declaration with utf-8, keep it on the patched copy
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def pdf_print_options_outputs_single_file(base_xml: str) -> bool:
    """
    Return whether a .PdfPrintOptions XML combines all drawings into one file.

    Reads `Options/OutputToSingleFile`. Customers can set this directly in the
    base settings file (see docs/configuration.md), so callers expecting one
    output file per drawing must check this first - a successful combined
    print produces a single file regardless of how many drawings were printed.

    Args:
        base_xml: Source .PdfPrintOptions.xml text.

    Returns:
        True if `OutputToSingleFile` is `true`, False otherwise (including if
        the element is missing).
    """
    root = ET.fromstring(base_xml)
    options = root.find("Options")
    if options is None:
        return False
    element = options.find("OutputToSingleFile")
    if element is None or element.text is None:
        return False
    return element.text.strip().lower() == "true"


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
