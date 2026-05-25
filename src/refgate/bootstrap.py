from __future__ import annotations

from datetime import date
import json
import re
from pathlib import Path
from typing import Any

from .bibtex import parse_bibtex_entry, parse_bibtex_file, sha256_text, split_bibtex_entries
from .claim_audit import update_claim_stub_file
from .models import LockEntry, Lockfile


def _authors(value: str) -> list[str]:
    return [author.strip() for author in re.split(r"\s+and\s+", value) if author.strip()]


def _year(value: str | None) -> int | str | None:
    if not value:
        return None
    return int(value) if value.isdigit() else value


def _short_title(title: str | None, citation_key: str) -> str:
    if not title:
        return citation_key
    return title.split(":", 1)[0].strip() or title[:40].strip()


def bootstrap_lock_from_bib(
    bib_path: str | Path,
    output_path: str | Path,
    *,
    project: str | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Create a blocking starter lockfile from an existing BibTeX file.

    This is the generic onboarding path for manuscript repositories that have
    only `.tex` and `.bib`. Entries are intentionally marked as missing
    provenance so they cannot pass submission until resolved through Refgate.
    """

    bib_text = Path(bib_path).read_text(encoding="utf-8")
    bib_entries = parse_bibtex_file(bib_text)
    raw_entries = {parse_bibtex_entry(entry)["citation_key"]: entry for entry in split_bibtex_entries(bib_text)}
    checked = checked_at or date.today().isoformat()
    entries: list[LockEntry] = []

    for citation_key, bib_entry in sorted(bib_entries.items()):
        raw_text = raw_entries.get(citation_key, "")
        title = bib_entry.get("title")
        url = bib_entry.get("url") or ""
        entries.append(
            LockEntry(
                citation_key=citation_key,
                short_title=_short_title(title, citation_key),
                status="missing_bibtex_provenance",
                record={
                    "title": title,
                    "authors": _authors(bib_entry.get("author", "")),
                    "year": _year(bib_entry.get("year")),
                    "venue": bib_entry.get("booktitle") or bib_entry.get("journal") or bib_entry.get("howpublished"),
                    "doi": bib_entry.get("doi"),
                    "arxiv_id": bib_entry.get("eprint"),
                    "url": url,
                    "accessed_at": None,
                },
                authority={
                    "source": "unverified_bibtex",
                    "record_url": url,
                    "record_type": "paper_record",
                    "source_priority": 99,
                    "bibtex_url": None,
                },
                bibtex={
                    "entry_type": bib_entry.get("entry_type", "misc"),
                    "citation_key": citation_key,
                    "source_kind": "unknown",
                    "raw_sha256": sha256_text(raw_text),
                    "normalized_sha256": sha256_text(raw_text.strip() + "\n"),
                    "field_checks": {
                        "title": "present" if title else "missing",
                        "first_author": "present" if bib_entry.get("author") else "missing",
                        "year": "present" if bib_entry.get("year") else "missing",
                        "doi": "present" if bib_entry.get("doi") else "missing",
                        "url": "present" if url else "missing",
                        "bibtex_source": "missing_provenance",
                    },
                },
                resolver={
                    "score": 0,
                    "blocking_issues": [
                        {
                            "code": "MISSING_BIBTEX_PROVENANCE",
                            "message": "Starter lock entry was bootstrapped from BibTeX only and still needs official or fallback provenance.",
                            "citation_key": citation_key,
                        }
                    ],
                    "warnings": [],
                    "decision_trace": ["bootstrapped from existing BibTeX without authority verification"],
                },
                checked_at=checked,
            )
        )

    lockfile = Lockfile(project=project, generated_at=checked, entries=entries)
    Path(output_path).write_text(json.dumps(lockfile.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "bib": str(bib_path),
        "output": str(output_path),
        "entries": len(entries),
        "status": "starter_lock_requires_resolution",
    }


def bootstrap_paper(
    tex_path: str | Path,
    bib_path: str | Path,
    lock_output: str | Path,
    claims_output: str | Path,
    *,
    project: str | None = None,
) -> dict[str, Any]:
    lock_result = bootstrap_lock_from_bib(bib_path, lock_output, project=project)
    tex_text = Path(tex_path).read_text(encoding="utf-8")
    stubs = update_claim_stub_file(tex_text, claims_output)
    return {
        "tex": str(tex_path),
        "bib": str(bib_path),
        "lock": lock_result,
        "claims": {
            "output": str(claims_output),
            "created": len(stubs),
            "status": "claim_stubs_require_review",
        },
    }
