from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_experimental.graph_transformers import LLMGraphTransformer
from tenacity import retry, stop_after_attempt, wait_exponential


def build_transformer(
    llm: BaseChatModel,
    allowed_nodes: list[str],
    allowed_relationships: list[str],
) -> LLMGraphTransformer:
    """Empty lists => generic auto-derive mode; populated => domain mode."""
    return LLMGraphTransformer(
        llm=llm,
        allowed_nodes=allowed_nodes,
        allowed_relationships=allowed_relationships,
        # The FC gateway (fc: -> OpenRouter) does not pass tool calls or
        # response_format=json_schema through, so the default function-calling
        # extraction path fails. Prompt-based mode parses JSON from content.
        ignore_tool_usage=True,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
def _convert(transformer: LLMGraphTransformer, docs: list[Document]):
    return transformer.convert_to_graph_documents(docs)


def extract_graph(
    transformer: LLMGraphTransformer,
    chunks: list[Document],
    on_progress=None,
):
    """Extract per chunk; isolate failures so one bad chunk does not abort the run."""
    graph_docs = []
    failures = 0
    for i, chunk in enumerate(chunks):
        if on_progress:
            on_progress(i)
        try:
            graph_docs.extend(_convert(transformer, [chunk]))
        except Exception as exc:
            failures += 1
            print(f"WARN: extraction failed for chunk "
                  f"{chunk.metadata.get('chunk_id')}: {exc}")
    if on_progress:
        on_progress(len(chunks))
    return graph_docs, failures
