"""Local cross-encoder rerank of graph facts against the question.

Optional — requires `sentence-transformers` + a local BGE cross-encoder (no
gateway, no sidecar). If the dependency or model isn't available, callers fall
back to the expander's deterministic order. The model is loaded once and cached.
"""

from functools import lru_cache


def rerank_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


def _fact_text(f: dict) -> str:
    return f"{f['subject']} {f['predicate']} {f['object']}"


@lru_cache(maxsize=2)
def _model(name: str):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(name)


def rerank_facts(question: str, facts: list[dict], top_n: int,
                 model_name: str = "BAAI/bge-reranker-base") -> list[dict]:
    """Return the top_n facts most relevant to `question`, by cross-encoder score.

    Deterministic: ties (and float jitter is avoided as the tiebreak) are broken
    by (subject, predicate, object), so the kept set is stable across runs.
    """
    if not facts:
        return []
    model = _model(model_name)
    scores = model.predict([(question, _fact_text(f)) for f in facts])
    ranked = sorted(
        zip(facts, scores),
        key=lambda fs: (-float(fs[1]), fs[0]["subject"], fs[0]["predicate"], fs[0]["object"]),
    )
    return [f for f, _ in ranked[:top_n]]
