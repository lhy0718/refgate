from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

from refgate.auth import semantic_scholar_api_key
from refgate.models import AuthorityRecord, CandidateRecord, PaperQuery
from refgate.resolver import normalize_title


S2_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


def _url_fetcher(url: str) -> str:
    headers = {}
    configured_value = semantic_scholar_api_key()
    if configured_value:
        headers["x-api-key"] = configured_value
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def _candidate_from_paper(paper: dict[str, Any]) -> CandidateRecord:
    external = paper.get("externalIds") or {}
    return CandidateRecord(
        source="semantic_scholar",
        title=paper.get("title") or "",
        authors=[author.get("name", "") for author in paper.get("authors", []) if author.get("name")],
        year=paper.get("year"),
        venue=paper.get("venue") or None,
        doi=external.get("DOI"),
        arxiv_id=external.get("ArXiv"),
        url=paper.get("url"),
        is_official_record=False,
        bibtex_url=None,
        source_priority=4,
        raw={
            "paper_id": paper.get("paperId"),
            "external_ids": external,
            "metadata_source": "semantic_scholar",
            "authority_role": "discovery_only",
        },
    )


@dataclass
class SemanticScholarAdapter:
    fetcher: Callable[[str], str] = _url_fetcher

    name: str = "semantic_scholar"
    role: str = "discovery"

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        params = urlencode(
            {
                "query": query.title,
                "limit": 5,
                "fields": "paperId,title,authors,year,venue,externalIds,url",
            }
        )
        data = json.loads(self.fetcher(f"{S2_API_URL}?{params}"))
        candidates = [_candidate_from_paper(item) for item in data.get("data", [])]
        return [candidate for candidate in candidates if normalize_title(candidate.title) == normalize_title(query.title)]

    def fetch_authority(self, candidate: CandidateRecord) -> AuthorityRecord | None:
        return None

    def find_export_endpoints(self, authority: AuthorityRecord) -> list:
        return []

    def fetch_bibtex(self, authority: AuthorityRecord, endpoint) -> None:
        return None
