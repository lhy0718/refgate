from pathlib import Path

from refgate.adapters.arxiv import ArxivAdapter
from refgate.cache import RawRecord, write_raw_record
from refgate.live_smoke import cached_fetcher
from refgate.models import CandidateRecord, PaperQuery
from refgate.resolver import resolve


FIXTURES = Path(__file__).parent / "fixtures"


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_arxiv_exact_id_lookup_preserves_version_and_manual_fallback_provenance():
    adapter = ArxivAdapter(
        fetcher=lambda _url: load_text("arxiv_exact_id.xml"),
        accessed_at="2026-05-19",
    )
    query = PaperQuery(
        query_id="refgate-preprint",
        title="Refgate Fixture: Deterministic Reference Gates for Manuscripts",
        authors=["Ada Smith"],
        year=2026,
        arxiv_id="2601.00001v2",
        citation_key="smith2026refgatefixture",
    )

    candidates = adapter.discover(query)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.arxiv_id == "2601.00001"
    assert candidate.raw["arxiv_version"] == "v2"
    assert candidate.raw["accessed_at"] == "2026-05-19"
    assert candidate.raw["official_record_status"] == "preprint_only"

    decision = resolve(query, candidates)

    assert decision.ok
    assert decision.status == "arxiv_fallback_verified"
    assert decision.authority is not None
    assert decision.authority.source == "arxiv"
    assert decision.authority.record_type == "preprint_record"
    assert decision.authority.bibtex_url is None

    bibtex = adapter.build_manual_bibtex(candidate, query.citation_key)

    assert bibtex.source_kind == "arxiv_manual_normalized"
    assert "archivePrefix = {arXiv}" in bibtex.raw_text
    assert "eprint = {2601.00001}" in bibtex.raw_text
    assert "note = {arXiv version v2, accessed 2026-05-19}" in bibtex.raw_text


def test_arxiv_manual_fallback_adds_accessed_date_when_candidate_came_from_crosscheck():
    record = CandidateRecord(
        source="semantic_scholar",
        title="LoRA: Low-Rank Adaptation of Large Language Models",
        authors=["J. Hu"],
        year=2021,
        venue="International Conference on Learning Representations",
        url="https://www.semanticscholar.org/paper/example",
        arxiv_id="2106.09685",
        is_official_record=False,
    )

    bibtex = ArxivAdapter(fetcher=lambda _url: "", accessed_at="2026-05-25").build_manual_bibtex(record, "hu2021lora")

    assert "note = {accessed 2026-05-25}" in bibtex.raw_text


def test_arxiv_title_search_requires_exact_normalized_title_and_blocks_official_pending():
    adapter = ArxivAdapter(
        fetcher=lambda _url: load_text("arxiv_title_search.xml"),
        accessed_at="2026-05-19",
    )
    query = PaperQuery(
        query_id="refgate-official-pending",
        title="Refgate Fixture: Deterministic Reference Gates for Manuscripts",
        authors=["Ada Smith"],
        year=2026,
        preferred_venues=["ICLR"],
    )

    candidates = adapter.discover(query)

    assert len(candidates) == 1
    assert candidates[0].title == "Refgate Fixture: Deterministic Reference Gates for Manuscripts"
    assert candidates[0].raw["official_record_status"] == "official_record_pending"

    decision = resolve(query, candidates)

    assert not decision.ok
    assert decision.status == "official_record_pending"
    assert any(issue.code == "OFFICIAL_RECORD_PENDING" for issue in decision.blocking_issues)


def test_arxiv_preprint_venue_does_not_trigger_official_pending():
    adapter = ArxivAdapter(
        fetcher=lambda _url: load_text("arxiv_exact_id.xml"),
        accessed_at="2026-05-19",
    )
    query = PaperQuery(
        query_id="refgate-preprint",
        title="Refgate Fixture: Deterministic Reference Gates for Manuscripts",
        arxiv_id="2601.00001",
        preferred_venues=["arXiv preprint"],
    )

    candidates = adapter.discover(query)
    decision = resolve(query, candidates)

    assert candidates[0].raw["official_record_status"] == "preprint_only"
    assert decision.ok
    assert decision.status == "arxiv_fallback_verified"


def test_live_smoke_fetcher_can_seed_from_reviewed_cache(tmp_path):
    url = "https://example.org/arxiv"
    write_raw_record(
        RawRecord(
            source="arxiv",
            url=url,
            status=200,
            headers={},
            body=load_text("arxiv_exact_id.xml"),
            fetched_at="2026-05-20T00:00:00+00:00",
        ),
        cache_root=tmp_path,
    )

    def fail_fetch(_url):
        raise AssertionError("network should not be used when reviewed cache exists")

    fetch = cached_fetcher("arxiv", fail_fetch, tmp_path, prefer_cache=True)

    assert "Refgate Fixture" in fetch(url)
