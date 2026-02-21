"""
Embedding utilities for semantic search and similarity matching.
"""

from typing import TYPE_CHECKING

from tekla_mcp_server.config import get_config
from tekla_mcp_server.init import logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_embedding_model: "SentenceTransformer | None" = None
_embedding_threshold: float | None = None


def is_embeddings_enabled() -> bool:
    """Check if embeddings/semantic search is enabled in config."""
    config = get_config()
    return config.embeddings_enabled


def _ensure_loaded() -> None:
    """Lazily load the embedding model and threshold."""
    global _embedding_model, _embedding_threshold
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        config = get_config()
        model_name = config.embedding_model
        threshold = config.embedding_threshold
        if not model_name or threshold is None:
            raise ImportError("Attribute mapper configuration missing. Add 'embeddings' section to config with 'embedding_model' and 'embedding_threshold'.")
        logger.info("Loading embedding model: %s", model_name)
        _embedding_model = SentenceTransformer(model_name)
        _embedding_threshold = threshold
        logger.info("Embedding model loaded")


def get_embedding_model_and_threshold() -> tuple["SentenceTransformer", float]:
    """Returns cached embedding model and threshold."""
    _ensure_loaded()
    assert _embedding_model is not None
    assert _embedding_threshold is not None
    return _embedding_model, _embedding_threshold


def get_embedding_model() -> "SentenceTransformer":
    """Returns cached embedding model."""
    _ensure_loaded()
    assert _embedding_model is not None
    return _embedding_model


def get_embedding_threshold() -> float:
    """Returns embedding threshold."""
    _ensure_loaded()
    assert _embedding_threshold is not None
    return _embedding_threshold


def semantic_match(
    user_input: str,
    candidates_embeddings: dict[str, list[float]],
    threshold: float,
    model: "SentenceTransformer",
) -> tuple[str | None, float]:
    """
    Perform semantic similarity search to find best matching key.

    Args:
        user_input: User-provided input string
        candidates_embeddings: Dict of candidate names to their embeddings
        threshold: Minimum similarity score threshold
        model: Sentence transformer model for encoding

    Returns:
        Tuple of (best_match_key, best_score) or (None, 0.0) if no match
    """
    from sentence_transformers import util

    user_embedding = model.encode(user_input)

    # Collect all scores
    all_scores = []
    for key, embedding in candidates_embeddings.items():
        score = util.cos_sim(user_embedding, embedding).item()
        all_scores.append((key, score))

    # Sort by score descending
    all_scores.sort(key=lambda x: x[1], reverse=True)

    # Log top 5 for debugging
    top5 = all_scores[:5]
    top5_str = ", ".join(f"{k} ({s:.2f})" for k, s in top5)
    logger.debug("Semantic match for '%s': top 5 = [%s]", user_input, top5_str)

    # Find best match above threshold
    best_match = None
    best_score = 0.0
    for key, score in all_scores:
        if score >= threshold and score > best_score:
            best_score = score
            best_match = key

    return best_match, best_score
