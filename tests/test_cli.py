from typer.testing import CliRunner

from graphrag.cli import app

runner = CliRunner()


def test_cli_has_ingest_and_query():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest" in result.output
    assert "query" in result.output
