from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document

SUFFIX_LOADERS = {".txt": TextLoader, ".md": TextLoader, ".pdf": PyPDFLoader}


def load_folder(folder: Path | str) -> list[Document]:
    folder = Path(folder)
    docs: list[Document] = []
    for path in sorted(folder.rglob("*")):
        loader_cls = SUFFIX_LOADERS.get(path.suffix.lower())
        if not path.is_file() or loader_cls is None:
            continue
        try:
            loaded = loader_cls(str(path)).load()
            for d in loaded:
                d.metadata["source"] = str(path)
            docs.extend(loaded)
        except Exception as exc:  # isolate per-file failures
            print(f"WARN: skipping {path}: {exc}")
    return docs
