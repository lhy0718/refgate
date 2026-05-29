from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .assist import query_from_lock_entry, recommended_sources
from .lockfile import load_lockfile
from .models import LockEntry
from .reference_check import run_reference_check


OFFICIAL_MONITOR_SOURCES = [
    "aaai",
    "acl",
    "acm",
    "cambridge",
    "crossref",
    "cvf",
    "elsevier",
    "frontiers",
    "iclr",
    "ieee",
    "jmlr",
    "lipics",
    "mdpi",
    "nature",
    "neurips",
    "openreview",
    "oxford",
    "pmlr",
    "pnas",
    "sage",
    "science",
    "springer",
    "taylorfrancis",
    "usenix",
    "wiley",
]


def needs_official_record_monitor(entry: LockEntry) -> bool:
    source_kind = str(entry.bibtex.get("source_kind") or "")
    authority_source = str(entry.authority.get("source") or "")
    return (
        entry.status in {"arxiv_fallback_verified", "official_record_pending"}
        or source_kind == "arxiv_manual_normalized"
        or authority_source == "arxiv"
    )


def official_monitor_sources(entry: LockEntry, requested_sources: list[str] | None = None) -> list[str]:
    if requested_sources:
        return [source for source in requested_sources if source in OFFICIAL_MONITOR_SOURCES]
    sources = [source for source in recommended_sources(entry) if source in OFFICIAL_MONITOR_SOURCES]
    if "crossref" not in sources:
        sources.append("crossref")
    return sources


def _shell_command(parts: list[str | Path]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def _monitor_command(
    *,
    lock_path: str | Path,
    citation_key: str,
    sources: list[str],
    cache_root: str | Path,
    prefer_cache: bool,
    write_lock: str | Path | None,
    fetch_official_bibtex: bool,
) -> str:
    parts: list[str | Path] = ["python", "-m", "refgate", "reference-check", "--lock", lock_path]
    for source in sources:
        parts.extend(["--source", source])
    parts.extend(["--cache-root", cache_root, "--citation-key", citation_key])
    if prefer_cache:
        parts.append("--prefer-cache")
    if write_lock:
        parts.extend(["--write-lock", write_lock])
    if fetch_official_bibtex:
        parts.append("--fetch-official-bibtex")
    parts.extend(["--live", "--json"])
    return _shell_command(parts)


def build_official_monitor_plan(
    lock_path: str | Path,
    *,
    sources: list[str] | None = None,
    cache_root: str | Path = ".refgate/cache",
    prefer_cache: bool = False,
    write_lock: str | Path | None = None,
    fetch_official_bibtex: bool = True,
    max_entries: int | None = None,
) -> dict[str, Any]:
    lockfile = load_lockfile(lock_path)
    items: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for entry in lockfile.entries:
        if not needs_official_record_monitor(entry):
            skipped.append({"citation_key": entry.citation_key, "status": entry.status})
            continue
        item_sources = official_monitor_sources(entry, sources)
        query = query_from_lock_entry(entry)
        items.append(
            {
                "citation_key": entry.citation_key,
                "status": entry.status,
                "current_authority_source": entry.authority.get("source"),
                "current_bibtex_source_kind": entry.bibtex.get("source_kind"),
                "query": query.to_dict(),
                "recommended_sources": item_sources,
                "command": _monitor_command(
                    lock_path=lock_path,
                    citation_key=entry.citation_key,
                    sources=item_sources,
                    cache_root=cache_root,
                    prefer_cache=prefer_cache,
                    write_lock=write_lock,
                    fetch_official_bibtex=fetch_official_bibtex,
                ),
            }
        )
    selected_items = items[:max_entries] if max_entries is not None else items
    return {
        "schema_version": "refgate.official_monitor.v1",
        "lock": str(lock_path),
        "monitor_count": len(selected_items),
        "skipped_count": len(skipped) + max(0, len(items) - len(selected_items)),
        "items": selected_items,
        "skipped": skipped,
    }


def run_official_monitor(
    lock_path: str | Path,
    *,
    sources: list[str] | None = None,
    cache_root: str | Path = ".refgate/cache",
    prefer_cache: bool = False,
    write_lock: str | Path | None = None,
    fetch_official_bibtex: bool = True,
    max_entries: int | None = None,
    live: bool = False,
) -> dict[str, Any]:
    plan = build_official_monitor_plan(
        lock_path,
        sources=sources,
        cache_root=cache_root,
        prefer_cache=prefer_cache,
        write_lock=write_lock,
        fetch_official_bibtex=fetch_official_bibtex,
        max_entries=max_entries,
    )
    next_actions = [
        {
            "code": "CHECK_OFFICIAL_RECORD",
            "kind": "live_reference_check",
            "citation_key": item["citation_key"],
            "sources": item["recommended_sources"],
            "command": item["command"],
            "network_required": True,
            "writes_files": bool(write_lock),
            "requires_human_review": False,
        }
        for item in plan["items"]
    ]
    blocking: list[dict[str, Any]] = []
    reference_check: dict[str, Any] | None = None
    if live and plan["items"]:
        citation_keys = [item["citation_key"] for item in plan["items"]]
        selected_sources = sorted({source for item in plan["items"] for source in item["recommended_sources"]})
        reference_check = run_reference_check(
            lock_path,
            live=True,
            sources=selected_sources,
            cache_root=cache_root,
            prefer_cache=prefer_cache,
            write_lock=write_lock,
            fetch_official_bibtex=fetch_official_bibtex,
            citation_keys=citation_keys,
        )
        blocking.extend(reference_check["blocking_issues"])
        next_actions = reference_check.get("next_actions", [])
    return {
        "ok": not blocking,
        "plan": plan,
        "reference_check": reference_check,
        "blocking_issues": blocking,
        "next_actions": next_actions,
    }
