FROM python:3.11-slim
WORKDIR /app

# --- Layers below are ordered cheapest-to-invalidate first, so that editing
# --- demos/eval/config (the frequently-changed files, copied last) does not
# --- rebuild the expensive torch / dependency / model-download layers.

# Install CPU-only torch FIRST from PyTorch's CPU index. The rerank extra pulls
# sentence-transformers -> torch, and the default PyPI torch wheel bundles ~2.7 GB of
# CUDA runtime libs (nvidia-*). The demo reranker runs on CPU, so pre-satisfying torch
# with the CPU wheel keeps the image small. Depends on nothing else, so it is cached
# until the wheel/index changes.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Dependencies only need pyproject.toml + the graphrag package (editable install
# resolves extras against them). Copy just these so a demos/config edit doesn't
# invalidate the dependency layer.
COPY pyproject.toml ./
COPY graphrag ./graphrag
RUN pip install --no-cache-dir -e ".[openai,vector,rerank]" uvicorn[standard]

# Pre-bake the BGE cross-encoder (matches config.yaml expander.rerank_model) so Live
# reranking works with no HuggingFace egress at runtime and the first query isn't slow.
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-base')"

# Frequently-edited files last: changing these reuses every layer above.
COPY demos ./demos
COPY eval ./eval
COPY config.yaml ./

EXPOSE 8800
# Build graph + vectors once, then serve. Stores reached by service name on graphrag-net.
CMD ["sh", "-c", "python -m demos.load && python -m uvicorn demos.server:app --host 0.0.0.0 --port 8800"]
