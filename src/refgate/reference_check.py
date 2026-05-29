from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from .adapters.arxiv import ArxivAdapter
from .adapters.base import default_fetcher
from .adapters.official_html import official_bibtex_record
from .assist import query_from_lock_entry, recommended_sources
from .bibtex import normalize_bibtex_fields, parse_bibtex_entry, sha256_text
from .live_smoke import adapter_for_source, cached_fetcher, run_live_smoke
from .lockfile import build_lock_entry, load_lockfile, merge_lock_entry, write_lockfile
from .models import BibtexRecord, CandidateRecord
from .resolver import normalize_title, resolve


REFGATE_COMMAND = "python -m refgate"


def _refgate_command(*parts: str | Path) -> str:
    return " ".join([REFGATE_COMMAND, *(shlex.quote(str(part)) for part in parts)])


def _load_candidates(path: Path) -> list[CandidateRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if "candidates" in data:
            data = data["candidates"]
        else:
            data = [data]
    return [CandidateRecord.from_dict(item) for item in data]


def _candidate_file(candidate_dir: Path, citation_key: str) -> Path | None:
    for suffix in (".json", ".candidates.json"):
        path = candidate_dir / f"{citation_key}{suffix}"
        if path.exists():
            return path
    return None


def _bibtex_file(bibtex_dir: Path, citation_key: str) -> Path | None:
    for suffix in (".bib", ".bibtex"):
        path = bibtex_dir / f"{citation_key}{suffix}"
        if path.exists():
            return path
    return None


def _official_bibtex_file(official_bibtex_dir: Path, citation_key: str, source: str) -> Path | None:
    for suffix in (".bib", ".bibtex"):
        for name in (f"{citation_key}.{source}{suffix}", f"{citation_key}.source{suffix}", f"{citation_key}{suffix}"):
            path = official_bibtex_dir / name
            if path.exists():
                return path
    return None


def _fixture_html_file(fixture_html_dir: Path, citation_key: str, source: str) -> Path | None:
    for name in (f"{citation_key}.{source}.html", f"{citation_key}.html"):
        path = fixture_html_dir / name
        if path.exists():
            return path
    return None


def _bibtex_title(path: Path) -> str | None:
    try:
        return parse_bibtex_entry(path.read_text(encoding="utf-8")).get("title")
    except Exception:
        return None


def _bibtex_file_for_reference(
    bibtex_dir: Path,
    citation_key: str,
    *,
    expected_title: str,
) -> tuple[Path | None, str | None, list[dict[str, Any]]]:
    exact = _bibtex_file(bibtex_dir, citation_key)
    if exact:
        return exact, "citation_key_file", []

    normalized_expected = normalize_title(expected_title)
    title_matches = []
    for path in sorted([*bibtex_dir.glob("*.bib"), *bibtex_dir.glob("*.bibtex")]):
        title = _bibtex_title(path)
        if title and normalize_title(title) == normalized_expected:
            title_matches.append(path)

    if len(title_matches) == 1:
        return title_matches[0], "title_exact", []
    if len(title_matches) > 1:
        return (
            None,
            None,
            [
                {
                    "code": "BIBTEX_PROVENANCE_AMBIGUOUS",
                    "message": "Multiple BibTeX files have an exact normalized title match for this reference.",
                    "citation_key": citation_key,
                    "evidence": [str(path) for path in title_matches],
                }
            ],
        )
    return None, None, []


def _bibtex_from_file(path: Path, citation_key: str, source_kind: str) -> BibtexRecord:
    raw_text = path.read_text(encoding="utf-8")
    parsed = parse_bibtex_entry(raw_text)
    return BibtexRecord(
        entry_type=parsed["entry_type"],
        citation_key=parsed["citation_key"],
        source_kind=source_kind,  # type: ignore[arg-type]
        raw_text=raw_text,
        raw_sha256=sha256_text(raw_text),
        normalized_sha256=sha256_text(raw_text.strip() + "\n"),
    )


def _official_bibtex_checks(
    *,
    bibtex_record: BibtexRecord,
    decision: Any,
    expected_title: str,
    citation_key: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    parsed = normalize_bibtex_fields(parse_bibtex_entry(bibtex_record.raw_text))
    checks: dict[str, Any] = {
        "title": "not_checked",
        "doi": "not_checked",
        "exported_citation_key": parsed.get("citation_key"),
    }
    issues: list[dict[str, Any]] = []

    bibtex_title = parsed.get("title", "")
    if bibtex_title and normalize_title(bibtex_title) == normalize_title(expected_title):
        checks["title"] = "exact_normalized_match"
    else:
        checks["title"] = "mismatch"
        issues.append(
            {
                "code": "OFFICIAL_BIBTEX_TITLE_MISMATCH",
                "message": "Official BibTeX export title does not match the selected authority record title.",
                "citation_key": citation_key,
                "evidence": [bibtex_title, expected_title],
            }
        )

    candidate_doi = decision.selected_candidate.doi if decision.selected_candidate else None
    bibtex_doi = parsed.get("doi", "")
    if candidate_doi and bibtex_doi:
        checks["doi"] = "exact_match" if candidate_doi.lower() == bibtex_doi.lower() else "mismatch"
        if checks["doi"] == "mismatch":
            issues.append(
                {
                    "code": "OFFICIAL_BIBTEX_DOI_MISMATCH",
                    "message": "Official BibTeX export DOI does not match the selected authority record DOI.",
                    "citation_key": citation_key,
                    "evidence": [bibtex_doi, candidate_doi],
                }
            )
    elif candidate_doi:
        checks["doi"] = "missing_in_bibtex"
    elif bibtex_doi:
        checks["doi"] = "authority_doi_missing"

    return checks, issues


def _issue_with_citation(issue: Any, citation_key: str) -> dict[str, Any]:
    data = issue.to_dict()
    if not data.get("citation_key"):
        data["citation_key"] = citation_key
    return data


def _fetch_official_bibtex(
    authority: Any,
    *,
    cache_root: str | Path,
    prefer_cache: bool,
    fixture_html_path: Path | None = None,
) -> BibtexRecord:
    try:
        if fixture_html_path and authority.bibtex_url == authority.record_url:
            html = fixture_html_path.read_text(encoding="utf-8")
            adapter = adapter_for_source(authority.source, lambda _url: html)
        else:
            adapter = adapter_for_source(
                authority.source,
                cached_fetcher(
                    authority.source,
                    default_fetcher,
                    cache_root,
                    prefer_cache=prefer_cache,
                ),
            )
    except ValueError:
        return official_bibtex_record(default_fetcher(authority.bibtex_url))

    endpoints = adapter.find_export_endpoints(authority)
    for endpoint in endpoints:
        if endpoint.format != "bibtex" or not endpoint.is_official:
            continue
        bibtex_record = adapter.fetch_bibtex(authority, endpoint)
        if bibtex_record is not None:
            return bibtex_record
    return official_bibtex_record(default_fetcher(authority.bibtex_url))


def _candidates_from_fixture_html(
    *,
    fixture_html_dir: Path,
    citation_key: str,
    query: Any,
    sources: list[str],
) -> tuple[list[CandidateRecord], list[dict[str, Any]], Path | None]:
    candidates: list[CandidateRecord] = []
    results: list[dict[str, Any]] = []
    first_path: Path | None = None
    for source in sources:
        path = _fixture_html_file(fixture_html_dir, citation_key, source)
        if path is None:
            continue
        if first_path is None:
            first_path = path
        html = path.read_text(encoding="utf-8")
        try:
            adapter = adapter_for_source(source, lambda _url, html=html: html)
            source_candidates = adapter.discover(query)
        except Exception as exc:
            results.append(
                {
                    "source": source,
                    "fixture_html": str(path),
                    "candidate_count": 0,
                    "ok": False,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            )
            continue
        candidates.extend(source_candidates)
        results.append(
            {
                "source": source,
                "fixture_html": str(path),
                "candidate_count": len(source_candidates),
                "ok": bool(source_candidates),
            }
        )
    return candidates, results, first_path


def _reference_check_rerun_command(
    *,
    lock_path: str | Path,
    candidate_dir: str | Path | None,
    bibtex_dir: str | Path | None,
    official_bibtex_dir: str | Path | None,
    fixture_html_dir: str | Path | None,
    live: bool,
    sources: list[str] | None,
    cache_root: str | Path,
    prefer_cache: bool,
    write_lock: str | Path | None,
    fallback_reason: str | None,
    max_entries: int | None,
    fetch_official_bibtex: bool,
    citation_keys: list[str] | None,
) -> str:
    parts: list[str | Path] = ["reference-check", "--lock", lock_path]
    if candidate_dir:
        parts.extend(["--candidate-dir", candidate_dir])
    if bibtex_dir:
        parts.extend(["--bibtex-dir", bibtex_dir])
    if official_bibtex_dir:
        parts.extend(["--official-bibtex-dir", official_bibtex_dir])
    if fixture_html_dir:
        parts.extend(["--fixture-html-dir", fixture_html_dir])
    for source in sources or []:
        parts.extend(["--source", source])
    if cache_root != ".refgate/cache":
        parts.extend(["--cache-root", cache_root])
    if prefer_cache:
        parts.append("--prefer-cache")
    if write_lock:
        parts.extend(["--write-lock", write_lock])
    if fallback_reason:
        parts.extend(["--fallback-reason", fallback_reason])
    if max_entries is not None:
        parts.extend(["--max-entries", str(max_entries)])
    for citation_key in citation_keys or []:
        parts.extend(["--citation-key", citation_key])
    if fetch_official_bibtex:
        parts.append("--fetch-official-bibtex")
    if live:
        parts.append("--live")
    parts.append("--json")
    return _refgate_command(*parts)


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped = []
    for action in actions:
        key = (action.get("code", ""), action.get("citation_key", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _source_guidance(source: str, citation_key: str) -> dict[str, Any]:
    html_examples = [f"{citation_key}.{source}.html", f"{citation_key}.html"] if citation_key else []
    guidance: dict[str, Any] = {
        "source": source,
        "fixture_html_file_examples": html_examples,
        "official_bibtex_file_examples": (
            [
                f"{citation_key}.{source}.bib",
                f"{citation_key}.source.bib",
                f"{citation_key}.bib",
            ]
            if citation_key
            else []
        ),
    }
    if source == "acm":
        guidance.update(
            {
                "record_url_patterns": ["https://dl.acm.org/doi/DOI", "https://dl.acm.org/doi/abs/DOI"],
                "official_bibtex_url_pattern": (
                    "https://dl.acm.org/action/exportCiteProcCitation?"
                    "dois=URL_ENCODED_DOI&targetFile=custom-bibtex&format=bibTex"
                ),
                "source_pdf_url_pattern": "https://dl.acm.org/doi/pdf/DOI",
                "live_fetch_note": "ACM may block automated HTML fetches; use reviewed official HTML or official BibTeX fixtures when needed.",
            }
        )
    elif source == "springer":
        guidance.update(
            {
                "record_url_patterns": ["https://link.springer.com/chapter/DOI", "https://link.springer.com/article/DOI"],
                "source_pdf_url_pattern": "https://link.springer.com/content/pdf/DOI.pdf",
                "live_fetch_note": "Springer BibTeX links may contain escaped query separators; keep the reviewed official export URL unescaped.",
            }
        )
    elif source == "ieee":
        guidance.update(
            {
                "record_url_patterns": ["https://ieeexplore.ieee.org/document/DOCUMENT_ID"],
                "live_fetch_note": "IEEE pages often store metadata in scripts; save reviewed official HTML if live parsing is blocked.",
            }
        )
    elif source == "pnas":
        guidance.update(
            {
                "record_url_patterns": ["https://www.pnas.org/doi/abs/DOI", "https://www.pnas.org/doi/full/DOI"],
                "source_pdf_url_pattern": "https://www.pnas.org/doi/pdf/DOI",
            }
        )
    elif source == "science":
        guidance.update(
            {
                "record_url_patterns": ["https://www.science.org/doi/abs/DOI", "https://www.science.org/doi/full/DOI"],
                "source_pdf_url_pattern": "https://www.science.org/doi/pdf/DOI",
            }
        )
    elif source == "frontiers":
        guidance.update(
            {
                "record_url_patterns": ["https://www.frontiersin.org/journals/JOURNAL/articles/DOI/full"],
                "source_pdf_url_pattern": "Replace the final /full path segment with /pdf.",
            }
        )
    elif source == "mdpi":
        guidance.update(
            {
                "record_url_patterns": ["https://www.mdpi.com/JOURNAL/VOLUME/ISSUE/ARTICLE"],
                "source_pdf_url_pattern": "Append /pdf or replace /htm with /pdf.",
            }
        )
    elif source in {"oxford", "cambridge", "lipics"}:
        guidance.update(
            {
                "live_fetch_note": "Use reviewed official HTML and official BibTeX fixtures when the record page does not expose a verified BibTeX endpoint.",
            }
        )
    return guidance


def _row_for_citation(rows: list[dict[str, Any]], citation_key: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("citation_key") == citation_key:
            return row
    return None


def _decision_authority(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    authority = decision.get("authority") if isinstance(decision.get("authority"), dict) else {}
    return authority or {}


def build_reference_check_next_actions(
    *,
    lock_path: str | Path,
    rows: list[dict[str, Any]],
    blocking: list[dict[str, Any]],
    candidate_dir: str | Path | None,
    bibtex_dir: str | Path | None,
    official_bibtex_dir: str | Path | None,
    fixture_html_dir: str | Path | None,
    live: bool,
    sources: list[str] | None,
    cache_root: str | Path,
    prefer_cache: bool,
    write_lock: str | Path | None,
    fallback_reason: str | None,
    max_entries: int | None,
    updated_entries: int,
    fetch_official_bibtex: bool = False,
    citation_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    candidate_root = Path(candidate_dir) if candidate_dir else Path("REFERENCE_CANDIDATES_DIR")
    bibtex_root = Path(bibtex_dir) if bibtex_dir else Path("REVIEWED_FALLBACK_BIBTEX_DIR")
    official_bibtex_root = Path(official_bibtex_dir) if official_bibtex_dir else Path("OFFICIAL_BIBTEX_DIR")
    for issue in blocking:
        citation_key = issue.get("citation_key", "")
        if issue.get("code") in {"REFERENCE_CANDIDATES_MISSING", "NO_CANDIDATES"}:
            actions.append(
                {
                    "code": "ADD_REFERENCE_CANDIDATES",
                    "kind": "reference_candidate_input",
                    "requires_human_review": True,
                    "writes_files": True,
                    "network_required": False,
                    "message": "Add reviewed candidate records for this citation key, or rerun reference-check with --live.",
                    "citation_key": citation_key,
                    "candidate_file": str(candidate_root / f"{citation_key}.json") if citation_key else str(candidate_root),
                    "command": _reference_check_rerun_command(
                        lock_path=lock_path,
                        candidate_dir=candidate_dir or "REFERENCE_CANDIDATES_DIR",
                        bibtex_dir=bibtex_dir,
                        official_bibtex_dir=official_bibtex_dir,
                        fixture_html_dir=fixture_html_dir,
                        live=live,
                        sources=sources,
                        cache_root=cache_root,
                        prefer_cache=prefer_cache,
                        write_lock=write_lock,
                        fallback_reason=fallback_reason,
                        max_entries=max_entries,
                        fetch_official_bibtex=fetch_official_bibtex,
                        citation_keys=citation_keys,
                    ),
                }
            )
        elif issue.get("code") in {"LOW_CONFIDENCE", "OFFICIAL_RECORD_PENDING"}:
            actions.append(
                {
                    "code": "REVIEW_REFERENCE_CANDIDATE",
                    "kind": "reference_candidate_review",
                    "requires_human_review": True,
                    "writes_files": True,
                    "network_required": False,
                    "message": (
                        "Review the best low-confidence or preprint-only candidate, then add a citation-key "
                        "candidate file with an official venue record or an explicit reviewed fallback."
                    ),
                    "citation_key": citation_key,
                    "candidate_file": str(candidate_root / f"{citation_key}.json") if citation_key else str(candidate_root),
                    "blocking_code": issue.get("code"),
                    "evidence": issue.get("evidence", []),
                    "command": _reference_check_rerun_command(
                        lock_path=lock_path,
                        candidate_dir=candidate_dir or "REFERENCE_CANDIDATES_DIR",
                        bibtex_dir=bibtex_dir,
                        official_bibtex_dir=official_bibtex_dir,
                        fixture_html_dir=fixture_html_dir,
                        live=live,
                        sources=sources,
                        cache_root=cache_root,
                        prefer_cache=prefer_cache,
                        write_lock=write_lock,
                        fallback_reason=fallback_reason,
                        max_entries=max_entries,
                        fetch_official_bibtex=fetch_official_bibtex,
                        citation_keys=citation_keys,
                    ),
                }
            )
        elif issue.get("code") == "REFERENCE_LIVE_LOOKUP_FAILED":
            example_source = (sources or ["source"])[0]
            source_guidance = _source_guidance(example_source, citation_key)
            actions.append(
                {
                    "code": "RETRY_OR_CACHE_LIVE_LOOKUP",
                    "kind": "live_lookup",
                    "requires_human_review": False,
                    "writes_files": True,
                    "network_required": True,
                    "message": "Live lookup failed; inspect rate limits or retry with reviewed cache/prefer-cache.",
                    "citation_key": citation_key,
                    "source_guidance": source_guidance,
                    "command": _reference_check_rerun_command(
                        lock_path=lock_path,
                        candidate_dir=candidate_dir,
                        bibtex_dir=bibtex_dir,
                        official_bibtex_dir=official_bibtex_dir,
                        fixture_html_dir=fixture_html_dir,
                        live=True,
                        sources=sources,
                        cache_root=cache_root,
                        prefer_cache=True,
                        write_lock=write_lock,
                        fallback_reason=fallback_reason,
                        max_entries=max_entries,
                        fetch_official_bibtex=fetch_official_bibtex,
                        citation_keys=citation_keys,
                    ),
                }
            )
            actions.append(
                {
                    "code": "ADD_OFFICIAL_HTML_FIXTURE",
                    "kind": "official_html_fixture_input",
                    "requires_human_review": True,
                    "writes_files": True,
                    "network_required": False,
                    "message": (
                        "If the publisher blocks live lookup, save the official record HTML as "
                        "citationkey.source.html or citationkey.html, then rerun reference-check with --fixture-html-dir."
                    ),
                    "citation_key": citation_key,
                    "fixture_html_dir": "OFFICIAL_HTML_DIR",
                    "fixture_html_file_examples": source_guidance["fixture_html_file_examples"],
                    "source_guidance": source_guidance,
                    "reviewed_bibtex_dir": "REVIEWED_FALLBACK_BIBTEX_DIR",
                    "command": _reference_check_rerun_command(
                        lock_path=lock_path,
                        candidate_dir=candidate_dir,
                        bibtex_dir=bibtex_dir or "REVIEWED_FALLBACK_BIBTEX_DIR",
                        official_bibtex_dir=official_bibtex_dir,
                        fixture_html_dir="OFFICIAL_HTML_DIR",
                        live=False,
                        sources=sources,
                        cache_root=cache_root,
                        prefer_cache=prefer_cache,
                        write_lock=write_lock,
                        fallback_reason=fallback_reason
                        or "Reviewed saved official HTML; manual BibTeX fallback retained because no official BibTeX endpoint was verified.",
                        max_entries=max_entries,
                        fetch_official_bibtex=fetch_official_bibtex,
                        citation_keys=citation_keys or ([citation_key] if citation_key else None),
                    ),
                }
            )
        elif issue.get("code") == "OFFICIAL_BIBTEX_FETCH_FAILED":
            row = _row_for_citation(rows, citation_key)
            authority = _decision_authority(row)
            source = str(authority.get("source") or (sources or ["source"])[0])
            source_guidance = _source_guidance(source, citation_key)
            actions.append(
                {
                    "code": "ADD_OFFICIAL_BIBTEX_FIXTURE",
                    "kind": "official_bibtex_fixture_input",
                    "requires_human_review": True,
                    "writes_files": True,
                    "network_required": False,
                    "message": "Official BibTeX fetch failed; save the reviewed official export as a citation-key file and rerun reference-check.",
                    "citation_key": citation_key,
                    "official_bibtex_dir": str(official_bibtex_root),
                    "official_bibtex_url": authority.get("bibtex_url"),
                    "official_bibtex_file_examples": [
                        str(official_bibtex_root / example) for example in source_guidance["official_bibtex_file_examples"]
                    ]
                    if citation_key
                    else [str(official_bibtex_root)],
                    "source_guidance": source_guidance,
                    "command": _reference_check_rerun_command(
                        lock_path=lock_path,
                        candidate_dir=candidate_dir,
                        bibtex_dir=bibtex_dir,
                        official_bibtex_dir=official_bibtex_dir or "OFFICIAL_BIBTEX_DIR",
                        fixture_html_dir=fixture_html_dir,
                        live=False,
                        sources=sources,
                        cache_root=cache_root,
                        prefer_cache=prefer_cache,
                        write_lock=write_lock,
                        fallback_reason=fallback_reason,
                        max_entries=max_entries,
                        fetch_official_bibtex=fetch_official_bibtex,
                        citation_keys=citation_keys or ([citation_key] if citation_key else None),
                    ),
                }
            )
        elif issue.get("code") == "BIBTEX_PROVENANCE_INPUT_MISSING":
            row = _row_for_citation(rows, citation_key)
            authority = _decision_authority(row)
            source = str(authority.get("source") or ((sources or [None])[0] or "source"))
            source_guidance = _source_guidance(source, citation_key)
            official_bibtex_url = authority.get("bibtex_url")
            if official_bibtex_url and not fetch_official_bibtex:
                actions.append(
                    {
                        "code": "FETCH_OFFICIAL_BIBTEX_EXPORT",
                        "kind": "official_bibtex_fetch",
                        "requires_human_review": False,
                        "writes_files": True,
                        "network_required": True,
                        "message": "The selected authority exposes an official BibTeX URL; fetch it before using a manual fallback.",
                        "citation_key": citation_key,
                        "official_bibtex_url": official_bibtex_url,
                        "source_guidance": source_guidance,
                        "command": _reference_check_rerun_command(
                            lock_path=lock_path,
                            candidate_dir=candidate_dir,
                            bibtex_dir=bibtex_dir,
                            official_bibtex_dir=official_bibtex_dir,
                            fixture_html_dir=fixture_html_dir,
                            live=live,
                            sources=sources,
                            cache_root=cache_root,
                            prefer_cache=prefer_cache,
                            write_lock=write_lock,
                            fallback_reason=fallback_reason,
                            max_entries=max_entries,
                            fetch_official_bibtex=True,
                            citation_keys=citation_keys or ([citation_key] if citation_key else None),
                        ),
                    }
                )
            actions.append(
                {
                    "code": "ADD_BIBTEX_PROVENANCE",
                    "kind": "bibtex_provenance_input",
                    "requires_human_review": True,
                    "writes_files": True,
                    "network_required": False,
                    "message": "Add a reviewed official BibTeX export fixture or reviewed manual fallback file before updating the lockfile.",
                    "citation_key": citation_key,
                    "bibtex_file": str(bibtex_root / f"{citation_key}.bib") if citation_key else str(bibtex_root),
                    "official_bibtex_url": official_bibtex_url,
                    "preferred_input": "official_bibtex_export" if official_bibtex_url else "reviewed_manual_fallback_or_official_fixture",
                    "source_guidance": source_guidance,
                    "missing_inputs": ["official_bibtex_export_or_reviewed_manual_fallback"],
                    "input_options": [
                        {
                            "kind": "official_bibtex_export_fixture",
                            "directory": str(official_bibtex_root),
                            "file_examples": (
                                [
                                    str(official_bibtex_root / f"{citation_key}.SOURCE.bib"),
                                    str(official_bibtex_root / f"{citation_key}.source.bib"),
                                    str(official_bibtex_root / f"{citation_key}.bib"),
                                ]
                                if citation_key
                                else [str(official_bibtex_root)]
                            ),
                            "source_kind": "official_export",
                            "requires_authority_bibtex_url": True,
                            "validation": ["title_exact_normalized", "doi_if_available"],
                        },
                        {
                            "kind": "reviewed_manual_fallback",
                            "directory": str(bibtex_root),
                            "file_examples": [str(bibtex_root / f"{citation_key}.bib")] if citation_key else [str(bibtex_root)],
                            "source_kind": "publisher_metadata_manual_normalized",
                            "requires_fallback_reason": True,
                            "validation": ["title_exact_normalized"],
                        },
                    ],
                    "official_bibtex_file_examples": (
                        [
                            str(official_bibtex_root / f"{citation_key}.SOURCE.bib"),
                            str(official_bibtex_root / f"{citation_key}.source.bib"),
                            str(official_bibtex_root / f"{citation_key}.bib"),
                        ]
                        if citation_key
                        else [str(official_bibtex_root)]
                    ),
                    "command": _reference_check_rerun_command(
                        lock_path=lock_path,
                        candidate_dir=candidate_dir,
                        bibtex_dir=bibtex_dir or "REVIEWED_FALLBACK_BIBTEX_DIR",
                        official_bibtex_dir=official_bibtex_dir or "OFFICIAL_BIBTEX_DIR",
                        fixture_html_dir=fixture_html_dir,
                        live=live,
                        sources=sources,
                        cache_root=cache_root,
                        prefer_cache=prefer_cache,
                        write_lock=write_lock,
                        fallback_reason=fallback_reason,
                        max_entries=max_entries,
                        fetch_official_bibtex=fetch_official_bibtex,
                        citation_keys=citation_keys,
                    ),
                }
            )

    if updated_entries:
        actions.append(
            {
                "code": "AUDIT_BIB_AFTER_REFERENCE_UPDATE",
                "kind": "validation_command",
                "requires_human_review": False,
                "writes_files": False,
                "network_required": False,
                "message": "Lockfile provenance was updated; rerun the submission bibliography audit.",
                "command": _refgate_command("audit-bib", "--bib", "PAPER_BIB", "--lock", write_lock or lock_path, "--submission", "--json"),
            }
        )
        actions.append(
            {
                "code": "SYNC_BIBTEX_AFTER_REFERENCE_UPDATE",
                "kind": "bibtex_sync",
                "requires_human_review": False,
                "writes_files": False,
                "network_required": False,
                "message": "Lockfile provenance was updated; plan a canonical BibTeX synchronization for the manuscript bibliography.",
                "command": _refgate_command("sync-bibtex", "--bib", "PAPER_BIB", "--lock", write_lock or lock_path, "--json"),
                "write_command": _refgate_command(
                    "sync-bibtex",
                    "--bib",
                    "PAPER_BIB",
                    "--lock",
                    write_lock or lock_path,
                    "--output",
                    "PAPER_BIB.refgate.bib",
                    "--json",
                ),
            }
        )

    if rows and not blocking and not updated_entries and write_lock is None:
        selected = [row for row in rows if row["decision"].get("ok")]
        if selected:
            actions.append(
                {
                    "code": "WRITE_REFERENCE_LOCK",
                    "kind": "lockfile_update",
                    "requires_human_review": True,
                    "writes_files": True,
                    "network_required": False,
                    "message": "References were selected but the lockfile was not updated; rerun with --write-lock when provenance inputs are ready.",
                    "command": _reference_check_rerun_command(
                        lock_path=lock_path,
                        candidate_dir=candidate_dir,
                        bibtex_dir=bibtex_dir,
                        official_bibtex_dir=official_bibtex_dir,
                        fixture_html_dir=fixture_html_dir,
                        live=live,
                        sources=sources,
                        cache_root=cache_root,
                        prefer_cache=prefer_cache,
                        write_lock=lock_path,
                        fallback_reason=fallback_reason,
                        max_entries=max_entries,
                        fetch_official_bibtex=fetch_official_bibtex,
                        citation_keys=citation_keys,
                    ),
                }
            )

    return _dedupe_actions(actions)


def run_reference_check(
    lock_path: str | Path,
    *,
    candidate_dir: str | Path | None = None,
    bibtex_dir: str | Path | None = None,
    official_bibtex_dir: str | Path | None = None,
    fixture_html_dir: str | Path | None = None,
    live: bool = False,
    sources: list[str] | None = None,
    cache_root: str | Path = ".refgate/cache",
    prefer_cache: bool = False,
    write_lock: str | Path | None = None,
    fallback_reason: str | None = None,
    max_entries: int | None = None,
    fetch_official_bibtex: bool = False,
    citation_keys: list[str] | None = None,
) -> dict[str, Any]:
    lockfile = load_lockfile(lock_path)
    candidate_root = Path(candidate_dir) if candidate_dir else None
    bibtex_root = Path(bibtex_dir) if bibtex_dir else None
    official_bibtex_root = Path(official_bibtex_dir) if official_bibtex_dir else None
    fixture_html_root = Path(fixture_html_dir) if fixture_html_dir else None
    updated_lockfile = lockfile
    rows: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    updated_entries = 0

    wanted_keys = set(citation_keys or [])
    filtered_entries = [entry for entry in lockfile.entries if not wanted_keys or entry.citation_key in wanted_keys]
    selected_entries = filtered_entries[:max_entries] if max_entries is not None else filtered_entries
    for entry in selected_entries:
        query = query_from_lock_entry(entry)
        candidates: list[CandidateRecord] = []
        candidate_path: Path | None = None

        if candidate_root:
            candidate_path = _candidate_file(candidate_root, entry.citation_key)
            if candidate_path:
                candidates.extend(_load_candidates(candidate_path))

        live_sources = sources or recommended_sources(entry)
        live_results: list[dict[str, Any]] = []
        fixture_html_results: list[dict[str, Any]] = []
        fixture_html_path: Path | None = None
        if fixture_html_root:
            html_candidates, fixture_html_results, fixture_html_path = _candidates_from_fixture_html(
                fixture_html_dir=fixture_html_root,
                citation_key=entry.citation_key,
                query=query,
                sources=live_sources,
            )
            candidates.extend(html_candidates)
        if live:
            live_lookup_failures: list[dict[str, Any]] = []
            for source in live_sources:
                try:
                    result = run_live_smoke(
                        source,
                        query,
                        cache_root=cache_root,
                        prefer_cache=prefer_cache,
                    )
                except Exception as exc:
                    live_results.append(
                        {
                            "source": source,
                            "candidate_count": 0,
                            "cache_paths": [],
                            "ok": False,
                            "error": f"{exc.__class__.__name__}: {exc}",
                        }
                    )
                    live_lookup_failures.append(
                        {
                            "code": "REFERENCE_LIVE_LOOKUP_FAILED",
                            "message": f"{source} live lookup failed for this reference.",
                            "citation_key": entry.citation_key,
                            "evidence": [f"{exc.__class__.__name__}: {exc}"],
                        }
                    )
                    continue
                live_results.append(
                    {
                        "source": source,
                        "candidate_count": result["candidate_count"],
                        "cache_paths": result["cache_paths"],
                        "ok": result["ok"],
                    }
                )
                candidates.extend(CandidateRecord.from_dict(item) for item in result.get("candidates", []))

        decision = resolve(query, candidates)
        row: dict[str, Any] = {
            "citation_key": entry.citation_key,
            "current_status": entry.status,
            "candidate_count": len(candidates),
            "candidate_file": str(candidate_path) if candidate_path else None,
            "fixture_html_results": fixture_html_results,
            "live_results": live_results,
            "decision": decision.to_dict(),
            "lock_updated": False,
        }
        if live and decision.ok:
            row["live_lookup_warnings"] = live_lookup_failures
        elif live:
            blocking.extend(live_lookup_failures)

        if not decision.ok:
            blocking.extend(_issue_with_citation(issue, entry.citation_key) for issue in decision.blocking_issues)
            if not candidates and not live_results:
                blocking.append(
                    {
                        "code": "REFERENCE_CANDIDATES_MISSING",
                        "message": "No fixture or live candidate records were available for this reference.",
                        "citation_key": entry.citation_key,
                    }
                )
            rows.append(row)
            continue

        bibtex_record: BibtexRecord | None = None
        expected_title = decision.selected_candidate.title if decision.selected_candidate else query.title
        bibtex_path = None
        bibtex_match_method = None
        official_bibtex_path = None
        if official_bibtex_root and decision.authority and decision.authority.bibtex_url:
            official_bibtex_path = _official_bibtex_file(
                official_bibtex_root,
                entry.citation_key,
                decision.authority.source,
            )
        if official_bibtex_path:
            bibtex_record = _bibtex_from_file(official_bibtex_path, entry.citation_key, "official_export")
            row["official_bibtex_file"] = str(official_bibtex_path)
            row["bibtex_file"] = str(official_bibtex_path)
            row["bibtex_match_method"] = "official_bibtex_fixture"
            checks, check_issues = _official_bibtex_checks(
                bibtex_record=bibtex_record,
                decision=decision,
                expected_title=expected_title,
                citation_key=entry.citation_key,
            )
            row["bibtex_checks"] = checks
            if check_issues:
                blocking.extend(check_issues)
                bibtex_record = None
        elif bibtex_root:
            bibtex_path, bibtex_match_method, bibtex_lookup_issues = _bibtex_file_for_reference(
                bibtex_root,
                entry.citation_key,
                expected_title=expected_title,
            )
            blocking.extend(bibtex_lookup_issues)
        if bibtex_path:
            source_kind = (
                "official_export"
                if decision.authority and decision.authority.bibtex_url and not fallback_reason
                else "publisher_metadata_manual_normalized"
            )
            bibtex_record = _bibtex_from_file(bibtex_path, entry.citation_key, source_kind)
            row["bibtex_file"] = str(bibtex_path)
            row["bibtex_match_method"] = bibtex_match_method
            if bibtex_record.source_kind == "official_export":
                checks, check_issues = _official_bibtex_checks(
                    bibtex_record=bibtex_record,
                    decision=decision,
                    expected_title=expected_title,
                    citation_key=entry.citation_key,
                )
                row["bibtex_checks"] = checks
                if check_issues:
                    blocking.extend(check_issues)
                    bibtex_record = None
        elif bibtex_record is None and not official_bibtex_path and fetch_official_bibtex and decision.authority and decision.authority.bibtex_url:
            try:
                bibtex_record = _fetch_official_bibtex(
                    decision.authority,
                    cache_root=cache_root,
                    prefer_cache=prefer_cache,
                    fixture_html_path=fixture_html_path,
                )
            except Exception as exc:
                blocking.append(
                    {
                        "code": "OFFICIAL_BIBTEX_FETCH_FAILED",
                        "message": "Official BibTeX export could not be fetched from the selected authority URL.",
                        "citation_key": entry.citation_key,
                        "evidence": [f"{exc.__class__.__name__}: {exc}", decision.authority.bibtex_url],
                    }
                )
                bibtex_record = None
            else:
                row["bibtex_file"] = None
                row["bibtex_fetched_from"] = decision.authority.bibtex_url
                checks, check_issues = _official_bibtex_checks(
                    bibtex_record=bibtex_record,
                    decision=decision,
                    expected_title=expected_title,
                    citation_key=entry.citation_key,
                )
                row["bibtex_checks"] = checks
                if check_issues:
                    blocking.extend(check_issues)
                    bibtex_record = None
        elif decision.status == "arxiv_fallback_verified" and decision.selected_candidate is not None:
            bibtex_record = ArxivAdapter(accessed_at=decision.selected_candidate.raw.get("accessed_at")).build_manual_bibtex(
                decision.selected_candidate,
                entry.citation_key,
            )
            row["bibtex_file"] = None
            row["bibtex_source_kind"] = "arxiv_manual_normalized"

        if write_lock and bibtex_record is not None:
            lock_entry = build_lock_entry(
                decision,
                bibtex_record,
                citation_key=entry.citation_key,
                fallback_reason=fallback_reason,
            )
            updated_lockfile = merge_lock_entry(updated_lockfile, lock_entry)
            updated_entries += 1
            row["lock_updated"] = True
            row["new_status"] = lock_entry.status
        elif write_lock:
            blocking.append(
                {
                    "code": "BIBTEX_PROVENANCE_INPUT_MISSING",
                    "message": "A selected reference cannot update the lockfile without an official BibTeX file or arXiv fallback metadata.",
                    "citation_key": entry.citation_key,
                }
            )

        rows.append(row)

    if write_lock:
        write_lockfile(updated_lockfile, write_lock)

    next_actions = build_reference_check_next_actions(
        lock_path=lock_path,
        rows=rows,
        blocking=blocking,
        candidate_dir=candidate_dir,
        bibtex_dir=bibtex_dir,
        official_bibtex_dir=official_bibtex_dir,
        fixture_html_dir=fixture_html_dir,
        live=live,
        sources=sources,
        cache_root=cache_root,
        prefer_cache=prefer_cache,
        write_lock=write_lock,
        fallback_reason=fallback_reason,
        max_entries=max_entries,
        updated_entries=updated_entries,
        fetch_official_bibtex=fetch_official_bibtex,
        citation_keys=citation_keys,
    )

    return {
        "ok": not blocking,
        "lock": str(lock_path),
        "write_lock": str(write_lock) if write_lock else None,
        "entry_count": len(lockfile.entries),
        "checked": len(rows),
        "skipped_entry_count": max(0, len(lockfile.entries) - len(selected_entries)),
        "citation_keys": citation_keys or [],
        "selected": sum(1 for row in rows if row["decision"].get("ok")),
        "updated_entries": updated_entries,
        "results": rows,
        "blocking_issues": blocking,
        "next_actions": next_actions,
    }
