from pathlib import Path

from refgate.claim_audit import audit_claims_table, audit_tex_bib_consistency, extract_citation_keys


FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_citation_keys_from_tex():
    assert extract_citation_keys(r"\citep{alpha2024,beta2025}") == {"alpha2024", "beta2025"}


def test_audit_claims_blocks_unchecked_submission_claim():
    issues = audit_claims_table(FIXTURES / "claims_unchecked.tsv", submission=True)

    assert any(issue.code == "CLAIM_NOT_CHECKED" and issue.severity == "blocking" for issue in issues)


def test_audit_tex_bib_consistency_passes_fixture():
    tex_text = (FIXTURES / "manuscript.tex").read_text(encoding="utf-8")
    bib_text = (FIXTURES / "sample.bib").read_text(encoding="utf-8")

    issues = audit_tex_bib_consistency(tex_text, bib_text, submission=True)

    assert not [issue for issue in issues if issue.severity == "blocking"]
