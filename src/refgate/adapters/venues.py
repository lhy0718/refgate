from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

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

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        candidates = super().discover(query)
        if query.doi and query.doi.lower().startswith("10.1145/"):
            candidates.append(
                CandidateRecord(
                    source=self.name,
                    title=query.title,
                    authors=query.authors,
                    year=query.year,
                    venue=self.venue_label,
                    doi=query.doi,
                    url=f"https://dl.acm.org/doi/{quote(query.doi, safe='/')}",
                    is_official_record=True,
                    bibtex_url=_acm_bibtex_url(query.doi),
                    source_priority=1,
                    raw={"metadata_source": "doi_derived_official_export"},
                )
            )
        return candidates

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

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        candidates = super().discover(query)
        if query.doi and query.doi.lower().startswith("10.1109/"):
            record_url = _doi_redirect_url(query.doi) or f"https://doi.org/{query.doi}"
            document_id = _ieee_document_id_from_url(record_url)
            candidates.append(
                CandidateRecord(
                    source=self.name,
                    title=query.title,
                    authors=query.authors,
                    year=query.year,
                    venue=self.venue_label,
                    doi=query.doi,
                    url=record_url,
                    is_official_record=True,
                    bibtex_url=_ieee_bibtex_url(document_id) if document_id else None,
                    source_priority=1,
                    raw={"metadata_source": "doi_redirect_official_record"},
                )
            )
        return candidates

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

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        candidates = super().discover(query)
        if query.doi and query.doi.lower().startswith("10.1518/"):
            candidates.append(
                CandidateRecord(
                    source=self.name,
                    title=query.title,
                    authors=query.authors,
                    year=query.year,
                    venue=self.venue_label,
                    doi=query.doi,
                    url=f"https://journals.sagepub.com/doi/{quote(query.doi, safe='/')}",
                    is_official_record=True,
                    bibtex_url=_sage_bibtex_url(query.doi),
                    source_priority=1,
                    raw={"metadata_source": "doi_derived_official_export"},
                )
            )
        return candidates


class TaylorFrancisAdapter(OfficialHtmlAdapter):
    name = "taylorfrancis"
    venue_label = "Taylor & Francis"
    url_domains = ("tandfonline.com",)


class OpenReviewAdapter(OfficialHtmlAdapter):
    name = "openreview"
    venue_label = "OpenReview"
    url_domains = ("openreview.net",)

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        candidates: list[CandidateRecord] = []
        seen_urls: set[str] = set()

        for value in query.preferred_venues:
            forum_id = _openreview_forum_id(value)
            if forum_id:
                candidate = self._candidate_from_api_id(forum_id)
                if candidate and candidate.url not in seen_urls:
                    candidates.append(candidate)
                    seen_urls.add(candidate.url or "")

        for venue_query in _openreview_venue_queries(query):
            matched = False
            for candidate in self._candidates_from_api_query(venue_query, match_query=query):
                if candidate.url not in seen_urls:
                    candidates.append(candidate)
                    seen_urls.add(candidate.url or "")
                    matched = True
            if matched:
                return candidates

        if candidates:
            return candidates
        return super().discover(query)

    def candidate_from_html(self, url: str, html: str) -> CandidateRecord:
        candidate = super().candidate_from_html(url, html)
        candidate.bibtex_url = None
        candidate.raw["official_bibtex_status"] = "not_discovered"
        _fill_openreview_embedded_metadata(candidate, html)
        return candidate

    def _candidate_from_api_id(self, forum_id: str) -> CandidateRecord | None:
        payload = self._fetch_api({"id": forum_id})
        notes = payload.get("notes") or []
        if not notes:
            return None
        return _openreview_candidate_from_note(notes[0])

    def _candidates_from_api_query(self, params: dict[str, str | int], *, match_query: PaperQuery | None = None) -> list[CandidateRecord]:
        limit = int(params.get("limit", 1000))
        max_pages = int(params.get("_max_pages", 5))
        api_params = {key: value for key, value in params.items() if not str(key).startswith("_")}
        candidates: list[CandidateRecord] = []
        for offset in range(0, limit * max_pages, limit):
            page_params = {**api_params, "offset": offset}
            payload = self._fetch_api(page_params)
            notes = payload.get("notes") or []
            page_candidates = [_openreview_candidate_from_note(note) for note in notes]
            if match_query is not None:
                matches = [candidate for candidate in page_candidates if _candidate_matches_openreview_query(candidate, match_query)]
                if matches:
                    return matches
            else:
                candidates.extend(page_candidates)
            count = int(payload.get("count") or len(notes))
            if len(notes) < limit or offset + limit >= count:
                break
        return candidates

    def _fetch_api(self, params: dict[str, str | int]) -> dict:
        url = "https://api2.openreview.net/notes?" + urlencode(params)
        return json.loads(self.fetcher(url))


def _openreview_forum_id(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.netloc.lower().endswith("openreview.net"):
        query_id = parse_qs(parsed.query).get("id")
        if query_id and query_id[0]:
            return query_id[0]
    if re.fullmatch(r"[A-Za-z0-9_-]{8,16}", value.strip()):
        return value.strip()
    return None


def _openreview_field_value(content: dict, field: str):
    value = content.get(field)
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _openreview_candidate_from_note(note: dict) -> CandidateRecord:
    content = note.get("content") or {}
    title = str(_openreview_field_value(content, "title") or "")
    authors_value = _openreview_field_value(content, "authors") or []
    authors = [str(author) for author in authors_value] if isinstance(authors_value, list) else []
    venue = _openreview_field_value(content, "venue") or _openreview_field_value(content, "venueid") or "OpenReview"
    bibtex = str(_openreview_field_value(content, "_bibtex") or "")
    year_match = re.search(r"\byear\s*=\s*\{?(\d{4})", bibtex, flags=re.IGNORECASE) or re.search(r"\b(20\d{2})\b", str(venue))
    forum_id = note.get("forum") or note.get("id")
    url = f"https://openreview.net/forum?id={forum_id}" if forum_id else None
    candidate = CandidateRecord(
        source="openreview",
        title=title,
        authors=authors,
        year=int(year_match.group(1)) if year_match else None,
        venue=str(venue),
        url=url,
        is_official_record=True,
        bibtex_url=None,
        source_priority=2,
        raw={
            "metadata_source": "openreview_api",
            "authority_role": "final_authority",
            "official_bibtex_status": "not_discovered",
            "openreview_note_id": note.get("id"),
            "openreview_venueid": _openreview_field_value(content, "venueid"),
        },
    )
    _fill_openreview_embedded_metadata(candidate, json.dumps(note, ensure_ascii=False))
    return candidate


def _openreview_venue_queries(query: PaperQuery) -> list[dict[str, str | int]]:
    if not query.title or not query.year:
        return []
    venue_text = " ".join(str(value).lower() for value in query.preferred_venues)
    title_text = query.title.lower()
    params: list[dict[str, str | int]] = []
    if "learning representations" in venue_text or "iclr" in venue_text:
        params.extend(
            [
                {"content.venueid": f"ICLR.cc/{query.year}/Conference", "limit": 1000},
                {"content.venue": f"ICLR {query.year} Poster", "limit": 1000},
            ]
        )
    if "neural information processing" in venue_text or "neurips" in venue_text:
        if "compression" in title_text:
            params.append({"content.venue": f"Compression Workshop @ NeurIPS {query.year}", "limit": 1000})
        params.extend(
            [
                {"content.venue": f"NeurIPS {query.year} Workshop", "limit": 1000},
                {"content.venue": f"NeurIPS {query.year} Poster", "limit": 1000},
                {"content.venueid": f"NeurIPS.cc/{query.year}/Conference", "limit": 1000},
            ]
        )
    if "tmlr" in venue_text or "transactions on machine learning research" in venue_text:
        params.append({"content.venue": "Transactions on Machine Learning Research", "limit": 1000})
    return params


def _candidate_matches_openreview_query(candidate: CandidateRecord, query: PaperQuery) -> bool:
    if normalize_title(candidate.title) != normalize_title(query.title):
        return False
    if query.year and candidate.year and int(query.year) != int(candidate.year):
        return False
    return True


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


def _sage_bibtex_url(doi: str) -> str:
    return f"https://journals.sagepub.com/action/downloadCitation?doi={quote(doi, safe='')}&format=bibtex"


def _doi_redirect_url(doi: str) -> str | None:
    request = Request(f"https://doi.org/{doi}", headers={"User-Agent": "refgate/0.1"}, method="HEAD")
    try:
        with urlopen(request, timeout=20) as response:
            return response.geturl()
    except Exception:
        return None


def _ieee_document_id_from_url(url: str) -> str | None:
    match = re.search(r"ieeexplore\.ieee\.org/document/(\d+)", url)
    return match.group(1) if match else None


def _ieee_bibtex_url(document_id: str) -> str:
    return (
        "https://ieeexplore.ieee.org/xpl/downloadCitations"
        f"?recordIds={quote(document_id, safe='')}"
        "&citations-format=citation-abstract&download-format=download-bibtex"
    )


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
