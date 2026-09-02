import json
from pathlib import Path

from refgate.models import PaperQuery
from refgate.scholar import (
    build_scholar_official_bridge_plan,
    extract_google_scholar_urls,
    google_scholar_discovery_search,
    google_scholar_query,
    google_scholar_search_url,
    google_scholar_captcha_markers,
    official_source_for_url,
    official_urls_from_scholar_html,
    official_urls_from_manual_file,
)


def test_google_scholar_discovery_search_is_not_official_provenance():
    query = PaperQuery(
        query_id="smith2026",
        citation_key="smith2026",
        title="A Paper With Official Venue",
        authors=["Ada Smith", "Bert Jones"],
        year=2026,
    )

    assert google_scholar_query(query) == '"A Paper With Official Venue" Ada Smith 2026'
    assert google_scholar_search_url(query).startswith("https://scholar.google.com/scholar?q=")
    search = google_scholar_discovery_search(query)
    assert search["source"] == "google_scholar"
    assert search["authority_role"] == "discovery_only"
    assert "not treat Google Scholar BibTeX as official provenance" in search["note"]


def test_scholar_html_extracts_official_url_candidates():
    html = (
        '<html><body>'
        '<a href="/scholar_url?url=https%3A%2F%2Faclanthology.org%2F2026.acl-main.1%2F&hl=en">ACL</a>'
        '<a href="https://arxiv.org/abs/2601.00001">arXiv</a>'
        '<a href="/url?q=https%3A%2F%2Fdoi.org%2F10.5555%2Ffixture">DOI</a>'
        '</body></html>'
    )

    urls = extract_google_scholar_urls(html)
    assert "https://aclanthology.org/2026.acl-main.1/" in urls
    assert official_source_for_url("https://aclanthology.org/2026.acl-main.1/") == "acl"
    assert official_source_for_url("https://doi.org/10.5555/fixture") == "crossref"
    official = official_urls_from_scholar_html(html)
    assert {item["source"] for item in official} == {"acl", "crossref"}
    assert all("arxiv" not in item["url"] for item in official)


def test_google_scholar_captcha_detection_and_manual_url_file(tmp_path):
    html = "<html><body>Our systems have detected unusual traffic. g-recaptcha</body></html>"
    markers = google_scholar_captcha_markers(html)
    assert "our systems have detected unusual traffic" in markers
    assert "g-recaptcha" in markers

    manual = tmp_path / "paper.official_urls.txt"
    manual.write_text(
        "# reviewed official source\nhttps://aclanthology.org/2026.acl-main.1/\nhttps://arxiv.org/abs/2601.00001\n",
        encoding="utf-8",
    )
    assert official_urls_from_manual_file(manual) == [{"source": "acl", "url": "https://aclanthology.org/2026.acl-main.1/"}]


def test_scholar_official_bridge_writes_candidate_and_reference_check_command(tmp_path):
    lock = tmp_path / "refgate.lock.json"
    scholar_dir = tmp_path / "scholar-html"
    candidate_dir = tmp_path / "reference-candidates"
    scholar_dir.mkdir()
    lock.write_text(
        json.dumps(
            {
                "schema_version": "refgate.lock.v1",
                "entries": [
                    {
                        "citation_key": "smith2026",
                        "short_title": "A Paper With Official Venue",
                        "status": "arxiv_fallback_verified",
                        "record": {
                            "title": "A Paper With Official Venue",
                            "authors": ["Ada Smith"],
                            "year": 2026,
                            "arxiv_id": "2601.00001",
                            "accessed_at": "2026-06-29",
                        },
                        "authority": {"source": "arxiv", "record_url": "https://arxiv.org/abs/2601.00001"},
                        "bibtex": {"source_kind": "arxiv_manual_normalized", "field_checks": {"doi": "missing"}},
                        "resolver": {},
                        "checked_at": "2026-06-29",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (scholar_dir / "smith2026.google_scholar.html").write_text(
        '<a href="/scholar_url?url=https%3A%2F%2Faclanthology.org%2F2026.acl-main.1%2F">ACL</a>',
        encoding="utf-8",
    )

    def fake_fetcher(url: str) -> str:
        assert url == "https://aclanthology.org/2026.acl-main.1/"
        return (
            '<html><head>'
            '<meta name="citation_title" content="A Paper With Official Venue">'
            '<meta name="citation_author" content="Ada Smith">'
            '<meta name="citation_publication_date" content="2026">'
            '</head></html>'
        )

    plan = build_scholar_official_bridge_plan(
        lock,
        scholar_html_dir=scholar_dir,
        candidate_dir=candidate_dir,
        live_official=True,
        write_candidates=True,
        write_lock=lock,
        fetch_official_bibtex=True,
        fetcher=fake_fetcher,
    )

    assert plan["blocking_issues"] == []
    item = plan["items"][0]
    assert item["official_url_candidates"] == [{"source": "acl", "url": "https://aclanthology.org/2026.acl-main.1/"}]
    assert item["official_candidate_fetches"][0]["ok"] is True
    candidate_file = Path(item["candidate_file"])
    saved = json.loads(candidate_file.read_text(encoding="utf-8"))
    candidate = saved["candidates"][0]
    assert candidate["source"] == "acl"
    assert candidate["is_official_record"] is True
    assert candidate["bibtex_url"] == "https://aclanthology.org/2026.acl-main.1.bib"
    action = plan["next_actions"][0]
    assert action["code"] == "RUN_REFERENCE_CHECK_FROM_SCHOLAR_CANDIDATES"
    assert "reference-check" in action["command"]
    assert "--candidate-dir" in action["command"]
    assert "--fetch-official-bibtex" in action["command"]


def test_scholar_official_bridge_can_fetch_scholar_then_official_candidate(tmp_path):
    lock = tmp_path / "refgate.lock.json"
    scholar_dir = tmp_path / "scholar-html"
    candidate_dir = tmp_path / "reference-candidates"
    lock.write_text(
        json.dumps(
            {
                "schema_version": "refgate.lock.v1",
                "entries": [
                    {
                        "citation_key": "smith2026",
                        "short_title": "A Paper With Official Venue",
                        "status": "arxiv_fallback_verified",
                        "record": {
                            "title": "A Paper With Official Venue",
                            "authors": ["Ada Smith"],
                            "year": 2026,
                            "arxiv_id": "2601.00001",
                            "accessed_at": "2026-06-29",
                        },
                        "authority": {"source": "arxiv", "record_url": "https://arxiv.org/abs/2601.00001"},
                        "bibtex": {"source_kind": "arxiv_manual_normalized", "field_checks": {"doi": "missing"}},
                        "resolver": {},
                        "checked_at": "2026-06-29",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_fetcher(url: str) -> str:
        if "scholar.google.com" in url:
            return '<a href="/scholar_url?url=https%3A%2F%2Faclanthology.org%2F2026.acl-main.1%2F">ACL</a>'
        assert url == "https://aclanthology.org/2026.acl-main.1/"
        return (
            '<html><head>'
            '<meta name="citation_title" content="A Paper With Official Venue">'
            '<meta name="citation_author" content="Ada Smith">'
            '<meta name="citation_publication_date" content="2026">'
            '</head></html>'
        )

    plan = build_scholar_official_bridge_plan(
        lock,
        scholar_html_dir=scholar_dir,
        candidate_dir=candidate_dir,
        live_scholar=True,
        live_official=True,
        write_candidates=True,
        write_lock=lock,
        fetch_official_bibtex=True,
        fetcher=fake_fetcher,
    )

    item = plan["items"][0]
    assert plan["blocking_issues"] == []
    assert item["google_scholar_fetch"]["ok"] is True
    assert Path(item["scholar_html"]).exists()
    assert item["official_url_candidates"] == [{"source": "acl", "url": "https://aclanthology.org/2026.acl-main.1/"}]
    assert item["official_candidate_fetches"][0]["ok"] is True
    assert Path(item["candidate_file"]).exists()
    assert plan["next_actions"][0]["code"] == "RUN_REFERENCE_CHECK_FROM_SCHOLAR_CANDIDATES"


def test_scholar_official_bridge_routes_captcha_to_human_review(tmp_path):
    lock = tmp_path / "refgate.lock.json"
    scholar_dir = tmp_path / "scholar-html"
    candidate_dir = tmp_path / "reference-candidates"
    lock.write_text(
        json.dumps(
            {
                "schema_version": "refgate.lock.v1",
                "entries": [
                    {
                        "citation_key": "smith2026",
                        "short_title": "A Paper With Official Venue",
                        "status": "arxiv_fallback_verified",
                        "record": {
                            "title": "A Paper With Official Venue",
                            "authors": ["Ada Smith"],
                            "year": 2026,
                            "arxiv_id": "2601.00001",
                            "accessed_at": "2026-06-29",
                        },
                        "authority": {"source": "arxiv", "record_url": "https://arxiv.org/abs/2601.00001"},
                        "bibtex": {"source_kind": "arxiv_manual_normalized", "field_checks": {"doi": "missing"}},
                        "resolver": {},
                        "checked_at": "2026-06-29",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_fetcher(url: str) -> str:
        assert "scholar.google.com" in url
        return "<html><body>Please show you're not a robot. recaptcha</body></html>"

    plan = build_scholar_official_bridge_plan(
        lock,
        scholar_html_dir=scholar_dir,
        candidate_dir=candidate_dir,
        live_scholar=True,
        live_official=True,
        write_candidates=True,
        write_lock=lock,
        fetch_official_bibtex=True,
        fetcher=fake_fetcher,
    )

    assert [issue["code"] for issue in plan["blocking_issues"]] == ["SCHOLAR_CAPTCHA_REVIEW_REQUIRED"]
    item = plan["items"][0]
    assert item["google_scholar_fetch"]["ok"] is True
    assert item["google_scholar_captcha"]["detected"] is True
    action = plan["next_actions"][0]
    assert action["code"] == "SCHOLAR_CAPTCHA_REVIEW_REQUIRED"
    assert action["requires_review"] is True
    assert action["target_file"].endswith("smith2026.google_scholar.html")
    assert action["manual_official_url_file"].endswith("smith2026.official_urls.txt")
    assert "--live-scholar" not in action["command"]
    assert "--live-official" in action["command"]


def test_scholar_official_bridge_can_resume_from_manual_official_url_file(tmp_path):
    lock = tmp_path / "refgate.lock.json"
    scholar_dir = tmp_path / "scholar-html"
    candidate_dir = tmp_path / "reference-candidates"
    scholar_dir.mkdir()
    lock.write_text(
        json.dumps(
            {
                "schema_version": "refgate.lock.v1",
                "entries": [
                    {
                        "citation_key": "smith2026",
                        "short_title": "A Paper With Official Venue",
                        "status": "arxiv_fallback_verified",
                        "record": {
                            "title": "A Paper With Official Venue",
                            "authors": ["Ada Smith"],
                            "year": 2026,
                            "arxiv_id": "2601.00001",
                            "accessed_at": "2026-06-29",
                        },
                        "authority": {"source": "arxiv", "record_url": "https://arxiv.org/abs/2601.00001"},
                        "bibtex": {"source_kind": "arxiv_manual_normalized", "field_checks": {"doi": "missing"}},
                        "resolver": {},
                        "checked_at": "2026-06-29",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (scholar_dir / "smith2026.official_urls.txt").write_text(
        "https://aclanthology.org/2026.acl-main.1/\n",
        encoding="utf-8",
    )

    def fake_fetcher(url: str) -> str:
        assert url == "https://aclanthology.org/2026.acl-main.1/"
        return (
            '<html><head>'
            '<meta name="citation_title" content="A Paper With Official Venue">'
            '<meta name="citation_author" content="Ada Smith">'
            '<meta name="citation_publication_date" content="2026">'
            '</head></html>'
        )

    plan = build_scholar_official_bridge_plan(
        lock,
        scholar_html_dir=scholar_dir,
        candidate_dir=candidate_dir,
        live_scholar=False,
        live_official=True,
        write_candidates=True,
        write_lock=lock,
        fetch_official_bibtex=True,
        fetcher=fake_fetcher,
    )

    assert plan["blocking_issues"] == []
    item = plan["items"][0]
    assert item["manual_official_url_file"].endswith("smith2026.official_urls.txt")
    assert item["official_url_candidates"] == [{"source": "acl", "url": "https://aclanthology.org/2026.acl-main.1/"}]
    assert item["official_candidate_fetches"][0]["ok"] is True
    assert Path(item["candidate_file"]).exists()
