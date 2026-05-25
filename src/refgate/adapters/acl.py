from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.request import urlopen
import re

from refgate.bibtex import parse_bibtex_entry, sha256_text
from refgate.models import AuthorityRecord, BibtexRecord, CandidateRecord, PaperQuery
from refgate.resolver import normalize_title

from .base import ExportEndpoint
from .official_html import meta_content, meta_contents


ACL_BASE_URL = "https://aclanthology.org"


def extract_acl_id(url: str) -> str | None:
    match = re.search(r"aclanthology\.org/([A-Za-z0-9.-]+)/?", url)
    return match.group(1) if match else None


def acl_bibtex_url(record_url: str) -> str | None:
    acl_id = extract_acl_id(record_url)
    if not acl_id:
        return None
    return f"{ACL_BASE_URL}/{acl_id}.bib"


def _url_fetcher(url: str) -> str:
    with urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


def candidate_from_acl_html(url: str, html: str) -> CandidateRecord:
    title = meta_content(html, "citation_title") or meta_content(html, "og:title") or ""
    authors = meta_contents(html, "citation_author")
    year_text = meta_content(html, "citation_publication_date") or ""
    year_match = re.search(r"\d{4}", year_text)
    bibtex_url = meta_content(html, "citation_bibtex_url") or acl_bibtex_url(url)
    return CandidateRecord(
        source="acl",
        title=title,
        authors=[re.sub(r"\s+", " ", author).strip() for author in authors],
        year=int(year_match.group(0)) if year_match else None,
        venue="ACL Anthology",
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
        urls = [venue for venue in query.preferred_venues if "aclanthology.org" in venue]
        candidates: list[CandidateRecord] = []
        for url in urls:
            html = self.fetcher(url)
            candidate = candidate_from_acl_html(url, html)
            if not query.title or normalize_title(candidate.title) == normalize_title(query.title):
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
