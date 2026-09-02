from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.request import urlopen
import re

from refgate.bibtex import parse_bibtex_entry, sha256_text
from refgate.models import AuthorityRecord, BibtexRecord, CandidateRecord, PaperQuery
from refgate.resolver import title_match_supported

from .base import ExportEndpoint
from .crossref import CrossrefAdapter
from .official_html import meta_content, meta_contents


ACL_BASE_URL = "https://aclanthology.org"
ACL_DOI_PREFIX = "10.18653/v1/"


def extract_acl_id(url: str) -> str | None:
    match = re.search(r"aclanthology\.org/([A-Za-z0-9.-]+)/?", url)
    return match.group(1) if match else None


def acl_bibtex_url(record_url: str) -> str | None:
    acl_id = extract_acl_id(record_url)
    if not acl_id:
        return None
    return f"{ACL_BASE_URL}/{acl_id}.bib"


def acl_record_url_from_doi(doi: str) -> str | None:
    if not doi.lower().startswith(ACL_DOI_PREFIX):
        return None
    acl_id = doi[len(ACL_DOI_PREFIX) :].strip()
    return f"{ACL_BASE_URL}/{acl_id}/" if acl_id else None


def _url_fetcher(url: str) -> str:
    with urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


def candidate_from_acl_html(url: str, html: str) -> CandidateRecord:
    title = meta_content(html, "citation_title") or meta_content(html, "og:title") or ""
    authors = meta_contents(html, "citation_author")
    year_text = meta_content(html, "citation_publication_date") or ""
    year_match = re.search(r"\d{4}", year_text)
    bibtex_url = meta_content(html, "citation_bibtex_url") or acl_bibtex_url(url)
    venue = meta_content(html, "citation_conference_title") or meta_content(html, "citation_journal_title") or "ACL Anthology"
    return CandidateRecord(
        source="acl",
        title=title,
        authors=[re.sub(r"\s+", " ", author).strip() for author in authors],
        year=int(year_match.group(0)) if year_match else None,
        venue=venue,
        doi=meta_content(html, "citation_doi"),
        url=url,
        is_official_record=True,
        bibtex_url=bibtex_url,
        source_priority=1,
        raw={"acl_id": extract_acl_id(url), "metadata_source": "acl_html"},
    )


@dataclass
class AclAdapter:
    fetcher: Callable[[str], str] = _url_fetcher

    name: str = "acl"
    role: str = "both"

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        urls: dict[str, tuple[str, str]] = {}

        def add_url(url: str, discovered_by: str) -> None:
            acl_id = extract_acl_id(url)
            dedupe_key = acl_id.lower() if acl_id else url.lower()
            urls.setdefault(dedupe_key, (url, discovered_by))

        for venue in query.preferred_venues:
            if "aclanthology.org" in venue:
                add_url(venue, "preferred_acl_url")
        if query.doi:
            doi_url = acl_record_url_from_doi(query.doi)
            if doi_url:
                add_url(doi_url, "query_acl_doi")
        if not urls and query.title and query.year is not None and query.authors:
            for bridge_candidate in CrossrefAdapter(fetcher=self.fetcher).discover(query):
                if not bridge_candidate.doi or not title_match_supported(query, bridge_candidate):
                    continue
                bridge_url = acl_record_url_from_doi(bridge_candidate.doi)
                if bridge_url:
                    add_url(bridge_url, "crossref_acl_doi_bridge")
        candidates: list[CandidateRecord] = []
        for url, discovered_by in urls.values():
            html = self.fetcher(url)
            candidate = candidate_from_acl_html(url, html)
            candidate.raw["discovered_by"] = discovered_by
            if not query.title or title_match_supported(query, candidate):
                candidates.append(candidate)
        return candidates

    def fetch_authority(self, candidate: CandidateRecord) -> AuthorityRecord | None:
        if candidate.source != self.name or not candidate.url:
            return None
        return AuthorityRecord(
            source=self.name,
            record_url=candidate.url,
            record_type="conference_proceedings",
            source_priority=candidate.source_priority,
            bibtex_url=candidate.bibtex_url or acl_bibtex_url(candidate.url),
        )

    def find_export_endpoints(self, authority: AuthorityRecord) -> list[ExportEndpoint]:
        if authority.source != self.name:
            return []
        bibtex_url = authority.bibtex_url or acl_bibtex_url(authority.record_url)
        if not bibtex_url:
            return []
        return [
            ExportEndpoint(
                format="bibtex",
                url=bibtex_url,
                confidence="high",
                discovered_by="acl_id_pattern",
                is_official=True,
            )
        ]

    def fetch_bibtex(self, authority: AuthorityRecord, endpoint: ExportEndpoint) -> BibtexRecord | None:
        if authority.source != self.name or endpoint.format != "bibtex" or not endpoint.is_official:
            return None
        raw_text = self.fetcher(endpoint.url)
        parsed = parse_bibtex_entry(raw_text)
        return BibtexRecord(
            entry_type=parsed["entry_type"],
            citation_key=parsed["citation_key"],
            source_kind="official_export",
            raw_text=raw_text,
            raw_sha256=sha256_text(raw_text),
            normalized_sha256=sha256_text(raw_text.strip() + "\n"),
        )
