from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .claim_audit import _best_evidence_match, _row_citation_keys, read_claim_rows, write_claim_rows
from .claim_consistency import review_claim_consistency
from .evidence_policy import is_weak_evidence_kind, normalize_evidence_kind
from .source_text import read_source_text, validate_source_text


def _read_source_map(path: str | Path) -> dict[str, list[dict[str, str]]]:
    target = Path(path)
    base_dir = target.parent
    if target.suffix.lower() == ".json":
        data = json.loads(target.read_text(encoding="utf-8"))
        rows = data.get("sources", data) if isinstance(data, dict) else data
    else:
        with target.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))

    source_map: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        citation_key = str(row.get("citation_key", "")).strip()
        source_text = str(row.get("source_text", "") or row.get("path", "")).strip()
        if not citation_key or not source_text:
            continue
        source_path = Path(source_text)
        resolved_source_text = str(source_path if source_path.is_absolute() else base_dir / source_path)
        evidence_kind = normalize_evidence_kind(
            str(row.get("evidence_kind", "") or row.get("source_kind", "") or row.get("evidence_source_kind", ""))
        )
        source_map.setdefault(citation_key, []).append(
            {
                "citation_key": citation_key,
                "source_text": resolved_source_text,
                "source_label": str(row.get("source_label", "") or Path(source_text).name),
                "evidence_kind": evidence_kind or "source_text",
            }
        )
    return source_map


def run_claim_source_check(
    claims_path: str | Path,
    source_map_path: str | Path,
    *,
    output_path: str | Path | None = None,
    min_overlap: int = 2,
    require_passing_status: bool = False,
    max_quote_chars: int = 320,
    rerank: str = "lexical",
) -> dict[str, Any]:
    if not Path(source_map_path).exists():
        return {
            "ok": False,
            "claims": str(claims_path),
            "source_map": str(source_map_path),
            "output": str(output_path) if output_path else None,
            "claim_count": 0,
            "source_count": 0,
            "updated": 0,
            "suggestions": [],
            "missing_source_keys": [],
            "no_match_claims": [],
            "consistency_summary": {
                "result_count": 0,
                "ok_count": 0,
                "blocking_issue_count": 1,
                "warning_count": 0,
            },
            "consistency": [],
            "blocking_issues": [
                {
                    "code": "SOURCE_MAP_MISSING",
                    "message": "Source map file does not exist.",
                    "evidence": [str(source_map_path)],
                }
            ],
            "warnings": [],
        }
    rows = read_claim_rows(claims_path)
    source_map = _read_source_map(source_map_path)
    source_paths = sorted({source["source_text"] for sources in source_map.values() for source in sources})
    validation = validate_source_text(source_paths) if source_paths else {"ok": False, "blocking_issues": []}
    if any(issue.get("code") == "PDF_TEXT_EXTRA_MISSING" for issue in validation.get("blocking_issues", [])):
        return {
            "ok": False,
            "claims": str(claims_path),
            "source_map": str(source_map_path),
            "output": str(output_path) if output_path else None,
            "claim_count": len(rows),
            "source_count": len(source_paths),
            "rerank": rerank,
            "updated": 0,
            "suggestions": [],
            "missing_source_keys": [],
            "no_match_claims": [],
            "consistency_summary": {
                "result_count": 0,
                "ok_count": 0,
                "blocking_issue_count": len(validation.get("blocking_issues", [])),
                "warning_count": 0,
            },
            "consistency": [],
            "blocking_issues": list(validation.get("blocking_issues", [])),
            "warnings": [],
        }
    source_text_cache: dict[str, str] = {}
    for path in source_paths:
        try:
            source_text_cache[path] = read_source_text(path)
        except Exception:
            continue

    updated = 0
    missing_source_keys: set[str] = set()
    no_match_claims: list[dict[str, str]] = []
    suggestions: list[dict[str, Any]] = []

    for row in rows:
        if row.get("quote_or_evidence", "").strip():
            continue
        keys = _row_citation_keys(row.get("citation_key", ""))
        available_sources = [source for key in keys for source in source_map.get(key, [])]
        if not available_sources:
            missing_source_keys.update(keys)
            continue

        best: dict[str, Any] | None = None
        for source in available_sources:
            if source["source_text"] not in source_text_cache:
                continue
            match = _best_evidence_match(row.get("claim_text", ""), source_text_cache[source["source_text"]], rerank=rerank)
            if match is None:
                continue
            candidate = {**match, "source_label": source["source_label"], "evidence_kind": source["evidence_kind"]}
            if rerank == "semantic-lite":
                candidate_rank = (
                    (candidate["semantic_lite_score"] or 0.0) + candidate.get("evidence_quality", 0.0),
                    candidate["overlap_score"],
                    candidate["coverage"],
                    candidate.get("word_count", 0),
                )
                best_rank = (
                    ((best.get("semantic_lite_score", 0.0) or 0.0) + best.get("evidence_quality", 0.0)) if best else 0.0,
                    best.get("overlap_score", 0) if best else 0,
                    best.get("coverage", 0.0) if best else 0.0,
                    best.get("word_count", 0) if best else 0,
                )
            else:
                candidate_rank = (
                    candidate["overlap_score"],
                    candidate["coverage"],
                    candidate.get("evidence_quality", 0.0),
                    candidate.get("word_count", 0),
                )
                best_rank = (
                    best.get("overlap_score", 0) if best else 0,
                    best.get("coverage", 0.0) if best else 0.0,
                    best.get("evidence_quality", 0.0) if best else 0.0,
                    best.get("word_count", 0) if best else 0,
                )
            if best is None or candidate_rank > best_rank:
                best = candidate

        if best is None:
            no_match_claims.append({"claim_id": row.get("claim_id", ""), "citation_key": row.get("citation_key", "")})
            continue

        block_label = best["block_label"]
        quote = best["quote"]
        score = best["overlap_score"]
        source_label = best["source_label"]
        evidence_kind = best["evidence_kind"]
        clipped = quote if len(quote) <= max_quote_chars else quote[: max_quote_chars - 3].rstrip() + "..."
        row["quote_or_evidence"] = clipped
        row["source_location"] = row.get("source_location", "").strip() or f"{source_label}: {block_label}"
        row["evidence_kind"] = evidence_kind
        if row.get("status", "").strip() in {"", "claim_unchecked"}:
            row["status"] = "needs_review_weak_evidence" if is_weak_evidence_kind(evidence_kind) else "needs_review"
        note = row.get("notes", "").strip()
        if is_weak_evidence_kind(evidence_kind):
            suggestion_note = (
                f"Refgate source-map overlap score {score}, coverage {best['coverage']:.2f} "
                f"from weak evidence kind {evidence_kind}; "
                "full source passage or human review required before marking checked."
            )
        else:
            suggestion_note = (
                f"Refgate source-map overlap score {score}, coverage {best['coverage']:.2f}; "
                "direct source review required before marking checked."
            )
        row["notes"] = f"{note} {suggestion_note}".strip() if note else suggestion_note
        updated += 1
        suggestions.append(
            {
                "claim_id": row.get("claim_id", ""),
                "citation_key": row.get("citation_key", ""),
                "source_location": row.get("source_location", ""),
                "overlap_score": score,
                "coverage": best["coverage"],
                "matched_terms": best["matched_terms"],
                "missing_terms": best["missing_terms"],
                "semantic_lite_score": best["semantic_lite_score"],
                "section_heading": best.get("section_heading"),
                "evidence_quality": best.get("evidence_quality"),
                "title_like": best.get("title_like"),
                "abstract_like": best.get("abstract_like"),
            }
        )

    if output_path:
        write_claim_rows(output_path, rows)

    consistency_results, consistency_issues = review_claim_consistency(
        output_path or claims_path,
        min_overlap=min_overlap,
        require_passing_status=require_passing_status,
    )
    blocking = list(validation.get("blocking_issues", []))
    for key in sorted(missing_source_keys):
        blocking.append(
            {
                "code": "SOURCE_TEXT_MISSING_FOR_CITATION",
                "message": "No source text/PDF was mapped for a cited claim.",
                "citation_key": key,
            }
        )
    for item in no_match_claims:
        blocking.append(
            {
                "code": "CLAIM_EVIDENCE_NOT_FOUND_IN_SOURCE",
                "message": "Mapped source text was provided, but no overlapping evidence block was found.",
                "citation_key": item["citation_key"],
                "evidence": [item["claim_id"]],
            }
        )
    blocking.extend(issue.to_dict() for issue in consistency_issues if issue.severity == "blocking")
    warnings = [issue.to_dict() for issue in consistency_issues if issue.severity == "warning"]

    return {
        "ok": not blocking,
        "claims": str(claims_path),
        "source_map": str(source_map_path),
        "output": str(output_path) if output_path else None,
        "claim_count": len(rows),
        "source_count": len(source_paths),
        "rerank": rerank,
        "updated": updated,
        "suggestions": suggestions,
        "missing_source_keys": sorted(missing_source_keys),
        "no_match_claims": no_match_claims,
        "consistency_summary": {
            "result_count": len(consistency_results),
            "ok_count": sum(1 for result in consistency_results if result.ok),
            "blocking_issue_count": len(blocking),
            "warning_count": len(warnings),
        },
        "consistency": [result.to_dict() for result in consistency_results],
        "blocking_issues": blocking,
        "warnings": warnings,
    }
