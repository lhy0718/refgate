from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import CandidateRecord, PaperQuery
from .resolver import resolve


@dataclass
class FixtureMatrixRow:
    query_id: str
    title: str
    candidate_count: int
    status: str
    ok: bool
    blocking_codes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_fixture_matrix(queries_data: list[dict[str, Any]], candidates_data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows: list[FixtureMatrixRow] = []
    missing_candidate_sets: list[str] = []
    placeholder_records: list[dict[str, str]] = []

    for query_data in queries_data:
        query = PaperQuery.from_dict(query_data)
        raw_candidates = candidates_data.get(query.query_id, [])
        if not raw_candidates:
            missing_candidate_sets.append(query.query_id)
        for item in raw_candidates:
            if str(item.get("url", "")).startswith("https://example.org/") or item.get("raw", {}).get("fixture_status") == "placeholder":
                placeholder_records.append({"query_id": query.query_id, "url": str(item.get("url", ""))})
        candidates = [CandidateRecord.from_dict(item) for item in raw_candidates]
        decision = resolve(query, candidates)
        rows.append(
            FixtureMatrixRow(
                query_id=query.query_id,
                title=query.title,
                candidate_count=len(candidates),
                status=decision.status,
                ok=decision.ok,
                blocking_codes=[issue.code for issue in decision.blocking_issues],
            )
        )

    blocking_rows = [row for row in rows if not row.ok]
    return {
        "total_queries": len(rows),
        "ok_queries": sum(1 for row in rows if row.ok),
        "missing_candidate_sets": missing_candidate_sets,
        "placeholder_records": placeholder_records,
        "blocking_rows": [row.to_dict() for row in blocking_rows],
        "rows": [row.to_dict() for row in rows],
        "ok": not missing_candidate_sets and not blocking_rows,
    }
