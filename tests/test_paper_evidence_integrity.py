from refgate.claim_audit import read_claim_rows, write_claim_rows
from refgate.claim_source_check import run_claim_source_check
from refgate.paper_flow import run_paper_audit
from refgate.source_title import check_source_titles
from refgate.claim_consistency import _overlap_terms, review_claim_consistency


def test_lexical_overlap_tolerates_pdf_wraps_without_approving_claims(tmp_path):
    assert _overlap_terms("Human character representations") == _overlap_terms("Hu-\nmans character repre-\nsentations")
    assert _overlap_terms("confusable inventories") == _overlap_terms("confusables inventory")
    assert _overlap_terms("rank words") == _overlap_terms("ranking word")
    assert _overlap_terms("tests testing") == {"test"}
    claims = tmp_path / "claims.tsv"
    write_claim_rows(claims, [{"claim_id": "claim-0001", "claim_text": "Rank words",
                             "quote_or_evidence": "Word ranking", "status": "needs_review"}])
    results, issues = review_claim_consistency(claims, require_passing_status=True)
    assert not results[0].ok
    assert any(i.code == "CLAIM_STATUS_NOT_FINAL" for i in issues)
    assert not (_overlap_terms("banana orchard") & _overlap_terms("fault detection"))


def test_checked_quotes_still_require_every_cited_source(tmp_path):
    claims = tmp_path / "claims.tsv"
    write_claim_rows(claims, [{
        "claim_id": "claim-0001", "citation_key": "alpha,beta",
        "claim_text": "Tests detect real faults", "status": "checked",
        "quote_or_evidence": "Tests detect real faults", "evidence_kind": "source_text",
        "source_location": "section 2",
    }])
    source_map = tmp_path / "sources.tsv"
    source_map.write_text("citation_key\tsource_text\n")
    result = run_claim_source_check(claims, source_map, require_passing_status=True)
    assert result["missing_source_keys"] == ["alpha", "beta"]
    assert not result["ok"]
    source = tmp_path / "alpha.txt"
    source.write_text("Tests detect real faults. " * 30)
    source_map.write_text("citation_key\tsource_text\nalpha\talpha.txt\n")
    result = run_claim_source_check(claims, source_map, require_passing_status=True)
    assert result["missing_source_keys"] == ["beta"]


def test_manuscript_changes_invalidate_old_claim_coverage(tmp_path):
    tex, bib, lock, claims = [tmp_path / name for name in ("main.tex", "refs.bib", "lock.json", "claims.tsv")]
    tex.write_text(r"Tests detect real faults \cite{alpha}.")
    bib.write_text("@article{alpha, title={Fault Detection}, author={A. Author}, year={2024}}")
    args = dict(tex=tex, bib=bib, lock=lock, claims=claims, submission=True)
    run_paper_audit(**args)
    rows = read_claim_rows(claims)
    rows[0].update(status="checked", source_location="section 2", evidence_kind="source_text",
                   quote_or_evidence="Tests detect real faults")
    write_claim_rows(claims, rows)
    result = run_paper_audit(**args)
    assert "CLAIM_SOURCE_MAP_REQUIRED" in {i["code"] for i in result["blocking_issues"]}
    assert next(p for p in result["phase_summary"] if p["phase"] == "source-title")["status"] == "not_run"
    assert "CLAIM_CURRENT_CONTEXT_UNREVIEWED" not in {i["code"] for i in result["blocking_issues"]}
    tex.write_text(r"Tests detect every possible fault \cite{alpha}.")
    result = run_paper_audit(**args)
    assert "CLAIM_CURRENT_CONTEXT_UNREVIEWED" in {i["code"] for i in result["blocking_issues"]}
    assert read_claim_rows(claims) == rows
    source_map = tmp_path / "sources.tsv"
    source_map.write_text("citation_key\tsource_text\n")
    titles = check_source_titles(lock, source_map)
    assert not titles["ok"]
    assert titles["checked"] == 0
    assert titles["blocking_issues"][0]["code"] == "SOURCE_TITLE_NO_SOURCES"
