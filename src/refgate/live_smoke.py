from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import shlex
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


def _rate_limit_retry_defaults(source: str) -> dict[str, int]:
    if source == "arxiv":
        return {"min_interval_seconds": 30, "retry": 3, "retry_after_seconds": 60}
    return {"min_interval_seconds": 5, "retry": 2, "retry_after_seconds": 10}


def _query_args(query: PaperQuery) -> list[str]:
    args = ["--title", query.title]
    if query.query_id:
        args.extend(["--query-id", query.query_id])
    if query.citation_key:
        args.extend(["--citation-key", query.citation_key])
    if query.year is not None:
        args.extend(["--year", str(query.year)])
    if query.doi:
        args.extend(["--doi", query.doi])
    if query.arxiv_id:
        args.extend(["--arxiv-id", query.arxiv_id])
    for author in query.authors:
        args.extend(["--author", author])
    for venue in query.preferred_venues:
        args.extend(["--preferred-venue", venue])
    return args


def _live_smoke_command(
    source: str,
    query: PaperQuery,
    *,
    cache_root: str | Path,
    prefer_cache: bool,
    min_interval_seconds: float,
    retry: int,
    retry_after_seconds: float,
) -> str:
    parts = [
        "python",
        "-m",
        "refgate",
        "live-smoke",
        "--source",
        source,
        *(_query_args(query)),
        "--cache-root",
        str(cache_root),
    ]
    if prefer_cache:
        parts.append("--prefer-cache")
    if min_interval_seconds:
        parts.extend(["--min-interval-seconds", str(min_interval_seconds)])
    if retry:
        parts.extend(["--retry", str(retry)])
    if retry_after_seconds:
        parts.extend(["--retry-after-seconds", str(retry_after_seconds)])
    parts.extend(["--live", "--json"])
    return " ".join(shlex.quote(part) for part in parts)


def _failure_code(error: str | None) -> str:
    if not error:
        return "NO_CANDIDATES"
    if "HTTP Error 429" in error or " 429" in error:
        return "LIVE_SMOKE_RATE_LIMITED"
    if "URLError" in error or "nodename nor servname" in error or "Name or service not known" in error:
        return "LIVE_SMOKE_NETWORK_UNAVAILABLE"
    if "HTTPError" in error:
        return "LIVE_SMOKE_HTTP_ERROR"
    return "LIVE_SMOKE_DISCOVERY_ERROR"


def _failure_message(code: str, source: str) -> str:
    if code == "LIVE_SMOKE_RATE_LIMITED":
        return f"{source} live endpoint rate-limited the request."
    if code == "LIVE_SMOKE_NETWORK_UNAVAILABLE":
        return "Network resolution failed before the live endpoint could be checked."
    if code == "NO_CANDIDATES":
        return f"{source} live lookup returned no candidates for the query."
    if code == "LIVE_SMOKE_HTTP_ERROR":
        return f"{source} live endpoint returned an HTTP error."
    return f"{source} live lookup failed before producing candidates."


def _live_smoke_next_actions(
    source: str,
    query: PaperQuery,
    *,
    cache_root: str | Path,
    error: str | None,
    prefer_cache: bool,
    min_interval_seconds: float,
    retry: int,
    retry_after_seconds: float,
) -> list[dict[str, Any]]:
    code = _failure_code(error)
    if code == "LIVE_SMOKE_RATE_LIMITED":
        defaults = _rate_limit_retry_defaults(source)
        retry_interval = max(min_interval_seconds, defaults["min_interval_seconds"])
        retry_count = max(retry, defaults["retry"])
        retry_after = max(retry_after_seconds, defaults["retry_after_seconds"])
        return [
            {
                "kind": "live_smoke_retry",
                "code": "RETRY_LIVE_SMOKE_RATE_LIMITED",
                "source": source,
                "citation_key": query.citation_key,
                "query_id": query.query_id,
                "requires_network": True,
                "writes_files": True,
                "command": _live_smoke_command(
                    source,
                    query,
                    cache_root=cache_root,
                    prefer_cache=True,
                    min_interval_seconds=retry_interval,
                    retry=retry_count,
                    retry_after_seconds=retry_after,
                ),
                "agent_hint": "Endpoint rate limit blocked this live check. Retry this citation separately with slower backoff and cache preference before preserving a reviewed manifest.",
            }
        ]
    if code == "LIVE_SMOKE_NETWORK_UNAVAILABLE":
        return [
            {
                "kind": "live_smoke_retry",
                "code": "RETRY_LIVE_SMOKE_AFTER_NETWORK_AVAILABLE",
                "source": source,
                "citation_key": query.citation_key,
                "query_id": query.query_id,
                "requires_network": True,
                "writes_files": True,
                "command": _live_smoke_command(
                    source,
                    query,
                    cache_root=cache_root,
                    prefer_cache=prefer_cache,
                    min_interval_seconds=min_interval_seconds,
                    retry=retry,
                    retry_after_seconds=retry_after_seconds,
                ),
                "agent_hint": "Network resolution failed. Do not mark the reference externally verified; rerun when network access is available.",
            }
        ]
    if code == "NO_CANDIDATES":
        return [
            {
                "kind": "live_smoke_review",
                "code": "REVIEW_LIVE_SMOKE_NO_CANDIDATES",
                "source": source,
                "citation_key": query.citation_key,
                "query_id": query.query_id,
                "requires_network": False,
                "writes_files": False,
                "command": _live_smoke_command(
                    source,
                    query,
                    cache_root=cache_root,
                    prefer_cache=True,
                    min_interval_seconds=min_interval_seconds,
                    retry=retry,
                    retry_after_seconds=retry_after_seconds,
                ),
                "agent_hint": "No live candidate matched. Check the title, DOI, arXiv ID, or official URL before trying another source or adding a reviewed fixture.",
            }
        ]
    return [
        {
            "kind": "live_smoke_retry",
            "code": "RETRY_LIVE_SMOKE_DISCOVERY",
            "source": source,
            "citation_key": query.citation_key,
            "query_id": query.query_id,
            "requires_network": True,
            "writes_files": True,
            "command": _live_smoke_command(
                source,
                query,
                cache_root=cache_root,
                prefer_cache=prefer_cache,
                min_interval_seconds=min_interval_seconds,
                retry=retry,
                retry_after_seconds=retry_after_seconds,
            ),
            "agent_hint": "Live discovery failed. Inspect the endpoint error before treating this reference as externally verified.",
        }
    ]


def _failure_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: dict[tuple[str, str], dict[str, Any]] = {}
    for result in results:
        if result.get("ok"):
            continue
        code = result.get("failure_code") or _failure_code(result.get("error"))
        source = result.get("source", "")
        key = (code, source)
        summary = summaries.setdefault(
            key,
            {
                "code": code,
                "source": source,
                "message": _failure_message(code, source),
                "count": 0,
                "citation_key_sample": [],
                "query_id_sample": [],
            },
        )
        summary["count"] += 1
        query = result.get("query") or {}
        citation_key = query.get("citation_key")
        query_id = query.get("query_id")
        if citation_key and citation_key not in summary["citation_key_sample"]:
            summary["citation_key_sample"].append(citation_key)
        if query_id and query_id not in summary["query_id_sample"]:
            summary["query_id_sample"].append(query_id)
    return list(summaries.values())


def live_smoke_failure_result(
    source: str,
    query: PaperQuery,
    *,
    cache_root: str | Path,
    error: str,
    prefer_cache: bool = False,
    min_interval_seconds: float = 0,
    retry: int = 0,
    retry_after_seconds: float = 0,
) -> dict[str, Any]:
    failure_code = _failure_code(error)
    return {
        "source": source,
        "query": query.to_dict(),
        "candidate_count": 0,
        "candidates": [],
        "cache_paths": [],
        "ok": False,
        "error": error,
        "failure_code": failure_code,
        "failure_message": _failure_message(failure_code, source),
        "next_actions": _live_smoke_next_actions(
            source,
            query,
            cache_root=cache_root,
            error=error,
            prefer_cache=prefer_cache,
            min_interval_seconds=min_interval_seconds,
            retry=retry,
            retry_after_seconds=retry_after_seconds,
        ),
    }


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
    result = {
        "source": source,
        "query": query.to_dict(),
        "candidate_count": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
        "cache_paths": sorted(dict.fromkeys(cache_paths)),
        "ok": bool(candidates),
    }
    if not candidates:
        result["failure_code"] = "NO_CANDIDATES"
        result["failure_message"] = _failure_message("NO_CANDIDATES", source)
        result["next_actions"] = _live_smoke_next_actions(
            source,
            query,
            cache_root=cache_root,
            error=None,
            prefer_cache=prefer_cache,
            min_interval_seconds=min_interval_seconds,
            retry=retry,
            retry_after_seconds=retry_after_seconds,
        )
    return result


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
            error = f"{exc.__class__.__name__}: {exc}"
            result = live_smoke_failure_result(
                item.source,
                item.query,
                cache_root=cache_root,
                error=error,
                prefer_cache=prefer_cache,
                min_interval_seconds=min_interval_seconds,
                retry=retry,
                retry_after_seconds=retry_after_seconds,
            )
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
        "failure_summary": _failure_summary(results),
        "next_actions": [action for result in results for action in result.get("next_actions", [])],
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
