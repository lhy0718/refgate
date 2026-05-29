import json

from refgate.cache import RawRecord, write_raw_record
from refgate.cli import main
from refgate.live_smoke import cache_manifest, cached_fetcher, compare_cache_manifest
from refgate.models import PaperQuery


def test_cache_manifest_compare_passes_for_matching_checksum(tmp_path):
    record = RawRecord(
        source="arxiv",
        url="https://example.org/arxiv",
        status=200,
        headers={},
        body="fixture body",
        fetched_at="2026-05-19T00:00:00+00:00",
    )
    write_raw_record(record, cache_root=tmp_path)

    actual = cache_manifest(tmp_path)
    expected = {"records": [{"source": "arxiv", "url": "https://example.org/arxiv", "body_sha256": record.body_sha256}]}

    assert compare_cache_manifest(actual, expected)["ok"] is True


def test_cli_live_smoke_manifest_compare_is_network_free(tmp_path, capsys):
    record = RawRecord(
        source="crossref",
        url="https://example.org/crossref",
        status=200,
        headers={},
        body="fixture body",
        fetched_at="2026-05-19T00:00:00+00:00",
    )
    write_raw_record(record, cache_root=tmp_path / "cache")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"records": [{"source": "crossref", "url": "https://example.org/crossref", "body_sha256": record.body_sha256}]}),
        encoding="utf-8",
    )

    exit_code = main(["live-smoke", "--cache-root", str(tmp_path / "cache"), "--manifest", str(manifest), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data"]["comparison"]["ok"] is True


def test_cli_live_smoke_writes_manifest_without_network(tmp_path, capsys):
    record = RawRecord(
        source="arxiv",
        url="https://example.org/arxiv",
        status=200,
        headers={},
        body="fixture body",
        fetched_at="2026-05-19T00:00:00+00:00",
    )
    write_raw_record(record, cache_root=tmp_path / "cache")
    manifest = tmp_path / "manifest.json"

    exit_code = main(["live-smoke", "--cache-root", str(tmp_path / "cache"), "--write-manifest", str(manifest), "--json"])

    payload = json.loads(capsys.readouterr().out)
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "cache_manifest_written"
    assert saved["records"][0]["body_sha256"] == record.body_sha256


def test_cli_live_smoke_suite_manifest_compare_is_network_free(tmp_path, capsys):
    record = RawRecord(
        source="pnas",
        url="https://www.pnas.org/doi/10.1073/refgate.pnas",
        status=200,
        headers={},
        body="fixture body",
        fetched_at="2026-05-19T00:00:00+00:00",
    )
    write_raw_record(record, cache_root=tmp_path / "cache")
    queries = tmp_path / "queries.json"
    queries.write_text(json.dumps([{"query_id": "q1", "title": "A Fixture Paper", "source": "pnas"}]), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"records": [{"source": "pnas", "url": record.url, "body_sha256": record.body_sha256}]}),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "live-smoke-suite",
            "--queries",
            str(queries),
            "--cache-root",
            str(tmp_path / "cache"),
            "--manifest",
            str(manifest),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "cache_manifest_compared"
    assert payload["data"]["comparison"]["ok"] is True


def test_cached_fetcher_reports_only_cache_paths_used_by_current_request(tmp_path):
    current = RawRecord(
        source="crossref",
        url="https://example.org/current",
        status=200,
        headers={},
        body="current body",
        fetched_at="2026-05-19T00:00:00+00:00",
    )
    stale = RawRecord(
        source="crossref",
        url="https://example.org/stale",
        status=200,
        headers={},
        body="stale body",
        fetched_at="2026-05-19T00:00:00+00:00",
    )
    current_path = write_raw_record(current, cache_root=tmp_path / "cache")
    stale_path = write_raw_record(stale, cache_root=tmp_path / "cache")
    cache_paths = []

    fetch = cached_fetcher(
        "crossref",
        lambda _url: "network body",
        tmp_path / "cache",
        prefer_cache=True,
        cache_paths=cache_paths,
    )

    assert fetch(current.url) == "current body"
    assert cache_paths == [str(current_path)]
    assert str(stale_path) not in cache_paths


def test_live_smoke_supports_fixture_backed_official_venue_sources(tmp_path):
    from refgate.live_smoke import run_live_smoke

    url = "https://dl.acm.org/doi/10.1145/refgate.acm"
    record = RawRecord(
        source="acm",
        url=url,
        status=200,
        headers={},
        body=(
            '<html><head><meta name="citation_title" content="Refgate Fixture: ACM Official Record">'
            '<meta name="citation_author" content="Ada Smith">'
            '<meta name="citation_publication_date" content="2026">'
            '<meta name="citation_doi" content="10.1145/refgate.acm"></head></html>'
        ),
        fetched_at="2026-05-19T00:00:00+00:00",
    )
    cache_path = write_raw_record(record, cache_root=tmp_path / "cache")

    result = run_live_smoke(
        "acm",
        PaperQuery(
            query_id="acm",
            title="Refgate Fixture: ACM Official Record",
            preferred_venues=[url],
        ),
        cache_root=tmp_path / "cache",
        prefer_cache=True,
    )

    assert result["ok"] is True
    assert result["candidates"][0]["source"] == "acm"
    assert result["candidates"][0]["doi"] == "10.1145/refgate.acm"
    assert result["cache_paths"] == [str(cache_path)]


def test_run_live_smoke_suite_keeps_default_source_for_empty_query_list():
    from refgate.live_smoke import run_live_smoke_suite

    result = run_live_smoke_suite([], source="arxiv")

    assert result["source"] == "arxiv"
    assert result["query_count"] == 0
    assert result["ok"] is False


def test_cli_live_smoke_suite_requires_live_flag(tmp_path, capsys):
    queries = tmp_path / "queries.json"
    queries.write_text(json.dumps([{"query_id": "q1", "title": "A Fixture Paper"}]), encoding="utf-8")

    exit_code = main(["live-smoke-suite", "--queries", str(queries), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["blocking_issues"][0]["code"] == "LIVE_MODE_REQUIRED"


def test_cli_live_smoke_suite_accepts_resolver_assist_output_and_max_queries(monkeypatch, tmp_path, capsys):
    queries = tmp_path / "resolver_assist.json"
    queries.write_text(
        json.dumps(
            {
                "work_items": [
                    {
                        "query": {
                            "query_id": "q1",
                            "citation_key": "smith2026",
                            "title": "A Fixture Paper",
                        }
                    },
                    {
                        "query": {
                            "query_id": "q2",
                            "citation_key": "jones2026",
                            "title": "Another Fixture Paper",
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_suite(loaded_queries, *, source, cache_root, **_kwargs):
        assert loaded_queries[0].citation_key == "smith2026"
        assert len(loaded_queries) == 2
        assert _kwargs["max_queries"] == 1
        return {"source": source, "query_count": 2, "run_query_count": 1, "skipped_query_count": 1, "ok_count": 1, "results": [], "ok": True}

    monkeypatch.setattr("refgate.cli.run_live_smoke_suite", fake_suite)

    exit_code = main(["live-smoke-suite", "--queries", str(queries), "--source", "arxiv", "--max-queries", "1", "--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["query_count"] == 2
    assert payload["data"]["run_query_count"] == 1


def test_cli_live_smoke_suite_can_use_per_query_sources(monkeypatch, tmp_path, capsys):
    queries = tmp_path / "mixed_queries.json"
    queries.write_text(
        json.dumps(
            [
                {
                    "query_id": "pnas-fixture",
                    "citation_key": "smith2026",
                    "title": "Refgate Fixture: PNAS Official Record",
                    "source": "pnas",
                },
                {
                    "query_id": "mdpi-fixture",
                    "citation_key": "jones2026",
                    "title": "Refgate Fixture: MDPI Official Record",
                    "live_smoke_source": "mdpi",
                },
            ]
        ),
        encoding="utf-8",
    )

    def fake_suite(items, *, cache_root, **_kwargs):
        assert [item.source for item in items] == ["pnas", "mdpi"]
        assert [item.query.citation_key for item in items] == ["smith2026", "jones2026"]
        assert _kwargs["max_queries"] == 2
        return {
            "source": "mixed",
            "sources": ["mdpi", "pnas"],
            "source_counts": {"mdpi": 1, "pnas": 1},
            "query_count": 2,
            "run_query_count": 2,
            "skipped_query_count": 0,
            "ok_count": 2,
            "results": [],
            "ok": True,
        }

    monkeypatch.setattr("refgate.cli.run_live_smoke_suite_items", fake_suite)

    exit_code = main(
        [
            "live-smoke-suite",
            "--queries",
            str(queries),
            "--source",
            "arxiv",
            "--per-query-source",
            "--max-queries",
            "2",
            "--live",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["source"] == "mixed"
    assert payload["data"]["source_counts"] == {"mdpi": 1, "pnas": 1}


def test_cli_live_smoke_suite_can_use_resolver_recommended_source(monkeypatch, tmp_path, capsys):
    queries = tmp_path / "resolver_assist.json"
    queries.write_text(
        json.dumps(
            {
                "work_items": [
                    {
                        "query": {
                            "query_id": "q1",
                            "citation_key": "smith2026",
                            "title": "A Fixture Paper",
                        },
                        "recommended_sources": ["science", "crossref"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_suite(items, *, cache_root, **_kwargs):
        assert [item.source for item in items] == ["science"]
        return {"source": "science", "query_count": 1, "run_query_count": 1, "skipped_query_count": 0, "ok_count": 1, "results": [], "ok": True}

    monkeypatch.setattr("refgate.cli.run_live_smoke_suite_items", fake_suite)

    exit_code = main(["live-smoke-suite", "--queries", str(queries), "--source", "arxiv", "--per-query-source", "--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["data"]["source"] == "science"


def test_cli_live_smoke_suite_rejects_unsupported_per_query_source(tmp_path, capsys):
    queries = tmp_path / "queries.json"
    queries.write_text(json.dumps([{"query_id": "q1", "title": "A Fixture Paper", "source": "private_database"}]), encoding="utf-8")

    exit_code = main(["live-smoke-suite", "--queries", str(queries), "--per-query-source", "--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["blocking_issues"][0]["code"] == "UNSUPPORTED_SOURCE"
    assert payload["blocking_issues"][0]["evidence"] == ["private_database"]
