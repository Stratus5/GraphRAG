from graphrag.retrieval.service import retrieve


class FakeGraph:
    def __init__(self, ret):
        self.ret = ret
        self.calls = []

    def query(self, q, params=None):
        self.calls.append((q, params))
        return self.ret


def test_retrieve_expands_given_chunks():
    facts = [{"subject": "Acme Corp", "predicate": "ACQUIRED", "object": "Beta Labs"}]
    g = FakeGraph(facts)
    out = retrieve(g, "tenantA", ["c1", "c2"], hops=2)
    assert out == facts
    # graph-only: the single query is the expansion, scoped to chunk_ids + tenant.
    assert len(g.calls) == 1
    cypher, params = g.calls[0]
    assert "*1..2" in cypher
    assert params["chunk_ids"] == ["c1", "c2"]
    assert params["tenant"] == "tenantA"


def test_retrieve_empty_chunks_short_circuits():
    g = FakeGraph([{"subject": "x", "predicate": "y", "object": "z"}])
    assert retrieve(g, "tenantA", [], hops=2) == []
    assert g.calls == []
