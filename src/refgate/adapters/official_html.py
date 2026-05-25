from __future__ import annotations

from urllib.parse import urljoin
from html import unescape
import re

from refgate.bibtex import parse_bibtex_entry, sha256_text
from refgate.models import AuthorityRecord, BibtexRecord, CandidateRecord

from .base import ExportEndpoint


def _tag_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([A-Za-z_:.-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\"'\s>]+))", tag):
        attrs[match.group(1).lower()] = next(group for group in match.groups()[1:] if group is not None)
    return attrs


def meta_contents(html: str, name: str) -> list[str]:
    values = []
    for match in re.finditer(r"<meta\s+[^>]*>", html, flags=re.IGNORECASE):
        attrs = _tag_attrs(match.group(0))
        attr_name = attrs.get("name") or attrs.get("property")
        if attr_name and attr_name.lower() == name.lower() and attrs.get("content") is not None:
            values.append(unescape(re.sub(r"\s+", " ", attrs["content"]).strip()))
    return values


def meta_content(html: str, name: str) -> str | None:
    values = meta_contents(html, name)
    return values[0] if values else None


def anchor_links(html: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for match in re.finditer(r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, flags=re.IGNORECASE | re.DOTALL):
        href = unescape(match.group(1))
        text = re.sub(r"<[^>]+>", "", match.group(2))
        text = unescape(re.sub(r"\s+", " ", text).strip())
        links.append((href, text))
    return links


def find_bibtex_endpoint(record_url: str, html: str, *, discovered_by: str = "html_anchor_text") -> ExportEndpoint | None:
    for meta_name in ["citation_bibtex_url", "bibtex_url", "dc.bibtex"]:
        value = meta_content(html, meta_name)
        if value:
            return ExportEndpoint(
                format="bibtex",
                url=urljoin(record_url, value),
                confidence="high",
                discovered_by=meta_name,
                is_official=True,
            )
    for href, text in anchor_links(html):
        href_lower = href.lower()
        text_lower = text.lower()
        if (
            "bibtex" in text_lower
            or href_lower.endswith(".bib")
            or "/bibtex" in href_lower
            or "format=bibtex" in href_lower
        ):
            return ExportEndpoint(
                format="bibtex",
                url=urljoin(record_url, href),
                confidence="high",
                discovered_by=discovered_by,
                is_official=True,
            )
    if extract_inline_bibtex(html):
        return ExportEndpoint(
            format="bibtex",
            url=record_url,
            confidence="high",
            discovered_by="inline_bibtex_code",
            is_official=True,
        )
    return None


def extract_inline_bibtex(html: str) -> str | None:
    for pattern in [
        r"<code\b[^>]*\bid=[\"']bibtex[\"'][^>]*>(.*?)</code>",
        r"<pre\b[^>]*\bid=[\"']bibtex[\"'][^>]*>(.*?)</pre>",
        r"<textarea\b[^>]*\bid=[\"']bibtex[\"'][^>]*>(.*?)</textarea>",
    ]:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        text = re.sub(r"<[^>]+>", "", match.group(1))
        text = unescape(text).strip()
        if re.match(r"@\w+\s*\{", text):
            return text + "\n"
    return None


def _first_meta(html: str, names: list[str]) -> str | None:
    for name in names:
        value = meta_content(html, name)
        if value:
            return value
    return None


def _doi_from_meta(html: str) -> str | None:
    value = _first_meta(html, ["citation_doi", "dc.identifier", "dc.identifier.doi", "prism.doi", "doi"])
    if not value:
        return None
    match = re.search(r"10\.\d{4,9}/\S+", value, flags=re.IGNORECASE)
    return match.group(0).rstrip(" .;,") if match else value.strip()


def official_bibtex_record(raw_text: str) -> BibtexRecord:
    parsed = parse_bibtex_entry(raw_text)
    return BibtexRecord(
        entry_type=parsed["entry_type"],
        citation_key=parsed["citation_key"],
        source_kind="official_export",
        raw_text=raw_text,
        raw_sha256=sha256_text(raw_text),
        normalized_sha256=sha256_text(raw_text.strip() + "\n"),
    )


def official_candidate(
    *,
    source: str,
    record_url: str,
    html: str,
    title_meta: str,
    author_meta: str,
    year_meta: str,
    venue: str,
) -> CandidateRecord:
    title = meta_content(html, title_meta) or meta_content(html, "citation_title") or meta_content(html, "og:title") or ""
    authors = meta_contents(html, author_meta)
    year_text = meta_content(html, year_meta) or meta_content(html, "citation_publication_date") or ""
    year_match = re.search(r"\d{4}", year_text)
    endpoint = find_bibtex_endpoint(record_url, html)
    doi = _doi_from_meta(html)
    venue_value = _first_meta(
        html,
        [
            "citation_conference_title",
            "citation_journal_title",
            "citation_inbook_title",
            "prism.publicationName",
            "dc.source",
        ],
    )
    return CandidateRecord(
        source=source,
        title=title,
        authors=[re.sub(r"\s+", " ", author).strip() for author in authors],
        year=int(year_match.group(0)) if year_match else None,
        venue=venue_value or venue,
        doi=doi,
        url=record_url,
        is_official_record=True,
        bibtex_url=endpoint.url if endpoint else None,
        source_priority=1,
        raw={"metadata_source": f"{source}_html"},
    )


def official_authority(candidate: CandidateRecord, source: str) -> AuthorityRecord | None:
    if candidate.source != source or not candidate.url:
        return None
    return AuthorityRecord(
        source=source,
        record_url=candidate.url,
        record_type="conference_proceedings",
        source_priority=candidate.source_priority,
        bibtex_url=candidate.bibtex_url,
    )
