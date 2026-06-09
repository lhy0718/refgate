from pathlib import Path

from refgate.cache import RawRecord, read_raw_record, write_raw_record
from refgate.lockfile import merge_lock_entry
from refgate.models import Lockfile
from refgate.reports import render_markdown_report
from refgate.audit import audit_bibliography_result
from refgate.claim_audit import audit_claims_table
import json


FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden"


def test_cache_write_read_roundtrip(tmp_path):
    record = RawRecord(
        source="crossref",
        url="https://api.crossref.org/works/10.5555/refgate.fixture",
        status=200,
        headers={"content-type": "application/json"},
        body='{"ok": true}',
        fetched_at="2026-05-19T00:00:00+00:00",
    )

    write_raw_record(record, cache_root=tmp_path)
    restored = read_raw_record(record.source, record.url, cache_root=tmp_path)

    assert restored is not None
    assert restored.body_sha256 == record.body_sha256
    assert restored.headers["content-type"] == "application/json"


def test_merge_lock_entry_replaces_existing_key():
    lockfile = Lockfile.from_dict(json.loads((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8")))
    entry = lockfile.entries[0]
    entry.bibtex["field_checks"] = {"title": "checked"}

    merged = merge_lock_entry(lockfile, entry)

    assert len(merged.entries) == 1
    assert merged.entries[0].bibtex["field_checks"]["title"] == "checked"


def test_audit_report_matches_golden():
    bib_text = (FIXTURES / "sample.bib").read_text(encoding="utf-8")
    lockfile = Lockfile.from_dict(json.loads((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8")))
    audit_result = audit_bibliography_result(bib_text, lockfile, submission=True)
    report = render_markdown_report(
        lockfile,
        audit_result.issues,
        accepted_provenance_notes=audit_result.accepted_provenance_notes,
    )

    assert report == (GOLDEN / "audit_pass_report.md").read_text(encoding="utf-8")


def test_lock_entry_summary_matches_golden():
    lockfile = Lockfile.from_dict(json.loads((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8")))
    entry = lockfile.entries[0]
    summary = {
        "authority_source": entry.authority.get("source"),
        "bibtex_source_kind": entry.bibtex.get("source_kind"),
        "citation_key": entry.citation_key,
        "status": entry.status,
    }

    assert summary == json.loads((GOLDEN / "lock_entry_summary.json").read_text(encoding="utf-8"))


def test_blocking_claim_audit_matches_golden():
    issues = audit_claims_table(FIXTURES / "claims_unchecked.tsv", submission=True)
    result = {
        "ok": not any(issue.severity == "blocking" for issue in issues),
        "blocking_issues": [issue.to_dict() for issue in issues if issue.severity == "blocking"],
        "warnings": [issue.to_dict() for issue in issues if issue.severity == "warning"],
    }

    assert result == json.loads((GOLDEN / "blocking_claim_audit.json").read_text(encoding="utf-8"))
