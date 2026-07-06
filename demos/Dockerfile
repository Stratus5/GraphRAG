FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY graphrag ./graphrag
COPY demos ./demos
COPY eval ./eval
COPY config.yaml ./
RUN pip install --no-cache-dir -e ".[openai,vector,rerank]" uvicorn[standard]
# Pre-bake the BGE cross-encoder (matches config.yaml expander.rerank_model) so Live
# reranking works with no HuggingFace egress at runtime and the first query isn't slow.
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-base')"
EXPOSE 8800
# Build graph + vectors once, then serve. Stores reached by service name on graphrag-net.
CMD ["sh", "-c", "python -m demos.load && python -m uvicorn demos.server:app --host 0.0.0.0 --port 8800"]
