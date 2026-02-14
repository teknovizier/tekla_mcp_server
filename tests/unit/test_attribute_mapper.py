"""
Unit tests for attribute_mapper module.
"""

from unittest.mock import MagicMock, patch

import os
import pytest

from attribute_mapper import AttributeMapper, map_attributes


class TestCosineSimilarity:
    def test_identical_vectors(self):
        result = AttributeMapper._cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert result == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        result = AttributeMapper._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert result == pytest.approx(0.0)

    def test_opposite_vectors(self):
        result = AttributeMapper._cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert result == pytest.approx(-1.0)

    def test_zero_vector(self):
        result = AttributeMapper._cosine_similarity([0.0, 0.0], [1.0, 1.0])
        assert result == 0.0


class TestConvertType:
    def test_int_to_int(self):
        assert AttributeMapper._convert_type(10, "int") == 10

    def test_float_to_float(self):
        assert AttributeMapper._convert_type(10.5, "float") == 10.5

    def test_string_to_int(self):
        assert AttributeMapper._convert_type("10", "int") == 10

    def test_string_to_float(self):
        assert AttributeMapper._convert_type("10.5", "float") == 10.5

    def test_string_to_string(self):
        assert AttributeMapper._convert_type("abc", "string") == "abc"


class TestMapKeys:
    @pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
    @patch.object(AttributeMapper, "_ensure_model_loaded")
    def test_success(self, mock_ensure):
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1, 0.2])

        mapper = AttributeMapper(model_name="test", threshold=0.3)
        mapper._model = mock_model
        mapper._schema_cache["Border Rebar"] = {
            "schema": {"SB_SIZE": {"description": "rebar size", "type": "int"}},
            "config_keys": ["SB_SIZE"],
            "embeddings": {"SB_SIZE": [0.1, 0.2]},
        }
        result = mapper.map_keys({"rebar size": 10}, "Border Rebar")
        assert result == {"SB_SIZE": 10}

    @pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
    @patch.object(AttributeMapper, "_ensure_model_loaded")
    def test_no_match_below_threshold(self, mock_ensure):
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1, -0.9])

        mapper = AttributeMapper(model_name="test", threshold=0.8)
        mapper._model = mock_model
        mapper._schema_cache["Border Rebar"] = {
            "schema": {"SB_SIZE": {"description": "rebar size", "type": "int"}},
            "config_keys": ["SB_SIZE"],
            "embeddings": {"SB_SIZE": [0.9, 0.9]},
        }
        result = mapper.map_keys({"xyz": 10}, "Border Rebar")
        assert result == {}

    @pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
    @patch.object(AttributeMapper, "_ensure_model_loaded")
    def test_multiple_keys(self, mock_ensure):
        mock_model = MagicMock()
        mock_model.encode.side_effect = [
            MagicMock(tolist=lambda: [0.1, 0.2]),
            MagicMock(tolist=lambda: [0.3, 0.4]),
        ]

        mapper = AttributeMapper(model_name="test", threshold=0.3)
        mapper._model = mock_model
        mapper._schema_cache["Border Rebar"] = {
            "schema": {
                "SB_SIZE": {"description": "rebar size", "type": "int"},
                "SB_CLASS": {"description": "rebar class", "type": "string"},
            },
            "config_keys": ["SB_SIZE", "SB_CLASS"],
            "embeddings": {"SB_SIZE": [0.1, 0.2], "SB_CLASS": [0.3, 0.4]},
        }
        result = mapper.map_keys({"rebar size": 10, "rebar class": "A"}, "Border Rebar")
        assert result["SB_SIZE"] == 10
        assert result["SB_CLASS"] == "A"

    @pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
    @patch.object(AttributeMapper, "_ensure_model_loaded")
    def test_no_schema(self, mock_ensure):
        mapper = AttributeMapper(model_name="test", threshold=0.3)
        mapper._model = MagicMock()
        result = mapper.map_keys({"rebar size": 10}, "Unknown")
        assert result == {}

    @pytest.mark.skipif(os.getenv("CI") == "true", reason="Tekla not available in CI")
    @patch.object(AttributeMapper, "_ensure_model_loaded")
    def test_empty_user_dict(self, mock_ensure):
        mapper = AttributeMapper(model_name="test", threshold=0.3)
        mapper._model = MagicMock()
        mapper._schema_cache["Border Rebar"] = {
            "schema": {"SB_SIZE": {"description": "rebar size", "type": "int"}},
            "config_keys": ["SB_SIZE"],
            "embeddings": {"SB_SIZE": [0.1, 0.2]},
        }
        result = mapper.map_keys({}, "Border Rebar")
        assert result == {}


class TestMapAttributes:
    @patch("attribute_mapper.get_attribute_mapper")
    def test_mapper_unavailable(self, mock_get):
        mock_get.return_value = None
        result = map_attributes({"rebar size": 10}, "Border Rebar")
        assert result == {}

    @patch("attribute_mapper.AttributeMapper.map_keys")
    @patch("attribute_mapper.get_attribute_mapper")
    def test_calls_mapper(self, mock_get, mock_map_keys):
        mock_mapper = MagicMock()
        mock_get.return_value = mock_mapper
        mock_mapper.map_keys.return_value = {"SB_SIZE": 10}
        result = map_attributes({"rebar size": 10}, "Border Rebar")
        mock_mapper.map_keys.assert_called_once_with({"rebar size": 10}, "Border Rebar")
        assert result == {"SB_SIZE": 10}
