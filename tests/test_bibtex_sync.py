import json
from pathlib import Path

from refgate.bibtex import sha256_text
from refgate.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def _lock_entry(citation_key: str, canonical_text: str) -> dict:
    return {
        "citation_key": citation_key,
        "short_title": "Official Title",
        "status": "verified_official_bibtex",
        "record": {
            "title": "Official Title",
            "authors": ["Doe, Jane"],
            "year": 2026,
            "doi": "10.1234/refgate.2026",
            "url": "https://publisher.example/refgate",
        },
        "authority": {
            "source": "publisher",
            "record_url": "https://publisher.example/refgate",
            "record_type": "journal_article",
            "source_priority": 1,
            "bibtex_url": "https://publisher.example/refgate.bib",
        },
        "bibtex": {
            "citation_key": citation_key,
            "source_kind": "official_export",
            "raw_sha256": "unused",
            "normalized_sha256": "",
            "canonical_text": canonical_text,
            "field_checks": {
                "bibtex_source": "official_export",
                "exported_citation_key": "publisher-key",
            },
        },
        "resolver": {"score": 100, "blocking_issues": [], "warnings": [], "decision_trace": []},
        "checked_at": "2026-05-23",
    }


def test_sync_bibtex_plans_and_writes_agent_friendly_json(tmp_path, capsys):
    canonical = """@article{doe2026refgate,
  title = {Official Title},
  author = {Doe, Jane},
  year = {2026},
  doi = {10.1234/refgate.2026}
}
"""
    lock_data = {"schema_version": "refgate.lock.v1", "entries": [_lock_entry("doe2026refgate", canonical)]}
    lock_data["entries"][0]["bibtex"]["normalized_sha256"] = sha256_text(canonical)
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    output = tmp_path / "references.refgate.bib"
    lock.write_text(json.dumps(lock_data), encoding="utf-8")
    bib.write_text(
        """% keep preface
@article{doe2026refgate,
  title = {Draft Title},
  author = {Doe, Jane},
  year = {2026}
}
""",
        encoding="utf-8",
    )

    plan_exit = main(["sync-bibtex", "--bib", str(bib), "--lock", str(lock), "--json"])
    plan = json.loads(capsys.readouterr().out)

    assert plan_exit == 0
    assert plan["ok"] is True
    assert plan["status"] == "bibtex_sync_plan_ready"
    assert plan["data"]["change_count"] == 1
    assert plan["data"]["wrote"] is False
    assert plan["data"]["actions"][0]["action"] == "replace"
    assert plan["next_actions"][0]["code"] == "WRITE_SYNCED_BIBTEX"

    write_exit = main(["sync-bibtex", "--bib", str(bib), "--lock", str(lock), "--output", str(output), "--json"])
    written = json.loads(capsys.readouterr().out)

    assert write_exit == 0
    assert written["status"] == "bibtex_sync_complete"
    assert written["data"]["wrote"] is True
    assert "% keep preface" in output.read_text(encoding="utf-8")
    assert "Draft Title" not in output.read_text(encoding="utf-8")
    assert "Official Title" in output.read_text(encoding="utf-8")


def test_sync_bibtex_output_keeps_blank_line_between_replaced_entries(tmp_path, capsys):
    canonical = """@article{doe2026refgate,
  title = {Official Title},
  author = {Doe, Jane},
  year = {2026}
}
"""
    lock_data = {"schema_version": "refgate.lock.v1", "entries": [_lock_entry("doe2026refgate", canonical)]}
    lock_data["entries"][0]["bibtex"]["normalized_sha256"] = sha256_text(canonical)
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    output = tmp_path / "references.refgate.bib"
    lock.write_text(json.dumps(lock_data), encoding="utf-8")
    bib.write_text(
        """@article{doe2026refgate,
  title = {Draft Title},
  author = {Doe, Jane}
}
@article{smith2025other,
  title = {Other Paper},
  author = {Smith, Ada}
}
""",
        encoding="utf-8",
    )

    exit_code = main(["sync-bibtex", "--bib", str(bib), "--lock", str(lock), "--output", str(output), "--json"])

    text = output.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "}\n@article{smith2025other" not in text
    assert "}\n\n@article{smith2025other" in text


def test_sync_bibtex_blocks_when_lock_has_no_canonical_text(tmp_path, capsys):
    entry = _lock_entry("doe2026refgate", "@article{doe2026refgate,\n  title = {Official Title}\n}\n")
    entry["bibtex"].pop("canonical_text")
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    output = tmp_path / "references.refgate.bib"
    lock.write_text(json.dumps({"schema_version": "refgate.lock.v1", "entries": [entry]}), encoding="utf-8")
    bib.write_text("@article{doe2026refgate,\n  title = {Draft Title}\n}\n", encoding="utf-8")

    exit_code = main(["sync-bibtex", "--bib", str(bib), "--lock", str(lock), "--output", str(output), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["blocking_issues"][0]["code"] == "CANONICAL_BIBTEX_TEXT_MISSING"
    assert payload["next_actions"][0]["code"] == "REFRESH_LOCK_CANONICAL_BIBTEX"
    assert "--fetch-official-bibtex" in payload["next_actions"][0]["command"]
    assert not output.exists()


def test_sync_bibtex_fixture_lock_is_already_synced(capsys):
    exit_code = main(
        [
            "sync-bibtex",
            "--bib",
            str(FIXTURES / "sample.bib"),
            "--lock",
            str(FIXTURES / "refgate.lock.json"),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data"]["actions"][0]["action"] == "unchanged"


def test_sync_bibtex_points_manual_fallback_to_reviewed_bibtex_backfill(tmp_path, capsys):
    entry = _lock_entry("doe2026refgate", "@article{doe2026refgate,\n  title = {Official Title}\n}\n")
    entry["status"] = "arxiv_fallback_verified"
    entry["bibtex"]["source_kind"] = "arxiv_manual_normalized"
    entry["bibtex"].pop("canonical_text")
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    lock.write_text(json.dumps({"schema_version": "refgate.lock.v1", "entries": [entry]}), encoding="utf-8")
    bib.write_text("@misc{doe2026refgate,\n  title = {Official Title}\n}\n", encoding="utf-8")

    exit_code = main(["sync-bibtex", "--bib", str(bib), "--lock", str(lock), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["next_actions"][0]["code"] == "BACKFILL_MANUAL_CANONICAL_BIBTEX"
    assert "REVIEWED_FALLBACK_BIBTEX_DIR" in payload["next_actions"][0]["command"]
