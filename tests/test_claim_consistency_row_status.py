import pytest

from refgate.claim_audit import write_claim_rows
from refgate.claim_consistency import review_claim_consistency


@pytest.mark.parametrize("kind,claim,evidence,code", [
    ("abstract", "Tests detect real faults", "Tests detect real faults",
     "CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE"),
    ("source_text", "Tests always detect real faults", "Tests may detect real faults",
     "CLAIM_MAY_BE_TOO_STRONG"),
])
def test_blocking_issue_invalidates_only_its_own_result(tmp_path, kind, claim, evidence, code):
    path = tmp_path / "claims.tsv"
    good = dict(citation_key="alpha", claim_text="Tests detect real faults",
                quote_or_evidence="Tests detect real faults", status="checked",
                evidence_kind="source_text", source_location="section 2")
    write_claim_rows(path, [dict(good, claim_id="claim-0001"),
                           dict(good, claim_id="claim-0002", claim_text=claim,
                                quote_or_evidence=evidence, evidence_kind=kind),
                           dict(good, claim_id="claim-0003")])
    results, issues = review_claim_consistency(path, require_passing_status=True)
    assert any(i.code == code and i.severity == "blocking" for i in issues)
    assert [r.ok for r in results] == [True, False, True]
    # Non-submission warnings must not become new blocking decisions.
    results, issues = review_claim_consistency(path, require_passing_status=False)
    assert [r.ok for r in results] == [True, True, True]
    assert not any(i.severity == "blocking" for i in issues)
