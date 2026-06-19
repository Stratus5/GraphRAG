from demos import scenario


def test_distractor_chunks_present_and_edgeless():
    distractors = [c for c in scenario.CHUNKS if c["chunk_id"].startswith("distractor_")]
    assert len(distractors) == 2
    # distractor graph docs add no relationships (curated answers unaffected)
    dgds = [g for g in scenario.GRAPH if g["source_chunk_id"].startswith("distractor_")]
    assert dgds and all(g["relationships"] == [] for g in dgds)


def test_company_chunks_still_first_in_graph():
    # read_steps()/server slice GRAPH[:len(COMPANIES)] — company docs must stay first.
    head = scenario.GRAPH[:len(scenario.COMPANIES)]
    assert all(not g["source_chunk_id"].startswith("distractor_") for g in head)
