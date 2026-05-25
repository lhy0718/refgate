from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable
from urllib.parse import quote, urlencode
from urllib.request import urlopen
import re
import textwrap
import xml.etree.ElementTree as ET

from refgate.bibtex import sha256_text
from refgate.models import AuthorityRecord, BibtexRecord, CandidateRecord, PaperQuery
from refgate.resolver import normalize_author, normalize_title


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
ARXIV_API_URL = "https://export.arxiv.org/api/query"


def normalize_arxiv_id(value: str) -> tuple[str, str | None]:
    text = value.strip()
    text = re.sub(r"^arxiv:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", text, flags=re.IGNORECASE)
    text = text.removesuffix(".pdf")
    match = re.match(r"(?P<base>[A-Za-z.-]+/\d{7}|\d{4}\.\d{4,5})(?P<version>v\d+)?$", text)
    if not match:
        return text, None
    return match.group("base"), match.group("version")


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _entry_text(entry: ET.Element, path: str) -> str:
    return _clean_text(entry.findtext(path, namespaces=ATOM_NS))


def _entry_year(entry: ET.Element) -> int | None:
    published = _entry_text(entry, "atom:published") or _entry_text(entry, "atom:updated")
    if len(published) >= 4 and published[:4].isdigit():
        return int(published[:4])
    return None


def _format_bibtex_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _default_citation_key(candidate: CandidateRecord) -> str:
    first_author = candidate.authors[0] if candidate.authors else "arxiv"
    first_author_part = normalize_author(first_author).split(" ")[-1] if normalize_author(first_author) else "arxiv"
    year = str(candidate.year or "nd")
    title_part = re.sub(r"[^a-z0-9]+", "", normalize_title(candidate.title).split(" ")[0])
    return f"{first_author_part}{year}{title_part or 'preprint'}"


def _url_fetcher(url: str) -> str:
    with urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


@dataclass
class ArxivAdapter:
    fetcher: Callable[[str], str] = _url_fetcher
    accessed_at: str | None = None

    name: str = "arxiv"
    role: str = "both"

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        if query.arxiv_id:
            xml_text = self.fetcher(self._id_lookup_url(query.arxiv_id))
            return [candidate for candidate in self._parse_feed(xml_text, query) if self._matches_arxiv_id(query, candidate)]

        xml_text = self.fetcher(self._title_search_url(query.title))
        return [
            candidate
            for candidate in self._parse_feed(xml_text, query)
            if normalize_title(candidate.title) == normalize_title(query.title)
        ]

    def fetch_authority(self, candidate: CandidateRecord) -> AuthorityRecord | None:
        if candidate.source != self.name or not candidate.url:
            return None
        return AuthorityRecord(
            source=self.name,
            record_url=candidate.url,
            record_type="preprint_record",
            source_priority=candidate.source_priority,
            bibtex_url=None,
        )

    def find_export_endpoints(self, authority: AuthorityRecord) -> list:
        if authority.source != self.name:
            return []
        return []

    def fetch_bibtex(self, authority: AuthorityRecord, endpoint) -> BibtexRecord | None:
        return None

    def build_manual_bibtex(self, candidate: CandidateRecord, citation_key: str | None = None) -> BibtexRecord:
        key = citation_key or _default_citation_key(candidate)
        arxiv_id = candidate.arxiv_id or candidate.raw.get("arxiv_id", "")
        fields = [
            ("title", candidate.title),
            ("author", " and ".join(candidate.authors)),
        ]
        if candidate.year is not None:
            fields.append(("year", str(candidate.year)))
        if arxiv_id:
            fields.append(("eprint", arxiv_id))
        fields.extend(
            [
                ("archivePrefix", "arXiv"),
                ("url", candidate.url or f"https://arxiv.org/abs/{arxiv_id}"),
            ]
        )
        primary_class = candidate.raw.get("primary_category")
        if primary_class:
            fields.append(("primaryClass", primary_class))
        version = candidate.raw.get("arxiv_version")
        accessed_at = candidate.raw.get("accessed_at") or self.accessed_at or date.today().isoformat()
        if version or accessed_at:
            note_parts = []
            if version:
                note_parts.append(f"arXiv version {version}")
            if accessed_at:
                note_parts.append(f"accessed {accessed_at}")
            fields.append(("note", ", ".join(note_parts)))

        rendered_fields = "\n".join(
            f"  {name} = {{{_format_bibtex_value(value)}}}," for name, value in fields if value
        )
        raw_text = f"@misc{{{key},\n{rendered_fields}\n}}\n"
        return BibtexRecord(
            entry_type="misc",
            citation_key=key,
            source_kind="arxiv_manual_normalized",
            raw_text=raw_text,
            raw_sha256=sha256_text(raw_text),
            normalized_sha256=sha256_text(textwrap.dedent(raw_text).strip() + "\n"),
        )

    def _id_lookup_url(self, arxiv_id: str) -> str:
        base_id, version = normalize_arxiv_id(arxiv_id)
        id_list = base_id + (version or "")
        return f"{ARXIV_API_URL}?{urlencode({'id_list': id_list, 'start': 0, 'max_results': 1})}"

    def _title_search_url(self, title: str) -> str:
        query = f'ti:"{title}"'
        return f"{ARXIV_API_URL}?search_query={quote(query)}&start=0&max_results=10"

    def _matches_arxiv_id(self, query: PaperQuery, candidate: CandidateRecord) -> bool:
        if not query.arxiv_id or not candidate.arxiv_id:
            return False
        query_base, query_version = normalize_arxiv_id(query.arxiv_id)
        if query_base.lower() != candidate.arxiv_id.lower():
            return False
        if query_version is None:
            return True
        return candidate.raw.get("arxiv_version", "").lower() == query_version.lower()

    def _parse_feed(self, xml_text: str, query: PaperQuery) -> list[CandidateRecord]:
        root = ET.fromstring(xml_text)
        return [self._entry_to_candidate(entry, query) for entry in root.findall("atom:entry", ATOM_NS)]

    def _entry_to_candidate(self, entry: ET.Element, query: PaperQuery) -> CandidateRecord:
        arxiv_url = _entry_text(entry, "atom:id")
        arxiv_id_text = arxiv_url.rsplit("/", 1)[-1] if arxiv_url else ""
        arxiv_id, arxiv_version = normalize_arxiv_id(arxiv_id_text)
        authors = [_clean_text(author.findtext("atom:name", namespaces=ATOM_NS)) for author in entry.findall("atom:author", ATOM_NS)]
        authors = [author for author in authors if author]
        doi = _entry_text(entry, "arxiv:doi") or None
        journal_ref = _entry_text(entry, "arxiv:journal_ref") or None
        primary_category = entry.find("arxiv:primary_category", ATOM_NS)
        official_record_status = self._official_record_status(query, doi=doi, journal_ref=journal_ref)
        record_url = f"https://arxiv.org/abs/{arxiv_id}{arxiv_version or ''}" if arxiv_id else arxiv_url

        return CandidateRecord(
            source=self.name,
            title=_entry_text(entry, "atom:title"),
            authors=authors,
            year=_entry_year(entry),
            venue=journal_ref or "arXiv preprint",
            doi=doi,
            arxiv_id=arxiv_id,
            url=record_url,
            is_official_record=True,
            bibtex_url=None,
            source_priority=2,
            raw={
                "arxiv_id": arxiv_id,
                "arxiv_version": arxiv_version,
                "accessed_at": self.accessed_at or date.today().isoformat(),
                "published": _entry_text(entry, "atom:published"),
                "updated": _entry_text(entry, "atom:updated"),
                "summary": _entry_text(entry, "atom:summary"),
                "primary_category": primary_category.get("term") if primary_category is not None else None,
                "official_record_status": official_record_status,
                "bibtex_source_kind": "arxiv_manual_normalized",
                "final_authority_source": None if official_record_status == "official_record_pending" else "arxiv",
            },
        )

    def _official_record_status(self, query: PaperQuery, *, doi: str | None, journal_ref: str | None) -> str:
        if doi or journal_ref:
            return "linked_publication_metadata"
        preferred_official_venues = [
            venue
            for venue in query.preferred_venues
            if "arxiv" not in venue.lower() and "preprint" not in venue.lower()
        ]
        if preferred_official_venues:
            return "official_record_pending"
        return "preprint_only"
