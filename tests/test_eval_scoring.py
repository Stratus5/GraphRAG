import numpy as np

from eval.scoring import bridge_predicates, cosine_topk, evidence_text, score_required


def test_cosine_topk_ranks_by_similarity():
    query = [1.0, 0.0]
    chunks = [
        [0.0, 1.0],   # orthogonal  -> sim 0
        [1.0, 0.0],   # identical    -> sim 1
        [0.9, 0.1],   # close        -> high
    ]
    assert cosine_topk(query, chunks, k=2) == [1, 2]


def test_cosine_topk_tie_breaks_by_index():
    query = [1.0, 0.0]
    chunks = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]
    assert cosine_topk(query, chunks, k=2) == [0, 1]


def test_cosine_topk_caps_at_available():
    assert cosine_topk([1.0, 0.0], [[1.0, 0.0]], k=5) == [0]


def test_evidence_text_includes_chunks_and_facts():
    text = evidence_text(
        ["Acme Corp is in Boston."],
        [{"subject": "Maria Garcia", "predicate": "CTO_OF", "object": "Acme Corp"}],
    )
    assert "boston" in text
    assert "maria garcia" in text
    assert "cto_of" in text


def test_evidence_text_handles_no_facts():
    text = evidence_text(["Acme Corp is in Boston."], [])
    assert "boston" in text


def test_score_required_counts_present_substrings():
    evidence = "maria garcia is the cto of acme corp"
    matched, total = score_required(["maria garcia", "beta labs"], evidence)
    assert (matched, total) == (1, 2)


def test_score_required_is_case_insensitive():
    matched, total = score_required(["Boston"], "acme corp is in boston")
    assert (matched, total) == (1, 1)


def test_bridge_predicates_collects_edges_touching_required():
    facts = [
        {"subject": "Maria Garcia", "predicate": "CTO_OF", "object": "Acme Corp"},
        {"subject": "Maria Garcia", "predicate": "HAS_ROLE", "object": "Chief Technology Officer"},
        {"subject": "Acme Corp", "predicate": "ACQUIRED", "object": "Beta Labs"},
    ]
    assert bridge_predicates(facts, ["maria garcia"]) == ["CTO_OF", "HAS_ROLE"]


def test_bridge_predicates_empty_when_no_match():
    facts = [{"subject": "Acme Corp", "predicate": "ACQUIRED", "object": "Beta Labs"}]
    assert bridge_predicates(facts, ["maria garcia"]) == []


def test_bridge_predicates_tolerates_none_endpoints():
    # The expander can return facts with a null endpoint (MENTIONS to an id-less node).
    facts = [
        {"subject": "Maria Garcia", "predicate": "MENTIONS", "object": None},
        {"subject": "Maria Garcia", "predicate": "CTO_OF", "object": "Acme Corp"},
    ]
    assert bridge_predicates(facts, ["maria garcia"]) == ["CTO_OF", "MENTIONS"]
