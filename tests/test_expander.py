from graphrag.retrieval.expander import build_expansion_query


def test_expansion_query_includes_hops():
    query = build_expansion_query(hops=2)
    assert "*1..2" in query
    assert "$chunk_ids" in query


def test_expansion_query_default_one_hop():
    query = build_expansion_query()
    assert "*1..1" in query


def test_expansion_query_is_tenant_scoped():
    query = build_expansion_query()
    assert "c.tenant = $tenant" in query
    assert "{tenant: $tenant}" in query  # entities matched on the tenant key


def test_expansion_query_is_cleaned_and_bounded():
    query = build_expansion_query()
    # entity-only traversal (no MENTIONS/HAS_CHUNK or id-less nodes)
    assert "n:__Entity__" in query
    assert "subject IS NOT NULL AND object IS NOT NULL" in query
    # super-node cap + deterministic ordered budget
    assert "$max_degree" in query
    assert "ORDER BY hop, subject, predicate, object" in query
    assert "LIMIT $limit" in query
