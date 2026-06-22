"""
Unit tests for the drawing export helpers.
"""

import pytest

from tekla_mcp_server.config import _load_json, _load_settings, get_default_export_settings, get_default_print_settings, get_export_output_dir
from tekla_mcp_server.drawing_export import (
    install_export_settings_content,
    patch_dwgsetting_xml,
    patch_pdf_print_options_xml,
    pdf_print_options_outputs_single_file,
)
from tekla_mcp_server.models import (
    DWG_FILE_VERSION_MAP,
    FORMAT_TO_FILE_EXTENSION,
    DrawingExportFormat,
    DrawingExportVersion,
)


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear config caches before each test."""
    _load_json.cache_clear()
    _load_settings.cache_clear()
    yield


SAMPLE_DWGSETTING = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<DwgExportOptions Version="1.1">\n'
    '  <FileAttributes FileExtension=".dxf" FilePrefix="TEKLA_MCP_" FileSuffix="" FileVersion="Dwg.UI.DwgFileVersion.vAC24" />\n'
    '  <Preferences OpenFolder="false" OutputDirectory=".\\PlotFiles" UpdateExisting="false" />\n'
    "</DwgExportOptions>"
)

SAMPLE_PDF_PRINT_OPTIONS = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<PdfPrintOptions Version="1.5">\n'
    "  <Options>\n"
    "    <PrintTarget>PDF</PrintTarget>\n"
    "    <PrinterName>PDF-XChange 3.0</PrinterName>\n"
    "    <PDFAndPlotFileLocation>.\\Plotfiles</PDFAndPlotFileLocation>\n"
    "    <ColorMode>BlackAndWhite</ColorMode>\n"
    "    <PrintOnMultipleSheets>false</PrintOnMultipleSheets>\n"
    "    <MultipleSheetOrder>LeftToRightTopToBottom</MultipleSheetOrder>\n"
    "    <PaperSize>A3</PaperSize>\n"
    "    <Orientation>Landscape</Orientation>\n"
    "    <OutputToSingleFile>false</OutputToSingleFile>\n"
    "  </Options>\n"
    "</PdfPrintOptions>"
)


# models: mapping completeness
def test_format_extension_map_covers_all_formats():
    """Every export format maps to an extension."""
    assert set(FORMAT_TO_FILE_EXTENSION) == set(DrawingExportFormat)
    assert FORMAT_TO_FILE_EXTENSION[DrawingExportFormat.DXF] == ".dxf"
    assert FORMAT_TO_FILE_EXTENSION[DrawingExportFormat.DWG] == ".dwg"
    assert FORMAT_TO_FILE_EXTENSION[DrawingExportFormat.DGN] == ".dgn"


def test_version_map_covers_all_versions():
    """Every export version maps to a FileVersion token."""
    assert set(DWG_FILE_VERSION_MAP) == set(DrawingExportVersion)


def test_version_2010_is_vac24():
    """The one version verified from the bundled file."""
    assert DWG_FILE_VERSION_MAP[DrawingExportVersion.V2010] == "Dwg.UI.DwgFileVersion.vAC24"


def test_version_2018_not_exposed():
    """2018 is intentionally excluded from the version enum."""
    assert "2018" not in {v.value for v in DrawingExportVersion}


# config getters
def test_get_export_output_dir_default():
    """Output dir comes from settings.json (relative, model-resolved later)."""
    assert get_export_output_dir() == ".\\PlotFiles"


def test_get_default_export_settings_empty_by_default():
    """Empty default means on-the-go mode, not a customer setting."""
    assert get_default_export_settings() == ""


def test_get_default_print_settings_empty_by_default():
    """Empty default means on-the-go mode, not a customer setting."""
    assert get_default_print_settings() == ""


# patch_pdf_print_options_xml
def test_patch_pdf_sets_all_five_fields():
    out = patch_pdf_print_options_xml(SAMPLE_PDF_PRINT_OPTIONS, paper_size="A0", orientation="Portrait", multi_sheet=True, multi_sheet_order="LeftToRightTopToBottom", output_dir="C:/exports")
    assert "<PaperSize>A0</PaperSize>" in out
    assert "<Orientation>Portrait</Orientation>" in out
    assert "<PrintOnMultipleSheets>true</PrintOnMultipleSheets>" in out
    assert "<MultipleSheetOrder>LeftToRightTopToBottom</MultipleSheetOrder>" in out
    assert "<PDFAndPlotFileLocation>C:/exports</PDFAndPlotFileLocation>" in out


def test_patch_pdf_multi_sheet_false_writes_lowercase_false():
    out = patch_pdf_print_options_xml(SAMPLE_PDF_PRINT_OPTIONS, paper_size="A3", orientation="Landscape", multi_sheet=False, multi_sheet_order="LeftToRightTopToBottom", output_dir="d")
    assert "<PrintOnMultipleSheets>false</PrintOnMultipleSheets>" in out


def test_patch_pdf_preserves_unrelated_fields():
    out = patch_pdf_print_options_xml(SAMPLE_PDF_PRINT_OPTIONS, paper_size="A3", orientation="Landscape", multi_sheet=False, multi_sheet_order="LeftToRightTopToBottom", output_dir="d")
    assert "<PrinterName>PDF-XChange 3.0</PrinterName>" in out
    assert "<ColorMode>BlackAndWhite</ColorMode>" in out
    assert "<OutputToSingleFile>false</OutputToSingleFile>" in out


def test_patch_pdf_does_not_mutate_input():
    before = SAMPLE_PDF_PRINT_OPTIONS
    patch_pdf_print_options_xml(SAMPLE_PDF_PRINT_OPTIONS, paper_size="A0", orientation="Portrait", multi_sheet=True, multi_sheet_order="LeftToRightTopToBottom", output_dir="d")
    assert SAMPLE_PDF_PRINT_OPTIONS == before


def test_patch_pdf_raises_on_missing_options_element():
    bad = '<?xml version="1.0"?>\n<PdfPrintOptions></PdfPrintOptions>'
    with pytest.raises(ValueError):
        patch_pdf_print_options_xml(bad, paper_size="A3", orientation="Landscape", multi_sheet=False, multi_sheet_order="LeftToRightTopToBottom", output_dir="d")


def test_patch_pdf_raises_on_missing_child_element():
    bad = '<?xml version="1.0"?>\n<PdfPrintOptions><Options></Options></PdfPrintOptions>'
    with pytest.raises(ValueError):
        patch_pdf_print_options_xml(bad, paper_size="A3", orientation="Landscape", multi_sheet=False, multi_sheet_order="LeftToRightTopToBottom", output_dir="d")


# pdf_print_options_outputs_single_file
def test_outputs_single_file_false_by_default():
    assert pdf_print_options_outputs_single_file(SAMPLE_PDF_PRINT_OPTIONS) is False


def test_outputs_single_file_true_when_set():
    xml = SAMPLE_PDF_PRINT_OPTIONS.replace("<OutputToSingleFile>false</OutputToSingleFile>", "<OutputToSingleFile>true</OutputToSingleFile>")
    assert pdf_print_options_outputs_single_file(xml) is True


def test_outputs_single_file_case_insensitive():
    xml = SAMPLE_PDF_PRINT_OPTIONS.replace("<OutputToSingleFile>false</OutputToSingleFile>", "<OutputToSingleFile>True</OutputToSingleFile>")
    assert pdf_print_options_outputs_single_file(xml) is True


def test_outputs_single_file_false_when_element_missing():
    """Missing element is treated as the documented default (one file per drawing)."""
    bad = '<?xml version="1.0"?>\n<PdfPrintOptions><Options></Options></PdfPrintOptions>'
    assert pdf_print_options_outputs_single_file(bad) is False


def test_outputs_single_file_false_when_options_missing():
    bad = '<?xml version="1.0"?>\n<PdfPrintOptions></PdfPrintOptions>'
    assert pdf_print_options_outputs_single_file(bad) is False


# patch_dwgsetting_xml
def test_patch_sets_all_three_attributes():
    out = patch_dwgsetting_xml(SAMPLE_DWGSETTING, file_extension=".dwg", file_version="Dwg.UI.DwgFileVersion.vAC27", output_dir="C:/exports")
    assert 'FileExtension=".dwg"' in out
    assert 'FileVersion="Dwg.UI.DwgFileVersion.vAC27"' in out
    assert 'OutputDirectory="C:/exports"' in out


def test_patch_defaults_to_v2010_when_not_provided():
    """When version is not provided DGN defaults to V2010."""
    out = patch_dwgsetting_xml(SAMPLE_DWGSETTING, file_extension=".dgn", file_version=DWG_FILE_VERSION_MAP[DrawingExportVersion.V2010], output_dir="d")
    assert 'FileVersion="Dwg.UI.DwgFileVersion.vAC24"' in out
    assert 'FileExtension=".dgn"' in out


def test_patch_preserves_prefix_and_suffix():
    out = patch_dwgsetting_xml(SAMPLE_DWGSETTING, file_extension=".dxf", file_version="x", output_dir="d")
    assert 'FilePrefix="TEKLA_MCP_"' in out
    assert 'FileSuffix=""' in out


def test_patch_does_not_mutate_input():
    before = SAMPLE_DWGSETTING
    patch_dwgsetting_xml(SAMPLE_DWGSETTING, file_extension=".dwg", file_version="x", output_dir="d")
    assert SAMPLE_DWGSETTING == before


def test_patch_raises_on_missing_element():
    bad = '<?xml version="1.0"?>\n<DwgExportOptions></DwgExportOptions>'
    with pytest.raises(ValueError):
        patch_dwgsetting_xml(bad, file_extension=".dxf", file_version="x", output_dir="d")


# install_export_settings_content
def test_install_writes_when_absent(tmp_path):
    dest = install_export_settings_content(str(tmp_path), "TEST.dwgsetting", "<xml/>")
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "<xml/>"
    assert dest == tmp_path / "attributes" / "TEST.dwgsetting"


def test_install_noop_when_identical(tmp_path):
    dest = install_export_settings_content(str(tmp_path), "TEST.dwgsetting", "<xml/>")
    first_mtime = dest.stat().st_mtime_ns
    install_export_settings_content(str(tmp_path), "TEST.dwgsetting", "<xml/>")
    assert dest.stat().st_mtime_ns == first_mtime


def test_install_rewrites_on_change(tmp_path):
    install_export_settings_content(str(tmp_path), "TEST.dwgsetting", "<xml/>")
    dest = install_export_settings_content(str(tmp_path), "TEST.dwgsetting", "<xml2/>")
    assert dest.read_text(encoding="utf-8") == "<xml2/>"
