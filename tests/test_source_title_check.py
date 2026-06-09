import json
from pathlib import Path

from refgate.cli import main
from refgate.source_title import source_title_candidates, source_title_matches


FIXTURES = Path(__file__).parent / "fixtures"


def test_source_title_match_keeps_short_wrapped_title_continuation():
    text = (
        "[page 1]\n"
        "MANTRA: Synthesizing SMT-Validated\n"
        "Compliance Benchmarks for Tool-Using LLM\n"
        "Agents\n"
        "Ashwani Anand, Ivi Chatzi, Ritam Raha, and Anne-Kathrin Schmuck\n"
        "Abstract\n"
        "Tool-using large language model agents are increasingly deployed.\n"
    )

    candidates = source_title_candidates(text)

    assert source_title_matches(
        "MANTRA: Synthesizing SMT-Validated Compliance Benchmarks for Tool-Using LLM Agents",
        candidates,
    )


def test_source_title_candidates_skip_google_permission_boilerplate():
    text = (
        "[page 1]\n"
        "Provided proper attribution is provided, Google hereby grants permission to\n"
        "reproduce the tables and figures in this paper solely for use in journalistic or\n"
        "scholarly works.\n"
        "Attention Is All You Need\n"
        "Ashish Vaswani, Noam Shazeer, Niki Parmar\n"
        "Abstract\n"
        "The dominant sequence transduction models are based on complex recurrent networks.\n"
    )

    candidates = source_title_candidates(text)

    assert candidates[0] == "Attention Is All You Need"
    assert source_title_matches("Attention Is All You Need", candidates)


def test_source_title_candidates_skip_acl_copyright_boilerplate():
    text = (
        "[page 1]\n"
        "August 11-16, 2024 ©2024 Association for Computational Linguistics\n"
        "AppWorld: A Controllable World of Apps and People\n"
        "for Benchmarking Interactive Coding Agents*\n"
        "Harsh Trivedi and Tushar Khot\n"
        "Abstract\n"
        "We introduce a controllable benchmark for interactive coding agents.\n"
    )

    candidates = source_title_candidates(text)

    assert candidates[0] == "AppWorld: A Controllable World of Apps and People"
    assert source_title_matches(
        "AppWorld: A Controllable World of Apps and People for Benchmarking Interactive Coding Agents",
        candidates,
    )


def test_source_title_candidates_match_title_with_arxiv_header_and_subtitle_wrap():
    text = (
        "[page 1]\n"
        "arXiv:2601.12345v2 [cs.CL] 23 May 2026\n"
        "Refgate for Long-Form Manuscripts:\n"
        "A Source-Grounded Reference Gate\n"
        "Ada Smith and Bert Jones\n"
        "Abstract\n"
        "We study deterministic reference verification for manuscripts.\n"
    )

    candidates = source_title_candidates(text)

    assert candidates[0] == "Refgate for Long-Form Manuscripts:"
    assert source_title_matches(
        "Refgate for Long-Form Manuscripts: A Source-Grounded Reference Gate",
        candidates,
    )


def test_source_title_matches_tex_tau_unicode_and_pdf_spacing():
    assert source_title_matches(
        "{$\\tau$-bench}: A Benchmark for Tool-Agent-User Interaction in Real-World Domains",
        ["τ -bench: A Benchmark for T ool-Agent-User"],
    )


def test_source_title_check_blocks_when_title_is_not_on_first_page(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    source = tmp_path / "debenedetti2024agentdojo.txt"
    source_map = tmp_path / "source_map.tsv"
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    source.write_text(
        "[page 1]\n"
        "Conference Front Matter\n"
        "Table of Contents\n\n"
        "[page 2]\n"
        "AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents\n"
        "Edoardo Debenedetti\n",
        encoding="utf-8",
    )
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\tevidence_kind\n"
        f"debenedetti2024agentdojo\t{source.name}\t{source.name}\tsource_text\n",
        encoding="utf-8",
    )

    exit_code = main(["check-source-titles", "--lock", str(lock), "--source-map", str(source_map), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["blocking_issues"][0]["code"] == "SOURCE_TITLE_MISMATCH"
    assert payload["data"]["results"][0]["title_candidates"][0] == "Conference Front Matter"


def test_check_source_titles_blocks_mismatched_first_page_title(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    source = tmp_path / "debenedetti2024agentdojo.txt"
    source_map = tmp_path / "source_map.tsv"
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    source.write_text(
        "[page 1]\n"
        "A Completely Different Paper Title\n"
        "Ada Example\n\n"
        "Abstract\n"
        "Refgate verifies references with source evidence before bibliography approval.\n",
        encoding="utf-8",
    )
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\tevidence_kind\n"
        f"debenedetti2024agentdojo\t{source.name}\t{source.name}\tsource_text\n",
        encoding="utf-8",
    )

    exit_code = main(["check-source-titles", "--lock", str(lock), "--source-map", str(source_map), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "source_titles_checked"
    assert any(issue["code"] == "SOURCE_TITLE_MISMATCH" for issue in payload["blocking_issues"])
    assert payload["data"]["results"][0]["title_candidates"][0] == "A Completely Different Paper Title"
    assert payload["next_actions"][0]["code"] == "REVIEW_SOURCE_TITLE_MISMATCH"
    assert payload["next_actions"][0]["kind"] == "source_integrity_review"
    assert payload["next_actions"][0]["review_schema"]["format"] == "jsonl"


def test_check_source_titles_accepts_reviewed_official_metadata_mismatch(tmp_path, capsys):
    lock = tmp_path / "refgate.lock.json"
    source = tmp_path / "debenedetti2024agentdojo.txt"
    source_map = tmp_path / "source_map.tsv"
    title_review = tmp_path / "source_title_review.jsonl"
    expected_title = "AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents"
    observed_title = "A Completely Different Paper Title"
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    source.write_text(
        "[page 1]\n"
        f"{observed_title}\n"
        "Ada Example\n\n"
        "Abstract\n"
        "Refgate verifies references with source evidence before bibliography approval.\n",
        encoding="utf-8",
    )
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\tevidence_kind\n"
        f"debenedetti2024agentdojo\t{source.name}\t{source.name}\tsource_text\n",
        encoding="utf-8",
    )
    title_review.write_text(
        json.dumps(
            {
                "citation_key": "debenedetti2024agentdojo",
                "source_text": str(source),
                "decision": "accepted_official_metadata_mismatch",
                "expected_title": expected_title,
                "source_title": observed_title,
                "reviewer": "test",
                "notes": "Official record and mapped PDF first page were manually compared.",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "check-source-titles",
            "--lock",
            str(lock),
            "--source-map",
            str(source_map),
            "--title-review",
            str(title_review),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["blocking_issues"] == []
    assert payload["data"]["reviewed_mismatch_count"] == 1
    assert payload["data"]["results"][0]["reviewed_mismatch"] is True
    assert payload["warnings"][0]["code"] == "SOURCE_TITLE_MISMATCH_REVIEWED"
    assert payload["next_actions"] == []


def test_check_source_titles_accepts_review_source_text_from_cwd_relative_path(tmp_path, monkeypatch, capsys):
    paper_dir = tmp_path / "paper"
    source_dir = paper_dir / ".refgate" / "sources"
    source_dir.mkdir(parents=True)
    lock = paper_dir / "refgate.lock.json"
    source = source_dir / "debenedetti2024agentdojo.txt"
    source_map = paper_dir / ".refgate" / "source_map.tsv"
    title_review = paper_dir / ".refgate" / "source_title_review.jsonl"
    expected_title = "AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents"
    observed_title = "A Reviewed Metadata Cover Page"
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    source.write_text(
        "[page 1]\n"
        f"{observed_title}\n"
        "Ada Example\n\n"
        "Abstract\n"
        "Refgate verifies references with source evidence before bibliography approval.\n",
        encoding="utf-8",
    )
    source_map.write_text(
        "citation_key\tsource_text\tsource_label\tevidence_kind\n"
        "debenedetti2024agentdojo\tsources/debenedetti2024agentdojo.txt\tsources/debenedetti2024agentdojo.txt\tsource_text\n",
        encoding="utf-8",
    )
    title_review.write_text(
        json.dumps(
            {
                "citation_key": "debenedetti2024agentdojo",
                "source_text": "paper/.refgate/sources/debenedetti2024agentdojo.txt",
                "decision": "accepted_official_metadata_mismatch",
                "expected_title": expected_title,
                "source_title": observed_title,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "check-source-titles",
            "--lock",
            str(lock),
            "--source-map",
            str(source_map),
            "--title-review",
            str(title_review),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data"]["reviewed_mismatch_count"] == 1
    assert payload["warnings"][0]["code"] == "SOURCE_TITLE_MISMATCH_REVIEWED"


def test_paper_audit_blocks_when_mapped_source_title_mismatches_lock_title(tmp_path, capsys):
    tex = tmp_path / "manuscript.tex"
    bib = tmp_path / "sample.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    tex.write_text((FIXTURES / "manuscript.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    claims.write_text(
        (FIXTURES / "claims_checked.tsv").read_text(encoding="utf-8").replace("Fixture evidence.", "Refgate verifies references."),
        encoding="utf-8",
    )
    (source_dir / "debenedetti2024agentdojo.txt").write_text(
        "[page 1]\n"
        "Securing Large Language Model Agents via Structured Graph Abstraction\n"
        "Ada Example\n\n"
        "Refgate verifies references with source evidence before bibliography approval.\n",
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
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "SOURCE_TITLE_MISMATCH" for issue in payload["blocking_issues"])
    assert payload["data"]["source_title_check"]["checked"] == 1
    assert any(action["code"] == "REVIEW_SOURCE_TITLE_MISMATCH" for action in payload["next_actions"])
    assert "## Source Title Check" in report.read_text(encoding="utf-8")


def test_paper_audit_accepts_reviewed_source_title_mismatch(tmp_path, capsys):
    tex = tmp_path / "manuscript.tex"
    bib = tmp_path / "sample.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    source_dir = tmp_path / "sources"
    title_review = tmp_path / "source_title_review.jsonl"
    source_dir.mkdir()
    tex.write_text((FIXTURES / "manuscript.tex").read_text(encoding="utf-8"), encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    claims.write_text(
        (FIXTURES / "claims_checked.tsv").read_text(encoding="utf-8").replace("Fixture evidence.", "Refgate verifies references."),
        encoding="utf-8",
    )
    source = source_dir / "debenedetti2024agentdojo.txt"
    observed_title = "Securing Large Language Model Agents via Structured Graph Abstraction"
    expected_title = "AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents"
    source.write_text(
        "[page 1]\n"
        f"{observed_title}\n"
        "Ada Example\n\n"
        "Refgate verifies references with source evidence before bibliography approval.\n",
        encoding="utf-8",
    )
    title_review.write_text(
        json.dumps(
            {
                "citation_key": "debenedetti2024agentdojo",
                "source_text": str(source),
                "decision": "accepted_official_metadata_mismatch",
                "expected_title": expected_title,
                "source_title": observed_title,
                "reviewer": "test",
                "notes": "Official record and mapped PDF first page were manually compared.",
            },
            sort_keys=True,
        )
        + "\n",
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
            "--source-title-review",
            str(title_review),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["blocking_issues"] == []
    assert payload["data"]["source_title_check"]["reviewed_mismatch_count"] == 1
    assert any(issue["code"] == "SOURCE_TITLE_MISMATCH_REVIEWED" for issue in payload["warnings"])
    report_text = report.read_text(encoding="utf-8")
    assert "### Reviewed Mismatches" in report_text
    assert observed_title in report_text
