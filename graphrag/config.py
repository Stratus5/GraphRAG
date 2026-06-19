import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class ProviderConfig:
    provider: str
    model: str


@dataclass
class ChunkingConfig:
    size: int = 1000
    overlap: int = 200


@dataclass
class SchemaConfig:
    allowed_nodes: list[str] = field(default_factory=list)
    allowed_relationships: list[str] = field(default_factory=list)


@dataclass
class Neo4jConfig:
    uri: str
    username: str
    password: str


@dataclass
class ExpanderConfig:
    max_degree: int = 50          # don't expand THROUGH entities above this degree
    candidate_limit: int = 500    # deterministic-ordered fact budget before rerank
    top_n: int = 10               # facts kept after rerank
    rerank_model: str = "BAAI/bge-reranker-base"


@dataclass
class Config:
    llm: ProviderConfig
    embeddings: ProviderConfig
    chunking: ChunkingConfig
    schema: SchemaConfig
    neo4j: Neo4jConfig
    expander: ExpanderConfig


def load_config(path: Path | str = "config.yaml") -> Config:
    load_dotenv()
    data = yaml.safe_load(Path(path).read_text())
    return Config(
        llm=ProviderConfig(**data["llm"]),
        embeddings=ProviderConfig(**data["embeddings"]),
        chunking=ChunkingConfig(**data.get("chunking", {})),
        schema=SchemaConfig(**data.get("schema", {})),
        neo4j=Neo4jConfig(
            uri=os.environ["NEO4J_URI"],
            username=os.environ["NEO4J_USERNAME"],
            password=os.environ["NEO4J_PASSWORD"],
        ),
        expander=ExpanderConfig(**data.get("expander", {})),
    )
