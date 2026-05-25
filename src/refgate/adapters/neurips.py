from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.request import urlopen

from refgate.models import AuthorityRecord, BibtexRecord, CandidateRecord, PaperQuery
from refgate.resolver import normalize_title

from .base import ExportEndpoint
from .official_html import find_bibtex_endpoint, official_authority, official_bibtex_record, official_candidate


def _url_fetcher(url: str) -> str:
    with urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


def candidate_from_neurips_html(url: str, html: str) -> CandidateRecord:
    return official_candidate(
        source="neurips",
        record_url=url,
        html=html,
        title_meta="citation_title",
        author_meta="citation_author",
        year_meta="citation_publication_date",
        venue="NeurIPS",
    )


def neurips_record_url(url: str) -> str:
    if "proceedings.neurips.cc" not in url:
        return url
    record_url = url.replace("/file/", "/hash/")
    if record_url.endswith(".pdf"):
        record_url = record_url[:-4] + ".html"
    record_url = record_url.replace("-Paper-", "-Abstract-")
    return record_url


@dataclass
class NeuripsAdapter:
    fetcher: Callable[[str], str] = _url_fetcher

    name: str = "neurips"
    role: str = "both"

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        urls = [neurips_record_url(venue) for venue in query.preferred_venues if "neurips.cc" in venue]
        candidates: list[CandidateRecord] = []
        for url in urls:
            html = self.fetcher(url)
            candidate = candidate_from_neurips_html(url, html)
            if not query.title or normalize_title(candidate.title) == normalize_title(query.title):
                candidates.append(candidate)
        return candidates

    def fetch_authority(self, candidate: CandidateRecord) -> AuthorityRecord | None:
        return official_authority(candidate, self.name)

    def find_export_endpoints(self, authority: AuthorityRecord) -> list[ExportEndpoint]:
        if authority.source != self.name:
            return []
        if authority.bibtex_url:
            return [
                ExportEndpoint(
                    format="bibtex",
                    url=authority.bibtex_url,
                    confidence="high",
                    discovered_by="html_anchor_text",
                    is_official=True,
                )
            ]
        html = self.fetcher(authority.record_url)
        endpoint = find_bibtex_endpoint(authority.record_url, html)
        return [endpoint] if endpoint else []

    def fetch_bibtex(self, authority: AuthorityRecord, endpoint: ExportEndpoint) -> BibtexRecord | None:
        if authority.source != self.name or endpoint.format != "bibtex" or not endpoint.is_official:
            return None
        return official_bibtex_record(self.fetcher(endpoint.url))
