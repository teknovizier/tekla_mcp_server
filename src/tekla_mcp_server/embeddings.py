"""
Embedding utilities for semantic search and similarity matching.
"""

from typing import TYPE_CHECKING

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_embedding_model: "SentenceTransformer | None" = None


def get_compute_device() -> str:
    """Safely determine compute device (CPU or CUDA)."""
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        logger.warning("torch not available, using CPU")
        return "cpu"


def is_embeddings_enabled() -> bool:
    """Check if embeddings/semantic search is enabled in config."""
    config = get_config()
    return config.embeddings_enabled


def _ensure_loaded() -> None:
    """Lazily load the embedding model."""
    global _embedding_model
    if _embedding_model is None:
        logger.info("Importing SentenceTransformer...")
        from sentence_transformers import SentenceTransformer

        config = get_config()
        model_name = config.embedding_model
        if not model_name:
            raise ImportError("Attribute mapper configuration missing. Add 'embeddings' section to config with 'embedding_model'.")
        logger.info("Loading embedding model: %s", model_name)
        _embedding_model = SentenceTransformer(model_name)
        logger.info("Embedding model loaded")


def get_embedding_model() -> "SentenceTransformer":
    """Returns cached embedding model."""
    _ensure_loaded()
    assert _embedding_model is not None
    return _embedding_model
