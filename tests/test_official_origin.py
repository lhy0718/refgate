import json

from refgate.lockfile import load_lockfile
from refgate.official_origin import origin_audit_issues, verify_official_bibtex_origin


EXPORT = """@inproceedings{publisher-key,
  title = {A Paper About Things},
  author = {Doe, Jane},
  year = {2026},
  doi = {10.1234/refgate.2026}
}
"""


def _lock(tmp_path, *, origin_check=None):
    entry = {
        "citation_key": "doe2026paper",
        "short_title": "A Paper",
        "status": "verified_official_bibtex",
        "record": {"title": "A Paper About Things", "authors": ["Doe, Jane"], "year": 2026},
        "authority": {"source": "acl", "bibtex_url": "https://publisher.example/doe2026.bib"},
        "bibtex": {"citation_key": "doe2026paper", "source_kind": "official_export"},
        "resolver": {"score": 100, "blocking_issues": [], "warnings": [], "decision_trace": []},
        "checked_at": "2026-05-23",
    }
    if origin_check is not None:
        entry["bibtex"]["origin_check"] = origin_check
    path = tmp_path / "refgate.lock.json"
    path.write_text(json.dumps({"schema_version": "refgate.lock.v1", "entries": [entry]}), encoding="utf-8")
    return path


def _export_dir(tmp_path, text=EXPORT):
    directory = tmp_path / "official-bibtex"
    directory.mkdir(exist_ok=True)
    (directory / "doe2026paper.bib").write_text(text, encoding="utf-8")
    return directory


def test_origin_check_passes_when_the_bytes_are_the_publisher_s(tmp_path):
    result = verify_official_bibtex_origin(
        lock=_lock(tmp_path),
        official_bibtex_dir=_export_dir(tmp_path),
        live=True,
        fetcher=lambda url: EXPORT,
    )

    assert result["ok"] is True
    assert result["verified"] == 1
    assert result["results"][0]["result"] == "match"


def test_origin_check_catches_a_transcription_that_differs_only_in_whitespace(tmp_path):
    """The failure this check exists for.

    An export retyped from a rendered page can match the publisher word for word
    and still not be the file. Here it differs by the trailing newline alone --
    which is exactly how one such entry was found in a real bibliography.
    """
    result = verify_official_bibtex_origin(
        lock=_lock(tmp_path),
        official_bibtex_dir=_export_dir(tmp_path, text=EXPORT.rstrip("\n")),
        live=True,
        fetcher=lambda url: EXPORT,
    )

    assert result["ok"] is False
    assert result["results"][0]["result"] == "whitespace_only_difference"
    assert {issue["code"] for issue in result["blocking_issues"]} == {"OFFICIAL_EXPORT_ORIGIN_MISMATCH"}


def test_origin_check_reports_a_real_content_difference(tmp_path):
    result = verify_official_bibtex_origin(
        lock=_lock(tmp_path),
        official_bibtex_dir=_export_dir(tmp_path, text=EXPORT.replace("2026", "2025")),
        live=True,
        fetcher=lambda url: EXPORT,
    )

    assert result["results"][0]["result"] == "differs"
    assert result["blocking_issues"][0]["code"] == "OFFICIAL_EXPORT_ORIGIN_MISMATCH"


def test_origin_check_does_nothing_without_live_and_says_so(tmp_path):
    result = verify_official_bibtex_origin(
        lock=_lock(tmp_path),
        official_bibtex_dir=_export_dir(tmp_path),
        live=False,
        fetcher=lambda url: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )

    assert result["results"][0]["result"] == "not_checked"
    assert result["verified"] == 0


def test_origin_check_records_its_verdict_in_the_lockfile(tmp_path):
    lock = _lock(tmp_path)
    verify_official_bibtex_origin(
        lock=lock,
        official_bibtex_dir=_export_dir(tmp_path),
        live=True,
        write_lock=lock,
        fetcher=lambda url: EXPORT,
    )
    stored = load_lockfile(lock).entries[0].bibtex["origin_check"]

    assert stored["result"] == "match"
    assert stored["url"] == "https://publisher.example/doe2026.bib"


def test_audit_blocks_an_official_export_whose_origin_was_never_checked(tmp_path):
    """source_kind is assigned from a directory, so an unchecked export is a claim, not a fact."""
    unchecked = load_lockfile(_lock(tmp_path))
    verified = load_lockfile(_lock(tmp_path, origin_check={"result": "match", "url": "https://publisher.example/doe2026.bib"}))

    submission = origin_audit_issues(unchecked, submission=True)
    ordinary = origin_audit_issues(unchecked, submission=False)

    assert [issue.code for issue in submission] == ["OFFICIAL_EXPORT_ORIGIN_UNVERIFIED"]
    assert submission[0].severity == "blocking"
    assert ordinary[0].severity == "warning"
    assert origin_audit_issues(verified, submission=True) == []
