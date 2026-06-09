import csv
import json
from pathlib import Path

from refgate.cli import main


FIXTURES = Path(__file__).parent / "fixtures"


def _write_claims(path: Path) -> None:
    path.write_text(
        "claim_id\tmanuscript_location\tclaim_text\tcitation_key\tsource_location\tquote_or_evidence\tevidence_kind\tstatus\tnotes\tclaim_type\timportance\n"
        "claim-0001\tline 10\tAgentDojo evaluates prompt injection attacks.\tdebenedetti2024agentdojo\t\t\t\tclaim_unchecked\t\trelated_work\tnormal\n",
        encoding="utf-8",
    )


def test_export_review_bundle_builds_codex_readable_queue_from_source_dir(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "sample.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    source_dir = tmp_path / "sources"
    output = tmp_path / ".refgate" / "codex_review_bundle.json"
    markdown = tmp_path / ".refgate" / "codex_review_bundle.md"
    source_map = tmp_path / ".refgate" / "codex_review_source_map.tsv"
    source_dir.mkdir()
    tex.write_text("\\cite{debenedetti2024agentdojo}\n", encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    _write_claims(claims)
    (source_dir / "debenedetti2024agentdojo.txt").write_text(
        "[page 1]\n"
        "AgentDojo is a benchmark for evaluating prompt injection attacks and defenses for LLM agents.\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "export-review-bundle",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--source-dir",
            str(source_dir),
            "--source-map-output",
            str(source_map),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "codex_review_bundle_exported"
    assert payload["data"]["claim_count"] == 1
    assert payload["data"]["source_candidate_count"] == 1
    assert bundle["schema_version"] == "refgate.codex_review_bundle.v1"
    assert bundle["claims"][0]["claim_id"] == "claim-0001"
    assert bundle["claims"][0]["source_candidates"][0]["candidate_found"] is True
    assert bundle["claims"][0]["source_candidates"][0]["evidence_candidates"]
    assert "refgate.codex_review_result.v1" in markdown.read_text(encoding="utf-8")
    assert source_map.exists()


def test_export_review_bundle_includes_multiple_evidence_candidates(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "sample.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    source_map = tmp_path / "source_map.tsv"
    source = tmp_path / "source.txt"
    output = tmp_path / "bundle.json"
    tex.write_text("\\cite{debenedetti2024agentdojo}\n", encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    _write_claims(claims)
    source.write_text(
        "[page 1]\n"
        "AgentDojo evaluates prompt injection attacks.\n\n"
        "[page 2]\n"
        "AgentDojo is a benchmark for evaluating prompt injection attacks and defenses for LLM agents.\n",
        encoding="utf-8",
    )
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\tevidence_kind\n"
        f"debenedetti2024agentdojo\t{source.name}\t{source.name}\tsource_text\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "export-review-bundle",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--output",
            str(output),
            "--max-candidates-per-source",
            "2",
            "--json",
        ]
    )

    bundle = json.loads(output.read_text(encoding="utf-8"))
    candidates = bundle["claims"][0]["source_candidates"][0]["evidence_candidates"]
    assert exit_code == 0
    assert len(candidates) == 2
    assert candidates[0]["overlap_score"] >= candidates[1]["overlap_score"]
    assert candidates[0]["confidence"] in {"medium", "high"}


def test_export_review_bundle_marks_low_overlap_candidate_low_confidence(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "sample.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "refgate_claims.tsv"
    source_map = tmp_path / "source_map.tsv"
    source = tmp_path / "source.txt"
    output = tmp_path / "bundle.json"
    markdown = tmp_path / "bundle.md"
    tex.write_text("\\cite{debenedetti2024agentdojo}\n", encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    claims.write_text(
        "claim_id\tmanuscript_location\tclaim_text\tcitation_key\tsource_location\tquote_or_evidence\tevidence_kind\tstatus\tnotes\tclaim_type\timportance\n"
        "claim-0001\tline 10\tAgentDojo evaluates prompt injection attacks and defenses.\tdebenedetti2024agentdojo\t\t\t\tclaim_unchecked\t\trelated_work\tnormal\n",
        encoding="utf-8",
    )
    source.write_text(
        "[page 1]\n"
        "AgentDojo is mentioned in a short index.\n\n"
        "[page 2]\n"
        "This unrelated body passage discusses database storage, replication, indexes, and recovery protocols.\n",
        encoding="utf-8",
    )
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\tevidence_kind\n"
        f"debenedetti2024agentdojo\t{source.name}\t{source.name}\tsource_text\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "export-review-bundle",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--source-map",
            str(source_map),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--json",
        ]
    )

    bundle = json.loads(output.read_text(encoding="utf-8"))
    candidate = bundle["claims"][0]["source_candidates"][0]
    assert exit_code == 0
    assert candidate["confidence"] == "low"
    assert "confidence=low" in markdown.read_text(encoding="utf-8")


def test_import_review_keeps_supported_claims_in_review_by_default(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    review = tmp_path / "codex_review_result.jsonl"
    output = tmp_path / "claims.reviewed.tsv"
    _write_claims(claims)
    review.write_text(
        json.dumps(
            {
                "schema_version": "refgate.codex_review_result.v1",
                "claim_id": "claim-0001",
                "decision": "supported",
                "source_location": "sources/debenedetti2024agentdojo.txt: page 1 paragraph 1",
                "quote_or_evidence": "AgentDojo is a benchmark for evaluating prompt injection attacks.",
                "evidence_kind": "source_text",
                "review_notes": "The claim is supported, but user review is still required.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "import-review",
            "--claims",
            str(claims),
            "--review",
            str(review),
            "--output",
            str(output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert payload["data"]["applied_count"] == 1
    assert rows[0]["status"] == "needs_review"
    assert rows[0]["source_location"].startswith("sources/debenedetti2024agentdojo.txt")
    assert "Codex review decision: supported." in rows[0]["notes"]


def test_import_review_allows_checked_only_with_explicit_flag_and_nonweak_evidence(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    review = tmp_path / "codex_review_result.jsonl"
    output = tmp_path / "claims.reviewed.tsv"
    _write_claims(claims)
    review.write_text(
        json.dumps(
            {
                "claim_id": "claim-0001",
                "decision": "checked",
                "source_location": "sources/debenedetti2024agentdojo.txt: page 1 paragraph 1",
                "quote_or_evidence": "AgentDojo is a benchmark for evaluating prompt injection attacks.",
                "evidence_kind": "source_text",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "import-review",
            "--claims",
            str(claims),
            "--review",
            str(review),
            "--output",
            str(output),
            "--allow-checked",
            "--json",
        ]
    )

    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert rows[0]["status"] == "checked"


def test_import_review_does_not_checked_weak_evidence_even_with_flag(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    review = tmp_path / "codex_review_result.jsonl"
    output = tmp_path / "claims.reviewed.tsv"
    _write_claims(claims)
    review.write_text(
        json.dumps(
            {
                "claim_id": "claim-0001",
                "decision": "checked",
                "quote_or_evidence": "Metadata summary says AgentDojo evaluates prompt injection.",
                "evidence_kind": "semantic_scholar_abstract",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "import-review",
            "--claims",
            str(claims),
            "--review",
            str(review),
            "--output",
            str(output),
            "--allow-checked",
            "--json",
        ]
    )

    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert rows[0]["status"] == "needs_review_weak_evidence"


def test_import_review_blocks_unknown_claim_id(tmp_path, capsys):
    claims = tmp_path / "claims.tsv"
    review = tmp_path / "codex_review_result.jsonl"
    output = tmp_path / "claims.reviewed.tsv"
    _write_claims(claims)
    review.write_text('{"claim_id":"missing","decision":"supported"}\n', encoding="utf-8")

    exit_code = main(
        [
            "import-review",
            "--claims",
            str(claims),
            "--review",
            str(review),
            "--output",
            str(output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["blocking_issues"][0]["code"] == "REVIEW_CLAIM_UNKNOWN"
    assert not output.exists()
