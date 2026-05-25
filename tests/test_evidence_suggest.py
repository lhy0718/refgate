import csv
import json
from pathlib import Path

import pytest

from refgate.cli import main
from refgate.source_text import read_source_text


FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_evidence_suggest_fills_review_suggestion(tmp_path, capsys):
    claims_path = tmp_path / "claims.tsv"
    output_path = tmp_path / "claims_suggested.tsv"
    claims_path.write_text((FIXTURES / "claims_unchecked.tsv").read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "evidence-suggest",
            "--claims",
            str(claims_path),
            "--text",
            str(FIXTURES / "source_excerpt.txt"),
            "--output",
            str(output_path),
            "--citation-key",
            "debenedetti2024agentdojo",
            "--source-label",
            "agentdojo extracted text",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert payload["data"]["updated"] == 1
    assert rows[0]["status"] == "needs_review"
    assert rows[0]["source_location"] == "agentdojo extracted text: paragraph 3"
    assert "verifies references" in rows[0]["quote_or_evidence"].lower()


def test_cli_evidence_suggest_accepts_pdf_when_extra_is_installed(tmp_path, capsys):
    pytest.importorskip("pypdf")
    try:
        extracted = read_source_text(FIXTURES / "source_excerpt_minimal.pdf")
    except Exception as exc:
        pytest.skip(f"minimal PDF fixture is not readable in this pypdf environment: {exc}")
    if "Refgate" not in extracted:
        pytest.skip("minimal PDF fixture did not yield expected extractable text")

    claims_path = tmp_path / "claims.tsv"
    output_path = tmp_path / "claims_suggested.tsv"
    claims_path.write_text((FIXTURES / "claims_unchecked.tsv").read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(
        [
            "evidence-suggest",
            "--claims",
            str(claims_path),
            "--text",
            str(FIXTURES / "source_excerpt_minimal.pdf"),
            "--output",
            str(output_path),
            "--citation-key",
            "debenedetti2024agentdojo",
            "--source-label",
            "source pdf",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8"), delimiter="\t"))
    assert exit_code == 0
    assert payload["data"]["updated"] == 1
    assert rows[0]["status"] == "needs_review"


def test_cli_validate_source_text_accepts_multi_page_pdf_when_extra_is_installed(capsys):
    pytest.importorskip("pypdf")
    pdf_path = FIXTURES / "source_excerpt_two_page.pdf"
    try:
        extracted = read_source_text(pdf_path)
    except Exception as exc:
        pytest.skip(f"two-page PDF fixture is not readable in this pypdf environment: {exc}")
    if "page two" not in extracted.lower():
        pytest.skip("two-page PDF fixture did not yield expected extractable text")

    exit_code = main(["validate-source-text", "--text", str(pdf_path), "--min-chars", "50", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["results"][0]["kind"] == "pdf"
    assert payload["data"]["results"][0]["ok"] is True
    assert payload["data"]["results"][0]["page_marker_count"] >= 2


def test_cli_vision_extract_plan_writes_codex_handoff_manifest(tmp_path, capsys):
    output = tmp_path / "vision_plan.json"
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "page-001.png").write_bytes(b"fixture")

    exit_code = main(
        [
            "vision-extract-plan",
            "--pdf",
            str(FIXTURES / "source_excerpt_minimal.pdf"),
            "--citation-key",
            "debenedetti2024agentdojo",
            "--source-label",
            "scanned source",
            "--image-dir",
            str(image_dir),
            "--page",
            "1",
            "--output",
            str(output),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "vision_extraction_plan_ready"
    assert saved["mode"] == "codex_vision_handoff"
    assert saved["can_refgate_call_codex_directly"] is False
    assert saved["pages"][0]["image_exists"] is True
    assert saved["source_map_row_template"]["citation_key"] == "debenedetti2024agentdojo"
