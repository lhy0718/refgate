from __future__ import annotations

import csv
import os
import re
import shlex
from pathlib import Path
from typing import Any, Literal

from .assist import build_resolver_assist
from .audit import audit_bibliography
from .bootstrap import bootstrap_paper
from .claim_audit import (
    _row_citation_keys,
    audit_claims_table,
    audit_tex_bib_consistency,
    read_claim_rows,
    render_claim_review_report,
    update_claim_stub_file_from_sources,
)
from .claim_source_check import run_claim_source_check
from .handoff import write_handoff
from .lockfile import load_lockfile
from .models import AuditIssue
from .reports import render_markdown_report
from .source_title import check_source_titles, render_source_title_check_section, source_title_next_actions
from .tex import load_tex_document


SUMMARY_KEY_LIMIT = 10
SOURCE_MAP_COLUMNS = ["citation_key", "source_text", "source_label", "evidence_kind"]
SOURCE_FILE_SUFFIXES = {".pdf", ".txt"}
REFGATE_COMMAND = "python -m refgate"
CLAIM_REPRESENTATIVE_CODES = {
    "CLAIM_STATUS_NOT_FINAL",
    "CLAIM_EVIDENCE_LOW_OVERLAP",
    "CLAIM_EVIDENCE_MISSING",
    "CLAIM_SOURCE_LOCATION_MISSING",
    "CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE",
    "CLAIM_MAY_BE_TOO_STRONG",
    "CLAIM_EVIDENCE_NOT_FOUND_IN_SOURCE",
}


def summarize_citation_keys(citation_keys: list[str]) -> dict[str, Any]:
    unique_keys = list(dict.fromkeys(key for key in citation_keys if key))
    return {
        "citation_key_sample": unique_keys[:SUMMARY_KEY_LIMIT],
        "omitted_citation_key_count": max(0, len(unique_keys) - SUMMARY_KEY_LIMIT),
    }


def summarize_issues(issues: list[Any]) -> list[dict[str, Any]]:
    summaries: dict[tuple[str, str], dict[str, Any]] = {}
    for issue in issues:
        key = (issue.code, issue.severity)
        summary = summaries.setdefault(
            key,
            {
                "code": issue.code,
                "severity": issue.severity,
                "message": issue.message,
                "count": 0,
                "citation_keys": [],
            },
        )
        summary["count"] += 1
        if issue.citation_key and issue.citation_key not in summary["citation_keys"]:
            summary["citation_keys"].append(issue.citation_key)
    for summary in summaries.values():
        key_summary = summarize_citation_keys(summary.pop("citation_keys"))
        summary.update(key_summary)
    return list(summaries.values())


def _claim_id_from_issue(issue: AuditIssue) -> str | None:
    match = re.search(r"\bclaim[-_]\d+\b", issue.message)
    return match.group(0) if match else None


def _dedupe_issues(issues: list[AuditIssue]) -> list[AuditIssue]:
    deduped: list[AuditIssue] = []
    seen: set[tuple[str, str, str | None, tuple[str, ...]]] = set()
    for issue in issues:
        key = (issue.code, issue.severity, issue.citation_key, tuple(issue.evidence))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _collapse_redundant_claim_blockers(issues: list[AuditIssue]) -> list[AuditIssue]:
    representative_claim_ids = {
        claim_id
        for issue in issues
        if issue.code in CLAIM_REPRESENTATIVE_CODES
        for claim_id in [_claim_id_from_issue(issue)]
        if claim_id
    }
    if not representative_claim_ids:
        return issues
    collapsed: list[AuditIssue] = []
    for issue in issues:
        claim_id = _claim_id_from_issue(issue)
        if issue.code == "CLAIM_NOT_CHECKED" and claim_id in representative_claim_ids:
            continue
        collapsed.append(issue)
    return collapsed


def _issue_phase(code: str) -> str:
    if code.startswith("SOURCE_TITLE"):
        return "source_title"
    if code.startswith("CLAIM") or code.startswith("SOURCE_TEXT") or code == "PDF_TEXT_EXTRA_MISSING":
        return "claim_review"
    if code.startswith("CITATION") or code.startswith("BIB_ENTRY") or code.startswith("TEX"):
        return "manuscript"
    return "bibliography"


def phase_summary_for_issues(issues: list[AuditIssue]) -> list[dict[str, Any]]:
    phase_labels = {
        "bibliography": "bibliography",
        "manuscript": "manuscript",
        "source_title": "source-title",
        "claim_review": "claim review",
    }
    phases: dict[str, dict[str, Any]] = {
        key: {"phase": label, "blocking_count": 0, "warning_count": 0, "blocking_codes": [], "warning_codes": []}
        for key, label in phase_labels.items()
    }
    for issue in issues:
        phase = phases[_issue_phase(issue.code)]
        if issue.severity == "blocking":
            phase["blocking_count"] += 1
            if issue.code not in phase["blocking_codes"]:
                phase["blocking_codes"].append(issue.code)
        else:
            phase["warning_count"] += 1
            if issue.code not in phase["warning_codes"]:
                phase["warning_codes"].append(issue.code)
    for phase in phases.values():
        phase["status"] = "blocked" if phase["blocking_count"] else "passed"
    return list(phases.values())


def _issue_from_payload(payload: dict[str, Any], *, severity: Literal["blocking", "warning"]) -> AuditIssue:
    return AuditIssue(
        code=str(payload.get("code", "")),
        message=str(payload.get("message", "")),
        severity=severity,
        citation_key=payload.get("citation_key"),
        evidence=[str(item) for item in payload.get("evidence", [])],
    )


def _claim_citation_keys(claims_path: Path) -> list[str]:
    keys: list[str] = []
    for row in read_claim_rows(claims_path):
        for key in _row_citation_keys(row.get("citation_key", "")):
            if key not in keys:
                keys.append(key)
    return keys


def _default_source_map_output(claims_path: Path) -> Path:
    if claims_path.name == "refgate_claims.tsv":
        return claims_path.with_name("refgate_source_map.tsv")
    return claims_path.with_name(f"{claims_path.stem}_source_map.tsv")


def build_source_map_from_dir(
    *,
    source_dir: str | Path,
    claims_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    source_root = Path(source_dir)
    claims_target = Path(claims_path)
    output_target = Path(output_path) if output_path else _default_source_map_output(claims_target)
    citation_keys = _claim_citation_keys(claims_target)
    citation_key_set = set(citation_keys)
    rows: list[dict[str, str]] = []

    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_FILE_SUFFIXES:
            continue
        if path.stem not in citation_key_set:
            continue
        relative_source = os.path.relpath(path, output_target.parent)
        rows.append(
            {
                "citation_key": path.stem,
                "source_text": relative_source,
                "source_label": relative_source,
                "evidence_kind": "source_text",
            }
        )

    output_target.parent.mkdir(parents=True, exist_ok=True)
    with output_target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=SOURCE_MAP_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    matched_keys = sorted({row["citation_key"] for row in rows})
    return {
        "output": str(output_target),
        "source_dir": str(source_root),
        "source_count": len(rows),
        "citation_key_count": len(citation_keys),
        "matched_citation_key_count": len(matched_keys),
        "matched_citation_key_sample": matched_keys[:SUMMARY_KEY_LIMIT],
        "omitted_matched_citation_key_count": max(0, len(matched_keys) - SUMMARY_KEY_LIMIT),
    }


def _default_claim_review_output(claims_path: Path) -> Path:
    if claims_path.name == "refgate_claims.tsv":
        return claims_path.with_name("refgate_claim_review.md")
    return claims_path.with_name(f"{claims_path.stem}_review.md")


def render_paper_claim_review_report(
    claims_path: str | Path,
    *,
    claim_source_check: dict[str, Any] | None = None,
) -> str:
    base_report = render_claim_review_report(claims_path).rstrip()
    if not claim_source_check:
        return base_report + "\n"

    blocking_issues = claim_source_check.get("blocking_issues", [])
    warnings = claim_source_check.get("warnings", [])
    suggestions = claim_source_check.get("suggestions", [])
    missing_source_keys = claim_source_check.get("missing_source_keys", [])
    no_match_claims = claim_source_check.get("no_match_claims", [])
    blocking_groups = _issue_payload_groups(blocking_issues)

    lines = [
        base_report,
        "",
        "## Source-Check Summary",
        "",
        f"- Source map: {claim_source_check.get('source_map') or '(none)'}",
        f"- Sources: {claim_source_check.get('source_count', 0)}",
        f"- Evidence suggestions: {claim_source_check.get('updated', 0)}",
        f"- Blocking source-check groups: {len(blocking_groups)}",
        f"- Blocking source-check rows: {len(blocking_issues)}",
        f"- Warnings: {len(warnings)}",
        "",
        "## Source-Check Review Queues",
        "",
    ]
    if suggestions:
        lines.extend(["### Evidence Suggestions", ""])
        for item in suggestions:
            lines.append(
                f"- `{item.get('claim_id', '')}` / `{item.get('citation_key', '')}`: "
                f"{item.get('source_location', '')} (overlap {item.get('overlap_score', 0)})"
            )
        lines.append("")
    if missing_source_keys:
        lines.extend(["### Missing Source Files", ""])
        for key in missing_source_keys:
            lines.append(f"- `{key}`")
        lines.append("")
    if no_match_claims:
        lines.extend(["### No Evidence Match In Mapped Source", ""])
        for item in no_match_claims:
            lines.append(f"- `{item.get('claim_id', '')}` / `{item.get('citation_key', '')}`")
        lines.append("")
    if blocking_issues:
        lines.extend(["### Blocking Issue Groups", ""])
        lines.extend(_issue_payload_group_lines(blocking_groups))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _generic_issue_payload_message(code: str, message: str) -> str:
    if code == "CLAIM_NOT_CHECKED":
        return "Claims are not marked checked."
    if code == "CLAIM_STATUS_NOT_FINAL":
        return "Claims have evidence but are not marked checked."
    if code == "CLAIM_EVIDENCE_LOW_OVERLAP":
        return "Claims have low lexical overlap with their evidence."
    if code == "CLAIM_EVIDENCE_MISSING":
        return "Claims have no evidence text."
    if code == "CLAIM_SOURCE_LOCATION_MISSING":
        return "Claims are checked but have no source location."
    if code == "CLAIM_MAY_BE_TOO_STRONG":
        return "Claims use strong wording that needs careful source support."
    if code == "CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE":
        return "Claims use weak evidence that cannot be marked checked."
    return message


def _issue_payload_groups(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for issue in issues:
        code = str(issue.get("code", ""))
        message = _generic_issue_payload_message(code, str(issue.get("message", "")))
        key = (code, message)
        group = groups.setdefault(
            key,
            {
                "code": key[0],
                "message": key[1],
                "count": 0,
                "citation_keys": [],
            },
        )
        group["count"] += 1
        citation_key = issue.get("citation_key")
        if citation_key and citation_key not in group["citation_keys"]:
            group["citation_keys"].append(citation_key)
    return list(groups.values())


def _issue_payload_group_lines(groups: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for group in groups:
        keys = [str(key) for key in group.get("citation_keys", [])]
        key_text = ", ".join(f"`{key}`" for key in keys[:5])
        more = f", ... {len(keys) - 5} more" if len(keys) > 5 else ""
        suffix = f" ({key_text}{more})" if key_text else ""
        lines.append(f"- `{group.get('code', '')}` x{group.get('count', 0)}: {group.get('message', '')}{suffix}")
    return lines


def render_claim_source_check_section(claim_source_check: dict[str, Any] | None) -> str:
    if not claim_source_check:
        return ""

    blocking_issues = claim_source_check.get("blocking_issues", [])
    blocking_groups = _issue_payload_groups(blocking_issues)

    lines = [
        "",
        "## Claim Source Check",
        "",
        f"- Source map: {claim_source_check.get('source_map') or '(none)'}",
        f"- Sources: {claim_source_check.get('source_count', 0)}",
        f"- Claims: {claim_source_check.get('claim_count', 0)}",
        f"- Evidence suggestions: {claim_source_check.get('updated', 0)}",
        f"- Blocking groups: {len(blocking_groups)}",
        f"- Blocking rows needing review: {len(blocking_issues)}",
        f"- Warnings: {len(claim_source_check.get('warnings', []))}",
        "",
    ]

    missing_source_keys = claim_source_check.get("missing_source_keys", [])
    if missing_source_keys:
        lines.extend(["### Missing Source Files", ""])
        for key in missing_source_keys[:SUMMARY_KEY_LIMIT]:
            lines.append(f"- `{key}`")
        if len(missing_source_keys) > SUMMARY_KEY_LIMIT:
            lines.append(f"- ... {len(missing_source_keys) - SUMMARY_KEY_LIMIT} more")
        lines.append("")

    no_match_claims = claim_source_check.get("no_match_claims", [])
    if no_match_claims:
        lines.extend(["### No Evidence Match In Mapped Source", ""])
        for item in no_match_claims[:SUMMARY_KEY_LIMIT]:
            lines.append(f"- `{item.get('claim_id', '')}` / `{item.get('citation_key', '')}`")
        if len(no_match_claims) > SUMMARY_KEY_LIMIT:
            lines.append(f"- ... {len(no_match_claims) - SUMMARY_KEY_LIMIT} more")
        lines.append("")

    suggestions = claim_source_check.get("suggestions", [])
    if suggestions:
        lines.extend(["### Evidence Suggestions Awaiting Review", ""])
        for item in suggestions[:SUMMARY_KEY_LIMIT]:
            location = item.get("source_location", "")
            score = item.get("overlap_score", 0)
            coverage = item.get("coverage", 0)
            lines.append(
                f"- `{item.get('claim_id', '')}` / `{item.get('citation_key', '')}`: "
                f"{location} (overlap {score}, coverage {coverage})"
            )
        if len(suggestions) > SUMMARY_KEY_LIMIT:
            lines.append(f"- ... {len(suggestions) - SUMMARY_KEY_LIMIT} more")
        lines.append("")

    if blocking_issues:
        lines.extend(["### Blocking Issue Groups", ""])
        lines.extend(_issue_payload_group_lines(blocking_groups[:SUMMARY_KEY_LIMIT]))
        if len(blocking_groups) > SUMMARY_KEY_LIMIT:
            lines.append(f"- ... {len(blocking_groups) - SUMMARY_KEY_LIMIT} more groups")
        lines.append("")

    warnings = claim_source_check.get("warnings", [])
    if warnings:
        lines.extend(["### Warnings", ""])
        for issue in warnings[:SUMMARY_KEY_LIMIT]:
            citation_key = issue.get("citation_key") or ""
            key_text = f" `{citation_key}`" if citation_key else ""
            lines.append(f"- `{issue.get('code', '')}`{key_text}: {issue.get('message', '')}")
        if len(warnings) > SUMMARY_KEY_LIMIT:
            lines.append(f"- ... {len(warnings) - SUMMARY_KEY_LIMIT} more")
        lines.append("")

    lines.extend(
        [
            "### Next Action",
            "",
            "- Keep mapped claims blocked until source evidence is reviewed and imported with `import-review`.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _refgate_command(*parts: str | Path) -> str:
    return " ".join([REFGATE_COMMAND, *(shlex.quote(str(part)) for part in parts)])


def _paper_audit_rerun_command(
    *,
    tex_path: Path,
    bib_path: Path,
    lock_path: Path,
    claims_path: Path,
    report: str | Path | None,
    resolver_output: str | Path | None,
    source_map: str | Path | None,
    source_dir: str | Path | None,
    source_map_output: str | Path | None,
    claim_review_output: str | Path | None,
    submission: bool,
) -> str:
    parts: list[str | Path] = [
        "paper-audit",
        "--tex",
        tex_path,
        "--bib",
        bib_path,
        "--lock",
        lock_path,
        "--claims",
        claims_path,
    ]
    if report:
        parts.extend(["--report", report])
    if resolver_output:
        parts.extend(["--resolver-output", resolver_output])
    if source_map:
        parts.extend(["--source-map", source_map])
    if source_dir:
        parts.extend(["--source-dir", source_dir])
    if source_map_output:
        parts.extend(["--source-map-output", source_map_output])
    if claim_review_output:
        parts.extend(["--claim-review-output", claim_review_output])
    if submission:
        parts.append("--submission")
    parts.append("--json")
    return _refgate_command(*parts)


def _codex_review_bundle_command(
    *,
    tex_path: Path,
    bib_path: Path,
    lock_path: Path,
    claims_path: Path,
    source_map: str | Path | None,
    source_dir: str | Path | None,
    source_map_output: str | Path | None,
) -> str:
    bundle_dir = claims_path.parent / ".refgate"
    bundle_output = bundle_dir / "codex_review_bundle.json"
    markdown_output = bundle_dir / "codex_review_bundle.md"
    parts: list[str | Path] = [
        "export-review-bundle",
        "--tex",
        tex_path,
        "--bib",
        bib_path,
        "--lock",
        lock_path,
        "--claims",
        claims_path,
    ]
    if source_map:
        parts.extend(["--source-map", source_map])
    elif source_dir:
        parts.extend(["--source-dir", source_dir])
        if source_map_output:
            parts.extend(["--source-map-output", source_map_output])
    parts.extend(["--output", bundle_output, "--markdown", markdown_output, "--json"])
    return _refgate_command(*parts)


def _sync_bibtex_action(*, bib_path: Path, lock_path: Path) -> dict[str, Any]:
    output_path = bib_path.with_name(f"{bib_path.stem}.refgate{bib_path.suffix}")
    return {
        "code": "SYNC_BIBTEX",
        "kind": "bibtex_sync",
        "requires_human_review": False,
        "writes_files": False,
        "network_required": False,
        "message": "Plan a lockfile-backed BibTeX synchronization for entries that differ from canonical provenance.",
        "command": _refgate_command("sync-bibtex", "--bib", bib_path, "--lock", lock_path, "--json"),
        "write_command": _refgate_command(
            "sync-bibtex",
            "--bib",
            bib_path,
            "--lock",
            lock_path,
            "--output",
            output_path,
            "--json",
        ),
    }


def _reference_check_command(
    *,
    lock_path: Path,
    fixture_html_dir: str | Path | None = None,
    bibtex_dir: str | Path | None = None,
    official_bibtex_dir: str | Path | None = None,
    live: bool = False,
    fetch_official_bibtex: bool = False,
    write_lock: str | Path | None = None,
    fallback_reason: str | None = None,
) -> str:
    parts: list[str | Path] = ["reference-check", "--lock", lock_path]
    if fixture_html_dir:
        parts.extend(["--fixture-html-dir", fixture_html_dir])
    if bibtex_dir:
        parts.extend(["--bibtex-dir", bibtex_dir])
    if official_bibtex_dir:
        parts.extend(["--official-bibtex-dir", official_bibtex_dir])
    if write_lock:
        parts.extend(["--write-lock", write_lock])
    if fallback_reason:
        parts.extend(["--fallback-reason", fallback_reason])
    if fetch_official_bibtex:
        parts.append("--fetch-official-bibtex")
    if live:
        parts.append("--live")
    parts.append("--json")
    return _refgate_command(*parts)


def build_paper_audit_next_actions(
    *,
    tex_path: Path,
    bib_path: Path,
    lock_path: Path,
    claims_path: Path,
    report: str | Path | None,
    resolver_output: str | Path | None,
    source_map: str | Path | None,
    source_dir: str | Path | None,
    source_map_output: str | Path | None,
    claim_review_output: str | Path | None,
    review_target: Path | None,
    submission: bool,
    resolver_summary: dict[str, Any],
    blocking: list[Any],
    claim_source_check: dict[str, Any] | None,
    handoff_output: str | Path | None,
    csl_output: str | Path | None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    work_item_count = int(resolver_summary.get("work_item_count", 0) or 0)
    blocking_codes = {issue.code for issue in blocking}
    if "OFFICIAL_EXPORT_CONTENT_CHANGED" in blocking_codes:
        actions.append(_sync_bibtex_action(bib_path=bib_path, lock_path=lock_path))

    if work_item_count:
        output_path = resolver_output or resolver_summary.get("output") or "refgate_queries.json"
        fixture_html_dir = claims_path.parent / ".refgate" / "official-html"
        reviewed_bibtex_dir = claims_path.parent / ".refgate" / "reviewed-bibtex"
        official_bibtex_dir = claims_path.parent / ".refgate" / "official-bibtex"
        actions.append(
            {
                "code": "RESOLVE_REFERENCE_PROVENANCE",
                "kind": "reference_provenance",
                "requires_human_review": True,
                "writes_files": True,
                "network_required": False,
                "message": "Resolve unresolved bibliography entries, then run discovery/reference-check with reviewed candidates.",
                "command": _refgate_command("resolver-assist", "--lock", lock_path, "--output", output_path, "--json"),
                "reference_check_command": _reference_check_command(
                    lock_path=lock_path,
                    fixture_html_dir=fixture_html_dir,
                    bibtex_dir=reviewed_bibtex_dir,
                    official_bibtex_dir=official_bibtex_dir,
                    write_lock=lock_path,
                    fallback_reason="Reviewed saved official HTML; manual BibTeX fallback retained because no official BibTeX endpoint was verified.",
                    fetch_official_bibtex=True,
                ),
                "live_reference_check_command": _reference_check_command(
                    lock_path=lock_path,
                    live=True,
                    fetch_official_bibtex=True,
                    write_lock=lock_path,
                ),
                "fixture_html_dir": str(fixture_html_dir),
                "fixture_html_naming": ["citationkey.source.html", "citationkey.html"],
                "fixture_html_file_examples": [f"{key}.html" for key in resolver_summary.get("citation_key_sample", [])[:3]],
                "reviewed_bibtex_dir": str(reviewed_bibtex_dir),
                "official_bibtex_dir": str(official_bibtex_dir),
                "official_bibtex_file_examples": [f"{key}.SOURCE.bib" for key in resolver_summary.get("citation_key_sample", [])[:3]],
                "missing_inputs": ["official_html_or_live_lookup", "official_bibtex_export_or_reviewed_manual_fallback"],
                "input_options": [
                    {
                        "kind": "official_html_fixture",
                        "directory": str(fixture_html_dir),
                        "file_examples": [f"{key}.source.html" for key in resolver_summary.get("citation_key_sample", [])[:3]],
                    },
                    {
                        "kind": "official_bibtex_export_fixture",
                        "directory": str(official_bibtex_dir),
                        "file_examples": [f"{key}.SOURCE.bib" for key in resolver_summary.get("citation_key_sample", [])[:3]],
                    },
                    {
                        "kind": "reviewed_manual_fallback",
                        "directory": str(reviewed_bibtex_dir),
                        "file_examples": [f"{key}.bib" for key in resolver_summary.get("citation_key_sample", [])[:3]],
                        "requires_fallback_reason": True,
                    },
                ],
                "work_item_count": work_item_count,
                "citation_key_sample": resolver_summary.get("citation_key_sample", []),
            }
        )

    claim_blocking_codes = {
        "CLAIM_NOT_CHECKED",
        "CLAIM_STATUS_NOT_FINAL",
        "CLAIM_EVIDENCE_MISSING",
        "CLAIM_SOURCE_LOCATION_MISSING",
        "CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE",
    }
    if not claim_source_check and blocking_codes & claim_blocking_codes:
        suggested_source_map = source_map_output or _default_source_map_output(claims_path)
        suggested_review = claim_review_output or _default_claim_review_output(claims_path)
        actions.append(
            {
                "code": "MAP_CLAIM_SOURCES",
                "kind": "claim_source_mapping",
                "requires_human_review": True,
                "writes_files": True,
                "network_required": False,
                "message": "Add full source text/PDF files named by citation key, then rerun paper-audit with source mapping.",
                "command": _paper_audit_rerun_command(
                    tex_path=tex_path,
                    bib_path=bib_path,
                    lock_path=lock_path,
                    claims_path=claims_path,
                    report=report,
                    resolver_output=resolver_output,
                    source_map=None,
                    source_dir="SOURCES_DIR",
                    source_map_output=suggested_source_map,
                    claim_review_output=suggested_review,
                    submission=submission,
                ),
                "file_name_examples": ["citation_key.txt", "citation_key.pdf"],
                "source_download_plan_command": _refgate_command(
                    "download-sources",
                    "--lock",
                    lock_path,
                    "--source-dir",
                    "SOURCES_DIR",
                    "--json",
                ),
            }
        )

    if claim_source_check:
        missing_keys = claim_source_check.get("missing_source_keys", [])
        if missing_keys:
            actions.append(
                {
                    "code": "ADD_MISSING_SOURCE_FILES",
                    "kind": "claim_source_mapping",
                    "requires_human_review": True,
                    "writes_files": True,
                    "network_required": False,
                    "message": "Add source text/PDF files for citation keys that have claims but no mapped source.",
                    "citation_key_sample": missing_keys[:SUMMARY_KEY_LIMIT],
                    "file_name_examples": [f"{key}.txt" for key in missing_keys[:3]],
                    "source_download_plan_command": _refgate_command(
                        "download-sources",
                        "--lock",
                        lock_path,
                        "--source-dir",
                        Path(source_dir) if source_dir else "SOURCES_DIR",
                        "--json",
                    ),
                    "command": _paper_audit_rerun_command(
                        tex_path=tex_path,
                        bib_path=bib_path,
                        lock_path=lock_path,
                        claims_path=claims_path,
                        report=report,
                        resolver_output=resolver_output,
                        source_map=source_map,
                        source_dir=source_dir,
                        source_map_output=source_map_output,
                        claim_review_output=claim_review_output,
                        submission=submission,
                    ),
                }
            )
        no_match_claims = claim_source_check.get("no_match_claims", [])
        if no_match_claims:
            actions.append(
                {
                    "code": "REVIEW_NO_MATCH_CLAIMS",
                    "kind": "claim_evidence_review",
                    "requires_human_review": True,
                    "writes_files": False,
                    "network_required": False,
                    "message": "Open the claim review report and inspect mapped sources that did not contain a matching evidence block.",
                    "claim_review": str(review_target) if review_target else None,
                    "claim_id_sample": [item.get("claim_id", "") for item in no_match_claims[:SUMMARY_KEY_LIMIT]],
                }
            )
        if claim_source_check.get("updated", 0) or blocking_codes & claim_blocking_codes:
            actions.append(
                {
                    "code": "EXPORT_CODEX_REVIEW_BUNDLE",
                    "kind": "codex_claim_review_bundle",
                    "requires_human_review": False,
                    "writes_files": True,
                    "network_required": False,
                    "message": "Export a Codex-readable claim review bundle with source candidates; Codex can review it and produce JSONL for import-review.",
                    "command": _codex_review_bundle_command(
                        tex_path=tex_path,
                        bib_path=bib_path,
                        lock_path=lock_path,
                        claims_path=claims_path,
                        source_map=source_map,
                        source_dir=source_dir,
                        source_map_output=source_map_output,
                    ),
                    "review_result": str(claims_path.parent / ".refgate" / "codex_review_result.jsonl"),
                    "import_command": _refgate_command(
                        "import-review",
                        "--claims",
                        claims_path,
                        "--review",
                        claims_path.parent / ".refgate" / "codex_review_result.jsonl",
                        "--output",
                        claims_path.with_name(f"{claims_path.stem}.reviewed{claims_path.suffix}"),
                        "--json",
                    ),
                }
            )
            actions.append(
                {
                    "code": "REVIEW_CLAIM_EVIDENCE",
                    "kind": "claim_evidence_review",
                    "requires_human_review": True,
                    "writes_files": False,
                    "network_required": False,
                    "message": "Review suggested evidence spans, then mark supported claims checked or rewrite/delete unsupported claims.",
                    "claim_review": str(review_target) if review_target else None,
                    "command": _refgate_command("claim-consistency", "--claims", claims_path, "--submission", "--json"),
                }
            )

    if not blocking and not handoff_output and not csl_output:
        actions.append(
            {
                "code": "EXPORT_HANDOFF",
                "kind": "handoff_export",
                "requires_human_review": False,
                "writes_files": True,
                "network_required": False,
                "message": "Audit passed; export a standalone handoff artifact if this manuscript is ready to share.",
                "command": _refgate_command(
                    "export-handoff",
                    "--bib",
                    bib_path,
                    "--lock",
                    lock_path,
                    "--output",
                    "refgate_handoff.json",
                    "--submission",
                    "--json",
                ),
            }
        )
    return actions


def run_paper_audit(
    *,
    tex: str | Path,
    bib: str | Path,
    lock: str | Path,
    claims: str | Path,
    report: str | Path | None = None,
    resolver_output: str | Path | None = None,
    handoff_output: str | Path | None = None,
    csl_output: str | Path | None = None,
    source_map: str | Path | None = None,
    source_dir: str | Path | None = None,
    source_map_output: str | Path | None = None,
    claim_review_output: str | Path | None = None,
    source_title_review: str | Path | None = None,
    project: str | None = None,
    submission: bool = False,
    allow_blocking_handoff: bool = False,
    update_claims: bool = False,
    include_work_items: bool = False,
) -> dict[str, Any]:
    tex_path = Path(tex)
    bib_path = Path(bib)
    lock_path = Path(lock)
    claims_path = Path(claims)

    tex_document = load_tex_document(tex_path, submission=submission)

    created: dict[str, Any] = {}
    if not lock_path.exists() or not claims_path.exists():
        created["bootstrap"] = bootstrap_paper(tex_path, bib_path, lock_path, claims_path, project=project)
    elif update_claims:
        stubs = update_claim_stub_file_from_sources(
            [{"source_file": source.display_path, "text": source.text} for source in tex_document.sources],
            claims_path,
        )
        created["claim_stubs_created"] = len(stubs)
    else:
        created["claim_stubs_created"] = 0
        created["claim_stubs_mode"] = "skipped_existing_claims"

    claim_source_check: dict[str, Any] | None = None
    source_title_check: dict[str, Any] | None = None
    source_map_build: dict[str, Any] | None = None
    active_source_map = Path(source_map) if source_map else None
    if source_dir:
        source_map_build = build_source_map_from_dir(
            source_dir=source_dir,
            claims_path=claims_path,
            output_path=source_map_output,
        )
        active_source_map = Path(source_map_build["output"])
    if active_source_map:
        claim_source_check = run_claim_source_check(
            claims_path,
            active_source_map,
            output_path=claims_path,
            require_passing_status=submission,
        )
        review_target = Path(claim_review_output) if claim_review_output else _default_claim_review_output(claims_path)
        review_target.parent.mkdir(parents=True, exist_ok=True)
        review_target.write_text(
            render_paper_claim_review_report(claims_path, claim_source_check=claim_source_check),
            encoding="utf-8",
        )
        source_title_check = check_source_titles(lock_path, active_source_map, title_review_path=source_title_review)
    else:
        review_target = Path(claim_review_output) if claim_review_output else None
        if review_target:
            review_target.parent.mkdir(parents=True, exist_ok=True)
            review_target.write_text(render_paper_claim_review_report(claims_path), encoding="utf-8")

    resolver_data = build_resolver_assist(lock_path, resolver_output)
    resolver_keys = [item.get("citation_key", "") for item in resolver_data.get("work_items", [])]
    resolver_summary = {
        "lock": resolver_data.get("lock"),
        "schema_version": resolver_data.get("schema_version"),
        "output": str(resolver_output) if resolver_output else None,
        "work_item_count": resolver_data.get("work_item_count", 0),
        "skipped_verified_count": resolver_data.get("skipped_verified_count", 0),
        **summarize_citation_keys(resolver_keys),
    }

    bib_text = bib_path.read_text(encoding="utf-8")
    tex_text = tex_document.combined_text
    lockfile = load_lockfile(lock_path)
    issues = audit_bibliography(bib_text, lockfile, submission=submission)
    issues.extend(tex_document.issues)
    issues.extend(audit_tex_bib_consistency(tex_text, bib_text, submission=submission))
    issues.extend(audit_claims_table(claims_path, submission=submission))
    if claim_source_check:
        issues.extend(
            _issue_from_payload(issue, severity="blocking")
            for issue in claim_source_check.get("blocking_issues", [])
        )
        issues.extend(
            _issue_from_payload(issue, severity="warning")
            for issue in claim_source_check.get("warnings", [])
        )
    if source_title_check:
        issues.extend(
            _issue_from_payload(issue, severity="blocking")
            for issue in source_title_check.get("blocking_issues", [])
        )
        issues.extend(
            _issue_from_payload(issue, severity="warning")
            for issue in source_title_check.get("warnings", [])
        )
    issues = _dedupe_issues(_collapse_redundant_claim_blockers(issues))
    blocking = [issue for issue in issues if issue.severity == "blocking"]
    warnings = [issue for issue in issues if issue.severity == "warning"]

    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        report_text = render_markdown_report(lockfile, issues)
        report_text += render_claim_source_check_section(claim_source_check)
        report_text += render_source_title_check_section(source_title_check)
        Path(report).write_text(report_text, encoding="utf-8")

    handoff: dict[str, Any] = {}
    if handoff_output and (allow_blocking_handoff or not blocking):
        handoff["refgate_json"] = write_handoff(lockfile, bib_text, handoff_output, export_format="refgate-json")
    if csl_output and (allow_blocking_handoff or not blocking):
        handoff["csl_json"] = write_handoff(lockfile, bib_text, csl_output, export_format="csl-json")

    next_actions = build_paper_audit_next_actions(
        tex_path=tex_path,
        bib_path=bib_path,
        lock_path=lock_path,
        claims_path=claims_path,
        report=report,
        resolver_output=resolver_output,
        source_map=source_map,
        source_dir=source_dir,
        source_map_output=source_map_output,
        claim_review_output=claim_review_output,
        review_target=review_target,
        submission=submission,
        resolver_summary=resolver_summary,
        blocking=blocking,
        claim_source_check=claim_source_check,
        handoff_output=handoff_output,
        csl_output=csl_output,
    )
    if source_title_check:
        next_actions.extend(source_title_next_actions(source_title_check))

    return {
        "ok": not blocking,
        "tex": str(tex_path),
        "bib": str(bib_path),
        "tex_sources": [source.display_path for source in tex_document.sources],
        "lock": str(lock_path),
        "claims": str(claims_path),
        "report": str(report) if report else None,
        "claim_review": str(review_target) if review_target else None,
        "resolver_assist": resolver_data if include_work_items else resolver_summary,
        "created": created,
        "source_map": source_map_build or ({"input": str(active_source_map)} if active_source_map else None),
        "claim_source_check": {
            key: value
            for key, value in (claim_source_check or {}).items()
            if key not in {"consistency", "blocking_issues", "warnings"}
        }
        if claim_source_check
        else None,
        "source_title_check": source_title_check,
        "handoff": handoff,
        "blocking_issues": [issue.to_dict() for issue in blocking],
        "warnings": [issue.to_dict() for issue in warnings],
        "next_actions": next_actions,
        "phase_summary": phase_summary_for_issues(issues),
        "issue_summary": {
            "blocking": summarize_issues(blocking),
            "warnings": summarize_issues(warnings),
        },
    }
