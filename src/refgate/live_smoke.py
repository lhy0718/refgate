from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
import time

from .adapters.acl import AclAdapter
from .adapters.arxiv import ArxivAdapter
from .adapters.crossref import CrossrefAdapter
from .adapters.iclr import IclrAdapter
from .adapters.neurips import NeuripsAdapter
from .adapters.openalex import OpenAlexAdapter
from .adapters.semantic_scholar import SemanticScholarAdapter
from .adapters.venues import ADAPTERS as VENUE_ADAPTERS
from .cache import RawRecord, raw_record_path, read_raw_record, utc_now, write_raw_record
from .models import PaperQuery


@dataclass(frozen=True)
class LiveSmokeQueryItem:
    source: str
    query: PaperQuery


def cached_fetcher(
    source: str,
    base_fetcher: Callable[[str], str],
    cache_root: str | Path,
    *,
    prefer_cache: bool = False,
    min_interval_seconds: float = 0,
    retry: int = 0,
    retry_after_seconds: float = 0,
    cache_paths: list[str] | None = None,
) -> Callable[[str], str]:
    last_fetch_at = 0.0

    def fetch(url: str) -> str:
        nonlocal last_fetch_at
        if prefer_cache:
            cached = read_raw_record(source, url, cache_root=cache_root)
            if cached is not None:
                if cache_paths is not None:
                    cache_paths.append(str(raw_record_path(source, url, cache_root=cache_root)))
                return cached.body
        for attempt in range(retry + 1):
            if min_interval_seconds > 0:
                elapsed = time.monotonic() - last_fetch_at
                if elapsed < min_interval_seconds:
                    time.sleep(min_interval_seconds - elapsed)
            try:
                body = base_fetcher(url)
                last_fetch_at = time.monotonic()
                break
            except HTTPError as exc:
                last_fetch_at = time.monotonic()
                if exc.code != 429 or attempt >= retry:
                    raise
                wait_seconds = retry_after_seconds or _retry_after_header(exc) or min_interval_seconds or 1
                time.sleep(wait_seconds)
        path = write_raw_record(
            RawRecord(
                source=source,
                url=url,
                status=200,
                headers={},
                body=body,
                fetched_at=utc_now(),
            ),
            cache_root=cache_root,
        )
        if cache_paths is not None:
            cache_paths.append(str(path))
        return body

    return fetch


def _retry_after_header(exc: HTTPError) -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    if value and value.isdigit():
        return float(value)
    return None


def adapter_for_source(source: str, fetcher: Callable[[str], str]):
    if source == "acl":
        return AclAdapter(fetcher=fetcher)
    if source == "arxiv":
        return ArxivAdapter(fetcher=fetcher)
    if source == "crossref":
        return CrossrefAdapter(fetcher=fetcher)
    if source == "iclr":
        return IclrAdapter(fetcher=fetcher)
    if source == "neurips":
        return NeuripsAdapter(fetcher=fetcher)
    if source == "openalex":
        return OpenAlexAdapter(fetcher=fetcher)
    if source == "semantic_scholar":
        return SemanticScholarAdapter(fetcher=fetcher)
    if source in VENUE_ADAPTERS:
        return VENUE_ADAPTERS[source](fetcher=fetcher)
    raise ValueError(f"Unsupported live smoke source: {source}")


def default_adapter_for_source(source: str):
    if source == "acl":
        return AclAdapter()
    if source == "arxiv":
        return ArxivAdapter()
    if source == "crossref":
        return CrossrefAdapter()
    if source == "iclr":
        return IclrAdapter()
    if source == "neurips":
        return NeuripsAdapter()
    if source == "openalex":
        return OpenAlexAdapter()
    if source == "semantic_scholar":
        return SemanticScholarAdapter()
    if source in VENUE_ADAPTERS:
        return VENUE_ADAPTERS[source]()
    raise ValueError(f"Unsupported live smoke source: {source}")


def run_live_smoke(
    source: str,
    query: PaperQuery,
    cache_root: str | Path = ".refgate/cache",
    *,
    prefer_cache: bool = False,
    min_interval_seconds: float = 0,
    retry: int = 0,
    retry_after_seconds: float = 0,
) -> dict[str, Any]:
    default_adapter = default_adapter_for_source(source)
    base_fetcher = default_adapter.fetcher
    cache_paths: list[str] = []
    adapter = adapter_for_source(
        source,
        cached_fetcher(
            source,
            base_fetcher,
            cache_root,
            prefer_cache=prefer_cache,
            min_interval_seconds=min_interval_seconds,
            retry=retry,
            retry_after_seconds=retry_after_seconds,
            cache_paths=cache_paths,
        ),
    )
    candidates = adapter.discover(query)
    return {
        "source": source,
        "query": query.to_dict(),
        "candidate_count": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
        "cache_paths": sorted(dict.fromkeys(cache_paths)),
        "ok": bool(candidates),
    }


def run_live_smoke_suite(
    queries: list[PaperQuery],
    *,
    source: str,
    cache_root: str | Path = ".refgate/cache",
    prefer_cache: bool = False,
    min_interval_seconds: float = 0,
    retry: int = 0,
    retry_after_seconds: float = 0,
    max_queries: int | None = None,
) -> dict[str, Any]:
    items = [LiveSmokeQueryItem(source=source, query=query) for query in queries]
    return run_live_smoke_suite_items(
        items,
        cache_root=cache_root,
        prefer_cache=prefer_cache,
        min_interval_seconds=min_interval_seconds,
        retry=retry,
        retry_after_seconds=retry_after_seconds,
        max_queries=max_queries,
        default_source=source,
    )


def run_live_smoke_suite_items(
    items: list[LiveSmokeQueryItem],
    *,
    cache_root: str | Path = ".refgate/cache",
    prefer_cache: bool = False,
    min_interval_seconds: float = 0,
    retry: int = 0,
    retry_after_seconds: float = 0,
    max_queries: int | None = None,
    default_source: str | None = None,
) -> dict[str, Any]:
    results = []
    selected_items = items[:max_queries] if max_queries is not None else items
    for item in selected_items:
        try:
            result = run_live_smoke(
                item.source,
                item.query,
                cache_root=cache_root,
                prefer_cache=prefer_cache,
                min_interval_seconds=min_interval_seconds,
                retry=retry,
                retry_after_seconds=retry_after_seconds,
            )
        except Exception as exc:
            result = {
                "source": item.source,
                "query": item.query.to_dict(),
                "candidate_count": 0,
                "candidates": [],
                "cache_paths": [],
                "ok": False,
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        results.append(result)
    sources = sorted({item.source for item in items})
    selected_sources = sorted({item.source for item in selected_items})
    source_counts = {source: sum(1 for item in items if item.source == source) for source in sources}
    source_label = sources[0] if len(sources) == 1 else ("mixed" if sources else default_source or "mixed")
    return {
        "source": source_label,
        "sources": sources,
        "selected_sources": selected_sources,
        "source_counts": source_counts,
        "query_count": len(items),
        "run_query_count": len(selected_items),
        "skipped_query_count": max(0, len(items) - len(selected_items)),
        "ok_count": sum(1 for item in results if item.get("ok")),
        "results": results,
        "ok": bool(results) and all(item.get("ok") for item in results),
    }


def cache_manifest(cache_root: str | Path = ".refgate/cache") -> dict[str, Any]:
    root = Path(cache_root)
    records = []
    if root.exists():
        for path in sorted(root.glob("*/*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            records.append(
                {
                    "source": data.get("source"),
                    "url": data.get("url"),
                    "body_sha256": data.get("body_sha256"),
                    "path": str(path),
                }
            )
    return {"cache_root": str(root), "records": records}


def compare_cache_manifest(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    actual_by_key = {(item["source"], item["url"]): item for item in actual.get("records", [])}
    missing = []
    changed = []
    for expected_item in expected.get("records", []):
        key = (expected_item.get("source"), expected_item.get("url"))
        actual_item = actual_by_key.get(key)
        if actual_item is None:
            missing.append(expected_item)
        elif expected_item.get("body_sha256") and actual_item.get("body_sha256") != expected_item.get("body_sha256"):
            changed.append({"expected": expected_item, "actual": actual_item})
    return {"ok": not missing and not changed, "missing": missing, "changed": changed}
