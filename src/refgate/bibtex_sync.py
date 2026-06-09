from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from .bibtex import parse_bibtex_entry, sha256_text
from .lockfile import load_lockfile


SYNCABLE_SOURCE_KINDS = {
    "official_export",
    "publisher_metadata_manual_normalized",
    "arxiv_manual_normalized",
}

PASSING_STATUSES = {
    "verified_official_bibtex",
    "verified_manual_fallback",
    "arxiv_fallback_verified",
}


@dataclass(frozen=True)
class BibtexSpan:
    start: int
    end: int
    text: str
    citation_key: str | None


def _bibtex_spans(text: str) -> list[BibtexSpan]:
    starts = [match.start() for match in re.finditer(r"@\s*\w+\s*\{", text)]
    spans: list[BibtexSpan] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        entry_text = text[start:end].strip()
        citation_key: str | None = None
        kind = re.match(r"@\s*(\w+)", entry_text)
        entry_kind = kind.group(1).lower() if kind else ""
        if entry_kind not in {"string", "comment", "preamble"}:
            try:
                citation_key = parse_bibtex_entry(entry_text)["citation_key"]
            except ValueError:
                citation_key = None
        spans.append(BibtexSpan(start=start, end=end, text=entry_text, citation_key=citation_key))
    return spans


def _canonical_text(entry_bibtex: dict[str, Any]) -> str | None:
    value = str(entry_bibtex.get("canonical_text") or "").strip()
    if not value:
        return None
    return value + "\n"


def _entry_text(text: str) -> str:
    return text.strip()


def _join_bibtex_blocks(blocks: list[str]) -> str:
    cleaned = [block.strip() for block in blocks if block.strip()]
    if not cleaned:
        return ""
    return "\n\n".join(cleaned) + "\n"


def _sync_action(
    *,
    citation_key: str,
    current_text: str | None,
    lock_entry: Any,
) -> tuple[dict[str, Any], str | None]:
    source_kind = str(lock_entry.bibtex.get("source_kind") or "unknown")
    if lock_entry.status not in PASSING_STATUSES:
        return (
            {
                "citation_key": citation_key,
                "action": "blocked",
                "reason": "non_passing_status",
                "status": lock_entry.status,
                "source_kind": source_kind,
            },
            None,
        )
    if source_kind not in SYNCABLE_SOURCE_KINDS:
        return (
            {
                "citation_key": citation_key,
                "action": "blocked",
                "reason": "unsyncable_source_kind",
                "status": lock_entry.status,
                "source_kind": source_kind,
            },
            None,
        )

    canonical_text = _canonical_text(lock_entry.bibtex)
    if canonical_text is None:
        return (
            {
                "citation_key": citation_key,
                "action": "blocked",
                "reason": "canonical_bibtex_text_missing",
                "status": lock_entry.status,
                "source_kind": source_kind,
            },
            None,
        )

    stored_hash = str(lock_entry.bibtex.get("normalized_sha256") or "")
    canonical_hash = sha256_text(canonical_text)
    if stored_hash and stored_hash != "placeholder" and stored_hash != canonical_hash:
        return (
            {
                "citation_key": citation_key,
                "action": "blocked",
                "reason": "canonical_checksum_mismatch",
                "status": lock_entry.status,
                "source_kind": source_kind,
                "stored_sha256": stored_hash,
                "canonical_sha256": canonical_hash,
            },
            None,
        )

    if current_text is None:
        return (
            {
                "citation_key": citation_key,
                "action": "add",
                "reason": "missing_from_bib",
                "status": lock_entry.status,
                "source_kind": source_kind,
                "canonical_sha256": canonical_hash,
            },
            canonical_text,
        )

    current_hash = sha256_text(current_text.strip() + "\n")
    if current_hash == canonical_hash:
        return (
            {
                "citation_key": citation_key,
                "action": "unchanged",
                "reason": "already_synced",
                "status": lock_entry.status,
                "source_kind": source_kind,
                "canonical_sha256": canonical_hash,
            },
            None,
        )

    return (
        {
            "citation_key": citation_key,
            "action": "replace",
            "reason": "current_bibtex_differs_from_lock_canonical",
            "status": lock_entry.status,
            "source_kind": source_kind,
            "current_sha256": current_hash,
            "canonical_sha256": canonical_hash,
        },
        canonical_text,
    )


def sync_bibtex(
    *,
    bib: str | Path,
    lock: str | Path,
    output: str | Path | None = None,
    citation_keys: list[str] | None = None,
    add_missing: bool = False,
    in_place: bool = False,
) -> dict[str, Any]:
    bib_path = Path(bib)
    bib_text = bib_path.read_text(encoding="utf-8")
    spans = _bibtex_spans(bib_text)
    lock_entries = load_lockfile(lock).by_citation_key()
    wanted = set(citation_keys or [])
    seen_keys = {span.citation_key for span in spans if span.citation_key}
    replacements: dict[str, str] = {}
    additions: list[str] = []
    actions: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for span in spans:
        if span.citation_key is None:
            continue
        if wanted and span.citation_key not in wanted:
            actions.append({"citation_key": span.citation_key, "action": "skipped", "reason": "not_requested"})
            continue
        lock_entry = lock_entries.get(span.citation_key)
        if lock_entry is None:
            warning = {
                "citation_key": span.citation_key,
                "code": "BIB_ENTRY_NOT_IN_LOCK",
                "message": "BibTeX entry has no matching lockfile entry and was left unchanged.",
            }
            warnings.append(warning)
            actions.append({"citation_key": span.citation_key, "action": "skipped", "reason": "missing_lock_entry"})
            continue
        action, replacement = _sync_action(
            citation_key=span.citation_key,
            current_text=span.text,
            lock_entry=lock_entry,
        )
        actions.append(action)
        if action["action"] == "blocked":
            blocking.append(
                {
                    "citation_key": span.citation_key,
                    "code": str(action["reason"]).upper(),
                    "message": "BibTeX entry cannot be synced from the current lockfile state.",
                }
            )
        elif replacement is not None:
            replacements[span.citation_key] = replacement

    missing_requested = sorted(wanted - seen_keys)
    for citation_key in missing_requested:
        lock_entry = lock_entries.get(citation_key)
        if lock_entry is None:
            blocking.append(
                {
                    "citation_key": citation_key,
                    "code": "LOCK_ENTRY_MISSING",
                    "message": "Requested citation key is missing from the lockfile.",
                }
            )
            actions.append({"citation_key": citation_key, "action": "blocked", "reason": "lock_entry_missing"})
            continue
        action, replacement = _sync_action(citation_key=citation_key, current_text=None, lock_entry=lock_entry)
        if action["action"] == "add" and not add_missing:
            action = {**action, "action": "skipped", "reason": "missing_from_bib_add_missing_disabled"}
            warnings.append(
                {
                    "citation_key": citation_key,
                    "code": "BIB_ENTRY_MISSING",
                    "message": "Requested citation key is missing from the BibTeX file; rerun with --add-missing to append it.",
                }
            )
            replacement = None
        actions.append(action)
        if action["action"] == "blocked":
            blocking.append(
                {
                    "citation_key": citation_key,
                    "code": str(action["reason"]).upper(),
                    "message": "BibTeX entry cannot be synced from the current lockfile state.",
                }
            )
        elif replacement is not None:
            additions.append(replacement)

    if not wanted and add_missing:
        for citation_key in sorted(set(lock_entries) - seen_keys):
            action, replacement = _sync_action(citation_key=citation_key, current_text=None, lock_entry=lock_entries[citation_key])
            actions.append(action)
            if action["action"] == "blocked":
                blocking.append(
                    {
                        "citation_key": citation_key,
                        "code": str(action["reason"]).upper(),
                        "message": "BibTeX entry cannot be synced from the current lockfile state.",
                    }
                )
            elif replacement is not None:
                additions.append(replacement)

    synced_text = bib_text
    if replacements:
        chunks: list[str] = []
        preface = bib_text[: spans[0].start].strip() if spans else ""
        if preface:
            chunks.append(preface)
        for span in spans:
            if span.citation_key in replacements:
                chunks.append(_entry_text(replacements[span.citation_key]))
            else:
                chunks.append(_entry_text(bib_text[span.start : span.end]))
        tail = bib_text[spans[-1].end :].strip() if spans else bib_text.strip()
        if tail:
            chunks.append(tail)
        synced_text = _join_bibtex_blocks(chunks)

    if additions:
        synced_text = synced_text.rstrip() + "\n\n" + "\n\n".join(item.strip() for item in additions) + "\n"
    elif replacements:
        synced_text = synced_text.rstrip() + "\n"

    target: Path | None = None
    if output:
        target = Path(output)
    elif in_place:
        target = bib_path

    wrote = False
    if target is not None and not blocking:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(synced_text, encoding="utf-8")
        wrote = True

    change_count = sum(1 for action in actions if action["action"] in {"replace", "add"})
    return {
        "bib": str(bib_path),
        "lock": str(lock),
        "output": str(target) if target else None,
        "in_place": in_place,
        "wrote": wrote,
        "change_count": change_count,
        "action_count": len(actions),
        "actions": actions,
        "blocking_issues": blocking,
        "warnings": warnings,
        "ok": not blocking,
    }
