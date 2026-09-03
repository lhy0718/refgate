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


def test_sync_bibtex_semantic_noop_plan_and_output_are_consistent(tmp_path, capsys):
    canonical = """@inproceedings{publisher-official-key,
  title = {Café LLM Study},
  author = {Doe, Jane and Smith, Ada},
  booktitle = {Proceedings of the Fixture Conference},
  year = {2026},
  pages = {10--20},
  doi = {10.1234/refgate.2026},
  publisher = {ACM}
}
"""
    manuscript = """% preserve exact manuscript bytes
@INPROCEEDINGS{manuscript_local_key,
  publisher = {Association for Computing Machinery},
  doi = {https://doi.org/10.1234/REFGATE.2026},
  pages = {10 - 20},
  year = 2026,
  booktitle = {Proceedings   of the Fixture Conference},
  author = {Doe, Jane   and Smith, Ada},
  title = {Café {LLM} Study}
}
"""
    entry = _lock_entry("manuscript_local_key", canonical)
    entry["short_title"] = "Café LLM Study"
    entry["record"].update(
        {
            "title": "Café LLM Study",
            "authors": ["Doe, Jane", "Smith, Ada"],
            "year": 2026,
            "doi": "10.1234/refgate.2026",
        }
    )
    entry["bibtex"]["normalized_sha256"] = sha256_text(canonical)
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    output = tmp_path / "references.synced.bib"
    lock.write_text(json.dumps({"schema_version": "refgate.lock.v1", "entries": [entry]}), encoding="utf-8")
    bib.write_text(manuscript, encoding="utf-8")

    audit_exit = main(
        [
            "audit-bib",
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--submission",
            "--json",
        ]
    )
    audit = json.loads(capsys.readouterr().out)
    plan_exit = main(
        [
            "sync-bibtex",
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--citation-key",
            "manuscript_local_key",
            "--json",
        ]
    )
    plan = json.loads(capsys.readouterr().out)
    write_exit = main(
        [
            "sync-bibtex",
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--citation-key",
            "manuscript_local_key",
            "--output",
            str(output),
            "--json",
        ]
    )
    written = json.loads(capsys.readouterr().out)

    assert audit_exit == 0
    assert not any(
        issue.get("code") == "OFFICIAL_EXPORT_CONTENT_CHANGED"
        for issue in [*audit.get("blocking_issues", []), *audit.get("warnings", [])]
    )
    assert plan_exit == 0
    assert plan["data"]["change_count"] == 0
    assert plan["data"]["actions"][0]["action"] == "unchanged"
    assert plan["data"]["actions"][0]["reason"] == "bibliographic_metadata_equivalent"
    assert write_exit == 0
    assert written["data"]["change_count"] == 0
    assert output.read_bytes() == bib.read_bytes()


def test_sync_bibtex_replaces_entry_followed_by_comment_and_keeps_the_comment(tmp_path, capsys):
    """A comment between two entries belongs to neither of them.

    Spans used to run to the next ``@``, so the comment was parsed as part of
    the entry above it. That entry's citation key then failed to parse, and
    ``sync-bibtex`` reported it as missing from the bib -- while still exiting
    ``ok``. Had the key parsed, the replacement would have overwritten the
    comment instead.
    """
    first = """@article{doe2026refgate,
  title = {Official Title},
  author = {Doe, Jane},
  year = {2026},
  doi = {10.1234/refgate.2026}
}
"""
    second = """@article{roe2026refgate,
  title = {Official Title},
  author = {Doe, Jane},
  year = {2026},
  doi = {10.1234/refgate.2026}
}
"""
    lock_data = {
        "schema_version": "refgate.lock.v1",
        "entries": [_lock_entry("doe2026refgate", first), _lock_entry("roe2026refgate", second)],
    }
    lock_data["entries"][0]["bibtex"]["normalized_sha256"] = sha256_text(first)
    lock_data["entries"][1]["bibtex"]["normalized_sha256"] = sha256_text(second)
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    output = tmp_path / "references.refgate.bib"
    lock.write_text(json.dumps(lock_data), encoding="utf-8")
    bib.write_text(
        """@article{doe2026refgate,
  title = {Draft Title},
  author = {Doe, Jane},
  year = {2026}
}

% why this reference is cited here
% second line of the same note

@article{roe2026refgate,
  title = {Draft Title},
  author = {Doe, Jane},
  year = {2026}
}
""",
        encoding="utf-8",
    )

    exit_code = main(["sync-bibtex", "--bib", str(bib), "--lock", str(lock), "--output", str(output), "--json"])
    result = json.loads(capsys.readouterr().out)
    written = output.read_text(encoding="utf-8")

    assert exit_code == 0
    assert [action["action"] for action in result["data"]["actions"]] == ["replace", "replace"]
    assert "Draft Title" not in written
    assert "% why this reference is cited here" in written
    assert "% second line of the same note" in written
    assert written.index("doe2026refgate") < written.index("% why this") < written.index("roe2026refgate")
