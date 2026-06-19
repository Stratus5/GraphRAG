"""Pure, deterministic scoring helpers for the frozen-fixture benchmark.

No Neo4j, no gateway, no LLM. Given recorded embeddings and retrieved
evidence, decide whether each gold question's required facts are present.
"""

import numpy as np


def cosine_topk(query_vec: list[float], chunk_vecs: list[list[float]], k: int) -> list[int]:
    """Indices of the top-k chunks by cosine similarity to query_vec.

    Ties broken by ascending index so the ranking is fully deterministic.
    """
    q = np.asarray(query_vec, dtype=float)
    m = np.asarray(chunk_vecs, dtype=float)
    qn = q / (np.linalg.norm(q) or 1.0)
    mn = m / (np.linalg.norm(m, axis=1, keepdims=True).clip(min=1e-12))
    sims = mn @ qn
    order = sorted(range(len(chunk_vecs)), key=lambda i: (-sims[i], i))
    return order[:k]


def evidence_text(chunk_texts: list[str], facts: list[dict]) -> str:
    """Flatten retrieved chunks + graph facts into one lowercased blob to match against."""
    parts = list(chunk_texts)
    for f in facts:
        parts.append(f"{f['subject']} {f['predicate']} {f['object']}")
    return "\n".join(parts).lower()


def score_required(required: list[str], evidence: str) -> tuple[int, int]:
    """(matched, total) — how many required lowercase substrings appear in evidence."""
    ev = evidence.lower()
    matched = sum(1 for r in required if r.lower() in ev)
    return matched, len(required)


def bridge_predicates(facts: list[dict], required: list[str]) -> list[str]:
    """Distinct predicates of facts whose subject or object touches a required entity.

    Surfaces the domain-vs-generic schema shape (spec finding #3): domain mode
    yields a single semantic edge (CTO_OF) while generic fragments it
    (WORKS_FOR + HAS_ROLE). Both reach the entity for retrieval; only the
    predicate set reveals whether the relation itself was captured.
    """
    req = [r.lower() for r in required]
    preds = {
        f["predicate"]
        for f in facts
        if any(r in (f["subject"] or "").lower() or r in (f["object"] or "").lower()
               for r in req)
    }
    return sorted(preds)
