"""
Unit tests for embeddings module.
"""

import pytest

from tekla_mcp_server.utils import find_normalized_match, normalize_attribute_name


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
