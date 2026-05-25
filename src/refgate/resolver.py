from __future__ import annotations

import re
import unicodedata

from .models import AuditIssue, AuthorityRecord, CandidateRecord, PaperQuery, ResolverDecision


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).lower().strip()
    text = re.sub(r"\\+([&%_$#{}])", r"\1", text)
    text = text.replace("{", "").replace("}", "")
    text = text.replace("‐", "-").replace("‑", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    text = text.strip("'\"“”‘’")
    text = re.sub(r"[.。]+$", "", text)
    return text


def normalize_author(author: str) -> str:
    text = unicodedata.normalize("NFKD", author).lower()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("đ", "dj").replace("ð", "d")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def score_candidate(query: PaperQuery, candidate: CandidateRecord) -> tuple[int, list[str]]:
    score = 0
    trace: list[str] = []

    if query.doi and candidate.doi and query.doi.lower() == candidate.doi.lower():
        return 100, ["doi exact match"]

    if query.arxiv_id and candidate.arxiv_id and query.arxiv_id.lower() == candidate.arxiv_id.lower():
        return 98, ["arxiv id exact match"]

    if normalize_title(query.title) == normalize_title(candidate.title):
        score += 60
        trace.append("title normalized exact match")

    if query.year is not None and candidate.year == query.year:
        score += 10
        trace.append("year match")

    if query.authors and candidate.authors:
        query_first = normalize_author(query.authors[0])
        candidate_first = normalize_author(candidate.authors[0])
        query_name_parts = set(query_first.split())
        candidate_name_parts = set(candidate_first.split())
        if query_first and candidate_first and (
            query_first in candidate_first
            or candidate_first in query_first
            or (query_name_parts == candidate_name_parts and len(query_name_parts) > 1)
        ):
            score += 10
            trace.append("first author match")

    if candidate.is_official_record:
        score += 15
        trace.append("official record")

    if candidate.bibtex_url:
        score += 5
        trace.append("official bibtex endpoint candidate")

    score -= max(candidate.source_priority - 1, 0)
    return score, trace


def find_conflicts(candidates: list[CandidateRecord]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    dois = {candidate.doi.lower() for candidate in candidates if candidate.doi}
    if len(dois) > 1:
        issues.append(
            AuditIssue(
                code="DOI_CONFLICT",
                message="Multiple high-confidence candidates disagree on DOI.",
                severity="blocking",
                evidence=sorted(dois),
            )
        )
    official_urls = {candidate.url for candidate in candidates if candidate.is_official_record and candidate.url}
    if len(official_urls) > 1:
        issues.append(
            AuditIssue(
                code="MULTIPLE_OFFICIAL_RECORDS",
                message="Multiple official record URLs were found.",
                severity="blocking",
                evidence=sorted(official_urls),
            )
        )
    return issues


def resolve(query: PaperQuery, candidates: list[CandidateRecord]) -> ResolverDecision:
    if not candidates:
        return ResolverDecision(
            query_id=query.query_id,
            decision="blocked",
            status="unresolved",
            authority=None,
            resolver_score=0,
            blocking_issues=[
                AuditIssue(
                    code="NO_CANDIDATES",
                    message="No candidate records were provided.",
                    severity="blocking",
                )
            ],
        )

    scored = [(score_candidate(query, candidate), candidate) for candidate in candidates]
    scored.sort(key=lambda item: item[0][0], reverse=True)
    top_score, top_trace = scored[0][0]
    top_candidate = scored[0][1]
    near_ties = [candidate for (score, _trace), candidate in scored if top_score - score <= 3 and candidate != top_candidate]
    conflicts = find_conflicts([top_candidate, *near_ties])

    if conflicts or top_score < 90:
        return ResolverDecision(
            query_id=query.query_id,
            decision="blocked",
            status="ambiguous" if conflicts else "unresolved",
            authority=None,
            resolver_score=top_score,
            blocking_issues=conflicts
            or [
                AuditIssue(
                    code="LOW_CONFIDENCE",
                    message="No candidate reached the automatic resolution threshold.",
                    severity="blocking",
                    evidence=[top_candidate.url or top_candidate.title],
                )
            ],
            decision_trace=top_trace,
            selected_candidate=top_candidate,
        )

    if query.title and not normalize_title(top_candidate.title):
        return ResolverDecision(
            query_id=query.query_id,
            decision="blocked",
            status="unresolved",
            authority=None,
            resolver_score=top_score,
            blocking_issues=[
                AuditIssue(
                    code="AUTHORITY_TITLE_MISSING",
                    message="The selected authority candidate has no title and cannot safely verify the bibliography title.",
                    severity="blocking",
                    evidence=[top_candidate.url or top_candidate.doi or top_candidate.source],
                )
            ],
            decision_trace=[*top_trace, "authority title missing"],
            selected_candidate=top_candidate,
        )

    if query.title and normalize_title(query.title) != normalize_title(top_candidate.title):
        return ResolverDecision(
            query_id=query.query_id,
            decision="blocked",
            status="unresolved",
            authority=None,
            resolver_score=top_score,
            blocking_issues=[
                AuditIssue(
                    code="AUTHORITY_TITLE_MISMATCH",
                    message="The selected authority candidate title does not exactly match the bibliography title.",
                    severity="blocking",
                    evidence=[top_candidate.title, query.title],
                )
            ],
            decision_trace=[*top_trace, "authority title mismatch"],
            selected_candidate=top_candidate,
        )

    if top_candidate.raw.get("official_record_status") == "official_record_pending":
        return ResolverDecision(
            query_id=query.query_id,
            decision="blocked",
            status="official_record_pending",
            authority=None,
            resolver_score=top_score,
            blocking_issues=[
                AuditIssue(
                    code="OFFICIAL_RECORD_PENDING",
                    message="Only an arXiv preprint record was found while a preferred official venue was requested.",
                    severity="blocking",
                    evidence=[top_candidate.url or top_candidate.title],
                )
            ],
            warnings=[],
            decision_trace=[*top_trace, "official record pending"],
            selected_candidate=top_candidate,
        )

    if top_candidate.is_official_record and top_candidate.bibtex_url:
        status = "verified_official_bibtex"
    elif top_candidate.arxiv_id:
        status = "arxiv_fallback_verified"
    else:
        status = "verified_manual_fallback"

    record_type = "conference_proceedings" if top_candidate.is_official_record else "fallback_metadata"
    if top_candidate.arxiv_id and not top_candidate.bibtex_url:
        record_type = "preprint_record"

    authority = AuthorityRecord(
        source=top_candidate.source,
        record_url=top_candidate.url or "",
        record_type=record_type,
        source_priority=top_candidate.source_priority,
        bibtex_url=top_candidate.bibtex_url,
    )
    return ResolverDecision(
        query_id=query.query_id,
        decision="selected",
        status=status,
        authority=authority,
        resolver_score=top_score,
        decision_trace=top_trace,
        selected_candidate=top_candidate,
    )
