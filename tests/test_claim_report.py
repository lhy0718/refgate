import json
from pathlib import Path

from refgate.claim_audit import render_claim_review_report
from refgate.cli import main


FIXTURES = Path(__file__).parent / "fixtures"


def test_render_claim_review_report_shows_missing_evidence():
    report = render_claim_review_report(FIXTURES / "claims_unchecked.tsv")

    assert "# Refgate Claim Review" in report
    assert "Evidence:" in report
    assert "(missing)" in report


def test_cli_claim_report_writes_markdown(tmp_path, capsys):
    output = tmp_path / "claim_review.md"

    exit_code = main(["claim-report", "--claims", str(FIXTURES / "claims_unchecked.tsv"), "--output", str(output), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "claim_report_ready"
    assert output.read_text(encoding="utf-8").startswith("# Refgate Claim Review")
