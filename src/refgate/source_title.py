from __future__ import annotations

import csv
import json
import re
import shlex
from pathlib import Path
from typing import Any

from .lockfile import load_lockfile
from .models import AuditIssue
from .resolver import normalize_title
from .source_text import pdf_text_extra_missing_issue, pdf_text_extraction_available, read_source_text


ACCEPTED_TITLE_REVIEW_DECISIONS = {
    "accepted_mismatch",
    "source_title_mismatch_accepted",
    "accepted_official_metadata_mismatch",
}


def _source_map_rows(path: str | Path) -> list[dict[str, str]]:
    target = Path(path)
    base_dir = target.parent
    if target.suffix.lower() == ".json":
        data = json.loads(target.read_text(encoding="utf-8"))
        rows = data.get("sources", data) if isinstance(data, dict) else data
    else:
        with target.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    resolved = []
    for row in rows:
        citation_key = str(row.get("citation_key", "")).strip()
        source_text = str(row.get("source_text", "") or row.get("path", "")).strip()
        if not citation_key or not source_text:
            continue
        source_path = Path(source_text)
        resolved.append(
            {
                "citation_key": citation_key,
                "source_text": str(source_path if source_path.is_absolute() else base_dir / source_path),
                "source_text_raw": source_text,
                "source_label": str(row.get("source_label", "") or Path(source_text).name),
                "evidence_kind": str(row.get("evidence_kind", "") or row.get("source_kind", "") or "source_text"),
            }
        )
    return resolved


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: expected object")
        rows.append(payload)
    return rows


def _review_source_text_candidates(value: str, review_path: Path) -> list[str]:
    source_path = Path(value)
    candidates = [value]
    if source_path.is_absolute():
        candidates.append(str(source_path))
    else:
        candidates.append(str(review_path.parent / source_path))
        candidates.append(str(Path.cwd() / source_path))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _load_title_reviews(path: str | Path | None) -> dict[str, list[dict[str, Any]]]:
    if not path:
        return {}
    review_path = Path(path)
    reviews: dict[str, list[dict[str, Any]]] = {}
    for row in _read_jsonl(review_path):
        citation_key = str(row.get("citation_key", "")).strip()
        if not citation_key:
            continue
        normalized = dict(row)
        if normalized.get("source_text"):
            raw_source_text = str(normalized["source_text"]).strip()
            normalized["source_text_raw"] = raw_source_text
            normalized["source_text_candidates"] = _review_source_text_candidates(raw_source_text, review_path)
        reviews.setdefault(citation_key, []).append(normalized)
    return reviews


def _first_page(text: str) -> str:
    page_match = re.search(r"(?ims)^\[page\s+1\]\s*(.*?)(?=^\[page\s+\d+\]|\Z)", text)
    if page_match:
        return page_match.group(1)
    return text[:4000]


def _looks_like_front_matter_boilerplate(line: str) -> bool:
    lowered = line.lower()
    google_permission_fragments = (
        "provided proper attribution",
        "google hereby grants permission",
        "reproduce the tables and figures",
        "solely for use in journalistic",
        "scholarly works",
    )
    if any(fragment in lowered for fragment in google_permission_fragments):
        return True
    if ("©" in line or "copyright" in lowered) and "association for computational linguistics" in lowered:
        return True
    if lowered.startswith(("published as a conference paper", "under review as a conference paper")):
        return True
    return False


def _meaningful_lines(text: str, *, limit: int = 8) -> list[str]:
    lines: list[str] = []
    for raw_line in _first_page(text).splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("[page ") or lowered.startswith("abstract"):
            continue
        if lowered.startswith(("arxiv:", "doi:", "preprint", "proceedings of")):
            continue
        if _looks_like_front_matter_boilerplate(line):
            continue
        if len(line) < 8 and not (lines and re.search(r"[A-Za-z]", line) and not re.search(r"[@\d]", line)):
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def source_title_candidates(text: str) -> list[str]:
    lines = _meaningful_lines(text)
    candidates: list[str] = []
    max_span = min(4, len(lines))
    for start in range(len(lines)):
        for span in range(1, max_span + 1):
            if start + span > len(lines):
                continue
            candidate = " ".join(lines[start : start + span]).strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _compact_title(title: str) -> str:
    text = normalize_title(title)
    text = re.sub(r"(?i)\\tau\b", "tau", text)
    text = text.replace("τ", "tau")
    text = re.sub(r"\$+", " ", text)
    return re.sub(r"[^a-z0-9]", "", text)


def _compact_title_matches(expected_compact: str, candidate_compact: str) -> bool:
    if not expected_compact or not candidate_compact:
        return False
    if expected_compact in candidate_compact:
        return True
    partial_min_len = min(32, len(expected_compact))
    return len(candidate_compact) >= partial_min_len and candidate_compact in expected_compact


def source_title_matches(expected_title: str, candidates: list[str]) -> bool:
    expected = normalize_title(expected_title)
    if not expected:
        return True
    expected_compact = _compact_title(expected_title)
    for candidate in candidates:
        candidate_normalized = normalize_title(candidate)
        if candidate_normalized == expected:
            return True
        candidate_compact = _compact_title(candidate)
        if _compact_title_matches(expected_compact, candidate_compact):
            return True
    return False


def _review_title_matches_current(review_title: str, candidates: list[str]) -> bool:
    review_normalized = normalize_title(review_title)
    if not review_normalized:
        return False
    review_compact = _compact_title(review_title)
    for candidate in candidates:
        if normalize_title(candidate) == review_normalized:
            return True
        if review_compact and review_compact == _compact_title(candidate):
            return True
    return False


def _same_source_text_path(reviewed_source: str, source_text: str) -> bool:
    if reviewed_source == source_text:
        return True
    return Path(reviewed_source).resolve(strict=False) == Path(source_text).resolve(strict=False)


def _source_text_values_for_row(row: dict[str, str]) -> list[str]:
    values = [
        row.get("source_text", ""),
        row.get("source_text_raw", ""),
        row.get("source_label", ""),
    ]
    source_text = row.get("source_text", "")
    if source_text:
        values.append(Path(source_text).name)
    return [value for value in dict.fromkeys(values) if value]


def _review_source_matches_row(review: dict[str, Any], row: dict[str, str]) -> bool:
    reviewed_candidates = [str(value) for value in review.get("source_text_candidates", []) if str(value).strip()]
    reviewed_raw = str(review.get("source_text_raw", "") or review.get("source_text", "")).strip()
    if reviewed_raw and reviewed_raw not in reviewed_candidates:
        reviewed_candidates.insert(0, reviewed_raw)
    if not reviewed_candidates:
        return True
    row_values = _source_text_values_for_row(row)
    for reviewed_source in reviewed_candidates:
        for row_value in row_values:
            if reviewed_source == row_value:
                return True
            if _same_source_text_path(reviewed_source, row_value):
                return True
    return False


def _review_title_and_decision_match(
    review: dict[str, Any],
    *,
    expected_title: str,
    candidates: list[str],
) -> bool:
    decision = str(review.get("decision", "")).strip().lower()
    if decision not in ACCEPTED_TITLE_REVIEW_DECISIONS:
        return False
    reviewed_expected = str(review.get("expected_title", "")).strip()
    if not reviewed_expected or normalize_title(reviewed_expected) != normalize_title(expected_title):
        return False
    reviewed_source_title = str(
        review.get("source_title", "") or review.get("source_candidate", "") or review.get("observed_title", "")
    ).strip()
    return bool(reviewed_source_title and _review_title_matches_current(reviewed_source_title, candidates))


def _matching_title_review(
    *,
    reviews: dict[str, list[dict[str, Any]]],
    citation_key: str,
    row: dict[str, str],
    expected_title: str,
    candidates: list[str],
) -> dict[str, Any] | None:
    for review in reviews.get(citation_key, []):
        if not _review_title_and_decision_match(review, expected_title=expected_title, candidates=candidates):
            continue
        if not _review_source_matches_row(review, row):
            continue
        return review
    return None


def _path_mismatched_title_review(
    *,
    reviews: dict[str, list[dict[str, Any]]],
    citation_key: str,
    row: dict[str, str],
    expected_title: str,
    candidates: list[str],
) -> dict[str, Any] | None:
    for review in reviews.get(citation_key, []):
        if not _review_title_and_decision_match(review, expected_title=expected_title, candidates=candidates):
            continue
        if _review_source_matches_row(review, row):
            continue
        return review
    return None


def check_source_titles(
    lock_path: str | Path,
    source_map_path: str | Path,
    *,
    title_review_path: str | Path | None = None,
) -> dict[str, Any]:
    lockfile = load_lockfile(lock_path)
    entries = lockfile.by_citation_key()
    rows = _source_map_rows(source_map_path)
    title_reviews = _load_title_reviews(title_review_path)
    results: list[dict[str, Any]] = []
    issues: list[AuditIssue] = []
    warnings: list[AuditIssue] = []
    seen: set[tuple[str, str]] = set()
    pdf_sources = [row["source_text"] for row in rows if Path(row["source_text"]).suffix.lower() == ".pdf"]
    if pdf_sources and not pdf_text_extraction_available():
        issues.append(
            AuditIssue(
                code="PDF_TEXT_EXTRA_MISSING",
                message="PDF source title extraction requires the optional pypdf dependency.",
                severity="blocking",
                evidence=pdf_text_extra_missing_issue(pdf_sources).get("evidence", []),
            )
        )
        return {
            "lock": str(lock_path),
            "source_map": str(source_map_path),
            "title_review": str(title_review_path) if title_review_path else None,
            "checked": 0,
            "ok_count": 0,
            "reviewed_mismatch_count": 0,
            "results": [],
            "blocking_issues": [issue.to_dict() for issue in issues],
            "warnings": [],
            "ok": False,
        }

    for row in rows:
        citation_key = row["citation_key"]
        source_path = row["source_text"]
        key = (citation_key, source_path)
        if key in seen:
            continue
        seen.add(key)
        entry = entries.get(citation_key)
        expected_title = str((entry.record.get("title") if entry else "") or "")
        result: dict[str, Any] = {
            "citation_key": citation_key,
            "source_text": source_path,
            "source_label": row["source_label"],
            "source_text_raw": row.get("source_text_raw", ""),
            "expected_title": expected_title,
            "ok": False,
            "title_candidates": [],
        }
        if entry is None:
            issues.append(
                AuditIssue(
                    code="SOURCE_TITLE_LOCK_ENTRY_MISSING",
                    message="Source title check could not find a matching lockfile entry.",
                    severity="blocking",
                    citation_key=citation_key,
                    evidence=[source_path],
                )
            )
            result["error"] = "lock_entry_missing"
            results.append(result)
            continue
        if not expected_title:
            issues.append(
                AuditIssue(
                    code="SOURCE_TITLE_EXPECTED_TITLE_MISSING",
                    message="Lockfile entry has no title to compare against the source file.",
                    severity="blocking",
                    citation_key=citation_key,
                    evidence=[source_path],
                )
            )
            result["error"] = "expected_title_missing"
            results.append(result)
            continue
        try:
            source_text = read_source_text(source_path)
        except Exception as exc:
            issues.append(
                AuditIssue(
                    code="SOURCE_TITLE_READ_FAILED",
                    message="Source file could not be read for title validation.",
                    severity="blocking",
                    citation_key=citation_key,
                    evidence=[source_path, f"{exc.__class__.__name__}: {exc}"],
                )
            )
            result["error"] = f"{exc.__class__.__name__}: {exc}"
            results.append(result)
            continue

        candidates = source_title_candidates(source_text)
        result["title_candidates"] = candidates[:5]
        if not candidates:
            issues.append(
                AuditIssue(
                    code="SOURCE_TITLE_CANDIDATE_MISSING",
                    message="No plausible first-page title candidate was found in the source file.",
                    severity="blocking",
                    citation_key=citation_key,
                    evidence=[source_path],
                )
            )
        elif source_title_matches(expected_title, candidates):
            result["ok"] = True
        else:
            reviewed_mismatch = _matching_title_review(
                reviews=title_reviews,
                citation_key=citation_key,
                row=row,
                expected_title=expected_title,
                candidates=candidates,
            )
            if reviewed_mismatch:
                result["ok"] = True
                result["reviewed_mismatch"] = True
                result["review"] = {
                    "decision": reviewed_mismatch.get("decision"),
                    "reviewer": reviewed_mismatch.get("reviewer"),
                    "notes": reviewed_mismatch.get("notes") or reviewed_mismatch.get("review_notes"),
                }
                warnings.append(
                    AuditIssue(
                        code="SOURCE_TITLE_MISMATCH_REVIEWED",
                        message="The source file title differs from the lockfile/BibTeX title, and the mismatch has an accepted source-title review record.",
                        severity="warning",
                        citation_key=citation_key,
                        evidence=[f"expected: {expected_title}", f"source candidate: {candidates[0]}", source_path],
                    )
                )
            else:
                path_mismatch = _path_mismatched_title_review(
                    reviews=title_reviews,
                    citation_key=citation_key,
                    row=row,
                    expected_title=expected_title,
                    candidates=candidates,
                )
                if path_mismatch:
                    result["review_path_mismatch"] = {
                        "review_source_text": path_mismatch.get("source_text_raw") or path_mismatch.get("source_text"),
                        "source_text": source_path,
                        "source_label": row.get("source_label", ""),
                    }
                    warnings.append(
                        AuditIssue(
                            code="SOURCE_TITLE_REVIEW_PATH_MISMATCH",
                            message="A matching source-title review exists, but its source_text does not match the current source-map row.",
                            severity="warning",
                            citation_key=citation_key,
                            evidence=[
                                f"review source_text: {result['review_path_mismatch']['review_source_text']}",
                                f"source map source_text: {source_path}",
                                f"source label: {row.get('source_label', '')}",
                            ],
                        )
                    )
                issues.append(
                    AuditIssue(
                        code="SOURCE_TITLE_MISMATCH",
                        message="The source file title does not match the lockfile/BibTeX title.",
                        severity="blocking",
                        citation_key=citation_key,
                        evidence=[f"expected: {expected_title}", f"source candidate: {candidates[0]}", source_path],
                    )
                )
        results.append(result)

    return {
        "lock": str(lock_path),
        "source_map": str(source_map_path),
        "title_review": str(title_review_path) if title_review_path else None,
        "checked": len(results),
        "ok_count": sum(1 for result in results if result.get("ok")),
        "reviewed_mismatch_count": sum(1 for result in results if result.get("reviewed_mismatch")),
        "results": results,
        "blocking_issues": [issue.to_dict() for issue in issues],
        "warnings": [issue.to_dict() for issue in warnings],
        "ok": not issues,
    }


def source_title_next_actions(result: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    mismatches = [
        item
        for item in result.get("results", [])
        if not item.get("ok") and item.get("citation_key")
    ]
    if mismatches:
        actions.append(
            {
                "code": "REVIEW_SOURCE_TITLE_MISMATCH",
                "kind": "source_integrity_review",
                "requires_human_review": True,
                "writes_files": False,
                "network_required": False,
                "message": "Review mapped source files whose first-page title does not match the lockfile title; replace the source file or repair the lock/BibTeX only after official provenance review.",
                "citation_key_sample": [item["citation_key"] for item in mismatches[:10]],
                "review_schema": {
                    "format": "jsonl",
                    "required_fields": ["citation_key", "decision", "expected_title", "source_title"],
                    "accepted_decisions": sorted(ACCEPTED_TITLE_REVIEW_DECISIONS),
                    "optional_fields": ["source_text", "reviewer", "notes"],
                },
                "command": (
                    "python -m refgate check-source-titles "
                    f"--lock {shlex.quote(str(result.get('lock')))} "
                    f"--source-map {shlex.quote(str(result.get('source_map')))} --json"
                ),
            }
        )
    return actions


def render_source_title_check_section(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    lines = [
        "",
        "## Source Title Check",
        "",
        f"- Source map: {result.get('source_map')}",
        f"- Checked sources: {result.get('checked', 0)}",
        f"- Passing sources: {result.get('ok_count', 0)}",
        f"- Reviewed mismatches: {result.get('reviewed_mismatch_count', 0)}",
        f"- Blocking issues: {len(result.get('blocking_issues', []))}",
        "",
    ]
    reviewed = [item for item in result.get("results", []) if item.get("reviewed_mismatch")]
    if reviewed:
        lines.extend(["### Reviewed Mismatches", ""])
        for item in reviewed:
            candidates = item.get("title_candidates") or []
            candidate = candidates[0] if candidates else "(no candidate)"
            lines.append(
                f"- `{item.get('citation_key', '')}`: expected `{item.get('expected_title', '')}`; "
                f"source candidate `{candidate}`"
            )
        lines.append("")
    failing = [item for item in result.get("results", []) if not item.get("ok")]
    if failing:
        lines.extend(["### Review Required", ""])
        for item in failing:
            candidates = item.get("title_candidates") or []
            candidate = candidates[0] if candidates else "(no candidate)"
            lines.append(
                f"- `{item.get('citation_key', '')}`: expected `{item.get('expected_title', '')}`; "
                f"source candidate `{candidate}`"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
