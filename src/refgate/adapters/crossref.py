from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote, urlencode
from urllib.request import urlopen
import json

from refgate.auth import append_query_param, crossref_mailto
from refgate.models import AuthorityRecord, CandidateRecord, PaperQuery
from refgate.resolver import normalize_title


CROSSREF_API_URL = "https://api.crossref.org/works"


def _url_fetcher(url: str) -> str:
    url = append_query_param(url, "mailto", crossref_mailto())
    with urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return value


def _year(message: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = message.get(key, {}).get("date-parts")
        if parts and parts[0]:
            return int(parts[0][0])
    return None


def _authors(message: dict[str, Any]) -> list[str]:
    authors = []
    for author in message.get("author", []):
        given = author.get("given", "")
        family = author.get("family", "")
        name = " ".join(part for part in [given, family] if part).strip()
        if name:
            authors.append(name)
    return authors


def _candidate_from_work(message: dict[str, Any]) -> CandidateRecord:
    doi = message.get("DOI")
    url = message.get("URL") or (f"https://doi.org/{doi}" if doi else None)
    container = _first(message.get("container-title")) or _first(message.get("short-container-title"))
    title = _first(message.get("title")) or ""
    return CandidateRecord(
        source="crossref",
        title=title,
        authors=_authors(message),
        year=_year(message),
        venue=container,
        doi=doi,
        url=url,
        is_official_record=bool(doi),
        bibtex_url=None,
        source_priority=2,
        raw={
            "metadata_source": "crossref",
            "type": message.get("type"),
            "publisher": message.get("publisher"),
            "reference_count": message.get("reference-count"),
        },
    )


@dataclass
class CrossrefAdapter:
    fetcher: Callable[[str], str] = _url_fetcher

    name: str = "crossref"
    role: str = "both"

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        if query.doi:
            url = f"{CROSSREF_API_URL}/{quote(query.doi)}"
            data = json.loads(self.fetcher(url))
            return [_candidate_from_work(data["message"])]

        params = urlencode({"query.title": query.title, "rows": 5})
        data = json.loads(self.fetcher(f"{CROSSREF_API_URL}?{params}"))
        candidates = [_candidate_from_work(item) for item in data.get("message", {}).get("items", [])]
        return [candidate for candidate in candidates if normalize_title(candidate.title) == normalize_title(query.title)]

    def fetch_authority(self, candidate: CandidateRecord) -> AuthorityRecord | None:
        if candidate.source != self.name or not candidate.url:
            return None
        return AuthorityRecord(
            source=self.name,
            record_url=candidate.url,
            record_type="doi_metadata",
            source_priority=candidate.source_priority,
            bibtex_url=None,
        )

    def find_export_endpoints(self, authority: AuthorityRecord) -> list:
        return []

    def fetch_bibtex(self, authority: AuthorityRecord, endpoint) -> None:
        return None
