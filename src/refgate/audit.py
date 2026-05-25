from __future__ import annotations

from .bibtex import parse_bibtex_file, sha256_text, split_bibtex_entries
from .models import AuditIssue, Lockfile
from .resolver import normalize_author, normalize_title

PASSING_STATUSES = {
    "verified_official_bibtex",
    "verified_manual_fallback",
    "arxiv_fallback_verified",
}

BLOCKED_SOURCE_KINDS = {"generated_unverified", "unknown"}
FALLBACK_SOURCE_KINDS = {"publisher_metadata_manual_normalized", "arxiv_manual_normalized"}


def _same_author_name(left: str, right: str) -> bool:
    left_norm = normalize_author(left)
    right_norm = normalize_author(right)
    if not left_norm or not right_norm:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True
    left_parts = set(left_norm.split())
    right_parts = set(right_norm.split())
    return bool(left_parts) and left_parts == right_parts


def audit_bibliography(bib_text: str, lockfile: Lockfile, submission: bool = False) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
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

        official_url = lock_entry.authority.get("bibtex_url")
        if official_url and source_kind != "official_export":
            issues.append(
                AuditIssue(
                    code="OFFICIAL_EXPORT_NOT_USED",
                    message="Official BibTeX endpoint exists, but entry is not marked as official export.",
                    severity="blocking",
                    citation_key=citation_key,
                    evidence=[official_url],
                )
            )
        if source_kind == "official_export":
            stored_hash = lock_entry.bibtex.get("normalized_sha256")
            current_raw = raw_entries.get(citation_key)
            current_hash = sha256_text(current_raw.strip() + "\n") if current_raw else None
            if stored_hash and stored_hash != "placeholder" and current_hash and stored_hash != current_hash:
                issues.append(
                    AuditIssue(
                        code="OFFICIAL_EXPORT_CONTENT_CHANGED",
                        message="Current BibTeX entry differs from the reviewed official export checksum.",
                        severity="blocking" if submission else "warning",
                        citation_key=citation_key,
                    )
                )
            elif not stored_hash or stored_hash == "placeholder":
                issues.append(
                    AuditIssue(
                        code="OFFICIAL_EXPORT_CHECKSUM_MISSING",
                        message="Official BibTeX export has no reviewed checksum in the lockfile.",
                        severity="warning",
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
            issues.append(
                AuditIssue(
                    code="ARXIV_FALLBACK",
                    message="Entry uses arXiv fallback rather than final publication BibTeX.",
                    severity="warning",
                    citation_key=citation_key,
                )
            )

        if not lock_entry.record.get("doi"):
            issues.append(
                AuditIssue(
                    code="DOI_MISSING",
                    message="Lockfile record has no DOI.",
                    severity="warning",
                    citation_key=citation_key,
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
    return issues
