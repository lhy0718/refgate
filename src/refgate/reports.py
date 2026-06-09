from __future__ import annotations

from .models import AuditIssue, Lockfile


def _issue_phase(code: str) -> str:
    if code.startswith("SOURCE_TITLE"):
        return "source-title"
    if code.startswith("CLAIM") or code.startswith("SOURCE_TEXT") or code == "PDF_TEXT_EXTRA_MISSING":
        return "claim review"
    if code.startswith("CITATION") or code.startswith("BIB_ENTRY") or code.startswith("TEX"):
        return "manuscript"
    return "bibliography"


def _phase_status_lines(issues: list[AuditIssue]) -> list[str]:
    phases = {
        "bibliography": {"blocking": 0, "warnings": 0},
        "manuscript": {"blocking": 0, "warnings": 0},
        "source-title": {"blocking": 0, "warnings": 0},
        "claim review": {"blocking": 0, "warnings": 0},
    }
    for issue in issues:
        phase = phases[_issue_phase(issue.code)]
        phase["blocking" if issue.severity == "blocking" else "warnings"] += 1
    lines = []
    for name, counts in phases.items():
        status = "blocked" if counts["blocking"] else "passed"
        lines.append(f"- {name}: {status} ({counts['blocking']} blocking, {counts['warnings']} warnings)")
    return lines


def _generic_issue_message(issue: AuditIssue) -> str:
    if issue.code == "CLAIM_NOT_CHECKED":
        return "Claims are not marked checked."
    if issue.code == "CLAIM_STATUS_NOT_FINAL":
        return "Claims have evidence but are not marked checked."
    if issue.code == "CLAIM_EVIDENCE_LOW_OVERLAP":
        return "Claims have low lexical overlap with their evidence."
    if issue.code == "CLAIM_EVIDENCE_MISSING":
        return "Claims have no evidence text."
    if issue.code == "CLAIM_SOURCE_LOCATION_MISSING":
        return "Claims are checked but have no source location."
    if issue.code == "CLAIM_MAY_BE_TOO_STRONG":
        return "Claims use strong wording that needs careful source support."
    if issue.code == "CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE":
        return "Claims use weak evidence that cannot be marked checked."
    return issue.message


def _issue_summary_lines(issues: list[AuditIssue]) -> list[str]:
    grouped: dict[str, dict[str, object]] = {}
    for issue in issues:
        group = grouped.setdefault(issue.code, {"issue": issue, "count": 0, "citation_keys": []})
        group["count"] = int(group["count"]) + 1
        keys = group["citation_keys"]
        if issue.citation_key and issue.citation_key not in keys:
            keys.append(issue.citation_key)
    lines = []
    for group in grouped.values():
        issue = group["issue"]
        keys = group["citation_keys"]
        key_text = ", ".join(f"`{key}`" for key in keys[:5])
        more = f", ... {len(keys) - 5} more" if len(keys) > 5 else ""
        suffix = f" ({key_text}{more})" if key_text else ""
        lines.append(f"- `{issue.code}` x{group['count']}: {_generic_issue_message(issue)}{suffix}")
    return lines


def render_markdown_report(
    lockfile: Lockfile,
    issues: list[AuditIssue] | None = None,
    *,
    accepted_provenance_notes: list[AuditIssue] | None = None,
) -> str:
    issues = issues or []
    accepted_provenance_notes = accepted_provenance_notes or []
    blocking = [issue for issue in issues if issue.severity == "blocking"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    official = [entry for entry in lockfile.entries if entry.bibtex.get("source_kind") == "official_export"]
    manual = [
        entry
        for entry in lockfile.entries
        if entry.bibtex.get("source_kind") == "publisher_metadata_manual_normalized"
    ]
    arxiv = [entry for entry in lockfile.entries if entry.bibtex.get("source_kind") == "arxiv_manual_normalized"]
    claim_issues = [issue for issue in issues if issue.code.startswith("CLAIM_")]

    lines = [
        "# Refgate Audit",
        "",
        "## Summary",
        "",
        f"- Entries: {len(lockfile.entries)}",
        f"- Blocking issues: {len(blocking)}",
        f"- Warnings: {len(warnings)}",
        f"- Accepted provenance notes: {len(accepted_provenance_notes)}",
        "",
        "## Phase Status",
        "",
        *_phase_status_lines(issues),
        "",
        "## Blocking Issues",
        "",
    ]
    if blocking:
        for issue in blocking:
            key = f" `{issue.citation_key}`" if issue.citation_key else ""
            lines.append(f"- `{issue.code}`{key}: {issue.message}")
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        for issue in warnings:
            key = f" `{issue.citation_key}`" if issue.citation_key else ""
            lines.append(f"- `{issue.code}`{key}: {issue.message}")
    else:
        lines.append("- None")
    lines.extend(["", "## Accepted Provenance Notes", ""])
    if accepted_provenance_notes:
        for issue in accepted_provenance_notes:
            key = f" `{issue.citation_key}`" if issue.citation_key else ""
            lines.append(f"- `{issue.code}`{key}: {issue.message}")
    else:
        lines.append("- None")
    lines.extend(["", "## Verified Official BibTeX", ""])
    if official:
        for entry in official:
            lines.append(f"- `{entry.citation_key}` — {entry.authority.get('source')}: {entry.authority.get('bibtex_url')}")
    else:
        lines.append("- None")

    lines.extend(["", "## Manual Fallbacks", ""])
    if manual:
        for entry in manual:
            reason = entry.bibtex.get("fallback_reason", "reason missing")
            lines.append(f"- `{entry.citation_key}` — {reason}")
    else:
        lines.append("- None")

    lines.extend(["", "## arXiv Fallbacks", ""])
    if arxiv:
        for entry in arxiv:
            accessed_at = entry.record.get("accessed_at") or "accessed date missing"
            lines.append(f"- `{entry.citation_key}` — {entry.record.get('arxiv_id')} ({accessed_at})")
    else:
        lines.append("- None")

    lines.extend(["", "## Claim-to-Source Status", ""])
    if claim_issues:
        lines.extend(_issue_summary_lines(claim_issues))
    else:
        lines.append("- No claim issues reported")

    lines.extend(
        [
            "",
            "## Submission Checklist",
            "",
            f"- [{'x' if not blocking else ' '}] Blocking issue count is zero.",
            "- [ ] Every citation key has a lockfile entry.",
            "- [ ] Official BibTeX export entries use `official_export`.",
            "- [ ] Manual fallback entries include fallback reason and field checks.",
            "- [ ] arXiv fallback entries include version and accessed date.",
            "- [ ] Important claims have source locations and evidence spans.",
        ]
    )
    lines.append("")
    return "\n".join(lines)
