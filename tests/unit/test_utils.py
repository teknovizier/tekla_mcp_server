"""
Unit tests for utils module.
"""

import pytest

from tekla_mcp_server.utils import (
    find_normalized_match,
    normalize_attribute_name,
    parse_coordinate_string,
    parse_label_string,
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
