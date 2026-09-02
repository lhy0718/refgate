from pathlib import Path

import json

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
    assert candidate.doi == "10.18653/v1/2026.acl-long.001"
    assert candidate.venue == "Proceedings of the 64th Annual Meeting of the Association for Computational Linguistics"
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


def test_acl_adapter_bridges_title_variant_through_acl_doi_and_keeps_acl_as_final_authority():
    html = (FIXTURES / "acl_title_variant_authority.html").read_text(encoding="utf-8")
    crossref = json.dumps(
        {
            "message": {
                "items": [
                    {
                        "DOI": "10.18653/v1/2024.emnlp-industry.91",
                        "URL": "https://doi.org/10.18653/v1/2024.emnlp-industry.91",
                        "title": [
                            "Let Me Speak Freely? A Study On The Impact Of Format Restrictions On Large Language Model Performance."
                        ],
                        "author": [
                            {"given": "Zhi Rui", "family": "Tam"},
                            {"given": "Cheng-Kuang", "family": "Wu"},
                        ],
                        "published": {"date-parts": [[2024]]},
                        "container-title": [
                            "Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing: Industry Track"
                        ],
                    }
                ]
            }
        }
    )

    def fake_fetch(url: str) -> str:
        if url.startswith("https://api.crossref.org/works?"):
            return crossref
        if url == "https://aclanthology.org/2024.emnlp-industry.91/":
            return html
        raise AssertionError(url)

    query = PaperQuery(
        query_id="let_me_speak_freely",
        citation_key="let_me_speak_freely",
        title="Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performance of Large Language Models",
        authors=["Zhi Rui Tam", "Cheng-Kuang Wu"],
        year=2024,
        arxiv_id="2408.02442",
        preferred_venues=["arXiv preprint", "https://arxiv.org/abs/2408.02442v3"],
    )

    candidates = AclAdapter(fetcher=fake_fetch).discover(query)
    decision = resolve(query, candidates)

    assert len(candidates) == 1
    assert candidates[0].source == "acl"
    assert candidates[0].doi == "10.18653/v1/2024.emnlp-industry.91"
    assert candidates[0].bibtex_url == "https://aclanthology.org/2024.emnlp-industry.91.bib"
    assert candidates[0].raw["discovered_by"] == "crossref_acl_doi_bridge"
    assert decision.ok
    assert decision.authority is not None
    assert decision.authority.source == "acl"
    assert "title high-overlap reordered match" in decision.decision_trace


def test_acl_adapter_dedupes_case_variant_doi_url_against_explicit_legacy_acl_url():
    html = """<html><head>
    <meta name="citation_title" content="Know What You Don't Know: Unanswerable Questions for SQuAD">
    <meta name="citation_author" content="Pranav Rajpurkar">
    <meta name="citation_publication_date" content="2018">
    <meta name="citation_doi" content="10.18653/v1/P18-2124">
    </head></html>"""
    fetched_urls = []

    def fake_fetch(url: str) -> str:
        fetched_urls.append(url)
        assert url == "https://aclanthology.org/P18-2124/"
        return html

    query = PaperQuery(
        query_id="rajpurkar_etal_2018_squad2",
        title="Know What You Don't Know: Unanswerable Questions for SQuAD",
        authors=["Pranav Rajpurkar"],
        year=2018,
        doi="10.18653/v1/p18-2124",
        preferred_venues=["https://aclanthology.org/P18-2124/"],
    )

    candidates = AclAdapter(fetcher=fake_fetch).discover(query)

    assert len(candidates) == 1
    assert fetched_urls == ["https://aclanthology.org/P18-2124/"]
    assert candidates[0].bibtex_url == "https://aclanthology.org/P18-2124.bib"
