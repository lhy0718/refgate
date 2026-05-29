import csv
import json
from pathlib import Path

from refgate.bibtex import rekey_bibtex_entry, sha256_text
from refgate.cli import main


FIXTURES = Path(__file__).parent / "fixtures"


def test_reference_check_can_write_verified_official_lock_entry(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    bibtex = tmp_path / "bibtex"
    candidates.mkdir()
    bibtex.mkdir()

    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "debenedetti2024agentdojo.json").write_text(
        (FIXTURES / "official_candidates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (bibtex / "debenedetti2024agentdojo.bib").write_text(
        (FIXTURES / "sample.bib").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--bibtex-dir",
            str(bibtex),
            "--write-lock",
            str(lock),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "reference_check_complete"
    assert payload["data"]["selected"] == 1
    assert payload["data"]["updated_entries"] == 1
    assert lock_data["entries"][0]["status"] == "verified_official_bibtex"
    assert lock_data["entries"][0]["bibtex"]["source_kind"] == "official_export"
    assert payload["next_actions"][0]["code"] == "AUDIT_BIB_AFTER_REFERENCE_UPDATE"
    assert payload["next_actions"][0]["kind"] == "validation_command"
    assert payload["next_actions"][0]["writes_files"] is False
    assert any(action["code"] == "SYNC_BIBTEX_AFTER_REFERENCE_UPDATE" for action in payload["next_actions"])


def test_reference_check_matches_official_bibtex_by_exact_title(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    bibtex = tmp_path / "bibtex"
    candidates.mkdir()
    bibtex.mkdir()

    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "debenedetti2024agentdojo.json").write_text(
        (FIXTURES / "official_candidates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (bibtex / "official-export-with-different-key.bib").write_text(
        (FIXTURES / "sample.bib").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--bibtex-dir",
            str(bibtex),
            "--write-lock",
            str(lock),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["results"][0]["bibtex_match_method"] == "title_exact"
    assert payload["data"]["results"][0]["bibtex_checks"]["title"] == "exact_normalized_match"
    assert payload["data"]["updated_entries"] == 1


def test_reference_check_can_fetch_official_bibtex_from_authority_url(monkeypatch, tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    candidates.mkdir()

    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "debenedetti2024agentdojo.json").write_text(
        (FIXTURES / "official_candidates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "refgate.reference_check.default_fetcher",
        lambda _url: (FIXTURES / "sample.bib").read_text(encoding="utf-8"),
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--write-lock",
            str(lock),
            "--fetch-official-bibtex",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["updated_entries"] == 1
    assert payload["data"]["results"][0]["bibtex_fetched_from"].endswith("/bibtex")
    assert len(lock_data["entries"]) == 1
    assert lock_data["entries"][0]["citation_key"] == "debenedetti2024agentdojo"
    assert lock_data["entries"][0]["bibtex"]["citation_key"] == "debenedetti2024agentdojo"
    assert lock_data["entries"][0]["bibtex"]["source_kind"] == "official_export"


def test_reference_check_fetches_inline_official_bibtex_through_adapter(monkeypatch, tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    bib.write_text(
        """@inproceedings{smith2026inline,
  title = {Refgate Fixture: Inline PMLR Export},
  author = {Smith, Ada},
  year = {2026},
  booktitle = {Proceedings of Machine Learning Research},
  url = {https://proceedings.mlr.press/v999/smith26.html}
}
""",
        encoding="utf-8",
    )
    main(["bootstrap-lock", "--bib", str(bib), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "smith2026inline.json").write_text(
        json.dumps(
            {
                "source": "pmlr",
                "title": "Refgate Fixture: Inline PMLR Export",
                "authors": ["Ada Smith"],
                "year": 2026,
                "venue": "PMLR",
                "url": "https://proceedings.mlr.press/v999/smith26.html",
                "is_official_record": True,
                "bibtex_url": "https://proceedings.mlr.press/v999/smith26.html",
                "source_priority": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "refgate.reference_check.default_fetcher",
        lambda _url: (FIXTURES / "pmlr_inline_bibtex_authority.html").read_text(encoding="utf-8"),
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--write-lock",
            str(lock),
            "--fetch-official-bibtex",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["updated_entries"] == 1
    assert payload["data"]["results"][0]["bibtex_fetched_from"].endswith("smith26.html")
    assert lock_data["entries"][0]["status"] == "verified_official_bibtex"
    assert lock_data["entries"][0]["bibtex"]["source_kind"] == "official_export"
    assert lock_data["entries"][0]["bibtex"]["citation_key"] == "smith2026inline"


def test_reference_check_can_use_fixture_html_dir_for_blocked_live_publishers(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    fixture_html = tmp_path / "official-html"
    manual_bibtex = tmp_path / "manual-bibtex"
    fixture_html.mkdir()
    manual_bibtex.mkdir()
    bib.write_text(
        """@inproceedings{smith2026acm,
  title = {Refgate Fixture: ACM Official Record},
  author = {Smith, Ada},
  year = {2026},
  booktitle = {ACM Fixture Conference},
  doi = {10.1145/refgate.acm},
  url = {https://dl.acm.org/doi/10.1145/refgate.acm}
}
""",
        encoding="utf-8",
    )
    main(["bootstrap-lock", "--bib", str(bib), "--output", str(lock), "--json"])
    capsys.readouterr()
    (fixture_html / "smith2026acm.acm.html").write_text((FIXTURES / "acm_authority.html").read_text(encoding="utf-8"), encoding="utf-8")
    (manual_bibtex / "smith2026acm.bib").write_text(bib.read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--fixture-html-dir",
            str(fixture_html),
            "--source",
            "acm",
            "--bibtex-dir",
            str(manual_bibtex),
            "--write-lock",
            str(lock),
            "--fallback-reason",
            "Reviewed saved ACM official HTML; manual BibTeX fallback retained because no official BibTeX endpoint was verified.",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["updated_entries"] == 1
    assert payload["data"]["results"][0]["fixture_html_results"][0]["ok"] is True
    assert lock_data["entries"][0]["status"] == "verified_manual_fallback"
    assert lock_data["entries"][0]["authority"]["source"] == "acm"
    assert lock_data["entries"][0]["bibtex"]["source_kind"] == "publisher_metadata_manual_normalized"


def test_reference_check_keeps_reviewed_fallback_manual_when_authority_has_bibtex_url(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    fixture_html = tmp_path / "official-html"
    manual_bibtex = tmp_path / "manual-bibtex"
    fixture_html.mkdir()
    manual_bibtex.mkdir()
    bib.write_text(
        """@inproceedings{smith2026aaai,
  title = {Refgate Fixture: AAAI Official Record},
  author = {Smith, Ada},
  year = {2026},
  booktitle = {AAAI Fixture Conference},
  doi = {10.1609/refgate.aaai},
  url = {https://ojs.aaai.org/index.php/AAAI/article/view/1}
}
""",
        encoding="utf-8",
    )
    main(["bootstrap-lock", "--bib", str(bib), "--output", str(lock), "--json"])
    capsys.readouterr()
    (fixture_html / "smith2026aaai.aaai.html").write_text(
        (FIXTURES / "aaai_authority.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (manual_bibtex / "smith2026aaai.bib").write_text(bib.read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--fixture-html-dir",
            str(fixture_html),
            "--source",
            "aaai",
            "--bibtex-dir",
            str(manual_bibtex),
            "--write-lock",
            str(lock),
            "--fallback-reason",
            "Reviewed saved AAAI official HTML; manual BibTeX fallback retained because the official BibTeX export was not fetched.",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["updated_entries"] == 1
    assert payload["data"]["results"][0]["fixture_html_results"][0]["ok"] is True
    assert lock_data["entries"][0]["status"] == "verified_manual_fallback"
    assert lock_data["entries"][0]["authority"]["source"] == "aaai"
    assert lock_data["entries"][0]["authority"]["bibtex_url"]
    assert lock_data["entries"][0]["bibtex"]["source_kind"] == "publisher_metadata_manual_normalized"


def test_reference_check_uses_official_bibtex_fixture_dir_without_live_network(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    fixture_html = tmp_path / "official-html"
    official_bibtex = tmp_path / "official-bibtex"
    fixture_html.mkdir()
    official_bibtex.mkdir()
    bib.write_text(
        """@inproceedings{smith2026aaai,
  title = {Refgate Fixture: AAAI Official Record},
  author = {Smith, Ada},
  year = {2026},
  booktitle = {AAAI Fixture Conference},
  doi = {10.1609/refgate.aaai},
  url = {https://ojs.aaai.org/index.php/AAAI/article/view/1}
}
""",
        encoding="utf-8",
    )
    main(["bootstrap-lock", "--bib", str(bib), "--output", str(lock), "--json"])
    capsys.readouterr()
    (fixture_html / "smith2026aaai.aaai.html").write_text(
        (FIXTURES / "aaai_authority.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (official_bibtex / "smith2026aaai.aaai.bib").write_text(
        bib.read_text(encoding="utf-8").replace("smith2026aaai", "AAAI2026_export_key", 1),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--fixture-html-dir",
            str(fixture_html),
            "--source",
            "aaai",
            "--official-bibtex-dir",
            str(official_bibtex),
            "--write-lock",
            str(lock),
            "--fetch-official-bibtex",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["updated_entries"] == 1
    assert payload["data"]["results"][0]["bibtex_match_method"] == "official_bibtex_fixture"
    assert payload["data"]["results"][0]["official_bibtex_file"].endswith("smith2026aaai.aaai.bib")
    assert lock_data["entries"][0]["status"] == "verified_official_bibtex"
    assert lock_data["entries"][0]["bibtex"]["source_kind"] == "official_export"
    assert lock_data["entries"][0]["bibtex"]["field_checks"]["bibtex_source"] == "official_export"
    assert lock_data["entries"][0]["bibtex"]["field_checks"]["exported_citation_key"] == "AAAI2026_export_key"
    assert lock_data["entries"][0]["bibtex"]["canonical_text"].startswith("@inproceedings{smith2026aaai,")


def test_reference_check_can_fetch_inline_bibtex_from_fixture_html_dir(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    bib = tmp_path / "references.bib"
    fixture_html = tmp_path / "official-html"
    fixture_html.mkdir()
    bib.write_text(
        """@inproceedings{smith2026inline,
  title = {Refgate Fixture: Inline PMLR Export},
  author = {Smith, Ada},
  year = {2026},
  booktitle = {Proceedings of Machine Learning Research},
  url = {https://proceedings.mlr.press/v999/smith26.html}
}
""",
        encoding="utf-8",
    )
    main(["bootstrap-lock", "--bib", str(bib), "--output", str(lock), "--json"])
    capsys.readouterr()
    (fixture_html / "smith2026inline.pmlr.html").write_text(
        (FIXTURES / "pmlr_inline_bibtex_authority.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--fixture-html-dir",
            str(fixture_html),
            "--source",
            "pmlr",
            "--write-lock",
            str(lock),
            "--fetch-official-bibtex",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["updated_entries"] == 1
    assert payload["data"]["results"][0]["fixture_html_results"][0]["ok"] is True
    assert payload["data"]["results"][0]["bibtex_fetched_from"].endswith("smith26.html")
    assert lock_data["entries"][0]["status"] == "verified_official_bibtex"
    assert lock_data["entries"][0]["bibtex"]["source_kind"] == "official_export"


def test_reference_check_preserves_manuscript_key_when_fetched_official_bibtex_uses_export_key(
    monkeypatch, tmp_path, capsys
):
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    candidates.mkdir()

    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "debenedetti2024agentdojo.json").write_text(
        (FIXTURES / "official_candidates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "refgate.reference_check.default_fetcher",
        lambda _url: (
            (FIXTURES / "sample.bib")
            .read_text(encoding="utf-8")
            .replace("debenedetti2024agentdojo", "NEURIPS2024_97091a51", 1)
            .replace("year = {2024},", "year = {2024},\n  doi = {10.52202/079017-2636},", 1)
        ),
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--write-lock",
            str(lock),
            "--fetch-official-bibtex",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    lock_data = json.loads(lock.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["updated_entries"] == 1
    assert [entry["citation_key"] for entry in lock_data["entries"]] == ["debenedetti2024agentdojo"]
    assert lock_data["entries"][0]["bibtex"]["citation_key"] == "debenedetti2024agentdojo"
    assert lock_data["entries"][0]["bibtex"]["field_checks"]["exported_citation_key"] == "NEURIPS2024_97091a51"
    assert lock_data["entries"][0]["record"]["doi"] == "10.52202/079017-2636"
    assert lock_data["entries"][0]["bibtex"]["normalized_sha256"] == sha256_text(
        rekey_bibtex_entry(
            (FIXTURES / "sample.bib")
            .read_text(encoding="utf-8")
            .replace("debenedetti2024agentdojo", "NEURIPS2024_97091a51", 1)
            .replace("year = {2024},", "year = {2024},\n  doi = {10.52202/079017-2636},", 1),
            "debenedetti2024agentdojo",
        ).strip()
        + "\n"
    )


def test_reference_check_blocks_official_bibtex_title_mismatch(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    bibtex = tmp_path / "bibtex"
    candidates.mkdir()
    bibtex.mkdir()

    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "debenedetti2024agentdojo.json").write_text(
        (FIXTURES / "official_candidates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (bibtex / "debenedetti2024agentdojo.bib").write_text(
        "@inproceedings{wrong,\n"
        "  title = {A Completely Different Paper},\n"
        "  author = {Debenedetti, Edoardo},\n"
        "  year = {2024}\n"
        "}\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--bibtex-dir",
            str(bibtex),
            "--write-lock",
            str(lock),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "OFFICIAL_BIBTEX_TITLE_MISMATCH" for issue in payload["blocking_issues"])
    assert payload["data"]["updated_entries"] == 0
    assert payload["data"]["results"][0]["bibtex_checks"]["title"] == "mismatch"


def test_reference_check_can_limit_entries_for_live_probe(tmp_path, capsys):
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    bib.write_text(
        (FIXTURES / "sample.bib").read_text(encoding="utf-8")
        + "\n@misc{extra2026,\n  title = {Extra Fixture Paper},\n  author = {Jones, Example},\n  year = {2026}\n}\n",
        encoding="utf-8",
    )
    candidates.mkdir()

    main(["bootstrap-lock", "--bib", str(bib), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "debenedetti2024agentdojo.json").write_text(
        (FIXTURES / "official_candidates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--max-entries",
            "1",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["entry_count"] == 2
    assert payload["data"]["checked"] == 1
    assert payload["data"]["skipped_entry_count"] == 1
    assert payload["next_actions"][0]["code"] == "WRITE_REFERENCE_LOCK"
    assert payload["next_actions"][0]["kind"] == "lockfile_update"


def test_reference_check_can_filter_by_citation_key(tmp_path, capsys):
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    bib.write_text(
        (FIXTURES / "sample.bib").read_text(encoding="utf-8")
        + "\n@misc{extra2026,\n  title = {Extra Fixture Paper},\n  author = {Jones, Example},\n  year = {2026}\n}\n",
        encoding="utf-8",
    )
    candidates.mkdir()

    main(["bootstrap-lock", "--bib", str(bib), "--output", str(lock), "--json"])
    capsys.readouterr()

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--citation-key",
            "extra2026",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["data"]["checked"] == 1
    assert payload["data"]["results"][0]["citation_key"] == "extra2026"
    assert payload["next_actions"][0]["candidate_file"].endswith("extra2026.json")


def test_monitor_official_records_plans_arxiv_fallback_reruns(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    lock.write_text(
        json.dumps(
            {
                "schema_version": "refgate.lock.v1",
                "entries": [
                    {
                        "citation_key": "preprint2026",
                        "short_title": "Preprint Fixture",
                        "status": "arxiv_fallback_verified",
                        "record": {
                            "title": "Preprint Fixture",
                            "authors": ["Ada Example"],
                            "year": 2026,
                            "venue": "arXiv preprint",
                            "arxiv_id": "2601.00001",
                            "url": "https://arxiv.org/abs/2601.00001",
                        },
                        "authority": {
                            "source": "arxiv",
                            "record_url": "https://arxiv.org/abs/2601.00001",
                            "record_type": "preprint_record",
                            "source_priority": 3,
                            "bibtex_url": None,
                        },
                        "bibtex": {
                            "entry_type": "misc",
                            "citation_key": "preprint2026",
                            "source_kind": "arxiv_manual_normalized",
                            "raw_sha256": "abc",
                            "normalized_sha256": "def",
                        },
                        "resolver": {"score": 100, "blocking_issues": [], "warnings": [], "decision_trace": []},
                        "checked_at": "2026-05-20",
                    },
                    {
                        "citation_key": "official2026",
                        "short_title": "Official Fixture",
                        "status": "verified_official_bibtex",
                        "record": {"title": "Official Fixture", "authors": ["Ada Example"], "year": 2026},
                        "authority": {
                            "source": "acl",
                            "record_url": "https://aclanthology.org/2026.acl-main.1/",
                            "record_type": "conference_proceedings",
                            "source_priority": 1,
                            "bibtex_url": "https://aclanthology.org/2026.acl-main.1.bib",
                        },
                        "bibtex": {
                            "entry_type": "inproceedings",
                            "citation_key": "official2026",
                            "source_kind": "official_export",
                            "raw_sha256": "abc",
                            "normalized_sha256": "def",
                        },
                        "resolver": {"score": 100, "blocking_issues": [], "warnings": [], "decision_trace": []},
                        "checked_at": "2026-05-20",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["monitor-official-records", "--lock", str(lock), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "official_monitor_ready"
    assert payload["data"]["plan"]["monitor_count"] == 1
    item = payload["data"]["plan"]["items"][0]
    assert item["citation_key"] == "preprint2026"
    assert item["recommended_sources"] == ["crossref"]
    assert "--citation-key preprint2026" in item["command"]
    assert "--fetch-official-bibtex" in item["command"]
    assert payload["next_actions"][0]["network_required"] is True


def test_reference_check_live_failure_returns_json_blocker(monkeypatch, tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()

    def fail_live(*_args, **_kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setattr("refgate.reference_check.run_live_smoke", fail_live)

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--source",
            "acm",
            "--live",
            "--max-entries",
            "1",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "reference_check_complete"
    assert any(issue["code"] == "REFERENCE_LIVE_LOOKUP_FAILED" for issue in payload["blocking_issues"])
    assert all(issue.get("citation_key") == "debenedetti2024agentdojo" for issue in payload["blocking_issues"])
    assert not any(issue["code"] == "REFERENCE_CANDIDATES_MISSING" for issue in payload["blocking_issues"])
    assert payload["next_actions"][0]["code"] == "RETRY_OR_CACHE_LIVE_LOOKUP"
    assert payload["next_actions"][0]["network_required"] is True
    html_action = next(action for action in payload["next_actions"] if action["code"] == "ADD_OFFICIAL_HTML_FIXTURE")
    assert html_action["kind"] == "official_html_fixture_input"
    assert html_action["network_required"] is False
    assert html_action["requires_human_review"] is True
    assert "--fixture-html-dir OFFICIAL_HTML_DIR" in html_action["command"]
    assert html_action["fixture_html_file_examples"] == [
        "debenedetti2024agentdojo.acm.html",
        "debenedetti2024agentdojo.html",
    ]
    assert html_action["source_guidance"]["source"] == "acm"
    assert html_action["source_guidance"]["official_bibtex_url_pattern"].endswith("format=bibTex")
    assert html_action["source_guidance"]["source_pdf_url_pattern"] == "https://dl.acm.org/doi/pdf/DOI"


def test_reference_check_suggests_candidate_files_when_missing(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "REFERENCE_CANDIDATES_MISSING" for issue in payload["blocking_issues"])
    assert payload["next_actions"][0]["code"] == "ADD_REFERENCE_CANDIDATES"
    assert payload["next_actions"][0]["kind"] == "reference_candidate_input"
    assert payload["next_actions"][0]["requires_human_review"] is True
    assert payload["next_actions"][0]["candidate_file"].endswith("debenedetti2024agentdojo.json")


def test_reference_check_suggests_review_for_low_confidence_candidate(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "debenedetti2024agentdojo.json").write_text(
        json.dumps(
            [
                {
                    "source": "semantic_scholar",
                    "title": "AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents",
                    "authors": ["Edoardo Debenedetti"],
                    "year": 2023,
                    "venue": "arXiv",
                    "url": "https://www.semanticscholar.org/paper/example",
                    "is_official_record": False,
                    "source_priority": 4,
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "LOW_CONFIDENCE" for issue in payload["blocking_issues"])
    assert payload["next_actions"][0]["code"] == "REVIEW_REFERENCE_CANDIDATE"
    assert payload["next_actions"][0]["kind"] == "reference_candidate_review"
    assert payload["next_actions"][0]["requires_human_review"] is True
    assert payload["next_actions"][0]["candidate_file"].endswith("debenedetti2024agentdojo.json")
    assert payload["next_actions"][0]["blocking_code"] == "LOW_CONFIDENCE"


def test_reference_check_suggests_bibtex_file_for_write_lock(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    bibtex = tmp_path / "official-bibtex"
    candidates.mkdir()
    bibtex.mkdir()
    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "debenedetti2024agentdojo.json").write_text(
        (FIXTURES / "official_candidates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--bibtex-dir",
            str(bibtex),
            "--write-lock",
            str(lock),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "BIBTEX_PROVENANCE_INPUT_MISSING" for issue in payload["blocking_issues"])
    assert payload["next_actions"][0]["code"] == "FETCH_OFFICIAL_BIBTEX_EXPORT"
    assert payload["next_actions"][0]["kind"] == "official_bibtex_fetch"
    assert payload["next_actions"][0]["network_required"] is True
    assert payload["next_actions"][0]["official_bibtex_url"].endswith("/bibtex")
    provenance_action = next(action for action in payload["next_actions"] if action["code"] == "ADD_BIBTEX_PROVENANCE")
    assert provenance_action["kind"] == "bibtex_provenance_input"
    assert provenance_action["bibtex_file"].endswith("debenedetti2024agentdojo.bib")
    assert provenance_action["preferred_input"] == "official_bibtex_export"
    assert "official_bibtex_export_or_reviewed_manual_fallback" in provenance_action["missing_inputs"]
    option_kinds = {option["kind"] for option in provenance_action["input_options"]}
    assert {"official_bibtex_export_fixture", "reviewed_manual_fallback"} <= option_kinds
    assert any(
        example.endswith("debenedetti2024agentdojo.SOURCE.bib")
        for example in provenance_action["official_bibtex_file_examples"]
    )


def test_reference_check_suggests_official_bibtex_fixture_when_fetch_fails(monkeypatch, tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    main(["bootstrap-lock", "--bib", str(FIXTURES / "sample.bib"), "--output", str(lock), "--json"])
    capsys.readouterr()
    (candidates / "debenedetti2024agentdojo.json").write_text(
        (FIXTURES / "official_candidates.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    def fail_fetch(*_args, **_kwargs):
        raise RuntimeError("publisher blocked")

    monkeypatch.setattr("refgate.reference_check._fetch_official_bibtex", fail_fetch)

    exit_code = main(
        [
            "reference-check",
            "--lock",
            str(lock),
            "--candidate-dir",
            str(candidates),
            "--write-lock",
            str(lock),
            "--fetch-official-bibtex",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "OFFICIAL_BIBTEX_FETCH_FAILED" for issue in payload["blocking_issues"])
    action = next(action for action in payload["next_actions"] if action["code"] == "ADD_OFFICIAL_BIBTEX_FIXTURE")
    assert action["kind"] == "official_bibtex_fixture_input"
    assert action["requires_human_review"] is True
    assert action["network_required"] is False
    assert action["official_bibtex_url"].endswith("/bibtex")
    assert any(example.endswith("debenedetti2024agentdojo.neurips.bib") for example in action["official_bibtex_file_examples"])
    assert "--official-bibtex-dir OFFICIAL_BIBTEX_DIR" in action["command"]


def test_claim_source_check_uses_citation_source_map_without_auto_checking(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    source_map = tmp_path / "source_map.tsv"
    output = tmp_path / "claims_suggested.tsv"
    claims.write_text((FIXTURES / "claims_unchecked.tsv").read_text(encoding="utf-8"), encoding="utf-8")
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\n"
        f"debenedetti2024agentdojo\t{FIXTURES / 'source_excerpt.txt'}\tagentdojo source text\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "claim-source-check",
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--output",
            str(output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert payload["status"] == "claim_source_check_complete"
    assert payload["data"]["updated"] == 1
    assert payload["data"]["consistency_summary"]["result_count"] == 1
    assert "consistency" not in payload["data"]
    assert rows[0]["status"] == "needs_review"
    assert rows[0]["source_location"] == "agentdojo source text: paragraph 3"
    assert "direct source review required" in rows[0]["notes"]
    assert "coverage" in rows[0]["notes"]
    assert payload["data"]["suggestions"][0]["coverage"] > 0
    assert "refgate" in payload["data"]["suggestions"][0]["matched_terms"]


def test_claim_source_check_semantic_lite_rerank_reports_score(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    source_map = tmp_path / "source_map.tsv"
    source = tmp_path / "source.txt"
    output = tmp_path / "claims_suggested.tsv"
    claims.write_text((FIXTURES / "claims_unchecked.tsv").read_text(encoding="utf-8"), encoding="utf-8")
    source.write_text(
        "Refgate verifies references.\n\n"
        "A separate paragraph discusses unrelated manuscript workflow details.",
        encoding="utf-8",
    )
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\n"
        f"debenedetti2024agentdojo\t{source}\tsemantic-lite source\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "claim-source-check",
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--output",
            str(output),
            "--rerank",
            "semantic-lite",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["rerank"] == "semantic-lite"
    assert payload["data"]["suggestions"][0]["semantic_lite_score"] > 0


def test_claim_source_check_marks_abstract_as_weak_evidence(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    source_map = tmp_path / "source_map.tsv"
    abstract = tmp_path / "abstract.txt"
    output = tmp_path / "claims_suggested.tsv"
    claims.write_text((FIXTURES / "claims_unchecked.tsv").read_text(encoding="utf-8"), encoding="utf-8")
    abstract.write_text(
        "Refgate verifies references with deterministic bibliography checks. "
        "This abstract-sized summary is intentionally weak evidence for claim review.",
        encoding="utf-8",
    )
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\tevidence_kind\n"
        f"debenedetti2024agentdojo\t{abstract}\tSemantic Scholar abstract\tabstract\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "claim-source-check",
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--output",
            str(output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert payload["status"] == "claim_source_check_complete"
    assert rows[0]["status"] == "needs_review_weak_evidence"
    assert rows[0]["evidence_kind"] == "abstract"
    assert "weak evidence kind abstract" in rows[0]["notes"]


def test_claim_source_check_blocks_submission_until_claim_is_checked(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    source_map = tmp_path / "source_map.tsv"
    claims.write_text((FIXTURES / "claims_unchecked.tsv").read_text(encoding="utf-8"), encoding="utf-8")
    source_map.write_text(
        "citation_key\tsource_text\n"
        f"debenedetti2024agentdojo\t{FIXTURES / 'source_excerpt.txt'}\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "claim-source-check",
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "CLAIM_STATUS_NOT_FINAL" for issue in payload["blocking_issues"])
    assert payload["blocking_issues"][0]["count"] == 1


def test_claim_source_check_can_include_full_consistency(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    source_map = tmp_path / "source_map.tsv"
    claims.write_text((FIXTURES / "claims_unchecked.tsv").read_text(encoding="utf-8"), encoding="utf-8")
    source_map.write_text(
        "citation_key\tsource_text\n"
        f"debenedetti2024agentdojo\t{FIXTURES / 'source_excerpt.txt'}\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "claim-source-check",
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--include-consistency",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["consistency"][0]["claim_id"] == "c1"


def test_claim_source_check_can_include_full_issues(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    source_map = tmp_path / "source_map.tsv"
    claims.write_text((FIXTURES / "claims_unchecked.tsv").read_text(encoding="utf-8"), encoding="utf-8")
    source_map.write_text(
        "citation_key\tsource_text\n"
        f"debenedetti2024agentdojo\t{FIXTURES / 'source_excerpt.txt'}\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "claim-source-check",
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--submission",
            "--include-issues",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert "count" not in payload["blocking_issues"][0]
    assert payload["blocking_issues"][0]["citation_key"] == "debenedetti2024agentdojo"


def test_audit_claims_blocks_checked_claim_with_abstract_evidence(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    claims.write_text(
        "\t".join(
            [
                "claim_id",
                "manuscript_location",
                "claim_text",
                "citation_key",
                "source_location",
                "quote_or_evidence",
                "evidence_kind",
                "status",
                "notes",
            ]
        )
        + "\n"
        + "\t".join(
            [
                "c1",
                "sec1",
                "AgentDojo evaluates AI agents under prompt injection attacks.",
                "debenedetti2024agentdojo",
                "Semantic Scholar abstract",
                "AgentDojo evaluates AI agents under prompt injection attacks.",
                "abstract",
                "checked",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["audit-claims", "--claims", str(claims), "--submission", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["blocking_issues"][0]["code"] == "CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE"


def test_claim_consistency_blocks_checked_claim_with_abstract_evidence(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    claims.write_text(
        "\t".join(
            [
                "claim_id",
                "manuscript_location",
                "claim_text",
                "citation_key",
                "source_location",
                "quote_or_evidence",
                "evidence_kind",
                "status",
                "notes",
            ]
        )
        + "\n"
        + "\t".join(
            [
                "c1",
                "sec1",
                "AgentDojo evaluates AI agents under prompt injection attacks.",
                "debenedetti2024agentdojo",
                "Semantic Scholar abstract",
                "AgentDojo evaluates AI agents under prompt injection attacks.",
                "abstract",
                "checked",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["claim-consistency", "--claims", str(claims), "--submission", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE" for issue in payload["blocking_issues"])


def test_claim_source_check_groups_default_issue_summary(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    source_map = tmp_path / "source_map.tsv"
    claims.write_text(
        "claim_id\tmanuscript_location\tclaim_text\tcitation_key\tsource_location\tquote_or_evidence\tstatus\tnotes\n"
        "c1\tsec1\tRefgate verifies references.\tdebenedetti2024agentdojo\t\t\tclaim_unchecked\t\n"
        "c2\tsec1\tRefgate verifies references.\tdebenedetti2024agentdojo\t\t\tclaim_unchecked\t\n",
        encoding="utf-8",
    )
    source_map.write_text("citation_key\tsource_text\n", encoding="utf-8")

    exit_code = main(
        [
            "claim-source-check",
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    missing = [issue for issue in payload["blocking_issues"] if issue["code"] == "CLAIM_EVIDENCE_MISSING"]
    assert len(missing) == 1
    assert missing[0]["count"] == 2


def test_claim_source_check_prefers_body_passage_over_title_like_match(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    source = tmp_path / "source.txt"
    source_map = tmp_path / "source_map.tsv"
    output = tmp_path / "claims.review.tsv"
    claims.write_text(
        "claim_id\tmanuscript_location\tclaim_text\tcitation_key\tsource_location\tquote_or_evidence\tstatus\tnotes\n"
        "c1\tsec1\tGraph agents enforce access control policies.\tsmith2026\t\t\tclaim_unchecked\t\n",
        encoding="utf-8",
    )
    source.write_text(
        "[page 1]\n"
        "Graph Agents Enforce Access Control Policies\n\n"
        "[page 2]\n"
        "In the evaluation section, graph agents enforce access control policies with runtime checks and audit logs. "
        "This body passage provides context beyond a title-like line.\n",
        encoding="utf-8",
    )
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\tevidence_kind\n"
        f"smith2026\t{source.name}\t{source.name}\tsource_text\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "claim-source-check",
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--output",
            str(output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert payload["data"]["suggestions"][0]["title_like"] is False
    assert "page 2" in rows[0]["source_location"]


def test_claim_source_check_reports_missing_source_map_as_json(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    claims.write_text((FIXTURES / "claims_unchecked.tsv").read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "claim-source-check",
            "--claims",
            str(claims),
            "--source-map",
            str(tmp_path / "missing_source_map.tsv"),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "claim_source_check_complete"
    assert payload["blocking_issues"][0]["code"] == "SOURCE_MAP_MISSING"
