"""
AXIOM AgPP — Semantic Router

Local semantic routing using MiniLM-L6-v2 (30MB model, fully offline).
No API key. No vendor dependency. Runs on CPU in <50ms per query.

Maps API descriptions/URLs to pre-defined budget categories using
cosine similarity of sentence embeddings. If the best match score
is below the semantic_threshold (default 0.7), the payment is BLOCKED
as an unrecognized API category.

This prevents agents from paying for APIs outside their approved
budget categories — even if the agent's prompt is manipulated.

Categories:
    weather, financial_data, news, search, maps, translation,
    image_gen, database, compute, communication

Usage:
    from axiom_agpp.semantic import route_api
    category, score = route_api("weather forecast API", budget_map)
    if category is None:
        raise SemanticMismatchError("Unrecognized API category")
"""

import logging
from typing import Optional, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
#  MODEL SINGLETON
# ─────────────────────────────────────────────────────────────────

_model: Optional[SentenceTransformer] = None


def get_model() -> SentenceTransformer:
    """
    Lazy-load the MiniLM-L6-v2 sentence transformer model.

    The model is ~30MB and runs entirely offline on CPU.
    First call downloads the model (cached for subsequent calls).
    """
    global _model
    if _model is None:
        logger.info("Loading semantic model: all-MiniLM-L6-v2...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Semantic model loaded successfully")
    return _model


def embed(text: str) -> np.ndarray:
    """
    Compute normalized sentence embedding for a text string.

    Args:
        text: Input text (API description, URL, etc.)

    Returns:
        Normalized embedding vector (384 dimensions for MiniLM).
    """
    return get_model().encode(text, normalize_embeddings=True)


# ─────────────────────────────────────────────────────────────────
#  SEMANTIC CATEGORIES
# ─────────────────────────────────────────────────────────────────

SEMANTIC_CATEGORIES = [
    ("weather", "weather forecast temperature rain wind climate meteorology"),
    ("financial_data", "stock price market index fund financial equity trading"),
    ("news", "news article headline current events journalism press media"),
    ("search", "web search query information lookup retrieval google bing"),
    ("maps", "location map directions geocode coordinates navigation routing"),
    ("translation", "translate language text localization multilingual i18n"),
    ("image_gen", "image generation diffusion visual creative art illustration"),
    ("database", "database query sql records storage retrieval data warehouse"),
    ("compute", "cloud compute processing gpu inference model training serverless"),
    ("communication", "email message notification send contact sms push alert"),
]

# Cache for category embeddings (computed once on first use)
_cat_embs: Optional[dict] = None


def get_category_embeddings() -> dict:
    """
    Compute and cache embeddings for all semantic categories.

    Returns:
        Dict of {category_label: embedding_vector}.
    """
    global _cat_embs
    if _cat_embs is None:
        model = get_model()
        _cat_embs = {
            label: model.encode(desc, normalize_embeddings=True)
            for label, desc in SEMANTIC_CATEGORIES
        }
        logger.info("Category embeddings computed for %d categories", len(_cat_embs))
    return _cat_embs


# ─────────────────────────────────────────────────────────────────
#  MAIN ROUTING FUNCTION
# ─────────────────────────────────────────────────────────────────

def route_api(
    api_description: str,
    budget_map: dict,
    threshold: float = 0.7,
) -> Tuple[Optional[str], float]:
    """
    Route an API description to the best matching budget category.

    Returns (None, score) if:
        - The best match score is below the threshold (unrecognized API)
        - The best matching category is not in the budget_map (not approved)

    Args:
        api_description: Text describing the API (URL, name, description, etc.)
        budget_map:      Dict of {category: max_spend_algo} from policy.yaml
        threshold:       Minimum cosine similarity required (default 0.7)

    Returns:
        Tuple of (matched_category, score):
            matched_category — category string if matched, None if blocked
            score            — cosine similarity score (0-1)
    """
    emb = embed(api_description)
    cat_embs = get_category_embeddings()

    best_cat: Optional[str] = None
    best_score: float = 0.0

    for cat, vec in cat_embs.items():
        similarity = float(np.dot(emb, vec))
        if similarity > best_score:
            best_score = similarity
            best_cat = cat

    # Check threshold and budget map
    if best_score < threshold:
        logger.warning(
            "Semantic MISMATCH — '%s' best match '%s' at %.3f (threshold=%.2f) → BLOCKED",
            api_description[:50],
            best_cat,
            best_score,
            threshold,
        )
        return None, best_score

    if best_cat not in budget_map:
        logger.warning(
            "Category '%s' not in budget_map → BLOCKED (score=%.3f)",
            best_cat,
            best_score,
        )
        return None, best_score

    logger.info(
        "Semantic match: '%s' → category '%s' (score=%.3f, budget=%.2f ALGO)",
        api_description[:50],
        best_cat,
        best_score,
        budget_map.get(best_cat, 0),
    )

    return best_cat, best_score


def get_all_scores(api_description: str) -> list[Tuple[str, float]]:
    """
    Get similarity scores for ALL categories (useful for debugging).

    Args:
        api_description: Text describing the API.

    Returns:
        List of (category, score) tuples, sorted by score descending.
    """
    emb = embed(api_description)
    cat_embs = get_category_embeddings()

    scores = [
        (cat, float(np.dot(emb, vec)))
        for cat, vec in cat_embs.items()
    ]
    return sorted(scores, key=lambda x: x[1], reverse=True)
