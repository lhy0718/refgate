from __future__ import annotations


WEAK_EVIDENCE_KINDS = {
    "abstract",
    "summary",
    "metadata_summary",
    "semantic_scholar_abstract",
    "openalex_abstract",
    "arxiv_summary",
}


def normalize_evidence_kind(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


def is_weak_evidence_kind(value: str | None) -> bool:
    return normalize_evidence_kind(value) in WEAK_EVIDENCE_KINDS
