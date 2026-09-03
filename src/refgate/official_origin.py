"""Check that an official BibTeX export is the publisher's file, not a copy of it.

Refgate assigns ``source_kind: official_export`` on the strength of where a file
sits -- inside ``--official-bibtex-dir`` -- and then verifies its title and DOI
against the authority record. Nothing establishes that the bytes came from the
publisher. A file retyped from a rendered page, or edited after download, passes
every existing check.

This module closes that gap the only way it can be closed: fetch the export again
from the URL the authority record already carries, and compare bytes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable

from .adapters.base import default_fetcher
from .bibtex import sha256_text
from .lockfile import load_lockfile, write_lockfile
from .models import AuditIssue
from .reference_check import _official_bibtex_file

ORIGIN_VERIFIED = "match"


def _origin_url(entry: Any) -> str | None:
    authority = entry.authority or {}
    url = str(authority.get("bibtex_url") or "").strip()
    return url or None


def verify_official_bibtex_origin(
    *,
    lock: str | Path,
    official_bibtex_dir: str | Path,
    live: bool = False,
    write_lock: str | Path | None = None,
    citation_keys: list[str] | None = None,
    fetcher: Callable[[str], str] = default_fetcher,
) -> dict[str, Any]:
    lockfile = load_lockfile(lock)
    root = Path(official_bibtex_dir)
    wanted = set(citation_keys or [])
    results: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checked_at = date.today().isoformat()
    updated = 0

    for entry in lockfile.entries:
        bibtex = entry.bibtex or {}
        if bibtex.get("source_kind") != "official_export":
            continue
        if wanted and entry.citation_key not in wanted:
            continue
        source = str((entry.authority or {}).get("source") or "")
        path = _official_bibtex_file(root, entry.citation_key, source)
        url = _origin_url(entry)
        row: dict[str, Any] = {
            "citation_key": entry.citation_key,
            "official_bibtex_file": str(path) if path else None,
            "export_url": url,
            "checked_at": checked_at,
        }

        if path is None:
            row["result"] = "fixture_missing"
            blocking.append(
                {
                    "code": "OFFICIAL_EXPORT_FILE_MISSING",
                    "message": "Entry claims an official export but no file was found in the export directory.",
                    "citation_key": entry.citation_key,
                }
            )
            results.append(row)
            continue

        local = path.read_text(encoding="utf-8")
        row["local_sha256"] = sha256_text(local)

        if not url:
            row["result"] = "no_export_url"
            warnings.append(
                {
                    "code": "OFFICIAL_EXPORT_URL_UNKNOWN",
                    "message": "No export URL is recorded, so the file's origin cannot be re-checked.",
                    "citation_key": entry.citation_key,
                }
            )
            results.append(row)
            continue

        if not live:
            row["result"] = "not_checked"
            results.append(row)
            continue

        try:
            remote = fetcher(url)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            row["result"] = "fetch_failed"
            row["error"] = f"{exc.__class__.__name__}: {exc}"
            warnings.append(
                {
                    "code": "OFFICIAL_EXPORT_REFETCH_FAILED",
                    "message": "The export could not be fetched again, so its origin stays unverified.",
                    "citation_key": entry.citation_key,
                    "evidence": [url, row["error"]],
                }
            )
            results.append(row)
            continue

        row["remote_sha256"] = sha256_text(remote)
        if row["remote_sha256"] == row["local_sha256"]:
            row["result"] = ORIGIN_VERIFIED
        elif remote.strip() == local.strip():
            # Same entry, different trailing bytes. Still not the published file,
            # which is how a transcription or a re-saved copy shows up.
            row["result"] = "whitespace_only_difference"
            blocking.append(
                {
                    "code": "OFFICIAL_EXPORT_ORIGIN_MISMATCH",
                    "message": "The stored export differs from the publisher's file in whitespace only, so it is a copy rather than the export.",
                    "citation_key": entry.citation_key,
                    "evidence": [url],
                }
            )
        else:
            row["result"] = "differs"
            blocking.append(
                {
                    "code": "OFFICIAL_EXPORT_ORIGIN_MISMATCH",
                    "message": "The stored export does not match the publisher's current file.",
                    "citation_key": entry.citation_key,
                    "evidence": [url, f"local {row['local_sha256']}", f"remote {row['remote_sha256']}"],
                }
            )

        if write_lock:
            bibtex["origin_check"] = {
                "url": url,
                "checked_at": checked_at,
                "result": row["result"],
                "local_sha256": row["local_sha256"],
                "remote_sha256": row["remote_sha256"],
            }
            updated += 1
        results.append(row)

    if write_lock:
        write_lockfile(lockfile, write_lock)

    verified = sum(1 for row in results if row.get("result") == ORIGIN_VERIFIED)
    return {
        "lock": str(lock),
        "official_bibtex_dir": str(root),
        "live": live,
        "checked": len(results),
        "verified": verified,
        "updated_entries": updated,
        "results": results,
        "blocking_issues": blocking,
        "warnings": warnings,
        "ok": not blocking,
    }


def origin_audit_issues(lockfile, *, submission: bool = False) -> list[AuditIssue]:
    """Flag official exports whose bytes were never checked against the publisher."""
    issues: list[AuditIssue] = []
    for entry in lockfile.entries:
        bibtex = entry.bibtex or {}
        if bibtex.get("source_kind") != "official_export":
            continue
        check = bibtex.get("origin_check") or {}
        result = str(check.get("result") or "")
        if result == ORIGIN_VERIFIED:
            continue
        if result:
            issues.append(
                AuditIssue(
                    code="OFFICIAL_EXPORT_ORIGIN_MISMATCH",
                    message=f"Official export origin check returned {result!r}.",
                    severity="blocking",
                    citation_key=entry.citation_key,
                    evidence=[str(check.get("url") or "")],
                )
            )
            continue
        issues.append(
            AuditIssue(
                code="OFFICIAL_EXPORT_ORIGIN_UNVERIFIED",
                message=(
                    "The file backing this official export was never compared against the publisher's. "
                    "Run verify-official-bibtex --live."
                ),
                severity="blocking" if submission else "warning",
                citation_key=entry.citation_key,
            )
        )
    return issues
