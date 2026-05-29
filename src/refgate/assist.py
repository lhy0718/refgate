from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .lockfile import load_lockfile
from .models import LockEntry, PaperQuery


PASSING_REFERENCE_STATUSES = {
    "verified_official_bibtex",
    "verified_manual_fallback",
    "arxiv_fallback_verified",
}


VENUE_SOURCE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("acl", ("association for computational linguistics", "acl", "emnlp", "aclanthology.org")),
    ("acm", ("acm", "dl.acm.org")),
    ("aaai", ("aaai", "aaai.org")),
    ("cambridge", ("cambridge", "cambridge.org", "cambridge core")),
    ("cvf", ("cvf", "cvpr", "iccv", "eccv", "openaccess.thecvf.com")),
    ("elsevier", ("elsevier", "sciencedirect.com")),
    ("frontiers", ("frontiers", "frontiersin.org")),
    ("iclr", ("learning representations", "iclr", "iclr.cc")),
    ("ieee", ("ieee", "cvpr", "iccv", "ieeexplore.ieee.org")),
    ("jmlr", ("jmlr", "journal of machine learning research", "jmlr.org")),
    ("lipics", ("lipics", "dagstuhl", "drops.dagstuhl.de")),
    ("mdpi", ("mdpi", "mdpi.com")),
    ("nature", ("nature", "nature.com", "nature machine intelligence", "scientific reports")),
    ("neurips", ("neural information processing", "neurips", "proceedings.neurips.cc")),
    ("openreview", ("openreview", "openreview.net", "tmlr")),
    ("oxford", ("oxford", "academic.oup.com", "oup")),
    ("pmlr", ("pmlr", "proceedings.mlr.press", "machine learning research")),
    ("pnas", ("pnas", "proceedings of the national academy", "pnas.org")),
    ("sage", ("sage", "journals.sagepub.com")),
    ("science", ("science", "science.org")),
    ("springer", ("springer", "link.springer.com")),
    ("taylorfrancis", ("taylor & francis", "taylor and francis", "tandfonline.com")),
    ("usenix", ("usenix", "usenix.org")),
    ("wiley", ("wiley", "onlinelibrary.wiley.com")),
)


def recommended_sources(entry: LockEntry) -> list[str]:
    record = entry.record
    venue = str(record.get("venue") or "").lower()
    url = str(record.get("url") or "").lower()
    source_text = f"{venue} {url}"
    sources: list[str] = []
    if record.get("doi"):
        sources.append("crossref")
    for source, hints in VENUE_SOURCE_HINTS:
        if any(hint in source_text for hint in hints):
            sources.append(source)
    if record.get("arxiv_id") or not sources:
        sources.append("arxiv")
    for fallback in ["openalex", "semantic_scholar"]:
        if fallback not in sources:
            sources.append(fallback)
    return sources


def source_commands(sources: list[str]) -> list[dict[str, str]]:
    commands = []
    for source in sources:
        commands.append(
            {
                "source": source,
                "discover": f"discover --source {source} --query QUERY_JSON --live --json",
                "resolve": "resolve --query QUERY_JSON --candidates CANDIDATES_JSON --json",
                "fetch_bibtex": "fetch-bibtex --resolved RESOLVED_JSON --write-lock REFGATE_LOCK_JSON --json",
            }
        )
    return commands


def query_from_lock_entry(entry: LockEntry) -> PaperQuery:
    record = entry.record
    title = (record.get("title") or entry.short_title or entry.citation_key).strip()
    authors = [str(author).strip() for author in record.get("authors", []) if str(author).strip()]
    year = record.get("year")
    if isinstance(year, str) and year.isdigit():
        year = int(year)
    elif not isinstance(year, int):
        year = None
    preferred_venues = []
    if record.get("venue"):
        preferred_venues.append(record["venue"])
    if record.get("url"):
        preferred_venues.append(record["url"])
    return PaperQuery(
        query_id=entry.citation_key,
        citation_key=entry.citation_key,
        title=title,
        authors=authors,
        year=year,
        doi=record.get("doi") or None,
        arxiv_id=record.get("arxiv_id") or None,
        preferred_venues=preferred_venues,
    )


def build_resolver_assist(
    lock_path: str | Path,
    output_path: str | Path | None = None,
    *,
    include_verified: bool = False,
) -> dict[str, Any]:
    lockfile = load_lockfile(lock_path)
    work_items = []
    skipped = []
    for entry in lockfile.entries:
        if not include_verified and entry.status in PASSING_REFERENCE_STATUSES:
            skipped.append({"citation_key": entry.citation_key, "status": entry.status})
            continue
        query = query_from_lock_entry(entry)
        sources = recommended_sources(entry)
        work_items.append(
            {
                "citation_key": entry.citation_key,
                "status": entry.status,
                "query": query.to_dict(),
                "recommended_sources": sources,
                "source_commands": source_commands(sources),
                "suggested_next": [
                    f"discover --source {sources[0]} --query QUERY_JSON --live --json",
                    "resolve --query QUERY_JSON --candidates CANDIDATES_JSON --json",
                    "fetch-bibtex --resolved RESOLVED_JSON --write-lock REFGATE_LOCK_JSON --json",
                ],
            }
        )

    data = {
        "schema_version": "refgate.resolver_assist.v1",
        "lock": str(lock_path),
        "work_item_count": len(work_items),
        "skipped_verified_count": len(skipped),
        "work_items": work_items,
        "skipped_verified": skipped,
    }
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data
