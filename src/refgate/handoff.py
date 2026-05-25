from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from .bibtex import parse_bibtex_file
from .models import Lockfile

HandoffFormat = Literal["refgate-json", "csl-json"]


ENTRY_TYPE_TO_CSL = {
    "article": "article-journal",
    "inproceedings": "paper-conference",
    "proceedings": "paper-conference",
    "book": "book",
    "inbook": "chapter",
    "incollection": "chapter",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "techreport": "report",
    "misc": "webpage",
}


MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _author_to_csl(author: str) -> dict[str, str]:
    if "," in author:
        family, given = [part.strip() for part in author.split(",", 1)]
        return {"family": family, "given": given}
    parts = author.split()
    if len(parts) <= 1:
        return {"literal": author}
    return {"given": " ".join(parts[:-1]), "family": parts[-1]}


def _authors_to_csl(author_field: str | None) -> list[dict[str, str]]:
    if not author_field:
        return []
    return [_author_to_csl(author.strip()) for author in author_field.split(" and ") if author.strip()]


def _date_parts(value: str | None) -> list[int | str] | None:
    if not value:
        return None
    parts = value.split("-")
    if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
        return [int(parts[0]), int(parts[1]), int(parts[2])]
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return [int(parts[0]), int(parts[1])]
    if value.isdigit():
        return [int(value)]
    return [value]


def _month(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.strip("{}").lower()
    if normalized.isdigit():
        month = int(normalized)
        return month if 1 <= month <= 12 else None
    return MONTHS.get(normalized[:3]) or MONTHS.get(normalized)


def _issued(year: int | str | None, month: str | None = None) -> dict[str, list[list[int | str]]] | None:
    if year is None:
        return None
    parts: list[int | str] = [int(year) if str(year).isdigit() else str(year)]
    month_value = _month(month)
    if month_value is not None:
        parts.append(month_value)
    return {"date-parts": [parts]}


def _copy_field(item: dict[str, Any], target: str, bib_entry: dict[str, str], *sources: str) -> None:
    for source in sources:
        value = bib_entry.get(source)
        if value:
            item[target] = value
            return


def csl_entry(citation_key: str, bib_entry: dict[str, str], lock_entry: dict[str, Any]) -> dict[str, Any]:
    entry_type = bib_entry.get("entry_type", "misc")
    record = lock_entry.get("record", {})
    authority = lock_entry.get("authority", {})
    bibtex = lock_entry.get("bibtex", {})
    item: dict[str, Any] = {
        "id": citation_key,
        "type": ENTRY_TYPE_TO_CSL.get(entry_type, "webpage"),
        "title": bib_entry.get("title") or record.get("title"),
        "author": _authors_to_csl(bib_entry.get("author")),
        "_refgate": {
            "status": lock_entry.get("status"),
            "authority_source": authority.get("source"),
            "authority_url": authority.get("record_url"),
            "bibtex_source_kind": bibtex.get("source_kind"),
            "bibtex_raw_sha256": bibtex.get("raw_sha256"),
        },
    }
    issued = _issued(bib_entry.get("year") or record.get("year"), bib_entry.get("month"))
    if issued:
        item["issued"] = issued
    accessed = _date_parts(record.get("accessed_at") or bib_entry.get("urldate"))
    if accessed:
        item["accessed"] = {"date-parts": [accessed]}
    if bib_entry.get("doi") or record.get("doi"):
        item["DOI"] = bib_entry.get("doi") or record.get("doi")
    if bib_entry.get("url") or record.get("url"):
        item["URL"] = bib_entry.get("url") or record.get("url")
    container = bib_entry.get("booktitle") or bib_entry.get("journal") or record.get("venue")
    if container:
        item["container-title"] = container
    _copy_field(item, "page", bib_entry, "pages")
    _copy_field(item, "volume", bib_entry, "volume")
    _copy_field(item, "issue", bib_entry, "number", "issue")
    _copy_field(item, "publisher", bib_entry, "publisher", "institution", "school")
    _copy_field(item, "publisher-place", bib_entry, "address")
    _copy_field(item, "edition", bib_entry, "edition")
    _copy_field(item, "ISBN", bib_entry, "isbn")
    _copy_field(item, "ISSN", bib_entry, "issn")
    _copy_field(item, "abstract", bib_entry, "abstract")
    _copy_field(item, "keyword", bib_entry, "keywords", "keyword")
    _copy_field(item, "archive", bib_entry, "archiveprefix")
    _copy_field(item, "archive_location", bib_entry, "eprint")
    _copy_field(item, "PMID", bib_entry, "pmid")
    _copy_field(item, "note", bib_entry, "note")
    return {key: value for key, value in item.items() if value not in (None, [], {})}


def build_handoff(lockfile: Lockfile, bib_text: str, *, export_format: HandoffFormat = "refgate-json") -> dict[str, Any] | list[dict[str, Any]]:
    bib_entries = parse_bibtex_file(bib_text)
    lock_entries = lockfile.by_citation_key()
    entries = []
    for citation_key in sorted(lock_entries):
        lock_entry = lock_entries[citation_key]
        bib_entry = bib_entries.get(citation_key, {})
        lock_data = lock_entry.to_dict()
        csl = csl_entry(citation_key, bib_entry, lock_data)
        entries.append(
            {
                "citation_key": citation_key,
                "status": lock_entry.status,
                "record": lock_data["record"],
                "authority": lock_data["authority"],
                "bibtex_provenance": lock_data["bibtex"],
                "bibtex": bib_entry,
                "csl": csl,
            }
        )
    if export_format == "csl-json":
        return [entry["csl"] for entry in entries]
    return {
        "schema_version": "refgate.handoff.v1",
        "project": lockfile.project,
        "entry_count": len(entries),
        "entries": entries,
    }


def write_handoff(
    lockfile: Lockfile,
    bib_text: str,
    output_path: str | Path,
    *,
    export_format: HandoffFormat = "refgate-json",
) -> dict[str, Any]:
    artifact = build_handoff(lockfile, bib_text, export_format=export_format)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entry_count = len(artifact) if isinstance(artifact, list) else int(artifact["entry_count"])
    return {"output": str(target), "format": export_format, "entry_count": entry_count}
