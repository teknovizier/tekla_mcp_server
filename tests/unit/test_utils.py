"""
Unit tests for utils module.
"""

from pathlib import Path

import pytest

from tekla_mcp_server.utils import (
    build_report_filename,
    find_normalized_match,
    normalize_attribute_name,
    format_coordinate_string,
    parse_coordinate_string,
    parse_label_string,
    resolve_model_relative_dir,
    sanitize_filename,
)


class TestNormalizeAttributeName:
    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("assembly_top_level", "ASSEMBLY_TOP_LEVEL"),
            ("assembly-top-level", "ASSEMBLY_TOP_LEVEL"),
            ("assembly top level", "ASSEMBLY_TOP_LEVEL"),
            ("ASSEMBLY_TOP_LEVEL", "ASSEMBLY_TOP_LEVEL"),
            ("  assembly__top   level  ", "ASSEMBLY_TOP_LEVEL"),
            ("weight-total", "WEIGHT_TOTAL"),
            ("WEIGHT_TOTAL", "WEIGHT_TOTAL"),
        ],
    )
    def test_normalize(self, input_name, expected):
        assert normalize_attribute_name(input_name) == expected


class TestFindNormalizedMatch:
    def test_exact_match(self):
        candidates = {"ASSEMBLY_TOP_LEVEL": "value1", "WEIGHT_TOTAL": "value2"}
        assert find_normalized_match("assembly_top_level", candidates) == "ASSEMBLY_TOP_LEVEL"

    def test_dash_match(self):
        candidates = {"ASSEMBLY_TOP_LEVEL": "value1", "WEIGHT_TOTAL": "value2"}
        assert find_normalized_match("assembly-top-level", candidates) == "ASSEMBLY_TOP_LEVEL"

    def test_case_insensitive(self):
        candidates = {"ASSEMBLY_TOP_LEVEL": "value1", "WEIGHT_TOTAL": "value2"}
        assert find_normalized_match("Assembly_Top_Level", candidates) == "ASSEMBLY_TOP_LEVEL"

    def test_no_match(self):
        candidates = {"ASSEMBLY_TOP_LEVEL": "value1", "WEIGHT_TOTAL": "value2"}
        assert find_normalized_match("xyz", candidates) is None

    def test_empty_candidates(self):
        assert find_normalized_match("test", {}) is None


class TestParseCoordinateString:
    @pytest.mark.parametrize(
        "coord_str,expected",
        [
            ("0.0 4900.0 400.0 4900.0", [0.0, 4900.0, 5300.0, 10200.0]),
            ("0.0 5*7200.0", [0.0, 7200.0, 14400.0, 21600.0, 28800.0, 36000.0]),
            ("-1000.0 5*7200.0", [-1000.0, 6200.0, 13400.0, 20600.0, 27800.0, 35000.0]),
            ("0.0", [0.0]),
            ("100 200 300", [100.0, 300.0, 600.0]),
            ("0", [0.0]),
            ("", []),
        ],
    )
    def test_parse_coordinate_string(self, coord_str, expected):
        assert parse_coordinate_string(coord_str) == expected


class TestFormatCoordinateString:
    @pytest.mark.parametrize(
        "coords,expected",
        [
            ([], ""),
            ([0], "0"),
            ([0, 5000, 10000], "0 5000 5000"),
            ([1000, 1000], "1000 0"),
            ([0, 6000, 12000, 18000], "0 6000 6000 6000"),
            ([0.0, 5000.5, 7500.0], "0 5000.5 2499.5"),
            ([-1000, 0, 1000], "-1000 1000 1000"),
        ],
    )
    def test_format_coordinate_string(self, coords, expected):
        assert format_coordinate_string(coords) == expected


class TestParseLabelString:
    @pytest.mark.parametrize(
        "label_str,expected",
        [
            ("A B C D", ["A", "B", "C", "D"]),
            ("1 2 3 4 5 6", ["1", "2", "3", "4", "5", "6"]),
            ("+0 +3600 +7200", ["+0", "+3600", "+7200"]),
            ("A", ["A"]),
            ("", []),
            ("  A   B  ", ["A", "B"]),
        ],
    )
    def test_parse_label_string(self, label_str, expected):
        assert parse_label_string(label_str) == expected


class TestSanitizeFilename:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Floor_3", "Floor_3"),
            ("Floor 3", "Floor 3"),
            ("Floor/3", "Floor_3"),
            ("Floor\\3", "Floor_3"),
            ('a:b*c?d"e<f>g|h', "a_b_c_d_e_f_g_h"),
            ("..\\wall", "_wall"),
            ("../wall", "_wall"),
            ("  spaced  ", "spaced"),
            ("...dots...", "dots"),
            ("name.with.dots", "name.with.dots"),
        ],
    )
    def test_sanitize_returns_cleaned_string(self, raw, expected):
        assert sanitize_filename(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "...",
            " . . ",
        ],
    )
    def test_sanitize_returns_none_when_nothing_remains(self, raw):
        assert sanitize_filename(raw) is None


class TestBuildReportFilename:
    def test_uses_template_name_when_filename_omitted(self):
        assert build_report_filename("Cast_Unit_List", None) == "Cast_Unit_List.xsr"

    def test_empty_filename_falls_back_to_template(self):
        assert build_report_filename("Cast_Unit_List", "") == "Cast_Unit_List.xsr"

    def test_uses_provided_filename(self):
        assert build_report_filename("Cast_Unit_List", "my_report") == "my_report.xsr"

    def test_keeps_explicit_extension(self):
        assert build_report_filename("Cast_Unit_List", "report.csv") == "report.csv"

    def test_sanitizes_invalid_characters(self):
        assert build_report_filename("Cast_Unit_List", "my:report*x") == "my_report_x.xsr"

    @pytest.mark.parametrize("name", ["ab", "ab.xsr", "x.csv"])
    def test_short_stem_raises(self, name):
        with pytest.raises(ValueError, match="at least 3 characters"):
            build_report_filename("Cast_Unit_List", name)

    def test_short_template_name_raises_when_filename_omitted(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            build_report_filename("ab", None)

    @pytest.mark.parametrize("name", ["abc", "abc.xsr", "report"])
    def test_long_enough_stem_accepted(self, name):
        # Stem has >= 3 characters, so no exception is raised.
        build_report_filename("Cast_Unit_List", name)

    @pytest.mark.parametrize("name", ["...", "   ", " . . "])
    def test_no_valid_characters_raises(self, name):
        with pytest.raises(ValueError, match="no valid filename characters"):
            build_report_filename("Cast_Unit_List", name)


class TestResolveModelRelativeDir:
    def test_absolute_path_is_normalized(self, tmp_path):
        sub = tmp_path / "out"
        sub.mkdir()
        result = resolve_model_relative_dir(str(sub), str(tmp_path / "model"))
        assert result == str(sub.resolve())

    def test_relative_path_resolved_against_model(self, tmp_path):
        model_dir = tmp_path / "model"
        (model_dir / "reports").mkdir(parents=True)
        result = resolve_model_relative_dir("reports", str(model_dir))
        assert result == str((model_dir / "reports").resolve())

    def test_dot_relative_path_resolved_against_model(self, tmp_path):
        # pathlib normalizes a leading "./" on both Windows and POSIX.
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        result = resolve_model_relative_dir("./out", str(model_dir))
        assert result == str((model_dir / "out").resolve())

    def test_relative_path_without_model_uses_cwd(self):
        # No model path: relative paths fall back to the process working directory.
        result = resolve_model_relative_dir("reports", "")
        assert result == str((Path.cwd() / "reports").resolve())
