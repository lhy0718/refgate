from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable
from urllib.request import urlopen

from .bibtex import parse_bibtex_entry
from .lockfile import load_lockfile
from .models import LockEntry


Fetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class SourceDownloadItem:
    citation_key: str
    url: str | None
    output: str
    status: str
    source: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_key": self.citation_key,
            "url": self.url,
            "output": self.output,
            "status": self.status,
            "source": self.source,
            "reason": self.reason,
        }


def _default_fetcher(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:
        return response.read()


def _normalize_arxiv_id(value: str) -> str:
    value = value.strip()
    value = re.sub(r"(?i)^arxiv:", "", value)
    value = value.split("/")[-1]
    return value


def _arxiv_pdf_url(arxiv_id: str) -> str | None:
    normalized = _normalize_arxiv_id(arxiv_id)
    if not normalized:
        return None
    return f"https://arxiv.org/pdf/{normalized}.pdf"


def _url_from_arxiv_record(url: str) -> str | None:
    match = re.search(r"arxiv\.org/(?:abs|html|pdf)/([^?#/]+)", url, flags=re.IGNORECASE)
    if not match:
        return None
    return _arxiv_pdf_url(match.group(1).removesuffix(".pdf"))


def _url_from_acl_record(url: str) -> str | None:
    match = re.match(r"^(https://aclanthology\.org/[^?#/]+)(?:/)?(?:[?#].*)?$", url, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}.pdf"
    return None


def _url_from_neurips_record(url: str) -> str | None:
    if "proceedings.neurips.cc" not in url:
        return None
    if url.lower().endswith(".pdf"):
        return url
    pdf_url = re.sub(r"(proceedings\.neurips\.cc)/paper/", r"\1/paper_files/paper/", url)
    pdf_url = pdf_url.replace("/hash/", "/file/")
    pdf_url = re.sub(r"-Abstract(?=[-.])", "-Paper", pdf_url)
    pdf_url = re.sub(r"\.html(?:[?#].*)?$", ".pdf", pdf_url)
    return pdf_url if pdf_url != url else None


def _url_from_iclr_record(url: str) -> str | None:
    if "proceedings.iclr.cc" not in url:
        return None
    if url.lower().endswith(".pdf"):
        return url
    pdf_url = url.replace("/hash/", "/file/")
    pdf_url = re.sub(r"-Abstract(?=[-.])", "-Paper", pdf_url)
    pdf_url = re.sub(r"\.html(?:[?#].*)?$", ".pdf", pdf_url)
    return pdf_url if pdf_url != url else None


def _url_from_pmlr_record(url: str) -> str | None:
    if "proceedings.mlr.press" not in url:
        return None
    if url.lower().endswith(".pdf"):
        return url
    pdf_url = re.sub(r"\.html(?:[?#].*)?$", ".pdf", url)
    return pdf_url if pdf_url != url else None


def _url_from_acm_record(url: str) -> str | None:
    match = re.match(r"^(https://dl\.acm\.org)/doi/(?:abs/|pdf/)?(.+?)(?:[?#].*)?$", url, flags=re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1)}/doi/pdf/{match.group(2)}"


def _url_from_jmlr_record(url: str) -> str | None:
    if "jmlr.org" not in url:
        return None
    if url.lower().endswith(".pdf"):
        return url
    legacy_match = re.match(r"^(https?://(?:www\.)?jmlr\.org)/papers/v(\d+)/([^/?#]+)\.html(?:[?#].*)?$", url, flags=re.IGNORECASE)
    if legacy_match:
        return f"{legacy_match.group(1)}/papers/volume{legacy_match.group(2)}/{legacy_match.group(3)}/{legacy_match.group(3)}.pdf"
    pdf_url = re.sub(r"\.html(?:[?#].*)?$", ".pdf", url)
    return pdf_url if pdf_url != url else None


def _url_from_cvf_record(url: str) -> str | None:
    if "openaccess.thecvf.com" not in url:
        return None
    if url.lower().endswith(".pdf"):
        return url
    pdf_url = url.replace("/html/", "/papers/")
    pdf_url = re.sub(r"\.html(?:[?#].*)?$", ".pdf", pdf_url)
    return pdf_url if pdf_url != url else None


def _url_from_springer_record(url: str) -> str | None:
    match = re.match(r"^(https://link\.springer\.com)/(?:chapter|article)/(.+?)(?:[?#].*)?$", url, flags=re.IGNORECASE)
    if not match:
        return url if "link.springer.com" in url and url.lower().endswith(".pdf") else None
    return f"{match.group(1)}/content/pdf/{match.group(2)}.pdf"


def _url_from_pnas_record(url: str) -> str | None:
    match = re.match(r"^(https://(?:www\.)?pnas\.org)/doi/(?:abs|full|pdf)/(.+?)(?:[?#].*)?$", url, flags=re.IGNORECASE)
    if not match:
        return url if "pnas.org" in url and url.lower().endswith(".pdf") else None
    return f"{match.group(1)}/doi/pdf/{match.group(2)}"


def _url_from_science_record(url: str) -> str | None:
    match = re.match(r"^(https://www\.science\.org)/doi/(?:abs|full|pdf)/(.+?)(?:[?#].*)?$", url, flags=re.IGNORECASE)
    if not match:
        return url if "science.org" in url and url.lower().endswith(".pdf") else None
    return f"{match.group(1)}/doi/pdf/{match.group(2)}"


def _url_from_frontiers_record(url: str) -> str | None:
    if "frontiersin.org" not in url:
        return None
    if url.lower().endswith("/pdf"):
        return url
    pdf_url = re.sub(r"/full(?:[?#].*)?$", "/pdf", url)
    return pdf_url if pdf_url != url else None


def _url_from_mdpi_record(url: str) -> str | None:
    if "mdpi.com" not in url:
        return None
    if url.lower().endswith("/pdf") or url.lower().endswith(".pdf"):
        return url
    pdf_url = re.sub(r"/htm(?:[?#].*)?$", "/pdf", url)
    if pdf_url != url:
        return pdf_url
    cleaned = re.sub(r"[?#].*$", "", url).rstrip("/")
    return f"{cleaned}/pdf"


def _source_from_pdf_url(url: str, fallback: str | None = None) -> str | None:
    lowered = url.lower()
    if "arxiv.org/" in lowered:
        return "arxiv"
    if "aclanthology.org/" in lowered:
        return "acl"
    if "proceedings.iclr.cc/" in lowered:
        return "iclr"
    if "proceedings.neurips.cc/" in lowered:
        return "neurips"
    if "proceedings.mlr.press/" in lowered:
        return "pmlr"
    if "dl.acm.org/" in lowered:
        return "acm"
    if "openaccess.thecvf.com/" in lowered:
        return "cvf"
    if "jmlr.org/" in lowered:
        return "jmlr"
    if "link.springer.com/" in lowered:
        return "springer"
    if "academic.oup.com/" in lowered:
        return "oxford"
    if "cambridge.org/" in lowered:
        return "cambridge"
    if "pnas.org/" in lowered:
        return "pnas"
    if "science.org/" in lowered:
        return "science"
    if "frontiersin.org/" in lowered:
        return "frontiers"
    if "mdpi.com/" in lowered:
        return "mdpi"
    if "drops.dagstuhl.de/" in lowered:
        return "lipics"
    return fallback


def source_pdf_url_for_entry(entry: LockEntry) -> tuple[str | None, str | None, str | None]:
    record = entry.record or {}
    authority = entry.authority or {}
    source = str(authority.get("source") or "")
    canonical_text = str((entry.bibtex or {}).get("canonical_text") or "")
    canonical_url = _url_from_bibtex(canonical_text)
    urls = [
        canonical_url or "",
        str(record.get("url") or ""),
        str(authority.get("record_url") or ""),
        str(authority.get("bibtex_url") or ""),
    ]
    for url in urls:
        if not url:
            continue
        if url.lower().endswith(".pdf"):
            return url, _source_from_pdf_url(url, source or "direct_pdf"), None
        arxiv_url = _url_from_arxiv_record(url)
        if arxiv_url:
            return arxiv_url, "arxiv", None
        acl_url = _url_from_acl_record(url)
        if acl_url:
            return acl_url, "acl", None
        neurips_url = _url_from_neurips_record(url)
        if neurips_url:
            return neurips_url, "neurips", None
        iclr_url = _url_from_iclr_record(url)
        if iclr_url:
            return iclr_url, "iclr", None
        pmlr_url = _url_from_pmlr_record(url)
        if pmlr_url:
            return pmlr_url, "pmlr", None
        acm_url = _url_from_acm_record(url)
        if acm_url:
            return acm_url, "acm", None
        cvf_url = _url_from_cvf_record(url)
        if cvf_url:
            return cvf_url, "cvf", None
        jmlr_url = _url_from_jmlr_record(url)
        if jmlr_url:
            return jmlr_url, "jmlr", None
        springer_url = _url_from_springer_record(url)
        if springer_url:
            return springer_url, "springer", None
        pnas_url = _url_from_pnas_record(url)
        if pnas_url:
            return pnas_url, "pnas", None
        science_url = _url_from_science_record(url)
        if science_url:
            return science_url, "science", None
        frontiers_url = _url_from_frontiers_record(url)
        if frontiers_url:
            return frontiers_url, "frontiers", None
        mdpi_url = _url_from_mdpi_record(url)
        if mdpi_url:
            return mdpi_url, "mdpi", None
    arxiv_id = str(record.get("arxiv_id") or "")
    if arxiv_id:
        return _arxiv_pdf_url(arxiv_id), "arxiv", None
    return None, source or None, "no_download_url"


def _url_from_bibtex(text: str) -> str | None:
    if not text.strip():
        return None
    try:
        entry = parse_bibtex_entry(text)
    except ValueError:
        return None
    url = entry.get("url", "").strip()
    return url or None


def build_source_download_plan(
    lock_path: str | Path,
    *,
    source_dir: str | Path = ".refgate/sources",
    citation_keys: list[str] | None = None,
) -> dict[str, Any]:
    lockfile = load_lockfile(lock_path)
    requested = set(citation_keys or [])
    root = Path(source_dir)
    items: list[SourceDownloadItem] = []
    warnings: list[dict[str, Any]] = []

    for entry in lockfile.entries:
        if requested and entry.citation_key not in requested:
            continue
        url, source, reason = source_pdf_url_for_entry(entry)
        output = root / f"{entry.citation_key}.pdf"
        status = "planned" if url else "missing_url"
        if not url:
            warnings.append(
                {
                    "code": "SOURCE_DOWNLOAD_URL_MISSING",
                    "message": "No deterministic source PDF URL could be derived from the lockfile entry.",
                    "citation_key": entry.citation_key,
                }
            )
        items.append(SourceDownloadItem(entry.citation_key, url, str(output), status, source, reason))

    missing_requested = sorted(requested - {item.citation_key for item in items})
    for citation_key in missing_requested:
        warnings.append(
            {
                "code": "SOURCE_DOWNLOAD_LOCK_ENTRY_MISSING",
                "message": "Requested citation key is not present in the lockfile.",
                "citation_key": citation_key,
            }
        )

    return {
        "lock": str(lock_path),
        "source_dir": str(root),
        "live": False,
        "item_count": len(items),
        "downloaded_count": 0,
        "items": [item.to_dict() for item in items],
        "warnings": warnings,
        "ok": True,
    }


def download_sources(
    lock_path: str | Path,
    *,
    source_dir: str | Path = ".refgate/sources",
    citation_keys: list[str] | None = None,
    live: bool = False,
    overwrite: bool = False,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    plan = build_source_download_plan(lock_path, source_dir=source_dir, citation_keys=citation_keys)
    if not live:
        return plan

    root = Path(source_dir)
    root.mkdir(parents=True, exist_ok=True)
    fetch = fetcher or _default_fetcher
    items: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    downloaded = 0

    for item in plan["items"]:
        url = item.get("url")
        output = Path(item["output"])
        if not url:
            items.append({**item, "status": "missing_url"})
            continue
        if output.exists() and not overwrite:
            items.append({**item, "status": "skipped_exists"})
            continue
        try:
            payload = fetch(url)
            output.write_bytes(payload)
            downloaded += 1
            items.append({**item, "status": "downloaded", "bytes": len(payload)})
        except Exception as exc:
            items.append({**item, "status": "download_failed", "error": f"{exc.__class__.__name__}: {exc}"})
            blocking.append(
                {
                    "code": "SOURCE_DOWNLOAD_FAILED",
                    "message": "Source PDF download failed.",
                    "citation_key": item["citation_key"],
                    "evidence": [url, f"{exc.__class__.__name__}: {exc}"],
                }
            )

    return {
        **plan,
        "live": True,
        "downloaded_count": downloaded,
        "items": items,
        "blocking_issues": blocking,
        "ok": not blocking,
    }
