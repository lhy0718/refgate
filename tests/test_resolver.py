from pathlib import Path
import json

from refgate.models import CandidateRecord, PaperQuery
from refgate.resolver import resolve
from refgate.resolver import score_candidate


FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_resolver_selects_official_bibtex_record():
    query = PaperQuery.from_dict(load_json("official_query.json"))
    candidates = [CandidateRecord.from_dict(item) for item in load_json("official_candidates.json")]

    decision = resolve(query, candidates)

    assert decision.ok
    assert decision.status == "verified_official_bibtex"
    assert decision.authority is not None
    assert decision.authority.source == "neurips"
    assert decision.authority.bibtex_url


def test_resolver_blocks_doi_conflict():
    query = PaperQuery.from_dict(load_json("conflict_query.json"))
    candidates = [CandidateRecord.from_dict(item) for item in load_json("conflict_candidates.json")]

    decision = resolve(query, candidates)

    assert not decision.ok
    assert decision.status == "ambiguous"
    assert any(issue.code == "DOI_CONFLICT" for issue in decision.blocking_issues)


def test_resolver_blocks_doi_exact_candidate_with_missing_title():
    query = PaperQuery(
        query_id="missing-title",
        title="BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        doi="10.18653/v1/N19-1423",
    )
    candidates = [
        CandidateRecord(
            source="crossref",
            title="",
            doi="10.18653/v1/N19-1423",
            url="https://doi.org/10.18653/v1/n19-1423",
            is_official_record=True,
        )
    ]

    decision = resolve(query, candidates)

    assert not decision.ok
    assert decision.status == "unresolved"
    assert decision.resolver_score >= 100
    assert decision.blocking_issues[0].code == "AUTHORITY_TITLE_MISSING"


def test_resolver_blocks_doi_exact_candidate_with_mismatched_title():
    query = PaperQuery(
        query_id="truncated-title",
        title="XGBoost: A Scalable Tree Boosting System",
        doi="10.1145/2939672.2939785",
    )
    candidates = [
        CandidateRecord(
            source="crossref",
            title="XGBoost",
            doi="10.1145/2939672.2939785",
            url="https://doi.org/10.1145/2939672.2939785",
            is_official_record=True,
        )
    ]

    decision = resolve(query, candidates)

    assert not decision.ok
    assert decision.status == "unresolved"
    assert decision.resolver_score >= 100
    assert decision.blocking_issues[0].code == "AUTHORITY_TITLE_MISMATCH"


def test_score_candidate_matches_reversed_first_author_name_parts():
    query = PaperQuery(query_id="author-order", title="Holistic Evaluation of Language Models", authors=["Liang, Percy"], year=2023)
    candidate = CandidateRecord(
        source="openreview",
        title="Holistic Evaluation of Language Models",
        authors=["Percy Liang"],
        year=2023,
        url="https://openreview.net/forum?id=iO4LZibEqW",
        is_official_record=True,
        source_priority=1,
    )

    score, trace = score_candidate(query, candidate)

    assert score >= 95
    assert "first author match" in trace


def test_resolver_accepts_long_reordered_title_only_with_official_year_and_author_support():
    query = PaperQuery(
        query_id="title-variant",
        title="Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performance of Large Language Models",
        authors=["Zhi Rui Tam"],
        year=2024,
    )
    candidate = CandidateRecord(
        source="acl",
        title="Let Me Speak Freely? A Study On The Impact Of Format Restrictions On Large Language Model Performance.",
        authors=["Zhi Rui Tam"],
        year=2024,
        doi="10.18653/v1/2024.emnlp-industry.91",
        url="https://aclanthology.org/2024.emnlp-industry.91/",
        is_official_record=True,
        bibtex_url="https://aclanthology.org/2024.emnlp-industry.91.bib",
        source_priority=1,
    )

    decision = resolve(query, [candidate])

    assert decision.ok
    assert decision.status == "verified_official_bibtex"
    assert "title high-overlap reordered match" in decision.decision_trace


def test_resolver_blocks_reordered_title_without_matching_year_support():
    query = PaperQuery(
        query_id="unsafe-title-variant",
        title="Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performance of Large Language Models",
        authors=["Zhi Rui Tam"],
        year=2024,
    )
    candidate = CandidateRecord(
        source="acl",
        title="Let Me Speak Freely? A Study On The Impact Of Format Restrictions On Large Language Model Performance.",
        authors=["Zhi Rui Tam"],
        year=2025,
        url="https://aclanthology.org/2025.fake.1/",
        is_official_record=True,
        bibtex_url="https://aclanthology.org/2025.fake.1.bib",
        source_priority=1,
    )

    decision = resolve(query, [candidate])

    assert not decision.ok
    assert decision.status == "unresolved"
