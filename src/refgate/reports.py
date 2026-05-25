from __future__ import annotations

from .models import AuditIssue, Lockfile


def render_markdown_report(lockfile: Lockfile, issues: list[AuditIssue] | None = None) -> str:
    issues = issues or []
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
        for issue in claim_issues:
            key = f" `{issue.citation_key}`" if issue.citation_key else ""
            lines.append(f"- `{issue.code}`{key}: {issue.message}")
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
