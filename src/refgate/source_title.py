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
from .source_text import read_source_text


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
                "source_label": str(row.get("source_label", "") or Path(source_text).name),
                "evidence_kind": str(row.get("evidence_kind", "") or row.get("source_kind", "") or "source_text"),
            }
        )
    return resolved


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
    return re.sub(r"[^a-z0-9]", "", normalize_title(title))


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
        if expected_compact and expected_compact in candidate_compact:
            return True
    return False


def check_source_titles(lock_path: str | Path, source_map_path: str | Path) -> dict[str, Any]:
    lockfile = load_lockfile(lock_path)
    entries = lockfile.by_citation_key()
    rows = _source_map_rows(source_map_path)
    results: list[dict[str, Any]] = []
    issues: list[AuditIssue] = []
    seen: set[tuple[str, str]] = set()

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
        "checked": len(results),
        "ok_count": sum(1 for result in results if result.get("ok")),
        "results": results,
        "blocking_issues": [issue.to_dict() for issue in issues],
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
        f"- Blocking issues: {len(result.get('blocking_issues', []))}",
        "",
    ]
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
