from pathlib import Path

from refgate.adapters.acl import AclAdapter, candidate_from_acl_html
from refgate.models import PaperQuery
from refgate.resolver import resolve


FIXTURES = Path(__file__).parent / "fixtures"


def test_acl_adapter_builds_official_authority_and_fetches_bibtex():
    html = (FIXTURES / "acl_authority.html").read_text(encoding="utf-8")
    bib = (FIXTURES / "acl_official.bib").read_text(encoding="utf-8")
    url = "https://aclanthology.org/2026.acl-long.001/"
    candidate = candidate_from_acl_html(url, html)

    assert candidate.is_official_record
    assert candidate.bibtex_url == "https://aclanthology.org/2026.acl-long.001.bib"

    adapter = AclAdapter(fetcher=lambda _url: bib)
    authority = adapter.fetch_authority(candidate)
    assert authority is not None
    endpoints = adapter.find_export_endpoints(authority)
    assert endpoints[0].is_official

    bibtex = adapter.fetch_bibtex(authority, endpoints[0])
    assert bibtex is not None
    assert bibtex.source_kind == "official_export"
    assert bibtex.citation_key == "smith-lee-2026-refgate"

    query = PaperQuery(
        query_id="acl-fixture",
        title="Refgate Fixture: Official ACL Export",
        authors=["Ada Smith"],
        year=2026,
    )
    decision = resolve(query, [candidate])
    assert decision.ok
    assert decision.status == "verified_official_bibtex"
