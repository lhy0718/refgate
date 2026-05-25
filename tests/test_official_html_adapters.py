from pathlib import Path

from refgate.adapters.acl import candidate_from_acl_html
from refgate.adapters.iclr import IclrAdapter, candidate_from_iclr_html, iclr_record_url
from refgate.adapters.neurips import NeuripsAdapter, candidate_from_neurips_html, neurips_record_url
from refgate.models import PaperQuery
from refgate.resolver import normalize_author, normalize_title


FIXTURES = Path(__file__).parent / "fixtures"


def test_acl_candidate_parser_accepts_content_first_meta_attrs():
    html = (
        '<html><head><meta content="Content First Title" name=citation_title>'
        '<meta content="Ada Smith" name=citation_author>'
        '<meta content="2026/8" name=citation_publication_date></head></html>'
    )

    candidate = candidate_from_acl_html("https://aclanthology.org/2026.acl-main.1/", html)

    assert candidate.title == "Content First Title"
    assert candidate.authors == ["Ada Smith"]
    assert candidate.year == 2026
    assert candidate.bibtex_url == "https://aclanthology.org/2026.acl-main.1.bib"


def test_title_normalization_ignores_bibtex_case_protection_braces():
    assert normalize_title("{A}pp{W}orld: A Controllable World") == normalize_title("AppWorld: A Controllable World")


def test_title_normalization_ignores_escaped_latex_punctuation():
    assert normalize_title("Refgate Fixture: Taylor \\& Francis Official Record") == normalize_title(
        "Refgate Fixture: Taylor & Francis Official Record"
    )
    assert normalize_title("Refgate Fixture: Taylor \\\\& Francis Official Record") == normalize_title(
        "Refgate Fixture: Taylor & Francis Official Record"
    )


def test_author_normalization_handles_diacritics_for_audit_matching():
    assert normalize_author("Đorđe Klisura") == normalize_author("Djordje Klisura")


def test_neurips_adapter_discovers_official_bibtex_endpoint():
    html = (FIXTURES / "neurips_authority.html").read_text(encoding="utf-8")
    bib = (FIXTURES / "neurips_official.bib").read_text(encoding="utf-8")
    url = "https://proceedings.neurips.cc/paper_files/paper/2026/hash/refgate-Abstract-Conference.html"
    candidate = candidate_from_neurips_html(url, html)
    adapter = NeuripsAdapter(fetcher=lambda _url: bib)
    authority = adapter.fetch_authority(candidate)

    assert authority is not None
    assert authority.bibtex_url == "https://proceedings.neurips.cc/paper_files/paper/2026/hash/refgate-/bibtex"
    assert adapter.fetch_bibtex(authority, adapter.find_export_endpoints(authority)[0]).source_kind == "official_export"


def test_neurips_adapter_discovers_from_pdf_url():
    html = (FIXTURES / "neurips_authority.html").read_text(encoding="utf-8")
    fetched_urls = []

    def fetch(url: str) -> str:
        fetched_urls.append(url)
        return html

    adapter = NeuripsAdapter(fetcher=fetch)
    candidates = adapter.discover(
        PaperQuery(
            query_id="refgate",
            title="Refgate Fixture: Official NeurIPS Export",
            preferred_venues=[
                "https://proceedings.neurips.cc/paper_files/paper/2026/file/refgate-Paper-Datasets_and_Benchmarks_Track.pdf"
            ],
        )
    )

    assert len(candidates) == 1
    assert fetched_urls == [
        "https://proceedings.neurips.cc/paper_files/paper/2026/hash/refgate-Abstract-Datasets_and_Benchmarks_Track.html"
    ]


def test_iclr_adapter_discovers_official_bibtex_endpoint():
    html = (FIXTURES / "iclr_authority.html").read_text(encoding="utf-8")
    bib = (FIXTURES / "iclr_official.bib").read_text(encoding="utf-8")
    url = "https://proceedings.iclr.cc/paper_files/paper/2026/hash/refgate-Abstract-Conference.html"
    candidate = candidate_from_iclr_html(url, html)
    adapter = IclrAdapter(fetcher=lambda _url: bib)
    authority = adapter.fetch_authority(candidate)

    assert authority is not None
    assert authority.bibtex_url == "https://proceedings.iclr.cc/paper_files/paper/2026/hash/refgate-/bibtex"
    assert adapter.fetch_bibtex(authority, adapter.find_export_endpoints(authority)[0]).source_kind == "official_export"


def test_iclr_adapter_discovers_from_pdf_url():
    html = (FIXTURES / "iclr_authority.html").read_text(encoding="utf-8")
    fetched_urls = []

    def fetch(url: str) -> str:
        fetched_urls.append(url)
        return html

    adapter = IclrAdapter(fetcher=fetch)
    candidates = adapter.discover(
        PaperQuery(
            query_id="refgate",
            title="Refgate Fixture: Official ICLR Export",
            preferred_venues=["https://proceedings.iclr.cc/paper_files/paper/2026/file/refgate-Paper-Conference.pdf"],
        )
    )

    assert len(candidates) == 1
    assert fetched_urls == ["https://proceedings.iclr.cc/paper_files/paper/2026/hash/refgate-Abstract-Conference.html"]


def test_pdf_url_normalizers_leave_html_urls_unchanged():
    assert (
        iclr_record_url("https://proceedings.iclr.cc/paper_files/paper/2026/hash/refgate-Abstract-Conference.html")
        == "https://proceedings.iclr.cc/paper_files/paper/2026/hash/refgate-Abstract-Conference.html"
    )
    assert (
        neurips_record_url("https://proceedings.neurips.cc/paper_files/paper/2026/hash/refgate-Abstract-Conference.html")
        == "https://proceedings.neurips.cc/paper_files/paper/2026/hash/refgate-Abstract-Conference.html"
    )
