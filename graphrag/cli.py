from pathlib import Path

import typer
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from graphrag.config import load_config

app = typer.Typer(help="GraphRAG CLI")


@app.command()
def ingest(folder: Path, config: Path = Path("config.yaml")):
    """Ingest a folder of files into the knowledge graph."""
    from graphrag.ingestion.pipeline import ingest as run_ingest

    cfg = load_config(config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=False,
    ) as progress:
        task_id = progress.add_task("Starting…", total=None)

        def on_progress(stage: str, current: int, total: int):
            if total == 0:
                # indeterminate — show spinner, no bar
                progress.update(task_id, description=stage, total=None, completed=0)
            else:
                progress.update(
                    task_id,
                    description=stage,
                    total=total,
                    completed=current,
                )

        stats = run_ingest(cfg, folder, on_progress=on_progress)

    typer.echo(
        f"\n[done] {stats['documents']} docs  "
        f"{stats['chunks']} chunks  "
        f"{stats['graph_documents']} graph-docs  "
        f"failures={stats['extraction_failures']}"
    )


@app.command()
def query(question: str, config: Path = Path("config.yaml"),
          k: int = 4, hops: int = 1):
    """Ask a question against the knowledge graph."""
    from graphrag.retrieval.pipeline import query as run_query

    cfg = load_config(config)
    typer.echo(run_query(cfg, question, k=k, hops=hops))


if __name__ == "__main__":
    app()
