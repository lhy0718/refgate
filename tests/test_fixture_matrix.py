import json
from pathlib import Path

from refgate.cli import main
from refgate.fixture_matrix import validate_fixture_matrix


FIXTURES = Path(__file__).parent / "fixtures"


def test_reference_priority_fixture_matrix_is_complete():
    queries = json.loads((FIXTURES / "reference_priority_queries.json").read_text(encoding="utf-8"))
    candidates = json.loads((FIXTURES / "reference_priority_candidates.json").read_text(encoding="utf-8"))

    result = validate_fixture_matrix(queries, candidates)

    assert result["ok"] is True
    assert result["total_queries"] == 10
    assert result["ok_queries"] == 10
    assert result["placeholder_records"] == []
    summary = {key: result[key] for key in ["ok", "ok_queries", "placeholder_records", "total_queries"]}
    assert summary == json.loads((Path(__file__).parent / "golden" / "fixture_matrix_summary.json").read_text(encoding="utf-8"))


def test_cli_fixture_matrix_returns_json(capsys):
    exit_code = main(
        [
            "fixture-matrix",
            "--queries",
            str(FIXTURES / "reference_priority_queries.json"),
            "--candidates",
            str(FIXTURES / "reference_priority_candidates.json"),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data"]["total_queries"] == 10
