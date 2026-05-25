from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from .claim_audit import _row_citation_keys, _text_blocks, evidence_match_score, read_claim_rows, write_claim_rows
from .evidence_policy import is_weak_evidence_kind, normalize_evidence_kind
from .lockfile import load_lockfile
from .source_text import read_source_text


BUNDLE_SCHEMA_VERSION = "refgate.codex_review_bundle.v1"
REVIEW_SCHEMA_VERSION = "refgate.codex_review_result.v1"
SUPPORTED_DECISIONS = {
    "supported",
    "checked",
    "needs_review",
    "too_strong",
    "wrong_source",
    "no_evidence",
    "delete_or_rewrite",
    "unsupported",
}


def _display_path(path: str | Path, *, base_dir: Path) -> str:
    target = Path(path)
    try:
        rel = os.path.relpath(target, base_dir)
        if not rel.startswith(".."):
            return rel
    except ValueError:
        pass
    return str(path)


def _source_rows_by_key(path: str | Path) -> dict[str, list[dict[str, str]]]:
    target = Path(path)
    base_dir = target.parent
    if target.suffix.lower() == ".json":
        data = json.loads(target.read_text(encoding="utf-8"))
        raw_rows = data.get("sources", data) if isinstance(data, dict) else data
    else:
        with target.open(newline="", encoding="utf-8") as handle:
            raw_rows = list(csv.DictReader(handle, delimiter="\t"))

    rows_by_key: dict[str, list[dict[str, str]]] = {}
    for raw_row in raw_rows:
        citation_key = str(raw_row.get("citation_key", "")).strip()
        source_text = str(raw_row.get("source_text", "") or raw_row.get("path", "")).strip()
        if not citation_key or not source_text:
            continue
        source_path = Path(source_text)
        resolved = source_path if source_path.is_absolute() else base_dir / source_path
        rows_by_key.setdefault(citation_key, []).append(
            {
                "citation_key": citation_key,
                "source_text": str(resolved),
                "source_label": str(raw_row.get("source_label", "") or Path(source_text).name),
                "evidence_kind": normalize_evidence_kind(
                    str(
                        raw_row.get("evidence_kind", "")
                        or raw_row.get("source_kind", "")
                        or raw_row.get("evidence_source_kind", "")
                        or "source_text"
                    )
                ),
            }
        )
    return rows_by_key


def _reference_summaries(lock_path: str | Path) -> dict[str, dict[str, Any]]:
    lockfile = load_lockfile(lock_path)
    summaries: dict[str, dict[str, Any]] = {}
    for entry in lockfile.entries:
        summaries[entry.citation_key] = {
            "citation_key": entry.citation_key,
            "status": entry.status,
            "record": entry.record,
            "authority": entry.authority,
            "bibtex": {
                "source_kind": entry.bibtex.get("source_kind"),
                "raw_sha256": entry.bibtex.get("raw_sha256"),
                "normalized_sha256": entry.bibtex.get("normalized_sha256"),
                "fallback_reason": entry.bibtex.get("fallback_reason"),
                "field_checks": entry.bibtex.get("field_checks", {}),
            },
        }
    return summaries


def _clip_quote(text: str, *, max_quote_chars: int) -> str:
    return text if len(text) <= max_quote_chars else text[: max_quote_chars - 3].rstrip() + "..."


def _evidence_candidates_for_text(
    claim_text: str,
    source_text: str,
    *,
    max_quote_chars: int,
    max_candidates: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for block_label, block_text in _text_blocks(source_text):
        score = evidence_match_score(claim_text, block_text)
        if score["overlap_score"] <= 0:
            continue
        candidates.append(
            {
                "block_label": block_label,
                "quote_or_evidence": _clip_quote(block_text, max_quote_chars=max_quote_chars),
                "overlap_score": score["overlap_score"],
                "coverage": score["coverage"],
                "matched_terms": score["matched_terms"],
                "missing_terms": score["missing_terms"],
            }
        )
    candidates.sort(key=lambda item: (item["overlap_score"], item["coverage"], len(item["quote_or_evidence"])), reverse=True)
    return candidates[:max_candidates]


def _evidence_candidate_for_source(
    claim_text: str,
    source: dict[str, str],
    *,
    max_quote_chars: int,
    max_candidates: int,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "citation_key": source["citation_key"],
        "source_label": source["source_label"],
        "source_text": source["source_text"],
        "evidence_kind": source["evidence_kind"],
        "candidate_found": False,
    }
    try:
        text = read_source_text(source["source_text"])
    except Exception as exc:
        candidate["read_error"] = f"{exc.__class__.__name__}: {exc}"
        return candidate

    matches = _evidence_candidates_for_text(
        claim_text,
        text,
        max_quote_chars=max_quote_chars,
        max_candidates=max_candidates,
    )
    if not matches:
        return candidate
    best = matches[0]
    evidence_candidates = [
        {
            "source_location": f"{source['source_label']}: {match['block_label']}",
            "quote_or_evidence": match["quote_or_evidence"],
            "overlap_score": match["overlap_score"],
            "coverage": match["coverage"],
            "matched_terms": match["matched_terms"],
            "missing_terms": match["missing_terms"],
        }
        for match in matches
    ]
    candidate.update(
        {
            "candidate_found": True,
            "source_location": evidence_candidates[0]["source_location"],
            "quote_or_evidence": evidence_candidates[0]["quote_or_evidence"],
            "overlap_score": best["overlap_score"],
            "coverage": best["coverage"],
            "matched_terms": best["matched_terms"],
            "missing_terms": best["missing_terms"],
            "evidence_candidates": evidence_candidates,
        }
    )
    return candidate


def build_codex_review_bundle(
    *,
    tex: str | Path,
    bib: str | Path,
    lock: str | Path,
    claims: str | Path,
    source_map: str | Path | None = None,
    output: str | Path | None = None,
    max_quote_chars: int = 500,
    max_candidates_per_source: int = 5,
) -> dict[str, Any]:
    output_base = Path(output).parent if output else Path.cwd()
    claim_rows = read_claim_rows(claims)
    references = _reference_summaries(lock)
    source_rows = _source_rows_by_key(source_map) if source_map else {}

    bundle_claims: list[dict[str, Any]] = []
    for row in claim_rows:
        citation_keys = _row_citation_keys(row.get("citation_key", ""))
        claim_sources = [source for key in citation_keys for source in source_rows.get(key, [])]
        evidence_candidates = [
            _evidence_candidate_for_source(
                row.get("claim_text", ""),
                source,
                max_quote_chars=max_quote_chars,
                max_candidates=max_candidates_per_source,
            )
            for source in claim_sources
        ]
        for candidate in evidence_candidates:
            candidate["source_text"] = _display_path(candidate["source_text"], base_dir=output_base)
        bundle_claims.append(
            {
                "claim_id": row.get("claim_id", ""),
                "manuscript_location": row.get("manuscript_location", ""),
                "claim_text": row.get("claim_text", ""),
                "citation_key": row.get("citation_key", ""),
                "citation_keys": citation_keys,
                "current_source_location": row.get("source_location", ""),
                "current_quote_or_evidence": row.get("quote_or_evidence", ""),
                "current_evidence_kind": row.get("evidence_kind", ""),
                "current_status": row.get("status", ""),
                "current_notes": row.get("notes", ""),
                "claim_type": row.get("claim_type", ""),
                "importance": row.get("importance", ""),
                "references": [references.get(key, {"citation_key": key, "status": "missing_lock_entry"}) for key in citation_keys],
                "source_candidates": evidence_candidates,
                "review_result_template": {
                    "schema_version": REVIEW_SCHEMA_VERSION,
                    "claim_id": row.get("claim_id", ""),
                    "decision": "needs_review",
                    "source_location": "",
                    "quote_or_evidence": "",
                    "evidence_kind": "source_text",
                    "review_notes": "",
                    "suggested_rewrite": "",
                },
            }
        )

    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "inputs": {
            "tex": str(tex),
            "bib": str(bib),
            "lock": str(lock),
            "claims": str(claims),
            "source_map": str(source_map) if source_map else None,
        },
        "review_policy": {
            "reviewer": "codex_assisted_human_review",
            "must_use_full_source_text": True,
            "abstract_or_metadata_only_is_weak_evidence": True,
            "do_not_mark_checked_without_user_approval": True,
            "import_default_status": "needs_review",
        },
        "output_contract": {
            "format": "jsonl",
            "schema_version": REVIEW_SCHEMA_VERSION,
            "required_fields": ["claim_id", "decision"],
            "allowed_decisions": sorted(SUPPORTED_DECISIONS),
            "max_candidates_per_source": max_candidates_per_source,
        },
        "claims": bundle_claims,
    }


def render_codex_review_bundle_markdown(bundle: dict[str, Any]) -> str:
    lines = [
        "# Refgate Codex Review Bundle",
        "",
        "Use this file as a review queue. Verify each claim against the cited source text/PDF before producing JSONL review results.",
        "",
        "## Output Contract",
        "",
        "- Write one JSON object per claim.",
        "- Required fields: `claim_id`, `decision`.",
        "- Allowed decisions: `supported`, `checked`, `needs_review`, `too_strong`, `wrong_source`, `no_evidence`, `delete_or_rewrite`, `unsupported`.",
        "- Include `source_location`, `quote_or_evidence`, and `evidence_kind` when evidence supports the claim.",
        "- Use `suggested_rewrite` instead of editing the manuscript directly.",
        "",
        "Example:",
        "",
        "```json",
        '{"schema_version":"refgate.codex_review_result.v1","claim_id":"claim-0001","decision":"supported","source_location":"sources/key.pdf: page 2 paragraph 3","quote_or_evidence":"...","evidence_kind":"source_text","review_notes":"The cited passage supports the narrower claim."}',
        "```",
        "",
        "## Claims",
        "",
    ]
    for claim in bundle.get("claims", []):
        lines.extend(
            [
                f"### {claim.get('claim_id', '')} — `{claim.get('citation_key', '')}`",
                "",
                f"- Location: {claim.get('manuscript_location', '')}",
                f"- Current status: `{claim.get('current_status', '')}`",
                f"- Importance: `{claim.get('importance', '')}`",
                "",
                "Claim:",
                "",
                str(claim.get("claim_text", "")) or "(empty)",
                "",
                "References:",
                "",
            ]
        )
        for ref in claim.get("references", []):
            record = ref.get("record", {})
            lines.append(f"- `{ref.get('citation_key', '')}`: {record.get('title', '(missing title)')} [{ref.get('status', '')}]")
        lines.extend(["", "Evidence candidates:", ""])
        candidates = claim.get("source_candidates", [])
        if not candidates:
            lines.append("- (no mapped source)")
        for candidate in candidates:
            location = candidate.get("source_location") or candidate.get("source_text") or "(missing)"
            found = "found" if candidate.get("candidate_found") else "not_found"
            lines.append(f"- `{found}` {location}")
            if candidate.get("quote_or_evidence"):
                lines.append(f"  - Quote: {candidate.get('quote_or_evidence')}")
            for index, evidence_candidate in enumerate(candidate.get("evidence_candidates", [])[1:], start=2):
                lines.append(f"  - Alternative {index}: {evidence_candidate.get('source_location', '')}")
                lines.append(f"    - Quote: {evidence_candidate.get('quote_or_evidence', '')}")
        lines.extend(["", "Review result template:", "", "```json"])
        lines.append(json.dumps(claim.get("review_result_template", {}), ensure_ascii=False, sort_keys=True))
        lines.extend(["```", ""])
    return "\n".join(lines).rstrip() + "\n"


def write_codex_review_bundle(
    *,
    tex: str | Path,
    bib: str | Path,
    lock: str | Path,
    claims: str | Path,
    source_map: str | Path | None,
    output: str | Path,
    markdown: str | Path | None = None,
    max_quote_chars: int = 500,
    max_candidates_per_source: int = 5,
) -> dict[str, Any]:
    bundle = build_codex_review_bundle(
        tex=tex,
        bib=bib,
        lock=lock,
        claims=claims,
        source_map=source_map,
        output=output,
        max_quote_chars=max_quote_chars,
        max_candidates_per_source=max_candidates_per_source,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "output": str(output_path),
        "claim_count": len(bundle["claims"]),
        "source_candidate_count": sum(len(claim.get("source_candidates", [])) for claim in bundle["claims"]),
        "schema_version": bundle["schema_version"],
    }
    if markdown:
        markdown_path = Path(markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_codex_review_bundle_markdown(bundle), encoding="utf-8")
        result["markdown"] = str(markdown_path)
    return result


def _load_review_items(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if target.suffix.lower() == ".jsonl":
        items = []
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))
        return items
    data = json.loads(target.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if "reviews" in data:
            return list(data["reviews"])
        if "claim_id" in data:
            return [data]
    return list(data)


def _status_for_decision(decision: str, evidence_kind: str, *, allow_checked: bool) -> str:
    normalized = decision.strip().lower()
    if normalized in {"supported", "checked"}:
        if allow_checked and not is_weak_evidence_kind(evidence_kind):
            return "checked"
        return "needs_review_weak_evidence" if is_weak_evidence_kind(evidence_kind) else "needs_review"
    if normalized == "needs_review":
        return "needs_review_weak_evidence" if is_weak_evidence_kind(evidence_kind) else "needs_review"
    if normalized == "too_strong":
        return "too_strong"
    if normalized == "wrong_source":
        return "wrong_source"
    if normalized in {"delete_or_rewrite", "unsupported"}:
        return "delete_or_rewrite"
    if normalized == "no_evidence":
        return "claim_unchecked"
    return "needs_review"


def import_codex_review(
    *,
    claims: str | Path,
    review: str | Path,
    output: str | Path,
    allow_checked: bool = False,
) -> dict[str, Any]:
    rows = read_claim_rows(claims)
    row_by_id = {row.get("claim_id", ""): row for row in rows if row.get("claim_id", "")}
    review_items = _load_review_items(review)
    blocking: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []

    for item in review_items:
        claim_id = str(item.get("claim_id", "")).strip()
        decision = str(item.get("decision", "")).strip().lower()
        if not claim_id:
            blocking.append({"code": "REVIEW_CLAIM_ID_MISSING", "message": "Review row is missing claim_id."})
            continue
        if claim_id not in row_by_id:
            blocking.append({"code": "REVIEW_CLAIM_UNKNOWN", "message": "Review row references an unknown claim_id.", "evidence": [claim_id]})
            continue
        if decision not in SUPPORTED_DECISIONS:
            blocking.append({"code": "REVIEW_DECISION_UNSUPPORTED", "message": "Review row has an unsupported decision.", "evidence": [claim_id, decision]})
            continue

        row = row_by_id[claim_id]
        evidence_kind = normalize_evidence_kind(str(item.get("evidence_kind", "") or row.get("evidence_kind", "") or "source_text"))
        source_location = str(item.get("source_location", "")).strip()
        quote = str(item.get("quote_or_evidence", "")).strip()
        if source_location:
            row["source_location"] = source_location
        if quote:
            row["quote_or_evidence"] = quote
        if evidence_kind:
            row["evidence_kind"] = evidence_kind
        row["status"] = _status_for_decision(decision, evidence_kind, allow_checked=allow_checked)

        notes = row.get("notes", "").strip()
        review_notes = str(item.get("review_notes", "") or item.get("notes", "")).strip()
        suggested_rewrite = str(item.get("suggested_rewrite", "")).strip()
        note_parts = [f"Codex review decision: {decision}."]
        if review_notes:
            note_parts.append(f"Review notes: {review_notes}")
        if suggested_rewrite:
            note_parts.append(f"Suggested rewrite: {suggested_rewrite}")
        import_note = " ".join(note_parts)
        row["notes"] = f"{notes} {import_note}".strip() if notes else import_note
        applied.append({"claim_id": claim_id, "decision": decision, "status": row["status"]})

    if blocking:
        return {
            "ok": False,
            "claims": str(claims),
            "review": str(review),
            "output": str(output),
            "applied": [],
            "applied_count": 0,
            "blocking_issues": blocking,
            "warnings": [],
        }

    write_claim_rows(output, rows)
    return {
        "ok": True,
        "claims": str(claims),
        "review": str(review),
        "output": str(output),
        "allow_checked": allow_checked,
        "applied": applied,
        "applied_count": len(applied),
        "blocking_issues": [],
        "warnings": [],
    }
