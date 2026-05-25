import json
import stat

from refgate.auth import append_query_param, auth_status
from refgate.cli import main


def test_auth_status_prefers_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("REFGATE_AUTH_CONFIG", str(tmp_path / "auth.json"))
    monkeypatch.setenv("REFGATE_SEMANTIC_SCHOLAR_API_KEY", "s2-value-123456")

    payload = auth_status()
    source = next(item for item in payload["sources"] if item["source"] == "semantic-scholar")

    assert source["configured"] is True
    assert source["origin"] == "env:REFGATE_SEMANTIC_SCHOLAR_API_KEY"
    assert source["display"] == "s2-v...3456"


def test_cli_auth_set_writes_user_local_config(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "auth.json"
    monkeypatch.setenv("REFGATE_AUTH_CONFIG", str(config_path))

    exit_code = main(["auth", "set", "semantic-scholar", "--value", "s2-local-abcdef", "--json"])

    output = json.loads(capsys.readouterr().out)
    stored = json.loads(config_path.read_text(encoding="utf-8"))
    mode = stat.S_IMODE(config_path.stat().st_mode)
    assert exit_code == 0
    assert output["ok"] is True
    assert output["data"]["configured"] is True
    assert stored["semantic_scholar_api_key"] == "s2-local-abcdef"
    assert mode == 0o600


def test_cli_auth_doctor_reports_missing_optional_values(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("REFGATE_AUTH_CONFIG", str(tmp_path / "auth.json"))
    monkeypatch.delenv("REFGATE_SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("S2_API_KEY", raising=False)
    monkeypatch.delenv("REFGATE_CROSSREF_MAILTO", raising=False)
    monkeypatch.delenv("REFGATE_OPENALEX_MAILTO", raising=False)

    exit_code = main(["auth", "doctor", "--json"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["ok"] is True
    assert {warning["source"] for warning in output["warnings"]} == {
        "semantic-scholar",
        "crossref-mailto",
        "openalex-mailto",
    }


def test_append_query_param_preserves_existing_value():
    url = append_query_param("https://api.example.test/works?rows=5&mailto=old@example.test", "mailto", "new@example.test")

    assert url == "https://api.example.test/works?rows=5&mailto=old%40example.test"


def test_append_query_param_adds_missing_value():
    url = append_query_param("https://api.example.test/works?rows=5", "mailto", "user@example.test")

    assert url == "https://api.example.test/works?rows=5&mailto=user%40example.test"
