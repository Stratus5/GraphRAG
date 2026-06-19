from unittest.mock import MagicMock, patch

from graphrag.retrieval import pipeline


def test_query_runs_vector_then_graph_then_answer():
    cfg = MagicMock()
    fake_client = MagicMock()
    hits = [{"chunk_id": "c1", "text": "t", "source": "s", "score": 0.9}]
    with patch("graphrag.retrieval.pipeline.vectorstore") as vs, \
         patch("graphrag.retrieval.pipeline.get_graph"), \
         patch("graphrag.retrieval.pipeline.get_embeddings"), \
         patch("graphrag.retrieval.pipeline.get_chat_model"), \
         patch("graphrag.retrieval.pipeline.expand", return_value=[{"subject": "a", "predicate": "P", "object": "b"}]) as exp, \
         patch("graphrag.retrieval.pipeline.answer", return_value="ANSWER") as ans:
        vs.connect.return_value = fake_client
        vs.search.return_value = hits
        out = pipeline.query(cfg, "q?", k=3, hops=2, tenant="demo")
    assert out == "ANSWER"
    vs.search.assert_called_once()
    # chunk_ids from vector hits are passed to expand
    assert exp.call_args.args[1] == ["c1"]
    assert ans.called
    fake_client.close.assert_called_once()
