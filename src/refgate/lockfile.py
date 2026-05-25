from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from .bibtex import normalize_bibtex_fields, parse_bibtex_entry, rekey_bibtex_entry, sha256_text
from .models import BibtexRecord, LockEntry, Lockfile, ResolverDecision


def short_title(title: str) -> str:
    return title.split(":", 1)[0].strip() or title[:40].strip()


def build_lock_entry(
    decision: ResolverDecision,
    bibtex: BibtexRecord,
    *,
    citation_key: str | None = None,
    checked_at: str | None = None,
    fallback_reason: str | None = None,
) -> LockEntry:
    if decision.selected_candidate is None:
        raise ValueError("Cannot build lock entry without a selected candidate")
    if decision.authority is None:
        raise ValueError("Cannot build lock entry without an authority record")

    candidate = decision.selected_candidate
    if bibtex.source_kind == "arxiv_manual_normalized" and not fallback_reason:
        fallback_reason = "Official publication BibTeX was not confirmed; arXiv record was verified as fallback provenance."
    try:
        bibtex_fields = normalize_bibtex_fields(parse_bibtex_entry(bibtex.raw_text))
    except ValueError:
        bibtex_fields = {}
    doi = candidate.doi or bibtex_fields.get("doi")
    field_checks = {
        "title": "checked",
        "first_author": "checked" if candidate.authors else "missing",
        "year": "checked" if candidate.year is not None else "missing",
        "doi": "checked" if doi else "missing",
        "arxiv_id": "checked" if candidate.arxiv_id else "not_applicable",
        "url": "checked" if candidate.url else "missing",
    }
    if bibtex.source_kind == "official_export":
        field_checks["bibtex_source"] = "official_export"
        field_checks["exported_citation_key"] = bibtex.citation_key
    elif fallback_reason:
        field_checks["bibtex_source"] = "manual_fallback_with_reason"
    else:
        field_checks["bibtex_source"] = "manual_fallback_reason_missing"

    lock_citation_key = citation_key or bibtex.citation_key
    bibtex_data = bibtex.to_dict()
    bibtex_data.pop("raw_text", None)
    bibtex_data["citation_key"] = lock_citation_key
    canonical_text = bibtex.raw_text.strip() + "\n"
    if bibtex.citation_key != lock_citation_key:
        canonical_text = rekey_bibtex_entry(bibtex.raw_text, lock_citation_key).strip() + "\n"
    bibtex_data["canonical_text"] = canonical_text
    bibtex_data["normalized_sha256"] = sha256_text(canonical_text)
    if fallback_reason:
        bibtex_data["fallback_reason"] = fallback_reason
    bibtex_data["field_checks"] = field_checks

    status = decision.status
    if status == "verified_official_bibtex" and bibtex.source_kind != "official_export":
        status = "verified_manual_fallback"

    accessed_at = candidate.raw.get("accessed_at")
    if bibtex.source_kind == "arxiv_manual_normalized" and not accessed_at:
        accessed_at = checked_at or date.today().isoformat()

    return LockEntry(
        citation_key=lock_citation_key,
        short_title=short_title(candidate.title),
        status=status,
        record={
            "title": candidate.title,
            "authors": candidate.authors,
            "year": candidate.year,
            "venue": candidate.venue,
            "doi": doi,
            "arxiv_id": candidate.arxiv_id,
            "url": candidate.url,
            "accessed_at": accessed_at,
        },
        authority=decision.authority.to_dict(),
        bibtex=bibtex_data,
        resolver={
            "score": decision.resolver_score,
            "blocking_issues": [issue.to_dict() for issue in decision.blocking_issues],
            "warnings": [issue.to_dict() for issue in decision.warnings],
            "decision_trace": decision.decision_trace,
        },
        checked_at=checked_at or date.today().isoformat(),
    )


def load_lockfile(path: str | Path) -> Lockfile:
    target = Path(path)
    if not target.exists():
        return Lockfile(entries=[])
    return Lockfile.from_dict(json.loads(target.read_text(encoding="utf-8")))


def merge_lock_entry(lockfile: Lockfile, entry: LockEntry) -> Lockfile:
    entries = [existing for existing in lockfile.entries if existing.citation_key != entry.citation_key]
    entries.append(entry)
    entries.sort(key=lambda item: item.citation_key)
    return Lockfile(
        schema_version=lockfile.schema_version,
        project=lockfile.project,
        generated_at=lockfile.generated_at,
        entries=entries,
        audit_policy=lockfile.audit_policy,
    )


def write_lockfile(lockfile: Lockfile, path: str | Path) -> None:
    Path(path).write_text(json.dumps(lockfile.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
