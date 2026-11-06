"""
Unit tests for per-element failure reporting in the property tools.

The provider imports the Tekla wrappers, which load the Tekla DLLs, so these tests
are skipped in CI environments where Tekla is not available. The model and the
selected objects are mocked, so no running Tekla model is needed.
"""

import importlib
import os
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.tekla.wrappers.model_object import TeklaAssembly, TeklaBoltGroup, TeklaPart, TeklaReinforcement, TeklaWeld

pp = importlib.import_module("tekla_mcp_server.providers.properties_provider")

NO_CHANGES = {"name": 0, "profile": 0, "udas": 0}


def _obj(spec: type, guid: str, **attrs: Any) -> MagicMock:
    """
    Build a mocked wrapped model object that passes `isinstance` checks for `spec`.

    Args:
        spec: Wrapper class to imitate
        guid: GUID of the object
        **attrs: Attributes or method mocks to set on the object

    Returns:
        The mocked object
    """
    obj = MagicMock(spec=spec)
    obj.guid = guid
    for key, value in attrs.items():
        setattr(obj, key, value)
    return obj


@pytest.fixture
def model() -> Iterator[MagicMock]:
    """Patch `TeklaModel` in the provider and return the mocked instance."""
    with patch.object(pp, "TeklaModel") as model_class:
        instance = model_class.return_value
        instance.commit_changes.return_value = True
        yield instance


def _run(tool: Any, objects: list[Any], **kwargs: Any) -> dict[str, Any]:
    """
    Call a tool with `objects` as the wrapped selection.

    Args:
        tool: Tool function to call
        objects: Wrapped objects the selection resolves to
        **kwargs: Tool arguments

    Returns:
        The tool's structured content
    """
    selection = MagicMock()
    selection.GetSize.return_value = len(objects)
    with patch.object(pp, "wrap_model_objects", return_value=objects):
        pp.TeklaModel.return_value.get_selected_objects.return_value = selection
        return tool(**kwargs).structured_content


class TestSetElementsPropertiesFailures:
    def test_exception_is_reported_per_element(self, model):
        ok = _obj(TeklaPart, "OK", set_properties=MagicMock(return_value={**NO_CHANGES, "name": 1}))
        bad = _obj(TeklaPart, "BAD", set_properties=MagicMock(side_effect=RuntimeError("boom")))

        result = _run(pp.set_elements_properties, [ok, bad], name="X")

        assert result["status"] == "partial"
        assert result["processed_count"] == 2
        assert result["modified_count"] == 1
        assert result["property_errors"] == [{"guid": "BAD", "errors": ["boom"]}]
        model.commit_changes.assert_called_once()

    def test_all_elements_failing_is_an_error(self, model):
        bad = _obj(TeklaAssembly, "BAD", set_properties=MagicMock(side_effect=RuntimeError("locked")))

        result = _run(pp.set_elements_properties, [bad], name="X")

        assert result["status"] == "error"
        assert result["modified_count"] == 0
        assert result["property_errors"] == [{"guid": "BAD", "errors": ["locked"]}]
        model.commit_changes.assert_not_called()

    def test_unsupported_objects_are_skipped_and_reported(self, model):
        part = _obj(TeklaPart, "P", set_properties=MagicMock(return_value={**NO_CHANGES, "name": 1}))
        rebar = _obj(TeklaReinforcement, "R")

        result = _run(pp.set_elements_properties, [part, rebar], name="X")

        assert result["status"] == "success"
        assert result["processed_count"] == 1
        assert result["skipped_objects"] == [{"guid": "R", "type": type(rebar).__name__}]

    def test_nothing_to_change_is_a_warning(self, model):
        part = _obj(TeklaPart, "P", set_properties=MagicMock(return_value=dict(NO_CHANGES)))

        result = _run(pp.set_elements_properties, [part])

        assert result["status"] == "warning"
        assert result["property_errors"] == []
        assert result["skipped_objects"] == []

    def test_bolt_gets_bolt_properties_and_catalog(self, model):
        catalog = [{"standard": "7990", "size": 16.0}]
        bolt = _obj(TeklaBoltGroup, "B", set_properties=MagicMock(return_value={"bolt_size": 1, "bolt_tolerance": 1}))

        with patch.object(pp, "get_all_bolt_items", return_value=catalog):
            result = _run(pp.set_elements_properties, [bolt], bolt_size=16.0, bolt_tolerance=3.0)

        kwargs = bolt.set_properties.call_args.kwargs
        assert kwargs["bolt_size"] == 16.0
        assert kwargs["bolt_tolerance"] == 3.0
        assert kwargs["bolt_catalog"] == catalog
        assert result["status"] == "success"
        assert result["changes_applied"]["bolt_size"] == 1
        assert result["changes_applied"]["bolt_tolerance"] == 1

    def test_catalog_not_read_without_standard_or_size(self, model):
        bolt = _obj(TeklaBoltGroup, "B", set_properties=MagicMock(return_value={"bolt_tolerance": 1}))

        with patch.object(pp, "get_all_bolt_items") as catalog:
            _run(pp.set_elements_properties, [bolt], bolt_tolerance=3.0)

        catalog.assert_not_called()


class TestBoltProperties:
    def test_flat_mode_returns_bolts(self, model):
        bolt = _obj(TeklaBoltGroup, "B", get_properties=MagicMock(return_value={"guid": "B", "bolt_extra_length": 5.0}))

        result = _run(pp.get_elements_properties, [bolt])

        assert result["status"] == "success"
        assert result["processed_count"] == 1
        assert result["bolts"] == [{"guid": "B", "bolt_extra_length": 5.0}]

    def test_snapshot_mode_returns_bolts(self, model):
        bolt = _obj(TeklaBoltGroup, "B", get_properties=MagicMock(return_value={"guid": "B", "bolt_tolerance": 2.0}))

        result = _run(pp.get_elements_properties, [bolt], mode="snapshot")

        assert result["status"] == "success"
        assert result["bolts"] == [{"guid": "B", "bolt_tolerance": 2.0}]


class TestWeldProperties:
    @pytest.mark.parametrize("mode", ["flat", "snapshot"])
    def test_welds_are_returned(self, model, mode):
        weld = _obj(TeklaWeld, "W", get_properties=MagicMock(return_value={"guid": "W", "weld_size_above": 5.0}))

        result = _run(pp.get_elements_properties, [weld], mode=mode)

        assert result["status"] == "success"
        assert result["processed_count"] == 1
        assert result["welds"] == [{"guid": "W", "weld_size_above": 5.0}]


class TestFlatPropertiesFailures:
    @pytest.fixture(autouse=True)
    def resolver(self) -> Iterator[MagicMock]:
        with patch.object(pp, "TemplateAttributeParser") as parser:
            parser.resolve_attributes.return_value = {"resolved": ["LENGTH"], "errors": []}
            yield parser

    def test_core_fallback_after_extra_properties_fail(self, model):
        part = _obj(TeklaPart, "P", get_properties=MagicMock(side_effect=[RuntimeError("bad LENGTH"), {"guid": "P"}]))

        result = _run(pp.get_elements_properties, [part], report_props_definitions=["length"])

        assert result["status"] == "partial"
        assert result["parts"] == [{"guid": "P"}]
        assert result["extraction_errors"] == [{"guid": "P", "error": "bad LENGTH"}]

    def test_unreadable_element_is_skipped_not_fatal(self, model):
        good = _obj(TeklaPart, "GOOD", get_properties=MagicMock(return_value={"guid": "GOOD"}))
        bad = _obj(TeklaPart, "BAD", get_properties=MagicMock(side_effect=RuntimeError("phase unreadable")))

        result = _run(pp.get_elements_properties, [bad, good], report_props_definitions=["length"])

        assert result["status"] == "partial"
        assert result["processed_count"] == 1
        assert result["parts"] == [{"guid": "GOOD"}]
        assert result["extraction_errors"] == [{"guid": "BAD", "error": "phase unreadable. Core properties also failed: phase unreadable"}]

    def test_no_retry_without_extra_properties(self, model):
        bad = _obj(TeklaPart, "BAD", get_properties=MagicMock(side_effect=RuntimeError("phase unreadable")))

        result = _run(pp.get_elements_properties, [bad])

        bad.get_properties.assert_called_once_with(None)
        assert result["status"] == "error"
        assert result["extraction_errors"] == [{"guid": "BAD", "error": "phase unreadable"}]


class TestEmptyUdaValue:
    @pytest.mark.parametrize(
        "value,expected",
        [("text", ""), (7, -2147483648), (1.5, float(-2147483648)), (True, None), (None, None), ([1], None)],
    )
    def test_empty_value(self, value, expected):
        result = pp._empty_uda_value(value)
        assert result == expected
        assert type(result) is type(expected)


class TestClearElementsUdasFailures:
    def test_counts_only_successful_writes(self, model):
        part = _obj(
            TeklaPart,
            "P",
            get_all_user_properties=MagicMock(return_value={"A": "x", "B": 3, "C": "y"}),
            set_user_property=MagicMock(side_effect=lambda key, _: key != "C"),
            modify=MagicMock(return_value=True),
        )

        result = _run(pp.clear_elements_udas, [part])

        assert result["status"] == "partial"
        assert result["cleared_udas_count"] == 2
        assert result["modified_parts_count"] == 1
        assert result["errors"] == [{"guid": "P", "errors": ["'C': SetUserProperty failed"]}]
        model.commit_changes.assert_called_once()

    def test_failed_modify_does_not_count(self, model):
        assembly = _obj(
            TeklaAssembly,
            "A",
            get_all_user_properties=MagicMock(return_value={"A": "x"}),
            set_user_property=MagicMock(return_value=True),
            modify=MagicMock(return_value=False),
        )

        result = _run(pp.clear_elements_udas, [assembly])

        assert result["status"] == "error"
        assert result["cleared_udas_count"] == 0
        assert result["modified_assemblies_count"] == 0
        assert result["errors"] == [{"guid": "A", "errors": ["Modify() failed"]}]
        model.commit_changes.assert_not_called()

    def test_unsupported_value_type_is_reported(self, model):
        part = _obj(
            TeklaPart,
            "P",
            get_all_user_properties=MagicMock(return_value={"FLAG": True}),
            set_user_property=MagicMock(return_value=True),
        )

        result = _run(pp.clear_elements_udas, [part])

        part.set_user_property.assert_not_called()
        assert result["status"] == "error"
        assert result["errors"] == [{"guid": "P", "errors": ["'FLAG': unsupported UDA value type bool"]}]

    def test_exception_is_reported_and_other_elements_continue(self, model):
        bad = _obj(TeklaPart, "BAD", get_all_user_properties=MagicMock(side_effect=RuntimeError("boom")))
        good = _obj(
            TeklaPart,
            "GOOD",
            get_all_user_properties=MagicMock(return_value={"A": "x"}),
            set_user_property=MagicMock(return_value=True),
            modify=MagicMock(return_value=True),
        )

        result = _run(pp.clear_elements_udas, [bad, good])

        assert result["status"] == "partial"
        assert result["cleared_udas_count"] == 1
        assert result["errors"] == [{"guid": "BAD", "errors": ["boom"]}]

    def test_clean_run_is_success(self, model):
        part = _obj(
            TeklaPart,
            "P",
            get_all_user_properties=MagicMock(return_value={"A": "x", "B": 2.5}),
            set_user_property=MagicMock(return_value=True),
            modify=MagicMock(return_value=True),
        )

        result = _run(pp.clear_elements_udas, [part], uda_names=["B"])

        part.set_user_property.assert_called_once_with("B", float(-2147483648))
        assert result["status"] == "success"
        assert result["cleared_udas_count"] == 1
        assert result["errors"] == []
