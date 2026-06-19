from graphrag import vectorstore


def test_ensure_collection_is_idempotent(weaviate_available):
    client = weaviate_available
    client.collections.delete(vectorstore.COLLECTION)  # clean slate
    vectorstore.ensure_collection(client)
    assert client.collections.exists(vectorstore.COLLECTION)
    vectorstore.ensure_collection(client)  # second call must not raise
    assert client.collections.exists(vectorstore.COLLECTION)
