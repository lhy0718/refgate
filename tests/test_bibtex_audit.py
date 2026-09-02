from pathlib import Path
import copy
import json

import pytest

from refgate.audit import audit_bibliography, audit_bibliography_result
from refgate.bibtex import parse_bibtex_file, sha256_text
from refgate.models import Lockfile
from refgate.resolver import normalize_title


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


def test_verified_arxiv_fallback_becomes_accepted_provenance_note_and_monitor_warning():
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
    monitor_warnings = [issue for issue in result.issues if issue.code == "ARXIV_OFFICIAL_RECORD_MONITOR_REQUIRED"]
    assert len(monitor_warnings) == 1
    assert monitor_warnings[0].severity == "warning"
    assert monitor_warnings[0].citation_key == "debenedetti2024agentdojo"


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


def test_manual_fallback_is_blocking_when_policy_disallows_it():
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["status"] = "verified_manual_fallback"
    entry["record"]["doi"] = "10.5555/refgate.fixture"
    entry["authority"] = {
        "source": "crossref",
        "record_url": "https://doi.org/10.5555/refgate.fixture",
        "retrieval_method": "reviewed_official_metadata",
        "source_priority": 2,
    }
    entry["bibtex"]["source_kind"] = "publisher_metadata_manual_normalized"
    entry["bibtex"]["fallback_reason"] = "Reviewed official metadata; no official BibTeX endpoint was verified."
    entry["bibtex"]["field_checks"]["doi"] = "checked"
    lock_data = _fixture_lock_data()
    lock_data["audit_policy"]["allow_manual_fallback"] = False
    lock_data["entries"] = [entry]

    result = audit_bibliography_result(
        _fixture_bib_text(extra_field="  doi = {10.5555/refgate.fixture},\n"),
        Lockfile.from_dict(lock_data),
        submission=True,
    )

    blockers = [issue for issue in result.issues if issue.severity == "blocking"]
    assert any(issue.code == "MANUAL_FALLBACK_NOT_ALLOWED" for issue in blockers)


def test_arxiv_fallback_is_blocking_when_policy_disallows_it():
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
    lock_data = _fixture_lock_data()
    lock_data["audit_policy"]["allow_arxiv_fallback"] = False
    lock_data["entries"] = [entry]

    result = audit_bibliography_result(_fixture_bib_text(), Lockfile.from_dict(lock_data), submission=True)

    blockers = [issue for issue in result.issues if issue.severity == "blocking"]
    assert any(issue.code == "ARXIV_FALLBACK_NOT_ALLOWED" for issue in blockers)


def test_reviewed_manual_fallback_with_blocked_official_endpoint_is_accepted_note():
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["status"] = "verified_manual_fallback"
    entry["authority"]["bibtex_url"] = "https://publisher.example/blocked-official.bib"
    entry["bibtex"]["source_kind"] = "publisher_metadata_manual_normalized"
    entry["bibtex"]["fallback_reason"] = "Reviewed official HTML; official BibTeX endpoint was blocked during automated fetch."
    entry["bibtex"]["field_checks"]["doi"] = "checked"

    result = audit_bibliography_result(_fixture_bib_text(extra_field="  doi = {10.5555/refgate.fixture},\n"), _lockfile_with_entry(entry), submission=True)

    assert not any(issue.code == "OFFICIAL_EXPORT_NOT_USED" for issue in result.issues)
    assert any(issue.code == "OFFICIAL_EXPORT_NOT_USED" for issue in result.accepted_provenance_notes)


def test_unreasoned_manual_fallback_with_official_endpoint_stays_blocking():
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["status"] = "verified_manual_fallback"
    entry["authority"]["bibtex_url"] = "https://publisher.example/official.bib"
    entry["bibtex"]["source_kind"] = "publisher_metadata_manual_normalized"
    entry["bibtex"].pop("fallback_reason", None)
    entry["bibtex"]["field_checks"]["doi"] = "checked"

    result = audit_bibliography_result(_fixture_bib_text(extra_field="  doi = {10.5555/refgate.fixture},\n"), _lockfile_with_entry(entry), submission=True)

    assert any(issue.code == "OFFICIAL_EXPORT_NOT_USED" and issue.severity == "blocking" for issue in result.issues)
    assert any(issue.code == "FALLBACK_REASON_MISSING" and issue.severity == "blocking" for issue in result.issues)


def test_author_match_allows_bibtex_last_first_full_given_against_short_given():
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["record"]["authors"] = ["Yoshi Suhara", "Xiaolan Wang"]
    bib_text = (
        "@inproceedings{debenedetti2024agentdojo,\n"
        "  title = {AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents},\n"
        "  author = {Suhara, Yoshihiko and Wang, Xiaolan},\n"
        "  booktitle = {Advances in Neural Information Processing Systems},\n"
        "  year = {2024},\n"
        "  doi = {10.5555/refgate.fixture},\n"
        "  url = {https://proceedings.neurips.cc/paper_files/paper/2024/hash/example-Abstract-Conference.html}\n"
        "}\n"
    )

    result = audit_bibliography_result(bib_text, _lockfile_with_entry(entry), submission=True)

    assert not any(issue.code == "AUTHOR_MISMATCH" for issue in result.issues)


def test_title_normalization_matches_tex_apostrophe_and_curly_apostrophe():
    assert normalize_title("Can {LLM}s Ground when they (Don{'}t) Know") == normalize_title("Can LLMs Ground when they (Don’t) Know")


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


def test_official_export_audit_ignores_nonbibliographic_raw_text_differences():
    canonical = """@inproceedings{publisher-official-key,
  title = {Café LLM Study},
  author = {Doe, Jane and Smith, Ada},
  booktitle = {Proceedings of the Fixture Conference},
  year = {2026},
  pages = {10--20},
  doi = {10.1234/refgate.2026},
  publisher = {ACM}
}
"""
    manuscript = """@INPROCEEDINGS{manuscript_local_key,
  publisher = {Association for Computing Machinery},
  doi = {https://doi.org/10.1234/REFGATE.2026},
  pages = {10 - 20},
  year = 2026,
  booktitle = {Proceedings   of the Fixture Conference},
  author = {Doe, Jane   and Smith, Ada},
  title = {Café {LLM} Study}
}
"""
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["citation_key"] = "manuscript_local_key"
    entry["short_title"] = "Café LLM Study"
    entry["status"] = "verified_official_bibtex"
    entry["record"].update(
        {
            "title": "Café LLM Study",
            "authors": ["Doe, Jane", "Smith, Ada"],
            "year": 2026,
            "venue": "Proceedings of the Fixture Conference",
            "doi": "10.1234/refgate.2026",
        }
    )
    entry["bibtex"].update(
        {
            "citation_key": "manuscript_local_key",
            "source_kind": "official_export",
            "canonical_text": canonical,
            "normalized_sha256": sha256_text(canonical),
        }
    )

    result = audit_bibliography_result(manuscript, _lockfile_with_entry(entry), submission=True)

    assert not any(issue.code == "OFFICIAL_EXPORT_CONTENT_CHANGED" for issue in result.issues)
    assert not [issue for issue in result.issues if issue.severity == "blocking"]


@pytest.mark.parametrize(
    ("original", "changed"),
    [
        ("Official Title", "Changed Title"),
        ("Doe, Jane", "Roe, Jane"),
        ("Proceedings of the Fixture Conference", "Proceedings of a Different Conference"),
        ("2026", "2025"),
        ("10--20", "11--20"),
        ("10.1234/refgate.2026", "10.1234/refgate.changed"),
    ],
)
def test_official_export_audit_blocks_meaningful_metadata_change(original, changed):
    canonical = """@inproceedings{manuscript_local_key,
  title = {Official Title},
  author = {Doe, Jane},
  booktitle = {Proceedings of the Fixture Conference},
  year = {2026},
  pages = {10--20},
  doi = {10.1234/refgate.2026}
}
"""
    manuscript = canonical.replace(original, changed)
    entry = copy.deepcopy(_fixture_lock_data()["entries"][0])
    entry["citation_key"] = "manuscript_local_key"
    entry["record"].update(
        {
            "title": "Official Title",
            "authors": ["Doe, Jane"],
            "year": 2026,
            "venue": "Proceedings of the Fixture Conference",
            "doi": "10.1234/refgate.2026",
        }
    )
    entry["bibtex"].update(
        {
            "citation_key": "manuscript_local_key",
            "source_kind": "official_export",
            "canonical_text": canonical,
            "normalized_sha256": sha256_text(canonical),
        }
    )

    result = audit_bibliography_result(manuscript, _lockfile_with_entry(entry), submission=True)

    assert any(issue.code == "OFFICIAL_EXPORT_CONTENT_CHANGED" and issue.severity == "blocking" for issue in result.issues)
