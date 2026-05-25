import csv
import json
import shlex
from pathlib import Path

import pytest

from refgate.bibtex import sha256_text
from refgate.models import CandidateRecord, AuthorityRecord
from refgate.cli import main


FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_audit_claims_blocks_unchecked_claim(capsys):
    exit_code = main(["audit-claims", "--claims", str(FIXTURES / "claims_unchecked.tsv"), "--submission", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["blocking_issues"][0]["code"] == "CLAIM_NOT_CHECKED"


def test_cli_claim_stubs_writes_missing_rows(tmp_path, capsys):
    output = tmp_path / "claims.tsv"

    exit_code = main(["claim-stubs", "--tex", str(FIXTURES / "manuscript_claims.tex"), "--output", str(output), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["created"] == 1
    assert "debenedetti2024agentdojo" in output.read_text(encoding="utf-8")


def test_cli_bootstrap_paper_creates_blocking_starter_artifacts(tmp_path, capsys):
    lock_output = tmp_path / "refgate.lock.json"
    claims_output = tmp_path / "refgate_claims.tsv"

    exit_code = main(
        [
            "bootstrap-paper",
            "--tex",
            str(FIXTURES / "manuscript_claims.tex"),
            "--bib",
            str(FIXTURES / "sample.bib"),
            "--lock-output",
            str(lock_output),
            "--claims-output",
            str(claims_output),
            "--project",
            "fixture-paper",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    lock = json.loads(lock_output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "paper_bootstrapped"
    assert payload["data"]["lock"]["entries"] == 1
    assert payload["data"]["claims"]["created"] == 1
    assert lock["entries"][0]["status"] == "missing_bibtex_provenance"
    assert lock["entries"][0]["bibtex"]["source_kind"] == "unknown"
    assert "claim_unchecked" in claims_output.read_text(encoding="utf-8")


def test_cli_resolver_assist_writes_query_work_items(tmp_path, capsys):
    lock_output = tmp_path / "refgate.lock.json"
    query_output = tmp_path / "refgate_queries.json"
    main(
        [
            "bootstrap-lock",
            "--bib",
            str(FIXTURES / "sample.bib"),
            "--output",
            str(lock_output),
            "--json",
        ]
    )
    capsys.readouterr()

    exit_code = main(["resolver-assist", "--lock", str(lock_output), "--output", str(query_output), "--json"])

    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(query_output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "resolver_assist_ready"
    assert saved["work_item_count"] == 1
    assert saved["work_items"][0]["query"]["citation_key"] == "debenedetti2024agentdojo"
    assert saved["work_items"][0]["recommended_sources"][0] == "neurips"
    assert saved["work_items"][0]["source_commands"][0]["source"] == "neurips"


def test_cli_paper_audit_bootstraps_common_tex_bib_repo(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    tex.write_text((FIXTURES / "manuscript_claims.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "paper-audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--report",
            str(report),
            "--resolver-output",
            str(queries),
            "--frozen",
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "paper_audit_complete"
    assert lock.exists()
    assert claims.exists()
    assert report.exists()
    assert queries.exists()
    assert payload["data"]["resolver_assist"]["work_item_count"] == 1
    assert "work_items" not in payload["data"]["resolver_assist"]
    assert payload["data"]["resolver_assist"]["citation_key_sample"]
    assert payload["data"]["resolver_assist"]["omitted_citation_key_count"] == 0
    assert payload["blocking_issues"][0]["count"] >= 1
    assert "citation_key_sample" in payload["blocking_issues"][0]
    assert "citation_keys" not in payload["blocking_issues"][0]
    action_codes = {action["code"] for action in payload["next_actions"]}
    assert {"RESOLVE_REFERENCE_PROVENANCE", "MAP_CLAIM_SOURCES"} <= action_codes
    reference_action = next(action for action in payload["next_actions"] if action["code"] == "RESOLVE_REFERENCE_PROVENANCE")
    assert "resolver-assist" in reference_action["command"]
    assert "--fixture-html-dir" in reference_action["reference_check_command"]
    assert "--official-bibtex-dir" in reference_action["reference_check_command"]
    assert "--fetch-official-bibtex" in reference_action["reference_check_command"]
    assert "--fallback-reason" in reference_action["reference_check_command"]
    assert "--live" in reference_action["live_reference_check_command"]
    assert reference_action["fixture_html_naming"] == ["citationkey.source.html", "citationkey.html"]
    assert reference_action["official_bibtex_dir"].endswith(".refgate/official-bibtex")
    assert {option["kind"] for option in reference_action["input_options"]} == {
        "official_html_fixture",
        "official_bibtex_export_fixture",
        "reviewed_manual_fallback",
    }
    assert all("kind" in action for action in payload["next_actions"])
    assert all("requires_human_review" in action for action in payload["next_actions"])
    assert all("writes_files" in action for action in payload["next_actions"])
    assert all("network_required" in action for action in payload["next_actions"])
    assert "next_actions" not in payload["data"]


def test_cli_paper_audit_writes_next_plan_manifest(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    plan = tmp_path / ".refgate" / "next_plan.json"
    tex.write_text((FIXTURES / "manuscript_claims.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "paper-audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--report",
            str(report),
            "--resolver-output",
            str(queries),
            "--next-plan-output",
            str(plan),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    saved_plan = json.loads(plan.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["status"] == "paper_audit_complete"
    assert saved_plan["schema_version"] == "refgate.next_actions.v1"
    assert saved_plan["input"] == "paper-audit"
    assert saved_plan["execute"] is False
    assert saved_plan["action_count"] == len(payload["next_actions"])
    assert saved_plan["selected_count"] == 0
    assert saved_plan["actions"][0]["skip_reason"] == "writes_files"
    assert "reference_check_command" in saved_plan["actions"][0]["available_command_fields"]
    assert "reference_check_command" in saved_plan["actions"][0]["command_choices"]


def test_cli_paper_audit_does_not_mutate_existing_claims_without_flag(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    tex.write_text((FIXTURES / "manuscript_claims.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    original_claims = (FIXTURES / "claims_checked.tsv").read_text(encoding="utf-8")
    claims.write_text(original_claims, encoding="utf-8")

    exit_code = main(
        [
            "paper-audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--report",
            str(report),
            "--resolver-output",
            str(queries),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["created"]["claim_stubs_mode"] == "skipped_existing_claims"
    assert claims.read_text(encoding="utf-8") == original_claims
    assert payload["next_actions"][0]["code"] == "EXPORT_HANDOFF"
    assert payload["next_actions"][0]["kind"] == "handoff_export"
    assert payload["next_actions"][0]["writes_files"] is True


def test_cli_paper_audit_recommends_sync_bibtex_for_canonical_mismatch(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    canonical = (FIXTURES / "sample.bib").read_text(encoding="utf-8").replace(
        "year = {2024},",
        "year = {2024},\n  doi = {10.52202/079017-2636},",
        1,
    )
    lock_data = json.loads((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"))
    lock_data["entries"][0]["bibtex"]["canonical_text"] = canonical
    lock_data["entries"][0]["bibtex"]["normalized_sha256"] = sha256_text(canonical.strip() + "\n")
    tex.write_text((FIXTURES / "manuscript.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text(json.dumps(lock_data), encoding="utf-8")
    claims.write_text((FIXTURES / "claims_checked.tsv").read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "paper-audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--report",
            str(report),
            "--resolver-output",
            str(queries),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    sync_action = next(action for action in payload["next_actions"] if action["code"] == "SYNC_BIBTEX")
    assert exit_code == 1
    assert sync_action["kind"] == "bibtex_sync"
    assert sync_action["writes_files"] is False
    assert "sync-bibtex" in sync_action["command"]
    assert "--output" in sync_action["write_command"]


def test_cli_paper_audit_can_include_work_items_when_requested(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    tex.write_text((FIXTURES / "manuscript_claims.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "paper-audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--report",
            str(report),
            "--resolver-output",
            str(queries),
            "--include-work-items",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["data"]["resolver_assist"]["work_items"]


def test_cli_paper_audit_can_include_full_issues_when_requested(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    tex.write_text((FIXTURES / "manuscript_claims.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "paper-audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--report",
            str(report),
            "--resolver-output",
            str(queries),
            "--include-issues",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert "count" not in payload["blocking_issues"][0]
    assert payload["blocking_issues"][0]["citation_key"]


def test_cli_paper_audit_can_build_source_map_from_citation_key_files(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    claim_review = tmp_path / "refgate_claim_review.md"
    source_dir = tmp_path / "sources"
    source_map = tmp_path / "refgate_source_map.tsv"
    source_dir.mkdir()
    tex.write_text((FIXTURES / "manuscript_claims.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    source_text = source_dir / "debenedetti2024agentdojo.txt"
    source_text.write_text(
        "AgentDojo demonstrates benchmark risks for tool-using agents in a controlled evaluation. "
        "The full source text provides enough context for Refgate claim review.",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "paper-audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--report",
            str(report),
            "--resolver-output",
            str(queries),
            "--source-dir",
            str(source_dir),
            "--source-map-output",
            str(source_map),
            "--claim-review-output",
            str(claim_review),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(claims.open(newline="", encoding="utf-8"), delimiter="\t"))
    source_map_text = source_map.read_text(encoding="utf-8")
    assert exit_code == 1
    assert payload["data"]["source_map"]["source_count"] == 1
    assert payload["data"]["claim_source_check"]["updated"] == 1
    assert payload["data"]["claim_review"] == str(claim_review)
    bundle_action = next(action for action in payload["next_actions"] if action["code"] == "EXPORT_CODEX_REVIEW_BUNDLE")
    assert bundle_action["kind"] == "codex_claim_review_bundle"
    assert "export-review-bundle" in bundle_action["command"]
    assert "import-review" in bundle_action["import_command"]
    review_action = next(action for action in payload["next_actions"] if action["code"] == "REVIEW_CLAIM_EVIDENCE")
    assert review_action["kind"] == "claim_evidence_review"
    assert review_action["requires_human_review"] is True
    assert review_action["writes_files"] is False
    assert rows[0]["status"] == "needs_review"
    assert rows[0]["source_location"].startswith("sources/debenedetti2024agentdojo.txt: ")
    assert "sources/debenedetti2024agentdojo.txt" in source_map_text
    assert str(tmp_path) not in source_map_text
    assert "## Source-Check Summary" in claim_review.read_text(encoding="utf-8")

    second_exit = main(
        [
            "paper-audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--report",
            str(report),
            "--resolver-output",
            str(queries),
            "--source-dir",
            str(source_dir),
            "--source-map-output",
            str(source_map),
            "--claim-review-output",
            str(claim_review),
            "--submission",
            "--json",
        ]
    )
    second_payload = json.loads(capsys.readouterr().out)
    assert second_exit == 1
    assert second_payload["data"]["claim_source_check"]["updated"] == 0
    assert any(action["code"] == "REVIEW_CLAIM_EVIDENCE" for action in second_payload["next_actions"])


def test_cli_paper_audit_claim_review_summarizes_no_match_sources(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    claim_review = tmp_path / "refgate_claim_review.md"
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    tex.write_text((FIXTURES / "manuscript_claims.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    (source_dir / "debenedetti2024agentdojo.txt").write_text(
        "This unrelated full text discusses database transactions, storage engines, query planners, "
        "replication, isolation levels, recovery protocols, and transaction durability guarantees.",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "paper-audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--report",
            str(report),
            "--resolver-output",
            str(queries),
            "--source-dir",
            str(source_dir),
            "--claim-review-output",
            str(claim_review),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    review = claim_review.read_text(encoding="utf-8")
    assert exit_code == 1
    assert payload["data"]["claim_source_check"]["updated"] == 0
    assert payload["data"]["claim_source_check"]["no_match_claims"][0]["claim_id"] == "claim-0001"
    no_match_action = next(action for action in payload["next_actions"] if action["code"] == "REVIEW_NO_MATCH_CLAIMS")
    assert no_match_action["kind"] == "claim_evidence_review"
    assert no_match_action["requires_human_review"] is True
    assert no_match_action["writes_files"] is False
    assert "No Evidence Match In Mapped Source" in review
    assert "CLAIM_EVIDENCE_NOT_FOUND_IN_SOURCE" in review


def test_cli_run_next_plans_actions_without_execution(tmp_path, capsys):
    next_json = tmp_path / "paper_audit.json"
    next_json.write_text(
        json.dumps(
            {
                "next_actions": [
                    {
                        "code": "AUDIT_BIB_AFTER_REFERENCE_UPDATE",
                        "kind": "validation_command",
                        "requires_human_review": False,
                        "writes_files": False,
                        "network_required": False,
                        "command": "python -m refgate audit-bib --bib PAPER_BIB --lock refgate.lock.json --submission --json",
                    },
                    {
                        "code": "MAP_CLAIM_SOURCES",
                        "kind": "claim_source_mapping",
                        "requires_human_review": True,
                        "writes_files": True,
                        "network_required": False,
                        "command": "python -m refgate paper-audit --tex paper.tex --bib references.bib --source-dir SOURCES_DIR --json",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["run-next", "--from", str(next_json), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "next_actions_planned"
    assert payload["data"]["selected_count"] == 0
    assert payload["data"]["actions"][0]["selected"] is False
    assert payload["data"]["actions"][0]["skip_reason"] == "input_required"
    assert payload["data"]["actions"][0]["command_placeholders"] == ["PAPER_BIB"]
    assert payload["data"]["actions"][0]["ready_to_execute"] is False
    assert payload["data"]["actions"][0]["agent_hint"].startswith("Provide reviewed input paths")
    assert payload["data"]["recommended_next"]["status"] == "blocked"
    assert payload["data"]["recommended_next"]["skip_reason"] == "input_required"
    assert payload["data"]["actions"][1]["skip_reason"] == "input_required"
    assert payload["data"]["actions"][1]["command_placeholders"] == ["SOURCES_DIR"]


def test_cli_run_next_accepts_saved_next_plan_manifest(tmp_path, capsys):
    next_plan = tmp_path / "next_plan.json"
    next_plan.write_text(
        json.dumps(
            {
                "schema_version": "refgate.next_actions.v1",
                "ok": True,
                "input": "paper-audit",
                "execute": False,
                "gates": {},
                "action_count": 1,
                "selected_count": 0,
                "skipped_count": 1,
                "failed_count": 0,
                "actions": [
                    {
                        "index": 0,
                        "selected": False,
                        "skip_reason": "writes_files",
                        "code": "RESOLVE_REFERENCE_PROVENANCE",
                        "kind": "reference_provenance",
                        "requires_human_review": True,
                        "writes_files": True,
                        "network_required": False,
                        "command": "python -m refgate resolver-assist --lock refgate.lock.json --json",
                        "message": "Resolve reference provenance.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["run-next", "--from", str(next_plan), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["action_count"] == 1
    assert payload["data"]["actions"][0]["code"] == "RESOLVE_REFERENCE_PROVENANCE"


def test_cli_run_next_can_plan_auxiliary_command_field_when_inputs_are_ready(tmp_path, capsys):
    next_json = tmp_path / "next.json"
    official_html = tmp_path / "official-html"
    official_bibtex = tmp_path / "official-bibtex"
    official_html.mkdir()
    official_bibtex.mkdir()
    next_json.write_text(
        json.dumps(
            {
                "next_actions": [
                    {
                        "code": "RESOLVE_REFERENCE_PROVENANCE",
                        "kind": "reference_provenance",
                        "requires_human_review": True,
                        "writes_files": True,
                        "network_required": False,
                        "command": "python -m refgate resolver-assist --lock refgate.lock.json --json",
                        "reference_check_command": (
                            "python -m refgate reference-check --lock refgate.lock.json "
                            f"--fixture-html-dir {shlex.quote(str(official_html))} "
                            f"--official-bibtex-dir {shlex.quote(str(official_bibtex))} --write-lock refgate.lock.json --json"
                        ),
                        "missing_inputs": ["official_html_or_live_lookup", "official_bibtex_export_or_reviewed_manual_fallback"],
                        "input_options": [
                            {"kind": "official_html_fixture", "directory": str(official_html)},
                            {"kind": "official_bibtex_export_fixture", "directory": str(official_bibtex)},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "run-next",
            "--from",
            str(next_json),
            "--command-field",
            "reference_check_command",
            "--allow-writes",
            "--allow-human-review",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["actions"][0]["selected"] is False
    assert payload["data"]["actions"][0]["skip_reason"] == "input_required"
    assert "reference_check_command" in payload["data"]["actions"][0]["available_command_fields"]

    (official_html / "paper.source.html").write_text("<html></html>", encoding="utf-8")
    (official_bibtex / "paper.source.bib").write_text("@inproceedings{paper,title={Paper}}\n", encoding="utf-8")
    exit_code = main(
        [
            "run-next",
            "--from",
            str(next_json),
            "--command-field",
            "reference_check_command",
            "--allow-writes",
            "--allow-human-review",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["actions"][0]["selected"] is True
    assert payload["data"]["actions"][0]["command_field"] == "reference_check_command"
    assert "reference-check" in payload["data"]["actions"][0]["command"]
    assert payload["data"]["recommended_next"]["status"] == "ready"
    assert payload["data"]["recommended_next"]["command_field"] == "reference_check_command"


def test_cli_run_next_preserves_source_guidance_for_agent_review(tmp_path, capsys):
    next_json = tmp_path / "next.json"
    next_json.write_text(
        json.dumps(
            {
                "next_actions": [
                    {
                        "code": "FETCH_OFFICIAL_BIBTEX_EXPORT",
                        "kind": "official_bibtex_fetch",
                        "citation_key": "smith2026acm",
                        "requires_human_review": False,
                        "writes_files": True,
                        "network_required": True,
                        "message": "The selected authority exposes an official BibTeX URL.",
                        "official_bibtex_url": "https://dl.acm.org/action/exportCiteProcCitation?dois=10.1145%2Ffixture&targetFile=custom-bibtex&format=bibTex",
                        "source_guidance": {
                            "source": "acm",
                            "fixture_html_file_examples": ["smith2026acm.acm.html", "smith2026acm.html"],
                            "official_bibtex_file_examples": ["smith2026acm.acm.bib", "smith2026acm.source.bib"],
                            "official_bibtex_url_pattern": "https://dl.acm.org/action/exportCiteProcCitation?dois=URL_ENCODED_DOI&targetFile=custom-bibtex&format=bibTex",
                            "source_pdf_url_pattern": "https://dl.acm.org/doi/pdf/DOI",
                        },
                        "command": "python -m refgate reference-check --lock refgate.lock.json --source acm --fetch-official-bibtex --write-lock refgate.lock.json --live --json",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["run-next", "--from", str(next_json), "--json"])

    payload = json.loads(capsys.readouterr().out)
    action = payload["data"]["actions"][0]
    assert exit_code == 0
    assert action["selected"] is False
    assert action["skip_reason"] == "network_required"
    assert action["citation_key"] == "smith2026acm"
    assert action["action_summary"] == "Fetch official BibTeX export for smith2026acm."
    assert action["agent_hint"].startswith("Official BibTeX export is available")
    assert action["official_bibtex_url"].startswith("https://dl.acm.org/action/exportCiteProcCitation")
    assert action["source_guidance_summary"]["source"] == "acm"
    assert action["source_guidance_summary"]["source_pdf_url_pattern"] == "https://dl.acm.org/doi/pdf/DOI"
    assert payload["data"]["recommended_next"]["code"] == "FETCH_OFFICIAL_BIBTEX_EXPORT"
    assert payload["data"]["recommended_next"]["source_guidance"]["source"] == "acm"


def test_cli_run_next_execute_runs_allowed_refgate_command(tmp_path, capsys):
    next_json = tmp_path / "next.json"
    source = tmp_path / "source.txt"
    source.write_text("Refgate verifies references with source evidence.", encoding="utf-8")
    next_json.write_text(
        json.dumps(
            {
                "next_actions": [
                    {
                        "code": "VALIDATE_SOURCE_TEXT",
                        "kind": "validation_command",
                        "requires_human_review": False,
                        "writes_files": False,
                        "network_required": False,
                        "command": (
                            "python -m refgate validate-source-text "
                            f"--text {shlex.quote(str(source))} --min-chars 20 --json"
                        ),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["run-next", "--from", str(next_json), "--execute", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "next_actions_executed"
    assert payload["data"]["actions"][0]["executed"] is True
    assert payload["data"]["actions"][0]["returncode"] == 0
    assert "source_text_validated" in payload["data"]["actions"][0]["stdout"]


def test_cli_run_next_writes_plan_and_run_log(tmp_path, capsys):
    next_json = tmp_path / "next.json"
    source = tmp_path / "source.txt"
    plan = tmp_path / "artifacts" / "next_plan.json"
    run_log = tmp_path / "artifacts" / "next_run_log.json"
    source.write_text("Refgate verifies references with source evidence.", encoding="utf-8")
    next_json.write_text(
        json.dumps(
            {
                "next_actions": [
                    {
                        "code": "VALIDATE_SOURCE_TEXT",
                        "kind": "validation_command",
                        "requires_human_review": False,
                        "writes_files": False,
                        "network_required": False,
                        "command": (
                            "python -m refgate validate-source-text "
                            f"--text {shlex.quote(str(source))} --min-chars 20 --json"
                        ),
                    },
                    {
                        "code": "WRITE_REVIEW",
                        "kind": "claim_evidence_review",
                        "requires_human_review": True,
                        "writes_files": True,
                        "network_required": False,
                        "command": "python -m refgate claim-report --claims claims.tsv --output review.md --json",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "run-next",
            "--from",
            str(next_json),
            "--execute",
            "--output-plan",
            str(plan),
            "--write-run-log",
            str(run_log),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    saved_plan = json.loads(plan.read_text(encoding="utf-8"))
    saved_run_log = json.loads(run_log.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["schema_version"] == "refgate.next_actions.v1"
    assert saved_plan["execute"] is False
    assert saved_plan["selected_count"] == 1
    assert saved_plan["actions"][1]["skip_reason"] == "writes_files"
    assert saved_run_log["execute"] is True
    assert saved_run_log["selected_count"] == 1
    assert saved_run_log["actions"][0]["executed"] is True
    assert saved_run_log["actions"][0]["returncode"] == 0
    assert saved_run_log["gates"]["allow_writes"] is False
    assert saved_plan["recommended_next"]["status"] == "ready"


def test_cli_run_summary_reports_remaining_actions(tmp_path, capsys):
    manifest = tmp_path / "next_run_log.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "refgate.next_actions.v1",
                "ok": False,
                "execute": True,
                "selected_count": 2,
                "failed_count": 1,
                "actions": [
                    {
                        "index": 0,
                        "selected": True,
                        "executed": True,
                        "returncode": 1,
                        "code": "VALIDATE_SOURCE_TEXT",
                        "kind": "validation_command",
                        "command": "python -m refgate validate-source-text --text source.txt --json",
                    },
                    {
                        "index": 1,
                        "selected": False,
                        "executed": False,
                        "skip_reason": "writes_files",
                        "code": "WRITE_REVIEW",
                        "kind": "claim_evidence_review",
                        "writes_files": True,
                        "command": "python -m refgate claim-report --claims claims.tsv --output review.md --json",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["run-summary", "--input", str(manifest), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "next_action_summary"
    assert payload["blocking_issues"][0]["code"] == "NEXT_ACTIONS_REMAINING"
    assert payload["data"]["failed_count"] == 1
    assert payload["data"]["remaining_count"] == 2
    assert payload["data"]["status_counts"]["failed"] == 1
    assert payload["data"]["status_counts"]["skipped_writes_files"] == 1
    assert "stdout" not in payload["data"]["remaining_actions"][0]
    assert "stderr" not in payload["data"]["remaining_actions"][0]
    assert payload["data"]["recommended_next"]["command"]


def test_cli_run_summary_writes_markdown_report(tmp_path, capsys):
    manifest = tmp_path / "next_plan.json"
    markdown = tmp_path / "next_summary.md"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "refgate.next_actions.v1",
                "ok": True,
                "execute": False,
                "selected_count": 0,
                "failed_count": 0,
                "actions": [
                    {
                        "index": 0,
                        "selected": False,
                        "skip_reason": "writes_files",
                        "code": "RESOLVE_REFERENCE_PROVENANCE",
                        "kind": "reference_provenance",
                        "action_summary": "Resolve unresolved bibliography entries.",
                        "agent_hint": "Enable --allow-writes only when file updates are intended.",
                        "writes_files": True,
                        "command": "python -m refgate resolver-assist --lock refgate.lock.json --json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["run-summary", "--input", str(manifest), "--markdown", str(markdown), "--json"])

    payload = json.loads(capsys.readouterr().out)
    report = markdown.read_text(encoding="utf-8")
    assert exit_code == 1
    assert payload["status"] == "next_action_summary"
    assert "# Refgate Next-Action Summary" in report
    assert "RESOLVE_REFERENCE_PROVENANCE" in report
    assert "Enable --allow-writes" in report
    assert "python -m refgate resolver-assist" in report


def test_cli_run_summary_keeps_compact_source_guidance(tmp_path, capsys):
    manifest = tmp_path / "next_plan.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "refgate.next_actions.v1",
                "ok": True,
                "execute": False,
                "selected_count": 0,
                "failed_count": 0,
                "actions": [
                    {
                        "index": 0,
                        "selected": False,
                        "skip_reason": "requires_human_review",
                        "code": "ADD_OFFICIAL_BIBTEX_FIXTURE",
                        "kind": "official_bibtex_fixture_input",
                        "citation_key": "smith2026acm",
                        "action_summary": "Save reviewed official BibTeX fixture for smith2026acm.",
                        "agent_hint": "Save the reviewed publisher BibTeX export using one of the official_bibtex_file_examples, then rerun reference-check.",
                        "official_bibtex_url": "https://dl.acm.org/action/exportCiteProcCitation?dois=10.1145%2Ffixture&targetFile=custom-bibtex&format=bibTex",
                        "source_guidance_summary": {
                            "source": "acm",
                            "official_bibtex_file_examples": ["smith2026acm.acm.bib"],
                        },
                        "requires_human_review": True,
                        "writes_files": True,
                        "network_required": False,
                        "command": "python -m refgate reference-check --lock refgate.lock.json --official-bibtex-dir OFFICIAL_BIBTEX_DIR --json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["run-summary", "--input", str(manifest), "--json"])

    payload = json.loads(capsys.readouterr().out)
    action = payload["data"]["remaining_actions"][0]
    assert exit_code == 1
    assert action["citation_key"] == "smith2026acm"
    assert action["action_summary"].startswith("Save reviewed official BibTeX fixture")
    assert action["source_guidance_summary"]["source"] == "acm"
    assert action["official_bibtex_url"].startswith("https://dl.acm.org/")
    assert payload["data"]["recommended_next"]["action_summary"].startswith("Save reviewed official BibTeX fixture")


def test_cli_run_summary_passes_clean_run_log(tmp_path, capsys):
    manifest = tmp_path / "next_run_log.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "refgate.next_actions.v1",
                "ok": True,
                "execute": True,
                "selected_count": 1,
                "failed_count": 0,
                "actions": [
                    {
                        "index": 0,
                        "selected": True,
                        "executed": True,
                        "returncode": 0,
                        "code": "VALIDATE_SOURCE_TEXT",
                        "kind": "validation_command",
                        "command": "python -m refgate validate-source-text --text source.txt --json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["run-summary", "--input", str(manifest), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["ok"] is True
    assert payload["data"]["remaining_count"] == 0
    assert payload["data"]["status_counts"]["succeeded"] == 1


def test_bootstrapped_lock_blocks_submission_until_resolved(tmp_path, capsys):
    lock_output = tmp_path / "refgate.lock.json"
    main(
        [
            "bootstrap-lock",
            "--bib",
            str(FIXTURES / "sample.bib"),
            "--output",
            str(lock_output),
            "--json",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "audit-bib",
            "--bib",
            str(FIXTURES / "sample.bib"),
            "--lock",
            str(lock_output),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    codes = {issue["code"] for issue in payload["blocking_issues"]}
    assert exit_code == 1
    assert payload["ok"] is False
    assert {"NON_PASSING_STATUS", "UNVERIFIED_BIBTEX_SOURCE"} <= codes


def test_cli_claim_consistency_blocks_low_overlap_for_submission(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    claims.write_text(
        "\t".join(["claim_id", "manuscript_location", "claim_text", "citation_key", "source_location", "quote_or_evidence", "status", "notes"])
        + "\n"
        + "\t".join(["c1", "sec1", "Graph rewiring improves robustness.", "smith2026", "p.1", "A dataset card lists baseline accuracy.", "checked", ""])
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["claim-consistency", "--claims", str(claims), "--submission", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["blocking_issues"][0]["code"] == "CLAIM_EVIDENCE_LOW_OVERLAP"


def test_cli_claim_consistency_flags_overstrong_claim(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    claims.write_text(
        "\t".join(["claim_id", "manuscript_location", "claim_text", "citation_key", "source_location", "quote_or_evidence", "status", "notes"])
        + "\n"
        + "\t".join(["c1", "sec1", "The method always outperforms baselines.", "smith2026", "p.1", "The method may outperform baselines.", "checked", ""])
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["claim-consistency", "--claims", str(claims), "--submission", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "CLAIM_MAY_BE_TOO_STRONG" for issue in payload["blocking_issues"])


def test_cli_validate_source_text_accepts_text_fixture(capsys):
    exit_code = main(["validate-source-text", "--text", str(FIXTURES / "source_excerpt.txt"), "--min-chars", "20", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "source_text_validated"
    assert payload["data"]["results"][0]["ok"] is True


def test_cli_evidence_suggest_bundle_selects_best_source(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    weak = tmp_path / "weak.txt"
    strong = tmp_path / "strong.txt"
    output = tmp_path / "suggested.tsv"
    claims.write_text(
        "\t".join(["claim_id", "manuscript_location", "claim_text", "citation_key", "source_location", "quote_or_evidence", "status", "notes"])
        + "\n"
        + "\t".join(["c1", "sec1", "Graph agents enforce access control policies.", "smith2026", "", "", "claim_unchecked", ""])
        + "\n",
        encoding="utf-8",
    )
    weak.write_text("A baseline table reports accuracy.", encoding="utf-8")
    strong.write_text("Graph agents enforce access control policies with runtime checks.", encoding="utf-8")

    exit_code = main(
        [
            "evidence-suggest-bundle",
            "--claims",
            str(claims),
            "--text",
            str(weak),
            "--text",
            str(strong),
            "--output",
            str(output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["updated"] == 1
    assert payload["data"]["suggestions"][0]["source_label"] == "strong.txt"
    assert "strong.txt" in output.read_text(encoding="utf-8")


def test_cli_evidence_suggest_preserves_pdf_page_location(tmp_path, capsys):
    pytest.importorskip("pypdf")
    claims = tmp_path / "claims.tsv"
    output = tmp_path / "suggested.tsv"
    claims.write_text(
        "\t".join(["claim_id", "manuscript_location", "claim_text", "citation_key", "source_location", "quote_or_evidence", "status", "notes"])
        + "\n"
        + "\t".join(["c1", "sec1", "Page two reports additional source context.", "smith2026", "", "", "claim_unchecked", ""])
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["evidence-suggest", "--claims", str(claims), "--text", str(FIXTURES / "source_excerpt_two_page.pdf"), "--output", str(output), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert "page 2" in output.read_text(encoding="utf-8").lower()


def test_cli_paper_agents_template_writes_generic_instructions(tmp_path, capsys):
    output = tmp_path / "AGENTS.refgate.md"

    exit_code = main(
        [
            "paper-agents-template",
            "--tex",
            "paper.tex",
            "--bib",
            "references.bib",
            "--lock",
            "refgate.lock.json",
            "--claims",
            "refgate_claims.tsv",
            "--report",
            "refgate_audit.md",
            "--output",
            str(output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    text = output.read_text(encoding="utf-8")
    assert exit_code == 0
    assert payload["status"] == "paper_agents_template_written"
    assert "paper-audit" in text
    assert "run-next --from .refgate/next_plan.json --json" in text
    assert "refgate-paper-audit" in text


def test_cli_publish_check_flags_sensitive_marker(tmp_path, capsys):
    (tmp_path / "notes.txt").write_text("never commit " + "sec" + "ret" + " material", encoding="utf-8")

    exit_code = main(["publish-check", "--root", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["blocking_issues"][0]["code"] == "PUBLISH_CHECK_FAILED"
    assert payload["data"]["findings"]


def test_cli_publish_check_skips_raw_live_cache(tmp_path, capsys):
    cache_file = tmp_path / ".refgate" / "cache" / "arxiv" / "raw.json"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("ordinary cached body with " + "to" + "ken" + " as a source word", encoding="utf-8")

    exit_code = main(["publish-check", "--root", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data"]["findings"] == []


def test_cli_publish_check_allows_github_oidc_permission(tmp_path, capsys):
    workflow = tmp_path / ".github" / "workflows" / "release.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("permissions:\n  contents: read\n  id-" + "to" + "ken: write\n", encoding="utf-8")

    exit_code = main(["publish-check", "--root", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data"]["findings"] == []


def test_cli_auth_setup_saves_selected_sources(tmp_path, capsys):
    config = tmp_path / "auth.json"

    exit_code = main(["auth", "setup", "--source", "semantic-scholar", "--value", "fixture-value", "--config", str(config), "--json"])

    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(config.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["count"] == 1
    assert saved["semantic_scholar_api_key"] == "fixture-value"


def test_cli_export_handoff_writes_standalone_json(tmp_path, capsys):
    output = tmp_path / "refgate_handoff.json"

    exit_code = main(
        [
            "export-handoff",
            "--bib",
            str(FIXTURES / "sample.bib"),
            "--lock",
            str(FIXTURES / "refgate.lock.json"),
            "--output",
            str(output),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "handoff_exported"
    assert artifact["schema_version"] == "refgate.handoff.v1"
    assert artifact["entries"][0]["citation_key"] == "debenedetti2024agentdojo"
    assert artifact["entries"][0]["bibtex_provenance"]["source_kind"] == "official_export"
    assert artifact["entries"][0]["csl"]["_refgate"]["authority_source"] == "neurips"


def test_cli_export_handoff_writes_csl_json(tmp_path, capsys):
    output = tmp_path / "references.csl.json"

    exit_code = main(
        [
            "export-handoff",
            "--bib",
            str(FIXTURES / "sample.bib"),
            "--lock",
            str(FIXTURES / "refgate.lock.json"),
            "--output",
            str(output),
            "--format",
            "csl-json",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["format"] == "csl-json"
    assert artifact[0]["id"] == "debenedetti2024agentdojo"
    assert artifact[0]["_refgate"]["bibtex_source_kind"] == "official_export"


def test_normalize_bibtex_accepts_one_item_candidate_list(tmp_path, capsys):
    candidate_path = tmp_path / "candidate_list.json"
    candidate_path.write_text(
        json.dumps(
            [
                {
                    "source": "arxiv",
                    "title": "A Fixture Paper",
                    "authors": ["Ada Smith"],
                    "year": 2026,
                    "venue": "arXiv preprint",
                    "arxiv_id": "2601.00001",
                    "url": "https://arxiv.org/abs/2601.00001v1",
                    "is_official_record": True,
                    "source_priority": 2,
                    "raw": {"accessed_at": "2026-05-20", "arxiv_version": "v1"},
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "normalize-bibtex",
            "--candidate",
            str(candidate_path),
            "--citation-key",
            "smith2026fixture",
            "--source-kind",
            "arxiv_manual_normalized",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["citation_key"] == "smith2026fixture"
    assert payload["data"]["source_kind"] == "arxiv_manual_normalized"


def test_live_smoke_missing_manifest_returns_json_error(tmp_path, capsys):
    missing_manifest = tmp_path / "missing_manifest.json"

    exit_code = main(
        [
            "live-smoke",
            "--cache-root",
            str(tmp_path / "cache"),
            "--manifest",
            str(missing_manifest),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["blocking_issues"][0]["code"] == "CACHE_MANIFEST_MISSING"


def test_discover_live_network_exception_returns_json_error(monkeypatch, capsys):
    from refgate.adapters.arxiv import ArxivAdapter

    def fail_discover(self, query):
        raise OSError("network unavailable")

    monkeypatch.setattr(ArxivAdapter, "discover", fail_discover)
    exit_code = main(
        [
            "discover",
            "--source",
            "arxiv",
            "--title",
            "A Fixture Paper",
            "--live",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["blocking_issues"][0]["code"] == "DISCOVERY_FAILED"


def test_cli_fetch_bibtex_merges_existing_lockfile(tmp_path, capsys):
    lock_path = tmp_path / "refgate.lock.json"
    lock_path.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    candidate_path = tmp_path / "candidate.json"
    authority_path = tmp_path / "authority.json"
    candidate = CandidateRecord(
        source="acl",
        title="Refgate Fixture: Official ACL Export",
        authors=["Ada Smith"],
        year=2026,
        venue="ACL Anthology",
        url="https://aclanthology.org/2026.acl-long.001/",
        is_official_record=True,
        bibtex_url="https://aclanthology.org/2026.acl-long.001.bib",
        source_priority=1,
    )
    authority = AuthorityRecord(
        source="acl",
        record_url="https://aclanthology.org/2026.acl-long.001/",
        record_type="conference_proceedings",
        source_priority=1,
        bibtex_url="https://aclanthology.org/2026.acl-long.001.bib",
    )
    candidate_path.write_text(json.dumps(candidate.to_dict()), encoding="utf-8")
    authority_path.write_text(json.dumps(authority.to_dict()), encoding="utf-8")

    exit_code = main(
        [
            "fetch-bibtex",
            "--candidate",
            str(candidate_path),
            "--authority",
            str(authority_path),
            "--bibtex-file",
            str(FIXTURES / "acl_official.bib"),
            "--write-lock",
            str(lock_path),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    merged = json.loads(lock_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["data"]["lock_entry"]["citation_key"] == "smith-lee-2026-refgate"
    assert len(merged["entries"]) == 2
    assert any(entry["citation_key"] == "debenedetti2024agentdojo" for entry in merged["entries"])
