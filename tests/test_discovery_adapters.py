import json
from pathlib import Path

from refgate.adapters.crossref import CrossrefAdapter
from refgate.adapters.openalex import OpenAlexAdapter
from refgate.adapters.semantic_scholar import SemanticScholarAdapter
from refgate.models import PaperQuery


FIXTURES = Path(__file__).parent / "fixtures"


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_crossref_doi_lookup_returns_doi_authority_candidate():
    adapter = CrossrefAdapter(fetcher=lambda _url: load_text("crossref_work.json"))
    query = PaperQuery(
        query_id="crossref-fixture",
        title="Refgate Fixture: DOI Metadata Verification",
        authors=["Ada Smith"],
        year=2026,
        doi="10.5555/refgate.fixture",
    )

    candidates = adapter.discover(query)
    authority = adapter.fetch_authority(candidates[0])

    assert candidates[0].source == "crossref"
    assert candidates[0].doi == "10.5555/refgate.fixture"
    assert candidates[0].is_official_record
    assert authority is not None
    assert authority.record_type == "doi_metadata"


def test_semantic_scholar_is_discovery_only():
    adapter = SemanticScholarAdapter(fetcher=lambda _url: load_text("semantic_scholar_search.json"))
    query = PaperQuery(query_id="s2-fixture", title="Refgate Fixture: Discovery Only Record")

    candidates = adapter.discover(query)

    assert candidates[0].source == "semantic_scholar"
    assert candidates[0].raw["authority_role"] == "discovery_only"
    assert adapter.fetch_authority(candidates[0]) is None


def test_openalex_is_discovery_cross_check_only():
    adapter = OpenAlexAdapter(fetcher=lambda _url: load_text("openalex_search.json"))
    query = PaperQuery(query_id="openalex-fixture", title="Refgate Fixture: OpenAlex Cross Check")

    candidates = adapter.discover(query)

    assert candidates[0].source == "openalex"
    assert candidates[0].doi == "10.5555/refgate.openalex"
    assert candidates[0].raw["authority_role"] == "discovery_cross_check"
    assert adapter.fetch_authority(candidates[0]) is None


def test_fixture_json_is_valid():
    for name in ["crossref_work.json", "semantic_scholar_search.json", "openalex_search.json"]:
        json.loads(load_text(name))
