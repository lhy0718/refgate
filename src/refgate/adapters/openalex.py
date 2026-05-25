from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen
import json

from refgate.auth import append_query_param, openalex_mailto
from refgate.models import AuthorityRecord, CandidateRecord, PaperQuery
from refgate.resolver import normalize_title


OPENALEX_API_URL = "https://api.openalex.org/works"


def _url_fetcher(url: str) -> str:
    url = append_query_param(url, "mailto", openalex_mailto())
    with urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


def _authors(work: dict[str, Any]) -> list[str]:
    authors = []
    for authorship in work.get("authorships", []):
        display = authorship.get("author", {}).get("display_name")
        if display:
            authors.append(display)
    return authors


def _candidate_from_work(work: dict[str, Any]) -> CandidateRecord:
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    doi = work.get("doi")
    if isinstance(doi, str) and doi.startswith("https://doi.org/"):
        doi = doi.removeprefix("https://doi.org/")
    return CandidateRecord(
        source="openalex",
        title=work.get("title") or work.get("display_name") or "",
        authors=_authors(work),
        year=work.get("publication_year"),
        venue=source.get("display_name"),
        doi=doi,
        url=primary.get("landing_page_url") or work.get("id"),
        is_official_record=False,
        bibtex_url=None,
        source_priority=4,
        raw={
            "openalex_id": work.get("id"),
            "metadata_source": "openalex",
            "authority_role": "discovery_cross_check",
            "primary_location": primary,
        },
    )


@dataclass
class OpenAlexAdapter:
    fetcher: Callable[[str], str] = _url_fetcher

    name: str = "openalex"
    role: str = "discovery"

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        if query.doi:
            params = urlencode({"filter": f"doi:{query.doi}"})
        else:
            params = urlencode({"search": query.title, "per-page": 5})
        data = json.loads(self.fetcher(f"{OPENALEX_API_URL}?{params}"))
        candidates = [_candidate_from_work(item) for item in data.get("results", [])]
        return [candidate for candidate in candidates if not query.title or normalize_title(candidate.title) == normalize_title(query.title)]

    def fetch_authority(self, candidate: CandidateRecord) -> AuthorityRecord | None:
        return None

    def find_export_endpoints(self, authority: AuthorityRecord) -> list:
        return []

    def fetch_bibtex(self, authority: AuthorityRecord, endpoint) -> None:
        return None
