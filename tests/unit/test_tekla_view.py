"""
Unit tests for TeklaDrawingView wrapper.
"""

from unittest.mock import MagicMock, patch

import pytest

from tekla_mcp_server.tekla.wrappers.view import TeklaDrawingView


@pytest.fixture
def mock_view() -> MagicMock:
    """Return a minimal mock DrawingView."""
    view = MagicMock()
    view.Origin.X = 100.0
    view.Origin.Y = 200.0
    view.Attributes = MagicMock(Scale=0.5)
    view.IsSheet = False
    view.Width = 500.0
    view.Height = 300.0
    view.Modify.return_value = True
    view.Delete.return_value = True
    view.ViewType = "FrontView"
    return view


@pytest.fixture
def wrapper(mock_view: MagicMock) -> TeklaDrawingView:
    return TeklaDrawingView(mock_view)


class TestOrigin:
    def test_getter_returns_tuple(self, wrapper: TeklaDrawingView):
        ox, oy = wrapper.origin
        assert isinstance(ox, float)
        assert isinstance(oy, float)

    def test_getter_values(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        mock_view.Origin.X = 123.45
        mock_view.Origin.Y = 678.91
        assert wrapper.origin == (123.5, 678.9)

    def test_setter_creates_point(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        with patch("tekla_mcp_server.tekla.wrappers.view.Point") as mock_point:
            wrapper.origin = (300.0, 400.0)
            mock_point.assert_called_once_with(300.0, 400.0, 0)
            assert mock_view.Origin == mock_point.return_value


class TestModify:
    def test_returns_true_on_success(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        assert wrapper.modify() is True

    def test_returns_false_on_failure(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        mock_view.Modify.return_value = False
        assert wrapper.modify() is False

    def test_forwards_call(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        wrapper.modify()
        mock_view.Modify.assert_called_once_with()


class TestDelete:
    def test_returns_true_on_success(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        assert wrapper.delete() is True

    def test_returns_false_on_failure(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        mock_view.Delete.return_value = False
        assert wrapper.delete() is False

    def test_forwards_call(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        wrapper.delete()
        mock_view.Delete.assert_called_once_with()


class TestSetScale:
    def test_sets_scale_and_modifies(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        assert wrapper.set_scale(1.0) is True
        assert mock_view.Attributes.Scale == 1.0
        mock_view.Modify.assert_called_once_with()

    def test_returns_false_when_modify_fails(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        mock_view.Modify.return_value = False
        assert wrapper.set_scale(0.25) is False

    def test_reassigns_attributes(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        wrapper.set_scale(2.0)
        assert mock_view.Attributes.Scale == 2.0

    def test_attributes_setter_was_called(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        orig_attrs = mock_view.Attributes
        orig_attrs.Scale = 3.0
        wrapper.set_scale(3.0)
        assert mock_view.Attributes.Scale == 3.0


class TestViewKeyFallback:
    def test_fallback_to_origin_on_reflection_failure(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        with patch.object(mock_view.GetType(), "GetProperty", return_value=None):
            key = wrapper.view_key
            assert key == "FrontView_100_200"

    def test_fallback_to_origin_on_reflection_exception(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        mock_view.GetType().GetProperty.side_effect = Exception("boom")
        key = wrapper.view_key
        assert key == "FrontView_100_200"

    def test_includes_identifier_id_when_available(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        mock_id = MagicMock()
        mock_id.ID = 42
        mock_view.GetType().GetProperty.return_value.GetValue.return_value = mock_id
        key = wrapper.view_key
        assert key == "FrontView_42"


class TestViewKeyStability:
    def test_different_views_have_different_keys(self, mock_view: MagicMock):
        v1 = MagicMock()
        v1.Origin.X = 100.0
        v1.Origin.Y = 200.0
        v1.ViewType = "FrontView"

        v2 = MagicMock()
        v2.Origin.X = 300.0
        v2.Origin.Y = 400.0
        v2.ViewType = "SectionView"

        with patch.object(v1.GetType(), "GetProperty", return_value=None), patch.object(v2.GetType(), "GetProperty", return_value=None):
            w1 = TeklaDrawingView(v1)
            w2 = TeklaDrawingView(v2)
            assert w1.view_key != w2.view_key


class TestToDict:
    def test_returns_dict_with_all_keys(self, wrapper: TeklaDrawingView):
        d = wrapper.to_dict()
        expected_keys = {"name", "view_key", "view_type", "scale", "is_sheet", "origin_x", "origin_y", "width", "height"}
        assert set(d.keys()) == expected_keys

    def test_values_match_properties(self, wrapper: TeklaDrawingView, mock_view: MagicMock):
        d = wrapper.to_dict()
        assert d["scale"] == mock_view.Attributes.Scale
        assert d["is_sheet"] == mock_view.IsSheet
        assert d["origin_x"] == round(mock_view.Origin.X, 1)
        assert d["origin_y"] == round(mock_view.Origin.Y, 1)
        assert d["width"] == round(mock_view.Width, 1)
        assert d["height"] == round(mock_view.Height, 1)
