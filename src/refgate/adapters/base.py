from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
import gzip
import zlib
from urllib.request import Request, urlopen

from refgate.models import AuthorityRecord, BibtexRecord, CandidateRecord, PaperQuery


def default_fetcher(url: str) -> str:
    request = Request(url, headers={"User-Agent": "refgate/0.1", "Accept-Encoding": "gzip, deflate, identity"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
        encoding = (response.headers.get("Content-Encoding") or "").lower()
        if "gzip" in encoding or body.startswith(b"\x1f\x8b"):
            body = gzip.decompress(body)
        elif "deflate" in encoding:
            body = zlib.decompress(body)
        return body.decode("utf-8", errors="replace")


@dataclass
class ExportEndpoint:
    format: Literal["bibtex", "ris", "endnote"]
    url: str
    confidence: Literal["high", "medium", "low", "none"]
    discovered_by: str
    is_official: bool


class SourceAdapter(Protocol):
    name: str
    role: Literal["discovery", "authority", "both"]

    def discover(self, query: PaperQuery) -> list[CandidateRecord]:
        ...

    def fetch_authority(self, candidate: CandidateRecord) -> AuthorityRecord | None:
        ...

    def find_export_endpoints(self, authority: AuthorityRecord) -> list[ExportEndpoint]:
        ...

    def fetch_bibtex(self, authority: AuthorityRecord, endpoint: ExportEndpoint) -> BibtexRecord | None:
        ...
