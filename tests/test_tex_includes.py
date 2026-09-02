import csv
import json
from pathlib import Path

from refgate.cli import main


FIXTURES = Path(__file__).parent / "fixtures"


def test_claim_stubs_follow_input_and_include_files(tmp_path, capsys):
    root = tmp_path / "paper.tex"
    sections = tmp_path / "sections"
    sections.mkdir()
    output = tmp_path / "claims.tsv"
    root.write_text(
        "\\section{Main}\n"
        "Root claim introduces the benchmark \\cite{root2026}.\n"
        "\\input{sections/background}\n",
        encoding="utf-8",
    )
    (sections / "background.tex").write_text(
        "Included claim covers source integrity checks \\cite{included2026}.\n",
        encoding="utf-8",
    )

    exit_code = main(["claim-stubs", "--tex", str(root), "--output", str(output), "--json"])

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert payload["data"]["tex_sources"] == ["paper.tex", "sections/background.tex"]
    assert [row["citation_key"] for row in rows] == ["root2026", "included2026"]
    assert rows[0]["source_file"] == "paper.tex"
    assert rows[1]["source_file"] == "sections/background.tex"
    assert rows[1]["manuscript_location"] == "sections/background.tex:line 1"


def test_audit_blocks_missing_include_in_submission_mode(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "claims.tsv"
    tex.write_text("\\input{sections/missing}\n\\cite{debenedetti2024agentdojo}\n", encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")
    claims.write_text((FIXTURES / "claims_checked.tsv").read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "audit",
            "--tex",
            str(tex),
            "--bib",
            str(bib),
            "--lock",
            str(lock),
            "--claims",
            str(claims),
            "--submission",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert any(issue["code"] == "TEX_INCLUDE_MISSING" for issue in payload["blocking_issues"])


def test_paper_audit_uses_included_citations_for_bib_consistency(tmp_path, capsys):
    tex = tmp_path / "paper.tex"
    section = tmp_path / "related.tex"
    bib = tmp_path / "references.bib"
    lock = tmp_path / "refgate.lock.json"
    claims = tmp_path / "claims.tsv"
    report = tmp_path / "refgate_audit.md"
    queries = tmp_path / "refgate_queries.json"
    tex.write_text("\\input{related}\n", encoding="utf-8")
    section.write_text("Included paper claim cites AgentDojo \\cite{debenedetti2024agentdojo}.\n", encoding="utf-8")
    bib.write_text((FIXTURES / "sample.bib").read_text(encoding="utf-8"), encoding="utf-8")
    lock.write_text((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"), encoding="utf-8")

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
    rows = list(csv.DictReader(claims.open(newline="", encoding="utf-8"), delimiter="\t"))
    codes = {issue["code"] for issue in payload["blocking_issues"]}
    assert exit_code == 1
    assert "BIB_ENTRY_NOT_CITED" not in codes
    assert rows[0]["source_file"] == "related.tex"
    assert payload["data"]["tex_sources"] == ["paper.tex", "related.tex"]


def test_claim_stubs_supports_additional_standalone_tex_roots(tmp_path, capsys):
    main_tex = tmp_path / "main.tex"
    supplementary_tex = tmp_path / "supplementary.tex"
    output = tmp_path / "claims.tsv"
    main_tex.write_text("Main claim cites \\cite{mainref}.\n", encoding="utf-8")
    supplementary_tex.write_text("Supplementary claim cites \\cite{suppref}.\n", encoding="utf-8")

    exit_code = main(
        [
            "claim-stubs",
            "--tex",
            str(main_tex),
            "--extra-tex",
            str(supplementary_tex),
            "--output",
            str(output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert payload["data"]["tex_sources"] == ["main.tex", "supplementary.tex"]
    assert [row["citation_key"] for row in rows] == ["mainref", "suppref"]


def test_paper_audit_uses_citation_union_from_standalone_tex_roots(tmp_path, capsys):
    main_tex = tmp_path / "main.tex"
    supplementary_tex = tmp_path / "supplementary.tex"
    bib = tmp_path / "references.bib"
    main_tex.write_text("Main paper cites \\cite{mainref}.\n", encoding="utf-8")
    supplementary_tex.write_text(
        "Supplement cites \\cite{sroie_mirror,openai_models}.\n",
        encoding="utf-8",
    )
    bib.write_text(
        """@misc{mainref, title={Main Reference}, author={Doe, Jane}, year={2026}}
@misc{sroie_mirror, title={SROIE Mirror}, author={Doe, Jane}, year={2026}}
@misc{openai_models, title={OpenAI Models}, author={Doe, Jane}, year={2026}}
@misc{uncitedref, title={Uncited Reference}, author={Doe, Jane}, year={2026}}
""",
        encoding="utf-8",
    )

    def run_audit(prefix: str, *, include_supplementary: bool):
        args = [
            "paper-audit",
            "--tex",
            str(main_tex),
            "--bib",
            str(bib),
            "--lock",
            str(tmp_path / f"{prefix}.lock.json"),
            "--claims",
            str(tmp_path / f"{prefix}.claims.tsv"),
            "--report",
            str(tmp_path / f"{prefix}.audit.md"),
            "--resolver-output",
            str(tmp_path / f"{prefix}.queries.json"),
            "--submission",
            "--include-issues",
            "--json",
        ]
        if include_supplementary:
            args[3:3] = ["--extra-tex", str(supplementary_tex)]
        exit_code = main(args)
        return exit_code, json.loads(capsys.readouterr().out)

    combined_exit, combined = run_audit("combined", include_supplementary=True)
    main_only_exit, main_only = run_audit("main-only", include_supplementary=False)

    combined_uncited = {
        issue.get("citation_key")
        for issue in combined["blocking_issues"]
        if issue["code"] == "BIB_ENTRY_NOT_CITED"
    }
    main_only_uncited = {
        issue.get("citation_key")
        for issue in main_only["blocking_issues"]
        if issue["code"] == "BIB_ENTRY_NOT_CITED"
    }
    assert combined_exit == 1
    assert main_only_exit == 1
    assert combined["data"]["tex_sources"] == ["main.tex", "supplementary.tex"]
    assert not {"sroie_mirror", "openai_models"} & combined_uncited
    assert "uncitedref" in combined_uncited
    assert {"sroie_mirror", "openai_models", "uncitedref"} <= main_only_uncited
    rerun_commands = [
        action.get("command", "")
        for action in combined["next_actions"]
        if "paper-audit" in action.get("command", "")
    ]
    assert rerun_commands
    assert all(f"--extra-tex {supplementary_tex}" in command for command in rerun_commands)
