import hashlib

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_documents(docs: list[Document], size: int, overlap: int) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap)
    chunks = splitter.split_documents(docs)
    for i, chunk in enumerate(chunks):
        source = chunk.metadata.get("source", "unknown")
        raw = f"{source}:{i}:{chunk.page_content}".encode()
        chunk.metadata["chunk_id"] = hashlib.sha1(raw).hexdigest()
        # langchain-neo4j prefers metadata["id"] for the source Document id;
        # aligning it with chunk_id lets us link Chunk nodes to extracted entities.
        chunk.metadata["id"] = chunk.metadata["chunk_id"]
    return chunks
