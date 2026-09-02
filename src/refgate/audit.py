from __future__ import annotations

from dataclasses import dataclass

from .bibtex import (
    bibtex_entries_semantically_equal,
    parse_bibtex_file,
    sha256_text,
    split_bibtex_entries,
)
from .models import AuditIssue, Lockfile
from .resolver import normalize_author, normalize_title

PASSING_STATUSES = {
    "verified_official_bibtex",
    "verified_manual_fallback",
    "arxiv_fallback_verified",
}

BLOCKED_SOURCE_KINDS = {"generated_unverified", "unknown"}
FALLBACK_SOURCE_KINDS = {"publisher_metadata_manual_normalized", "arxiv_manual_normalized"}
VERIFIED_PROVENANCE_SOURCE_KINDS = {"official_export", "publisher_metadata_manual_normalized", "arxiv_manual_normalized"}
DOI_ABSENCE_FIELD_CHECKS = {"missing", "not_applicable", "absent"}


@dataclass
class BibliographyAuditResult:
    issues: list[AuditIssue]
    accepted_provenance_notes: list[AuditIssue]


def _same_author_name(left: str, right: str) -> bool:
    left_norm = normalize_author(left)
    right_norm = normalize_author(right)
    if not left_norm or not right_norm:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True
    left_parts = set(left_norm.split())
    right_parts = set(right_norm.split())
    if bool(left_parts) and left_parts == right_parts:
        return True
    left_name = _author_name_parts(left)
    right_name = _author_name_parts(right)
    if left_name and right_name and left_name[1] == right_name[1]:
        left_given = left_name[0]
        right_given = right_name[0]
        return bool(left_given and right_given) and (left_given[0] == right_given[0] or left_given.startswith(right_given) or right_given.startswith(left_given))
    return False


def _author_name_parts(value: str) -> tuple[str, str] | None:
    if "," in value:
        last, given = value.split(",", 1)
    else:
        parts = value.split()
        if len(parts) < 2:
            return None
        given = " ".join(parts[:-1])
        last = parts[-1]
    given_norm = normalize_author(given)
    last_norm = normalize_author(last)
    if not given_norm or not last_norm:
        return None
    return given_norm, last_norm


def _authority_source(lock_entry) -> str:
    return str(lock_entry.authority.get("source") or "").strip().lower()


def _authority_record_url(lock_entry) -> str:
    return str(lock_entry.authority.get("record_url") or "").strip().lower()


def _is_verified_arxiv_fallback(lock_entry, source_kind: str) -> bool:
    if lock_entry.status != "arxiv_fallback_verified":
        return False
    return (
        source_kind == "arxiv_manual_normalized"
        or _authority_source(lock_entry) == "arxiv"
        or "arxiv.org" in _authority_record_url(lock_entry)
    )


def _arxiv_official_record_monitor_issue(lock_entry) -> AuditIssue:
    evidence = []
    record_url = str(lock_entry.authority.get("record_url") or "").strip()
    if record_url:
        evidence.append(record_url)
    arxiv_id = str(lock_entry.record.get("arxiv_id") or "").strip()
    if arxiv_id:
        evidence.append(f"arXiv:{arxiv_id}")
    return AuditIssue(
        code="ARXIV_OFFICIAL_RECORD_MONITOR_REQUIRED",
        message="Verified arXiv fallback should be refreshed against official venue records before submission.",
        severity="warning",
        citation_key=lock_entry.citation_key,
        evidence=evidence,
    )


def _has_reviewed_manual_fallback(lock_entry, source_kind: str) -> bool:
    return source_kind in FALLBACK_SOURCE_KINDS and bool(str(lock_entry.bibtex.get("fallback_reason") or "").strip())


def _has_verified_doi_absence(lock_entry, source_kind: str) -> bool:
    if lock_entry.status not in PASSING_STATUSES:
        return False
    if source_kind not in VERIFIED_PROVENANCE_SOURCE_KINDS:
        return False
    field_checks = lock_entry.bibtex.get("field_checks") or {}
    doi_check = str(field_checks.get("doi") or "").strip().lower()
    return doi_check in DOI_ABSENCE_FIELD_CHECKS


def audit_bibliography_result(bib_text: str, lockfile: Lockfile, submission: bool = False) -> BibliographyAuditResult:
    issues: list[AuditIssue] = []
    accepted_provenance_notes: list[AuditIssue] = []
    audit_policy = lockfile.audit_policy or {}
    allow_manual_fallback = bool(audit_policy.get("allow_manual_fallback", True))
    allow_arxiv_fallback = bool(audit_policy.get("allow_arxiv_fallback", True))
    bib_entries = parse_bibtex_file(bib_text)
    raw_entries = {}
    for raw in split_bibtex_entries(bib_text):
        parsed_raw = parse_bibtex_file(raw)
        for key in parsed_raw:
            raw_entries[key] = raw
    lock_entries = lockfile.by_citation_key()

    for citation_key, bib_entry in bib_entries.items():
        lock_entry = lock_entries.get(citation_key)
        if lock_entry is None:
            issues.append(
                AuditIssue(
                    code="MISSING_LOCK_ENTRY",
                    message="BibTeX entry has no Refgate lockfile entry.",
                    severity="blocking",
                    citation_key=citation_key,
                )
            )
            continue

        if lock_entry.status not in PASSING_STATUSES:
            issues.append(
                AuditIssue(
                    code="NON_PASSING_STATUS",
                    message=f"Lockfile status is {lock_entry.status}.",
                    severity="blocking",
                    citation_key=citation_key,
                )
            )

        source_kind = lock_entry.bibtex.get("source_kind", "unknown")
        if source_kind in BLOCKED_SOURCE_KINDS:
            issues.append(
                AuditIssue(
                    code="UNVERIFIED_BIBTEX_SOURCE",
                    message=f"BibTeX source kind is {source_kind}.",
                    severity="blocking",
                    citation_key=citation_key,
                )
            )
        if source_kind == "publisher_metadata_manual_normalized" and not allow_manual_fallback:
            evidence = []
            record_url = str(lock_entry.authority.get("record_url") or "").strip()
            if record_url:
                evidence.append(record_url)
            issues.append(
                AuditIssue(
                    code="MANUAL_FALLBACK_NOT_ALLOWED",
                    message="Audit policy requires an official BibTeX export; publisher metadata manual fallback is not allowed.",
                    severity="blocking",
                    citation_key=citation_key,
                    evidence=evidence,
                )
            )
        if source_kind == "arxiv_manual_normalized" and not allow_arxiv_fallback:
            evidence = []
            record_url = str(lock_entry.authority.get("record_url") or "").strip()
            if record_url:
                evidence.append(record_url)
            issues.append(
                AuditIssue(
                    code="ARXIV_FALLBACK_NOT_ALLOWED",
                    message="Audit policy does not allow arXiv fallback provenance for this bibliography.",
                    severity="blocking",
                    citation_key=citation_key,
                    evidence=evidence,
                )
            )

        official_url = lock_entry.authority.get("bibtex_url")
        if official_url and source_kind != "official_export":
            official_export_not_used = AuditIssue(
                code="OFFICIAL_EXPORT_NOT_USED",
                message="Official BibTeX endpoint exists, but entry is not marked as official export.",
                severity="warning",
                citation_key=citation_key,
                evidence=[official_url],
            )
            if allow_manual_fallback and _has_reviewed_manual_fallback(lock_entry, source_kind):
                accepted_provenance_notes.append(official_export_not_used)
            else:
                issues.append(
                    AuditIssue(
                        code=official_export_not_used.code,
                        message=official_export_not_used.message,
                        severity="blocking",
                        citation_key=citation_key,
                        evidence=official_export_not_used.evidence,
                    )
                )
        if source_kind == "official_export":
            stored_hash = lock_entry.bibtex.get("normalized_sha256")
            current_raw = raw_entries.get(citation_key)
            canonical_value = str(lock_entry.bibtex.get("canonical_text") or "").strip()
            canonical_text = canonical_value + "\n" if canonical_value else None
            if not stored_hash or stored_hash == "placeholder":
                issues.append(
                    AuditIssue(
                        code="OFFICIAL_EXPORT_CHECKSUM_MISSING",
                        message="Official BibTeX export has no reviewed checksum in the lockfile.",
                        severity="warning",
                        citation_key=citation_key,
                    )
                )
            elif canonical_text and stored_hash != sha256_text(canonical_text):
                issues.append(
                    AuditIssue(
                        code="OFFICIAL_EXPORT_CONTENT_CHANGED",
                        message="Lockfile canonical BibTeX differs from the reviewed official export checksum.",
                        severity="blocking" if submission else "warning",
                        citation_key=citation_key,
                    )
                )
            elif canonical_text and current_raw and not bibtex_entries_semantically_equal(current_raw, canonical_text):
                issues.append(
                    AuditIssue(
                        code="OFFICIAL_EXPORT_CONTENT_CHANGED",
                        message="Current BibTeX entry differs bibliographically from the reviewed official export.",
                        severity="blocking" if submission else "warning",
                        citation_key=citation_key,
                    )
                )
            elif not canonical_text and current_raw:
                current_hash = sha256_text(current_raw.strip() + "\n")
                if stored_hash != current_hash:
                    issues.append(
                        AuditIssue(
                            code="OFFICIAL_EXPORT_CONTENT_CHANGED",
                            message="Current BibTeX entry differs from the reviewed official export checksum.",
                            severity="blocking" if submission else "warning",
                            citation_key=citation_key,
                        )
                    )

        expected_title = lock_entry.record.get("title")
        actual_title = bib_entry.get("title")
        if expected_title and actual_title and normalize_title(expected_title) != normalize_title(actual_title):
            issues.append(
                AuditIssue(
                    code="TITLE_MISMATCH",
                    message="BibTeX title does not match lockfile record title.",
                    severity="blocking",
                    citation_key=citation_key,
                    evidence=[actual_title, expected_title],
                )
            )

        expected_year = lock_entry.record.get("year")
        actual_year = bib_entry.get("year")
        if expected_year and actual_year and str(expected_year) != str(actual_year):
            issues.append(
                AuditIssue(
                    code="YEAR_MISMATCH",
                    message="BibTeX year does not match lockfile record year.",
                    severity="blocking",
                    citation_key=citation_key,
                    evidence=[actual_year, str(expected_year)],
                )
            )

        expected_authors = lock_entry.record.get("authors") or []
        actual_author = bib_entry.get("author")
        if expected_authors and actual_author:
            expected_first = str(expected_authors[0])
            actual_first = actual_author.split(" and ")[0]
            if not _same_author_name(expected_first, actual_first):
                issues.append(
                    AuditIssue(
                        code="AUTHOR_MISMATCH",
                        message="BibTeX first author does not match lockfile record first author.",
                        severity="blocking",
                        citation_key=citation_key,
                        evidence=[actual_author.split(" and ")[0], str(expected_authors[0])],
                    )
                )

        if source_kind in FALLBACK_SOURCE_KINDS and not lock_entry.bibtex.get("fallback_reason"):
            issues.append(
                AuditIssue(
                    code="FALLBACK_REASON_MISSING",
                    message="Manual fallback BibTeX requires a fallback reason.",
                    severity="blocking" if submission else "warning",
                    citation_key=citation_key,
                )
            )

        if source_kind == "arxiv_manual_normalized":
            if not lock_entry.record.get("accessed_at"):
                issues.append(
                    AuditIssue(
                        code="ARXIV_ACCESSED_DATE_MISSING",
                        message="arXiv fallback entry requires an accessed date.",
                        severity="blocking" if submission else "warning",
                        citation_key=citation_key,
                    )
                )
            arxiv_fallback_issue = AuditIssue(
                code="ARXIV_FALLBACK",
                message="Entry uses arXiv fallback rather than final publication BibTeX.",
                severity="warning",
                citation_key=citation_key,
            )
            if _is_verified_arxiv_fallback(lock_entry, source_kind):
                accepted_provenance_notes.append(arxiv_fallback_issue)
                issues.append(_arxiv_official_record_monitor_issue(lock_entry))
            else:
                issues.append(arxiv_fallback_issue)

        if not lock_entry.record.get("doi"):
            doi_missing_issue = AuditIssue(
                code="DOI_MISSING",
                message="Lockfile record has no DOI.",
                severity="warning",
                citation_key=citation_key,
            )
            if _has_verified_doi_absence(lock_entry, source_kind):
                accepted_provenance_notes.append(doi_missing_issue)
            else:
                issues.append(doi_missing_issue)
        elif not bib_entry.get("doi"):
            issues.append(
                AuditIssue(
                    code="DOI_MISSING",
                    message="BibTeX entry is missing DOI present in the lockfile record.",
                    severity="warning",
                    citation_key=citation_key,
                    evidence=[str(lock_entry.record.get("doi"))],
                )
            )

    for citation_key in lock_entries:
        if citation_key not in bib_entries:
            severity = "blocking" if submission else "warning"
            issues.append(
                AuditIssue(
                    code="LOCK_ENTRY_NOT_IN_BIB",
                    message="Lockfile entry is not present in the BibTeX file.",
                    severity=severity,
                    citation_key=citation_key,
                )
            )
    return BibliographyAuditResult(issues=issues, accepted_provenance_notes=accepted_provenance_notes)


def audit_bibliography(bib_text: str, lockfile: Lockfile, submission: bool = False) -> list[AuditIssue]:
    return audit_bibliography_result(bib_text, lockfile, submission=submission).issues
