"""
Unit tests for component_props_mapper module.
"""

from unittest.mock import MagicMock, patch

import pytest

from tekla_mcp_server.tekla.component_props_mapper import ComponentPropsMapper, map_properties


class TestConvertType:
    @pytest.mark.parametrize(
        "value,expected_type,expected",
        [
            (10, "int", 10),
            (10.5, "int", 10),
            (10.9, "int", 10),
            (-5, "int", -5),
            ("10", "int", 10),
            ("10.5", "int", 10),
            ("-7", "int", -7),
            ("abc", "int", "abc"),
            (10.5, "float", 10.5),
            (10, "float", 10.0),
            ("10.5", "float", 10.5),
            ("10", "float", 10.0),
            ("abc", "float", "abc"),
            ("abc", "string", "abc"),
            (10, "string", "10"),
            (None, "string", "None"),
        ],
    )
    def test_convert_type(self, value, expected_type, expected):
        result = ComponentPropsMapper._convert_type(value, expected_type)
        assert result == expected


class TestMapKeys:
    def test_success(self):
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2], dtype=np.float32)

        mapper = ComponentPropsMapper()
        mapper._model = mock_model
        mapper._schema_cache["Border Rebar"] = {
            "schema": {"SB_SIZE": {"description": "rebar size", "type": "int"}},
            "config_keys": ["SB_SIZE"],
            "desc_to_config": {"rebar size": ("SB_SIZE", [0.1, 0.2])},
        }
        result = mapper.map_keys({"rebar size": 10}, "Border Rebar")
        assert result == {"SB_SIZE": 10, "unmapped_keys": []}

    def test_no_match_below_threshold(self):
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, -0.9], dtype=np.float32)

        mapper = ComponentPropsMapper()
        mapper._model = mock_model
        mapper._schema_cache["Border Rebar"] = {
            "schema": {"SB_SIZE": {"description": "rebar size", "type": "int"}},
            "config_keys": ["SB_SIZE"],
            "desc_to_config": {"rebar size": ("SB_SIZE", [0.9, 0.9])},
        }
        result = mapper.map_keys({"xyz": 10}, "Border Rebar")
        assert result == {"unmapped_keys": ["xyz"]}

    def test_multiple_keys(self):
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.side_effect = [
            np.array([0.1, 0.2], dtype=np.float32),
            np.array([0.3, 0.4], dtype=np.float32),
        ]

        mapper = ComponentPropsMapper()
        mapper._model = mock_model
        mapper._schema_cache["Border Rebar"] = {
            "schema": {
                "SB_SIZE": {"description": "rebar size", "type": "int"},
                "SB_CLASS": {"description": "rebar class", "type": "string"},
            },
            "config_keys": ["SB_SIZE", "SB_CLASS"],
            "desc_to_config": {
                "rebar size": ("SB_SIZE", [0.1, 0.2]),
                "rebar class": ("SB_CLASS", [0.3, 0.4]),
            },
        }
        result = mapper.map_keys({"rebar size": 10, "rebar class": "A"}, "Border Rebar")
        assert result["SB_SIZE"] == 10
        assert result["SB_CLASS"] == "A"
        assert result["unmapped_keys"] == []

    def test_empty_user_dict(self):
        import numpy as np

        mapper = ComponentPropsMapper()
        mapper._model = MagicMock()
        mapper._schema_cache["Border Rebar"] = {
            "schema": {"SB_SIZE": {"description": "rebar size", "type": "int"}},
            "config_keys": ["SB_SIZE"],
            "desc_to_config": {"rebar size": ("SB_SIZE", np.array([0.1, 0.2], dtype=np.float32))},
        }
        result = mapper.map_keys({}, "Border Rebar")
        assert result == {"unmapped_keys": []}

    def test_partial_mapping(self):
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.side_effect = [
            np.array([0.1, 0.2], dtype=np.float32),
            np.array([0.1, -0.9], dtype=np.float32),
        ]

        mapper = ComponentPropsMapper()
        mapper._model = mock_model
        mapper._schema_cache["Border Rebar"] = {
            "schema": {
                "SB_SIZE": {"description": "rebar size", "type": "int"},
            },
            "config_keys": ["SB_SIZE"],
            "desc_to_config": {
                "rebar size": ("SB_SIZE", [0.1, 0.2]),
            },
        }
        result = mapper.map_keys({"rebar size": 10, "xyzfoobar": "value"}, "Border Rebar")
        assert result["SB_SIZE"] == 10
        assert result["unmapped_keys"] == ["xyzfoobar"]


class TestMapAttributes:
    @patch("tekla_mcp_server.tekla.component_props_mapper.ComponentPropsMapper")
    def test_mapper_unavailable(self, mock_mapper_class):
        mock_mapper_class.side_effect = Exception("Model not available")
        result = map_properties({"rebar size": 10}, "Border Rebar")
        assert result == {}

    @patch("tekla_mcp_server.tekla.component_props_mapper.ComponentPropsMapper.map_keys")
    @patch("tekla_mcp_server.tekla.component_props_mapper.ComponentPropsMapper")
    def test_calls_mapper(self, mock_mapper_class, mock_map_keys):
        mock_mapper = MagicMock()
        mock_mapper_class.return_value = mock_mapper
        mock_mapper.map_keys.return_value = {"SB_SIZE": 10, "unmapped_keys": []}
        result = map_properties({"rebar size": 10}, "Border Rebar")
        mock_mapper.map_keys.assert_called_once_with({"rebar size": 10}, "Border Rebar")
        assert result == {"SB_SIZE": 10, "unmapped_keys": []}
