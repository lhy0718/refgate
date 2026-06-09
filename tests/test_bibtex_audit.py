from pathlib import Path
import copy
import json

from refgate.audit import audit_bibliography, audit_bibliography_result
from refgate.bibtex import parse_bibtex_file
from refgate.models import Lockfile


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_bibtex_file_extracts_entry():
    bib_entries = parse_bibtex_file((FIXTURES / "sample.bib").read_text(encoding="utf-8"))

    assert "debenedetti2024agentdojo" in bib_entries
    assert bib_entries["debenedetti2024agentdojo"]["year"] == "2024"


def test_audit_bibliography_passes_verified_official_export():
    bib_text = (FIXTURES / "sample.bib").read_text(encoding="utf-8")
    lockfile = Lockfile.from_dict(json.loads((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8")))

    issues = audit_bibliography(bib_text, lockfile, submission=True)

    assert not [issue for issue in issues if issue.severity == "blocking"]


def _fixture_lock_data() -> dict:
    return json.loads((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8"))


def _fixture_bib_text(extra_field: str = "") -> str:
    return (
        "@inproceedings{debenedetti2024agentdojo,\n"
        "  title = {AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents},\n"
        "  author = {Debenedetti, Edoardo},\n"
        "  booktitle = {Advances in Neural Information Processing Systems},\n"
        "  year = {2024},\n"
        f"{extra_field}"
        "  url = {https://proceedings.neurips.cc/paper_files/paper/2024/hash/example-Abstract-Conference.html}\n"
        "}\n"
    )


def _lockfile_with_entry(entry: dict) -> Lockfile:
    data = _fixture_lock_data()
    data["entries"] = [entry]
    return Lockfile.from_dict(data)


def test_verified_arxiv_fallback_becomes_accepted_provenance_note():
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["status"] = "arxiv_fallback_verified"
    entry["record"]["doi"] = None
    entry["record"]["arxiv_id"] = "2406.13352"
    entry["record"]["accessed_at"] = "2026-06-09"
    entry["authority"] = {
        "source": "arxiv",
        "record_url": "https://arxiv.org/abs/2406.13352",
        "retrieval_method": "arxiv_exact_id",
        "source_priority": 2,
    }
    entry["bibtex"]["source_kind"] = "arxiv_manual_normalized"
    entry["bibtex"]["fallback_reason"] = "Official publication BibTeX was not confirmed; arXiv record was verified as fallback provenance."
    entry["bibtex"]["field_checks"]["doi"] = "missing"

    result = audit_bibliography_result(_fixture_bib_text(), _lockfile_with_entry(entry), submission=True)

    assert not any(issue.code == "ARXIV_FALLBACK" for issue in result.issues)
    assert any(issue.code == "ARXIV_FALLBACK" for issue in result.accepted_provenance_notes)
    assert any(issue.code == "DOI_MISSING" for issue in result.accepted_provenance_notes)


def test_verified_doi_missing_manual_fallback_becomes_accepted_provenance_note():
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["status"] = "verified_manual_fallback"
    entry["record"]["doi"] = None
    entry["authority"] = {
        "source": "openreview",
        "record_url": "https://openreview.net/forum?id=fixture",
        "retrieval_method": "reviewed_official_html",
        "source_priority": 2,
    }
    entry["bibtex"]["source_kind"] = "publisher_metadata_manual_normalized"
    entry["bibtex"]["fallback_reason"] = "Reviewed official record; manual BibTeX fallback retained because no official BibTeX endpoint was verified."
    entry["bibtex"]["field_checks"]["doi"] = "missing"

    result = audit_bibliography_result(_fixture_bib_text(), _lockfile_with_entry(entry), submission=True)

    assert not any(issue.code == "DOI_MISSING" for issue in result.issues)
    assert any(issue.code == "DOI_MISSING" for issue in result.accepted_provenance_notes)


def test_unverified_arxiv_fallback_remains_unresolved_warning():
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["status"] = "official_record_pending"
    entry["record"]["doi"] = None
    entry["record"]["arxiv_id"] = "2406.13352"
    entry["record"]["accessed_at"] = "2026-06-09"
    entry["authority"] = {"source": "arxiv", "record_url": "https://arxiv.org/abs/2406.13352", "source_priority": 2}
    entry["bibtex"]["source_kind"] = "arxiv_manual_normalized"
    entry["bibtex"]["fallback_reason"] = "arXiv fallback still needs reviewed provenance."
    entry["bibtex"]["field_checks"]["doi"] = "missing"

    result = audit_bibliography_result(_fixture_bib_text(), _lockfile_with_entry(entry), submission=True)

    assert any(issue.code == "ARXIV_FALLBACK" and issue.severity == "warning" for issue in result.issues)
    assert not any(issue.code == "ARXIV_FALLBACK" for issue in result.accepted_provenance_notes)


def test_record_doi_missing_from_bibtex_remains_unresolved_warning():
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["record"]["doi"] = "10.5555/refgate.fixture"
    entry["bibtex"]["field_checks"]["doi"] = "checked"

    result = audit_bibliography_result(_fixture_bib_text(), _lockfile_with_entry(entry), submission=True)

    doi_warnings = [issue for issue in result.issues if issue.code == "DOI_MISSING"]
    assert len(doi_warnings) == 1
    assert doi_warnings[0].message == "BibTeX entry is missing DOI present in the lockfile record."
    assert result.accepted_provenance_notes == []
