"""
Unit tests for selection provider helpers.

The provider imports the Tekla loader, which loads the Tekla DLLs, so these tests
are skipped in CI environments where Tekla is not available.
"""

import importlib
import os

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.models import StringFilterOption

sp = importlib.import_module("tekla_mcp_server.providers.selection_provider")


class TestBoltTypeFilter:
    @pytest.mark.parametrize("value,expected", [("site", "0"), ("Workshop", "1"), (" SITE ", "0")])
    def test_value_is_translated(self, value, expected):
        option = StringFilterOption(conditions={"match_type": "Is Equal", "value": value})
        result = sp._to_bolt_type_filter(option)
        assert [c.value for c in result.conditions] == [expected]

    def test_several_conditions_keep_their_logic(self):
        option = StringFilterOption(conditions=[{"match_type": "Is Equal", "value": "site"}, {"match_type": "Is Equal", "value": "workshop"}], logic="OR")
        result = sp._to_bolt_type_filter(option)
        assert [c.value for c in result.conditions] == ["0", "1"]
        assert result.logic == "OR"

    def test_unknown_value_is_rejected(self):
        option = StringFilterOption(conditions={"match_type": "Is Equal", "value": "factory"})
        with pytest.raises(ValueError, match="factory"):
            sp._to_bolt_type_filter(option)
