"""
Embedding utilities for semantic search and similarity matching.
"""

from functools import lru_cache

from typing import TYPE_CHECKING

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


def is_embeddings_enabled() -> bool:
    """
    Check if embeddings/semantic search is enabled in config.

    Returns:
        True if embeddings are enabled, False otherwise
    """
    config = get_config()
    return config.embeddings_enabled


def check_embeddings_ready() -> bool:
    """
    Check embeddings configuration at startup.

    Checks:
    1. If embedding_model is configured
    2. If sentence_transformers package is installed

    Returns:
        True if all checks pass

    Raises:
        ValueError: If embeddings is enabled but no model is configured
        ImportError: If embeddings is enabled but sentence_transformers is not installed
    """
    if not get_config().embedding_model:
        raise ValueError("Embeddings are enabled but 'embedding_model' is not configured.")

    try:
        logger.info("Importing SentenceTransformer...")
        import sentence_transformers  # noqa: F401
    except ImportError as e:
        raise ImportError("Embeddings are enabled but 'sentence_transformers' package is not installed.") from e

    return True


@lru_cache
def get_embedding_model() -> "SentenceTransformer":
    """
    Lazily load and cache embedding model.

    Returns:
        The SentenceTransformer model instance

    Raises:
        ImportError: If the embedding model cannot be loaded
    """
    from sentence_transformers import SentenceTransformer

    config = get_config()
    model_name = config.embedding_model

    if not model_name:
        raise ValueError("embedding_model missing in config")

    logger.info("Loading embedding model: %s", model_name)
    return SentenceTransformer(model_name)


def get_compute_device() -> str:
    """
    Safely determine the compute device (CPU or CUDA).

    Returns:
        "cuda" if CUDA is available, "cpu" otherwise
    """
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        logger.warning("torch not available, using CPU")
        return "cpu"
