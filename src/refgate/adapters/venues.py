from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote, urlparse

from refgate.models import AuthorityRecord, BibtexRecord, CandidateRecord, PaperQuery
from refgate.resolver import normalize_title

from .base import ExportEndpoint, SourceAdapter, default_fetcher
from .official_html import extract_inline_bibtex, find_bibtex_endpoint, official_authority, official_bibtex_record, official_candidate


class OfficialHtmlAdapter(SourceAdapter):
    name = "official_html"
    role = "authority"
    venue_label = "Official venue"
    record_type = "publication_record"
    title_meta = "citation_title"
    author_meta = "citation_author"
    year_meta = "citation_publication_date"
    url_domains: tuple[str, ...] = ()

    def __init__(self, fetcher=default_fetcher):
        self.fetcher = fetcher

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        urls = [venue for venue in query.preferred_venues if self.url_matches(venue)]
        candidates = []
        for url in urls:
            candidates.append(self.discover_url(url))
        return candidates

    def url_matches(self, value: str) -> bool:
        if not self.url_domains:
            return False
        host = urlparse(value).netloc.lower()
        return any(host == domain or host.endswith(f".{domain}") for domain in self.url_domains)

    def candidate_from_html(self, url: str, html: str) -> CandidateRecord:
        candidate = official_candidate(
            source=self.name,
            record_url=url,
            html=html,
            venue=self.venue_label,
            title_meta=self.title_meta,
            author_meta=self.author_meta,
            year_meta=self.year_meta,
        )
        candidate.raw.setdefault("authority_role", "final_authority")
        return candidate

    def discover_url(self, url: str) -> CandidateRecord:
        return self.candidate_from_html(url, self.fetcher(url))

    def fetch_authority(self, candidate: CandidateRecord) -> AuthorityRecord | None:
        return official_authority(candidate, self.name)

    def find_export_endpoints(self, authority: AuthorityRecord) -> list[ExportEndpoint]:
        if authority.source != self.name:
            return []
        if authority.bibtex_url:
            discovered_by = "inline_bibtex_code" if authority.bibtex_url == authority.record_url else "citation_bibtex_url"
            return [
                ExportEndpoint(
                    format="bibtex",
                    url=authority.bibtex_url,
                    confidence="high",
                    discovered_by=discovered_by,
                    is_official=True,
                )
            ]
        html = self.fetcher(authority.record_url)
        endpoint = find_bibtex_endpoint(authority.record_url, html)
        return [endpoint] if endpoint else []

    def fetch_bibtex(self, authority: AuthorityRecord, endpoint: ExportEndpoint) -> BibtexRecord | None:
        if authority.source != self.name or endpoint.format != "bibtex" or not endpoint.is_official:
            return None
        raw_text = self.fetcher(endpoint.url)
        if endpoint.discovered_by == "inline_bibtex_code":
            inline_bibtex = extract_inline_bibtex(raw_text)
            return official_bibtex_record(inline_bibtex) if inline_bibtex else None
        return official_bibtex_record(raw_text)


class PmlrAdapter(OfficialHtmlAdapter):
    name = "pmlr"
    venue_label = "PMLR"
    url_domains = ("proceedings.mlr.press",)


class AcmAdapter(OfficialHtmlAdapter):
    name = "acm"
    venue_label = "ACM"
    url_domains = ("dl.acm.org",)

    def candidate_from_html(self, url: str, html: str) -> CandidateRecord:
        candidate = super().candidate_from_html(url, html)
        if not candidate.doi:
            candidate.doi = _acm_doi_from_url(url) or _json_value(html, "doi")
        if not candidate.title:
            candidate.title = _json_value(html, "name") or _json_value(html, "headline") or ""
        if not candidate.authors:
            candidate.authors = _json_author_names(html)
        if candidate.year is None:
            year_text = _json_value(html, "datePublished") or _json_value(html, "publicationDate") or ""
            year_match = re.search(r"\d{4}", year_text)
            if year_match:
                candidate.year = int(year_match.group(0))
        if not candidate.venue or candidate.venue == self.venue_label:
            candidate.venue = _json_value(html, "isPartOf", nested_field="name") or _json_value(html, "container-title") or self.venue_label
        if not candidate.bibtex_url and candidate.doi:
            candidate.bibtex_url = _acm_bibtex_url(candidate.doi)
        return candidate


class IeeeAdapter(OfficialHtmlAdapter):
    name = "ieee"
    venue_label = "IEEE"
    url_domains = ("ieeexplore.ieee.org",)

    def candidate_from_html(self, url: str, html: str) -> CandidateRecord:
        candidate = super().candidate_from_html(url, html)
        if not candidate.doi:
            doi_match = re.search(r'"doi"\s*:\s*"([^"]+)"', html)
            if doi_match:
                candidate.doi = doi_match.group(1)
        if candidate.year is None:
            year_match = re.search(r'"publicationYear"\s*:\s*"?(\d{4})', html)
            if year_match:
                candidate.year = int(year_match.group(1))
        if not candidate.venue or candidate.venue == self.venue_label:
            venue_match = re.search(r'"displayPublicationTitle"\s*:\s*"([^"]+)"', html)
            if venue_match:
                candidate.venue = venue_match.group(1)
        if not candidate.authors:
            authors_match = re.search(r'"authors"\s*:\s*\[(.*?)\]\s*,\s*"(?:isbn|issn|articleNumber)"', html, flags=re.DOTALL)
            if authors_match:
                candidate.authors = re.findall(r'"name"\s*:\s*"([^"]+)"', authors_match.group(1))
        if not candidate.title:
            title_match = re.search(r'"title"\s*:\s*"([^"]+)"', html)
            if title_match:
                candidate.title = title_match.group(1)
        return candidate


class SpringerAdapter(OfficialHtmlAdapter):
    name = "springer"
    venue_label = "Springer"
    url_domains = ("link.springer.com",)


class OxfordAdapter(OfficialHtmlAdapter):
    name = "oxford"
    venue_label = "Oxford Academic"
    url_domains = ("academic.oup.com",)


class CambridgeAdapter(OfficialHtmlAdapter):
    name = "cambridge"
    venue_label = "Cambridge Core"
    url_domains = ("cambridge.org",)


class PnasAdapter(OfficialHtmlAdapter):
    name = "pnas"
    venue_label = "PNAS"
    url_domains = ("pnas.org",)


class ScienceAdapter(OfficialHtmlAdapter):
    name = "science"
    venue_label = "Science"
    url_domains = ("science.org",)


class FrontiersAdapter(OfficialHtmlAdapter):
    name = "frontiers"
    venue_label = "Frontiers"
    url_domains = ("frontiersin.org",)


class MdpiAdapter(OfficialHtmlAdapter):
    name = "mdpi"
    venue_label = "MDPI"
    url_domains = ("mdpi.com",)


class LipicsAdapter(OfficialHtmlAdapter):
    name = "lipics"
    venue_label = "LIPIcs"
    url_domains = ("drops.dagstuhl.de",)


class ElsevierAdapter(OfficialHtmlAdapter):
    name = "elsevier"
    venue_label = "Elsevier"
    url_domains = ("sciencedirect.com",)


class UsenixAdapter(OfficialHtmlAdapter):
    name = "usenix"
    venue_label = "USENIX"
    url_domains = ("usenix.org",)


class AaaiAdapter(OfficialHtmlAdapter):
    name = "aaai"
    venue_label = "AAAI"
    url_domains = ("aaai.org",)


class CvfAdapter(OfficialHtmlAdapter):
    name = "cvf"
    venue_label = "CVF Open Access"
    url_domains = ("openaccess.thecvf.com",)


class JmlrAdapter(OfficialHtmlAdapter):
    name = "jmlr"
    venue_label = "JMLR"
    url_domains = ("jmlr.org",)


class NatureAdapter(OfficialHtmlAdapter):
    name = "nature"
    venue_label = "Nature Portfolio"
    url_domains = ("nature.com",)


class WileyAdapter(OfficialHtmlAdapter):
    name = "wiley"
    venue_label = "Wiley"
    url_domains = ("onlinelibrary.wiley.com",)


class SageAdapter(OfficialHtmlAdapter):
    name = "sage"
    venue_label = "SAGE"
    url_domains = ("journals.sagepub.com",)


class TaylorFrancisAdapter(OfficialHtmlAdapter):
    name = "taylorfrancis"
    venue_label = "Taylor & Francis"
    url_domains = ("tandfonline.com",)


class OpenReviewAdapter(OfficialHtmlAdapter):
    name = "openreview"
    venue_label = "OpenReview"
    url_domains = ("openreview.net",)

    def candidate_from_html(self, url: str, html: str) -> CandidateRecord:
        candidate = super().candidate_from_html(url, html)
        candidate.bibtex_url = None
        candidate.raw["official_bibtex_status"] = "not_discovered"
        _fill_openreview_embedded_metadata(candidate, html)
        return candidate


def _openreview_json_string(html: str, field: str) -> str | None:
    decoded = html.replace('\\"', '"').replace("\\n", "\n")
    pattern = rf'"{re.escape(field)}"\s*:\s*"([^"]*)"'
    match = re.search(pattern, decoded, flags=re.DOTALL)
    if not match:
        return None
    return unescape(match.group(1))


def _openreview_json_array(html: str, field: str) -> list[str]:
    pattern = rf'\\?"{re.escape(field)}\\?"\s*:\s*\[(.*?)\]'
    match = re.search(pattern, html, flags=re.DOTALL)
    if not match:
        return []
    body = match.group(1).replace('\\"', '"')
    return [unescape(item) for item in re.findall(r'"([^"]*)"', body)]


def _fill_openreview_embedded_metadata(candidate: CandidateRecord, html: str) -> None:
    authors = _openreview_json_array(html, "authors")
    if authors:
        candidate.authors = authors
    venue = _openreview_json_string(html, "venue")
    if venue:
        candidate.venue = venue
    embedded_bibtex = _openreview_json_string(html, "_bibtex")
    if embedded_bibtex:
        candidate.raw["embedded_bibtex_present"] = True
        year_match = re.search(r"\byear\s*=\s*\{?(\d{4})", embedded_bibtex, flags=re.IGNORECASE)
        if year_match:
            candidate.year = int(year_match.group(1))
        arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9.]+)(?:v\d+)?", embedded_bibtex, flags=re.IGNORECASE)
        if arxiv_match:
            candidate.arxiv_id = arxiv_match.group(1).rstrip(".")
    if candidate.arxiv_id is None:
        for field in ("html", "pdf"):
            value = _openreview_json_string(html, field) or ""
            arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9.]+)(?:v\d+)?", value, flags=re.IGNORECASE)
            if arxiv_match:
                candidate.arxiv_id = arxiv_match.group(1).rstrip(".")
                break


def _json_value(html: str, field: str, *, nested_field: str | None = None) -> str | None:
    decoded = html.replace('\\"', '"')
    if nested_field:
        nested_pattern = rf'"{re.escape(field)}"\s*:\s*\{{.*?"{re.escape(nested_field)}"\s*:\s*"([^"]+)"'
        nested_match = re.search(nested_pattern, decoded, flags=re.DOTALL)
        if nested_match:
            return unescape(nested_match.group(1))
        return None
    pattern = rf'"{re.escape(field)}"\s*:\s*"([^"]+)"'
    match = re.search(pattern, decoded, flags=re.DOTALL)
    return unescape(match.group(1)) if match else None


def _json_author_names(html: str) -> list[str]:
    decoded = html.replace('\\"', '"')
    author_block = re.search(r'"author"\s*:\s*\[(.*?)\]', decoded, flags=re.DOTALL)
    if not author_block:
        author_block = re.search(r'"authors"\s*:\s*\[(.*?)\]', decoded, flags=re.DOTALL)
    if not author_block:
        return []
    return [unescape(name) for name in re.findall(r'"name"\s*:\s*"([^"]+)"', author_block.group(1))]


def _acm_doi_from_url(url: str) -> str | None:
    match = re.search(r"dl\.acm\.org/doi/(?:abs/|pdf/)?(10\.\d{4,9}/[^?#]+)", url, flags=re.IGNORECASE)
    return match.group(1).rstrip("/") if match else None


def _acm_bibtex_url(doi: str) -> str:
    return f"https://dl.acm.org/action/exportCiteProcCitation?dois={quote(doi, safe='')}&targetFile=custom-bibtex&format=bibTex"


ADAPTERS: dict[str, type[OfficialHtmlAdapter]] = {
    "aaai": AaaiAdapter,
    "acm": AcmAdapter,
    "cambridge": CambridgeAdapter,
    "cvf": CvfAdapter,
    "elsevier": ElsevierAdapter,
    "frontiers": FrontiersAdapter,
    "ieee": IeeeAdapter,
    "jmlr": JmlrAdapter,
    "lipics": LipicsAdapter,
    "mdpi": MdpiAdapter,
    "nature": NatureAdapter,
    "openreview": OpenReviewAdapter,
    "oxford": OxfordAdapter,
    "pmlr": PmlrAdapter,
    "pnas": PnasAdapter,
    "sage": SageAdapter,
    "science": ScienceAdapter,
    "springer": SpringerAdapter,
    "taylorfrancis": TaylorFrancisAdapter,
    "usenix": UsenixAdapter,
    "wiley": WileyAdapter,
}


def candidate_from_venue_html(source: str, url: str, html: str) -> CandidateRecord:
    if source not in ADAPTERS:
        raise ValueError(f"Unsupported venue source: {source}")
    return ADAPTERS[source]().candidate_from_html(url, html)


def source_matches_query(candidate: CandidateRecord, query: PaperQuery) -> bool:
    if query.title and normalize_title(candidate.title) != normalize_title(query.title):
        return False
    if query.year and candidate.year and int(query.year) != int(candidate.year):
        return False
    return True
