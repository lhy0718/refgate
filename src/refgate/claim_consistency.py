from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .claim_audit import _claim_terms, read_claim_rows
from .evidence_policy import is_weak_evidence_kind
from .models import AuditIssue


PASSING_STATUSES = {"checked", "checked_arxiv", "checked-arxiv"}
STRONG_CLAIM_TERMS = {
    "always",
    "best",
    "guarantee",
    "guarantees",
    "never",
    "outperform",
    "outperforms",
    "prove",
    "proves",
    "significant",
    "state-of-the-art",
}
HEDGE_TERMS = {"approximately", "can", "could", "indicate", "indicates", "may", "might", "suggest", "suggests"}


@dataclass
class ClaimConsistencyResult:
    claim_id: str
    citation_key: str
    status: str
    overlap_score: int
    claim_terms: list[str]
    evidence_terms: list[str]
    shared_terms: list[str]
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def review_claim_consistency(
    claims_path: str | Path,
    *,
    min_overlap: int = 2,
    require_passing_status: bool = False,
) -> tuple[list[ClaimConsistencyResult], list[AuditIssue]]:
    rows = read_claim_rows(claims_path)
    results: list[ClaimConsistencyResult] = []
    issues: list[AuditIssue] = []
    for row in rows:
        claim_id = row.get("claim_id", "").strip()
        status = row.get("status", "").strip() or "claim_unchecked"
        citation_key = row.get("citation_key", "").strip()
        evidence = row.get("quote_or_evidence", "").strip()
        evidence_kind = row.get("evidence_kind", "").strip()
        claim_terms = _claim_terms(row.get("claim_text", ""))
        evidence_terms = _claim_terms(evidence)
        shared = sorted(claim_terms & evidence_terms)
        strong_terms = sorted(claim_terms & STRONG_CLAIM_TERMS)
        has_evidence_hedge = bool(evidence_terms & HEDGE_TERMS)
        enough_overlap = len(shared) >= min_overlap
        passing_status = status in PASSING_STATUSES
        ok = bool(evidence) and enough_overlap and (passing_status or not require_passing_status)
        result = ClaimConsistencyResult(
            claim_id=claim_id,
            citation_key=citation_key,
            status=status,
            overlap_score=len(shared),
            claim_terms=sorted(claim_terms),
            evidence_terms=sorted(evidence_terms),
            shared_terms=shared,
            ok=ok,
        )
        results.append(result)
        if not evidence:
            issues.append(
                AuditIssue(
                    code="CLAIM_EVIDENCE_MISSING",
                    message=f"Claim {claim_id or '(missing id)'} has no evidence text.",
                    severity="blocking" if require_passing_status else "warning",
                    citation_key=citation_key or None,
                )
            )
        elif not enough_overlap:
            issues.append(
                AuditIssue(
                    code="CLAIM_EVIDENCE_LOW_OVERLAP",
                    message=f"Claim {claim_id or '(missing id)'} has low lexical overlap with its evidence.",
                    severity="blocking" if require_passing_status else "warning",
                    citation_key=citation_key or None,
                    evidence=shared,
                )
            )
        if strong_terms and evidence and (len(shared) < min_overlap + 1 or has_evidence_hedge):
            issues.append(
                AuditIssue(
                    code="CLAIM_MAY_BE_TOO_STRONG",
                    message=f"Claim {claim_id or '(missing id)'} uses strong wording that needs careful source support.",
                    severity="blocking" if require_passing_status else "warning",
                    citation_key=citation_key or None,
                    evidence=strong_terms,
                )
            )
        if require_passing_status and evidence and enough_overlap and not passing_status:
            issues.append(
                AuditIssue(
                    code="CLAIM_STATUS_NOT_FINAL",
                    message=f"Claim {claim_id or '(missing id)'} has evidence but is not marked checked.",
                    severity="blocking",
                    citation_key=citation_key or None,
                )
            )
        if (
            require_passing_status
            and evidence
            and enough_overlap
            and passing_status
            and is_weak_evidence_kind(evidence_kind)
        ):
            issues.append(
                AuditIssue(
                    code="CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE",
                    message=f"Claim {claim_id or '(missing id)'} is marked checked using weak evidence kind {evidence_kind}.",
                    severity="blocking",
                    citation_key=citation_key or None,
                    evidence=[evidence_kind],
                )
            )
    return results, issues
