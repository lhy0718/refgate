from __future__ import annotations

import json
import re
import shlex
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from .adapters.base import default_fetcher
from .adapters.venues import ADAPTERS as VENUE_ADAPTERS
from .assist import query_from_lock_entry
from .live_smoke import adapter_for_source, cached_fetcher
from .lockfile import load_lockfile
from .models import CandidateRecord, LockEntry, PaperQuery

REFGATE_COMMAND = "python -m refgate"
SCHOLAR_CAPTCHA_MARKERS = (
    "our systems have detected unusual traffic",
    "unusual traffic from your computer network",
    "please show you're not a robot",
    "not a robot",
    "recaptcha",
    "g-recaptcha",
    "/sorry/",
    "captcha",
)

DIRECT_SOURCE_DOMAINS: dict[str, tuple[str, ...]] = {
    "acl": ("aclanthology.org",),
    "crossref": ("doi.org", "dx.doi.org"),
    "iclr": ("proceedings.iclr.cc",),
    "neurips": ("proceedings.neurips.cc",),
    "openreview": ("openreview.net",),
}


def _source_domains() -> dict[str, tuple[str, ...]]:
    domains = dict(DIRECT_SOURCE_DOMAINS)
    for source, adapter_cls in VENUE_ADAPTERS.items():
        url_domains = tuple(getattr(adapter_cls, "url_domains", ()) or ())
        if url_domains:
            domains[source] = tuple(dict.fromkeys([*domains.get(source, ()), *url_domains]))
    return domains


def official_source_for_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host_no_www = host[4:]
    else:
        host_no_www = host
    if not host_no_www:
        return None
    for source, domains in _source_domains().items():
        for domain in domains:
            domain = domain.lower()
            if host_no_www == domain or host_no_www.endswith(f".{domain}"):
                return source
    return None


def google_scholar_query(query: PaperQuery) -> str:
    terms: list[str] = []
    title = query.title.strip()
    if title:
        terms.append(f'"{title}"')
    if query.authors:
        first_author = query.authors[0].strip()
        if first_author:
            terms.append(first_author)
    if query.year:
        terms.append(str(query.year))
    if not terms and query.doi:
        terms.append(query.doi)
    if not terms and query.arxiv_id:
        terms.append(query.arxiv_id)
    return " ".join(terms).strip()


def google_scholar_search_url(query: PaperQuery) -> str:
    return f"https://scholar.google.com/scholar?q={quote_plus(google_scholar_query(query))}"


def google_scholar_discovery_search(query: PaperQuery) -> dict[str, str]:
    return {
        "source": "google_scholar",
        "kind": "manual_discovery_search",
        "authority_role": "discovery_only",
        "query": google_scholar_query(query),
        "url": google_scholar_search_url(query),
        "note": "Use only to discover an official venue, DOI, or publisher page; do not treat Google Scholar BibTeX as official provenance.",
    }


def _refgate_command(*parts: str | Path) -> str:
    return " ".join([REFGATE_COMMAND, *(shlex.quote(str(part)) for part in parts)])


def _needs_bridge(entry: LockEntry) -> bool:
    source_kind = str(entry.bibtex.get("source_kind") or "")
    authority_source = str(entry.authority.get("source") or "")
    return (
        entry.status in {"arxiv_fallback_verified", "official_record_pending"}
        or source_kind == "arxiv_manual_normalized"
        or authority_source == "arxiv"
    )


def _scholar_html_file(scholar_html_dir: Path, citation_key: str) -> Path | None:
    for name in (
        f"{citation_key}.google_scholar.html",
        f"{citation_key}.scholar.html",
        f"{citation_key}.html",
    ):
        path = scholar_html_dir / name
        if path.exists():
            return path
    return None


def _manual_official_url_file(scholar_html_dir: Path, citation_key: str) -> Path | None:
    for name in (
        f"{citation_key}.official_urls.txt",
        f"{citation_key}.official_url.txt",
    ):
        path = scholar_html_dir / name
        if path.exists():
            return path
    return None


def google_scholar_captcha_markers(html: str) -> list[str]:
    lowered = html.lower()
    return [marker for marker in SCHOLAR_CAPTCHA_MARKERS if marker in lowered]


def _decode_scholar_href(href: str) -> str | None:
    href = unescape(href).strip()
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("/scholar_url?") or href.startswith("https://scholar.google.com/scholar_url?"):
        query = parse_qs(urlparse(href).query)
        value = (query.get("url") or [""])[0]
        return unquote(value) if value else None
    if href.startswith("/url?") or href.startswith("https://www.google.com/url?") or href.startswith("https://google.com/url?"):
        query = parse_qs(urlparse(href).query)
        value = (query.get("q") or query.get("url") or [""])[0]
        return unquote(value) if value else None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return None


def extract_google_scholar_urls(html: str) -> list[str]:
    urls: list[str] = []
    for raw_href in re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE):
        url = _decode_scholar_href(raw_href)
        if not url:
            continue
        host = urlparse(url).netloc.lower()
        if not host or "google." in host or host.endswith("gstatic.com"):
            continue
        if url not in urls:
            urls.append(url)
    return urls


def official_urls_from_scholar_html(html: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for url in extract_google_scholar_urls(html):
        source = official_source_for_url(url)
        if not source:
            continue
        items.append({"source": source, "url": url})
    return items


def official_urls_from_manual_file(path: str | Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        url = line.split()[0].strip().strip(",")
        source = official_source_for_url(url)
        if not source:
            continue
        item = {"source": source, "url": url}
        if item not in items:
            items.append(item)
    return items


def _query_with_preferred_url(query: PaperQuery, url: str) -> PaperQuery:
    return PaperQuery(
        query_id=query.query_id,
        citation_key=query.citation_key,
        title=query.title,
        authors=list(query.authors),
        year=query.year,
        doi=query.doi,
        arxiv_id=query.arxiv_id,
        preferred_venues=[url],
    )


def _fallback_candidate_from_url(source: str, url: str, query: PaperQuery, *, error: str | None = None) -> CandidateRecord:
    raw = {
        "metadata_source": "google_scholar_official_url",
        "authority_role": "official_url_candidate",
        "google_scholar_bridge_status": "fallback_url_candidate",
    }
    if error:
        raw["official_fetch_error"] = error
    return CandidateRecord(
        source=source,
        title=query.title,
        authors=list(query.authors),
        year=query.year,
        doi=query.doi if source == "crossref" else None,
        arxiv_id=None,
        url=url,
        is_official_record=True,
        bibtex_url=None,
        source_priority=1,
        raw=raw,
    )


def official_candidate_from_url(
    source: str,
    url: str,
    query: PaperQuery,
    *,
    cache_root: str | Path = ".refgate/cache",
    prefer_cache: bool = False,
    fetcher: Callable[[str], str] = default_fetcher,
) -> tuple[CandidateRecord, dict[str, Any]]:
    adapter_fetcher = cached_fetcher(source, fetcher, cache_root, prefer_cache=prefer_cache)
    query_with_url = _query_with_preferred_url(query, url)
    try:
        adapter = adapter_for_source(source, adapter_fetcher)
        candidates = adapter.discover(query_with_url)
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"
        return _fallback_candidate_from_url(source, url, query, error=error), {
            "source": source,
            "url": url,
            "ok": False,
            "error": error,
            "fallback_candidate": True,
        }
    if candidates:
        return candidates[0], {"source": source, "url": url, "ok": True, "candidate_count": len(candidates)}
    return _fallback_candidate_from_url(source, url, query, error="no candidate parsed from official URL"), {
        "source": source,
        "url": url,
        "ok": False,
        "error": "no candidate parsed from official URL",
        "fallback_candidate": True,
    }


def _write_candidate_file(candidate_dir: Path, citation_key: str, candidates: list[CandidateRecord]) -> Path:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    target = candidate_dir / f"{citation_key}.json"
    target.write_text(
        json.dumps({"candidates": [candidate.to_dict() for candidate in candidates]}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _reference_check_command(
    *,
    lock_path: str | Path,
    candidate_dir: str | Path,
    citation_key: str,
    cache_root: str | Path,
    prefer_cache: bool,
    write_lock: str | Path | None,
    fetch_official_bibtex: bool,
) -> str:
    parts: list[str | Path] = [
        "reference-check",
        "--lock",
        lock_path,
        "--candidate-dir",
        candidate_dir,
        "--cache-root",
        cache_root,
        "--citation-key",
        citation_key,
    ]
    if prefer_cache:
        parts.append("--prefer-cache")
    if write_lock:
        parts.extend(["--write-lock", write_lock])
    if fetch_official_bibtex:
        parts.append("--fetch-official-bibtex")
    parts.append("--json")
    return _refgate_command(*parts)


def _bridge_command(
    *,
    lock_path: str | Path,
    scholar_html_dir: str | Path,
    candidate_dir: str | Path,
    cache_root: str | Path,
    prefer_cache: bool,
    write_lock: str | Path | None,
    fetch_official_bibtex: bool,
    citation_key: str | None = None,
    live_scholar: bool = True,
) -> str:
    parts: list[str | Path] = [
        "scholar-official-bridge",
        "--lock",
        lock_path,
        "--scholar-html-dir",
        scholar_html_dir,
        "--candidate-dir",
        candidate_dir,
        "--cache-root",
        cache_root,
        "--live-official",
        "--write-candidates",
    ]
    if live_scholar:
        parts.append("--live-scholar")
    if prefer_cache:
        parts.append("--prefer-cache")
    if write_lock:
        parts.extend(["--write-lock", write_lock])
    if fetch_official_bibtex:
        parts.append("--fetch-official-bibtex")
    if citation_key:
        parts.extend(["--citation-key", citation_key])
    parts.append("--json")
    return _refgate_command(*parts)


def _human_scholar_review_issue_and_action(
    *,
    code: str,
    message: str,
    citation_key: str,
    discovery: dict[str, str],
    target_html: Path,
    manual_url_file: Path,
    lock_path: str | Path,
    scholar_html_dir: str | Path,
    candidate_dir: str | Path,
    cache_root: str | Path,
    prefer_cache: bool,
    write_lock: str | Path | None,
    fetch_official_bibtex: bool,
    evidence: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    issue = {
        "code": code,
        "message": message,
        "citation_key": citation_key,
        "evidence": evidence,
    }
    action = {
        "code": code,
        "kind": "scholar_human_review",
        "requires_review": True,
        "writes_files": True,
        "network_required": True,
        "citation_key": citation_key,
        "message": (
            "Complete Google Scholar review in a browser, then either save the result HTML "
            "or paste an official venue/publisher URL into the manual URL file before rerunning the bridge."
        ),
        "google_scholar_url": discovery["url"],
        "target_file": str(target_html),
        "manual_official_url_file": str(manual_url_file),
        "command": _bridge_command(
            lock_path=lock_path,
            scholar_html_dir=scholar_html_dir,
            candidate_dir=candidate_dir,
            cache_root=cache_root,
            prefer_cache=prefer_cache,
            write_lock=write_lock,
            fetch_official_bibtex=fetch_official_bibtex,
            citation_key=citation_key,
            live_scholar=False,
        ),
    }
    return issue, action


def build_scholar_official_bridge_plan(
    lock_path: str | Path,
    *,
    scholar_html_dir: str | Path,
    candidate_dir: str | Path,
    cache_root: str | Path = ".refgate/cache",
    prefer_cache: bool = False,
    write_candidates: bool = False,
    live_official: bool = False,
    live_scholar: bool = False,
    write_lock: str | Path | None = None,
    fetch_official_bibtex: bool = True,
    max_entries: int | None = None,
    citation_keys: list[str] | None = None,
    fetcher: Callable[[str], str] = default_fetcher,
) -> dict[str, Any]:
    lockfile = load_lockfile(lock_path)
    scholar_root = Path(scholar_html_dir)
    candidate_root = Path(candidate_dir)
    wanted = set(citation_keys or [])
    entries = [entry for entry in lockfile.entries if _needs_bridge(entry) and (not wanted or entry.citation_key in wanted)]
    entries = entries[:max_entries] if max_entries is not None else entries
    items: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []

    for entry in entries:
        query = query_from_lock_entry(entry)
        discovery = google_scholar_discovery_search(query)
        html_path = _scholar_html_file(scholar_root, entry.citation_key)
        manual_url_path = _manual_official_url_file(scholar_root, entry.citation_key)
        target_html = scholar_root / f"{entry.citation_key}.google_scholar.html"
        target_manual_url = scholar_root / f"{entry.citation_key}.official_urls.txt"
        item: dict[str, Any] = {
            "citation_key": entry.citation_key,
            "status": entry.status,
            "query": query.to_dict(),
            "google_scholar_search": discovery,
            "scholar_html": str(html_path) if html_path else None,
            "manual_official_url_file": str(manual_url_path) if manual_url_path else None,
            "official_url_candidates": [],
            "candidate_file": None,
            "google_scholar_fetch": None,
            "official_candidate_fetches": [],
        }
        if manual_url_path is not None:
            official_urls = official_urls_from_manual_file(manual_url_path)
            item["official_url_candidates"] = official_urls
            if not official_urls:
                issue = {
                    "code": "MANUAL_OFFICIAL_URL_NOT_RECOGNIZED",
                    "message": "Manual official URL file did not contain a recognized official venue or publisher URL.",
                    "citation_key": entry.citation_key,
                    "evidence": [str(manual_url_path), discovery["url"]],
                }
                blocking.append(issue)
                next_actions.append(
                    {
                        "code": "REVIEW_MANUAL_OFFICIAL_URL_FILE",
                        "kind": "scholar_human_review",
                        "requires_review": True,
                        "writes_files": True,
                        "network_required": False,
                        "citation_key": entry.citation_key,
                        "message": "Replace the manual URL file with one recognized official venue or publisher URL.",
                        "google_scholar_url": discovery["url"],
                        "manual_official_url_file": str(manual_url_path),
                    }
                )
                items.append(item)
                continue
        else:
            official_urls = None
        if html_path is None and live_scholar:
            try:
                scholar_root.mkdir(parents=True, exist_ok=True)
                html = fetcher(discovery["url"])
                target_html.write_text(html, encoding="utf-8")
                html_path = target_html
                item["scholar_html"] = str(html_path)
                item["google_scholar_fetch"] = {"ok": True, "url": discovery["url"], "target_file": str(target_html)}
            except Exception as exc:
                error = f"{exc.__class__.__name__}: {exc}"
                item["google_scholar_fetch"] = {"ok": False, "url": discovery["url"], "target_file": str(target_html), "error": error}
                issue, action = _human_scholar_review_issue_and_action(
                    code="SCHOLAR_LIVE_FETCH_FAILED",
                    message="Live Google Scholar discovery failed; save the result HTML manually or paste an official URL.",
                    citation_key=entry.citation_key,
                    discovery=discovery,
                    target_html=target_html,
                    manual_url_file=target_manual_url,
                    lock_path=lock_path,
                    scholar_html_dir=scholar_html_dir,
                    candidate_dir=candidate_dir,
                    cache_root=cache_root,
                    prefer_cache=prefer_cache,
                    write_lock=write_lock,
                    fetch_official_bibtex=fetch_official_bibtex,
                    evidence=[discovery["url"], str(target_html), error],
                )
                blocking.append(issue)
                next_actions.append(action)
                items.append(item)
                continue
        if official_urls is None and html_path is None:
            issue = {
                "code": "SCHOLAR_HTML_MISSING",
                "message": "Save a Google Scholar result page before bridging to official venue records.",
                "citation_key": entry.citation_key,
                "evidence": [discovery["url"], str(target_html), str(target_manual_url)],
            }
            blocking.append(issue)
            next_actions.append(
                {
                    "code": "SAVE_GOOGLE_SCHOLAR_RESULTS",
                    "kind": "scholar_discovery_input",
                    "requires_review": True,
                    "writes_files": True,
                    "network_required": False,
                    "citation_key": entry.citation_key,
                    "message": "Save the Google Scholar result HTML, then rerun scholar-official-bridge.",
                    "google_scholar_url": discovery["url"],
                    "target_file": str(target_html),
                    "manual_official_url_file": str(target_manual_url),
                    "command": _bridge_command(
                        lock_path=lock_path,
                        scholar_html_dir=scholar_html_dir,
                        candidate_dir=candidate_dir,
                        cache_root=cache_root,
                        prefer_cache=prefer_cache,
                        write_lock=write_lock,
                        fetch_official_bibtex=fetch_official_bibtex,
                        citation_key=entry.citation_key,
                        live_scholar=True,
                    ),
                }
            )
            items.append(item)
            continue

        if official_urls is None:
            html = html_path.read_text(encoding="utf-8")
            captcha_markers = google_scholar_captcha_markers(html)
            if captcha_markers:
                issue, action = _human_scholar_review_issue_and_action(
                    code="SCHOLAR_CAPTCHA_REVIEW_REQUIRED",
                    message="Google Scholar returned a CAPTCHA or anti-automation interstitial.",
                    citation_key=entry.citation_key,
                    discovery=discovery,
                    target_html=target_html,
                    manual_url_file=target_manual_url,
                    lock_path=lock_path,
                    scholar_html_dir=scholar_html_dir,
                    candidate_dir=candidate_dir,
                    cache_root=cache_root,
                    prefer_cache=prefer_cache,
                    write_lock=write_lock,
                    fetch_official_bibtex=fetch_official_bibtex,
                    evidence=[str(html_path), discovery["url"], *captcha_markers[:3]],
                )
                item["google_scholar_captcha"] = {"detected": True, "markers": captcha_markers}
                blocking.append(issue)
                next_actions.append(action)
                items.append(item)
                continue
            official_urls = official_urls_from_scholar_html(html)
            item["official_url_candidates"] = official_urls
        if not official_urls:
            issue = {
                "code": "SCHOLAR_OFFICIAL_URL_NOT_FOUND",
                "message": "Google Scholar HTML did not contain a recognized official venue or publisher URL.",
                "citation_key": entry.citation_key,
                "evidence": [str(html_path), discovery["url"], str(target_manual_url)],
            }
            blocking.append(issue)
            next_actions.append(
                {
                    "code": "REVIEW_SCHOLAR_RESULTS_FOR_OFFICIAL_URL",
                    "kind": "scholar_discovery_review",
                    "requires_review": True,
                    "writes_files": False,
                    "network_required": False,
                    "citation_key": entry.citation_key,
                    "message": "Review the Scholar page and add a recognized official venue URL or use another official source adapter.",
                    "google_scholar_url": discovery["url"],
                    "scholar_html": str(html_path),
                    "manual_official_url_file": str(target_manual_url),
                }
            )
            items.append(item)
            continue

        candidates: list[CandidateRecord] = []
        if live_official:
            for official in official_urls:
                candidate, fetch_result = official_candidate_from_url(
                    official["source"],
                    official["url"],
                    query,
                    cache_root=cache_root,
                    prefer_cache=prefer_cache,
                    fetcher=fetcher,
                )
                candidates.append(candidate)
                item["official_candidate_fetches"].append(fetch_result)
            if candidates and write_candidates:
                candidate_file = _write_candidate_file(candidate_root, entry.citation_key, candidates)
                item["candidate_file"] = str(candidate_file)
                reference_command = _reference_check_command(
                    lock_path=lock_path,
                    candidate_dir=candidate_dir,
                    citation_key=entry.citation_key,
                    cache_root=cache_root,
                    prefer_cache=prefer_cache,
                    write_lock=write_lock,
                    fetch_official_bibtex=fetch_official_bibtex,
                )
                item["reference_check_command"] = reference_command
                next_actions.append(
                    {
                        "code": "RUN_REFERENCE_CHECK_FROM_SCHOLAR_CANDIDATES",
                        "kind": "reference_provenance",
                        "requires_review": False,
                        "writes_files": bool(write_lock),
                        "network_required": bool(fetch_official_bibtex),
                        "citation_key": entry.citation_key,
                        "message": "Run official reference-check from Google-Scholar-discovered official URL candidates.",
                        "candidate_file": str(candidate_file),
                        "command": reference_command,
                    }
                )
        else:
            next_actions.append(
                {
                    "code": "FETCH_OFFICIAL_RECORDS_FROM_SCHOLAR_URLS",
                    "kind": "scholar_to_official_bridge",
                    "requires_review": False,
                    "writes_files": True,
                    "network_required": True,
                    "citation_key": entry.citation_key,
                    "message": "Fetch the official venue URLs found via Google Scholar and write reference-check candidate files.",
                    "official_url_candidates": official_urls,
                    "command": _bridge_command(
                        lock_path=lock_path,
                        scholar_html_dir=scholar_html_dir,
                        candidate_dir=candidate_dir,
                        cache_root=cache_root,
                        prefer_cache=prefer_cache,
                        write_lock=write_lock,
                        fetch_official_bibtex=fetch_official_bibtex,
                        citation_key=entry.citation_key,
                    ),
                }
            )
        items.append(item)

    return {
        "schema_version": "refgate.scholar_official_bridge.v1",
        "lock": str(lock_path),
        "scholar_html_dir": str(scholar_html_dir),
        "candidate_dir": str(candidate_dir),
        "checked_count": len(items),
        "blocking_issues": blocking,
        "items": items,
        "next_actions": next_actions,
    }
