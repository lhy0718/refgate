import json
from pathlib import Path

from refgate.cli import main
from refgate.source_download import download_sources, source_pdf_url_for_entry
from refgate.lockfile import load_lockfile
from refgate.models import LockEntry


FIXTURES = Path(__file__).parent / "fixtures"


def test_source_download_plan_derives_arxiv_pdf_url_from_lockfile(capsys, tmp_path):
    lock = FIXTURES / "refgate.lock.json"
    source_dir = tmp_path / "sources"

    exit_code = main(["download-sources", "--lock", str(lock), "--source-dir", str(source_dir), "--json"])

    payload = json.loads(capsys.readouterr().out)
    item = payload["data"]["items"][0]
    assert exit_code == 0
    assert payload["status"] == "source_download_plan_ready"
    assert payload["data"]["live"] is False
    assert item["citation_key"] == "debenedetti2024agentdojo"
    assert item["url"] == "https://proceedings.neurips.cc/paper_files/paper/2024/file/example-Paper-Conference.pdf"
    assert item["status"] == "planned"
    assert payload["next_actions"][0]["network_required"] is True


def test_download_sources_live_uses_injected_fetcher(tmp_path):
    output_dir = tmp_path / "sources"

    result = download_sources(
        FIXTURES / "refgate.lock.json",
        source_dir=output_dir,
        live=True,
        fetcher=lambda url: b"%PDF-1.7 fixture\n",
    )

    assert result["ok"] is True
    assert result["downloaded_count"] == 1
    assert (output_dir / "debenedetti2024agentdojo.pdf").read_bytes().startswith(b"%PDF")
    assert result["items"][0]["status"] == "downloaded"


def test_source_download_url_derivation_prefers_pdf_records():
    entry = load_lockfile(FIXTURES / "refgate.lock.json").entries[0]

    url, source, reason = source_pdf_url_for_entry(entry)

    assert url == "https://proceedings.neurips.cc/paper_files/paper/2024/file/example-Paper-Conference.pdf"
    assert source == "neurips"
    assert reason is None


def test_source_download_labels_direct_iclr_pdf_url():
    entry = LockEntry(
        citation_key="iclrpaper2024",
        short_title="Fixture",
        status="missing_bibtex_provenance",
        record={
            "title": "Fixture Paper",
            "url": "https://proceedings.iclr.cc/paper_files/paper/2024/file/abc-Paper-Conference.pdf",
        },
        authority={"source": "unverified_bibtex", "record_url": ""},
        bibtex={"source_kind": "unknown"},
        resolver={},
        checked_at="2026-05-20",
    )

    url, source, reason = source_pdf_url_for_entry(entry)

    assert url == "https://proceedings.iclr.cc/paper_files/paper/2024/file/abc-Paper-Conference.pdf"
    assert source == "iclr"
    assert reason is None


def test_source_download_derives_iclr_pdf_url_from_abstract_record():
    entry = LockEntry(
        citation_key="iclrpaper2024",
        short_title="Fixture",
        status="verified_official_bibtex",
        record={
            "title": "Fixture Paper",
            "url": "https://proceedings.iclr.cc/paper_files/paper/2024/hash/abc-Abstract-Conference.html",
        },
        authority={"source": "iclr", "record_url": "https://proceedings.iclr.cc/paper_files/paper/2024/hash/abc-Abstract-Conference.html"},
        bibtex={"source_kind": "official_export"},
        resolver={},
        checked_at="2026-05-20",
    )

    url, source, reason = source_pdf_url_for_entry(entry)

    assert url == "https://proceedings.iclr.cc/paper_files/paper/2024/file/abc-Paper-Conference.pdf"
    assert source == "iclr"
    assert reason is None


def test_source_download_derives_openreview_pdf_url_from_forum_record():
    entry = LockEntry(
        citation_key="liu2024agentbench",
        short_title="AgentBench",
        status="verified_manual_fallback",
        record={"title": "AgentBench", "url": "https://openreview.net/forum?id=zAdUB0aCTQ"},
        authority={"source": "openreview", "record_url": "https://openreview.net/forum?id=zAdUB0aCTQ"},
        bibtex={"source_kind": "publisher_metadata_manual_normalized"},
        resolver={},
        checked_at="2026-06-09",
    )

    url, source, reason = source_pdf_url_for_entry(entry)

    assert url == "https://openreview.net/pdf?id=zAdUB0aCTQ"
    assert source == "openreview"
    assert reason is None


def test_source_download_prefers_official_bibtex_pdf_url_over_neurips_abstract_record():
    entry = LockEntry(
        citation_key="brown2020language",
        short_title="Language Models are Few-Shot Learners",
        status="verified_official_bibtex",
        record={
            "title": "Language Models are Few-Shot Learners",
            "url": "https://proceedings.neurips.cc/paper/2020/hash/1457c0d6bfcb4967418bfb8ac142f64a-Abstract.html",
        },
        authority={
            "source": "neurips",
            "record_url": "https://proceedings.neurips.cc/paper/2020/hash/1457c0d6bfcb4967418bfb8ac142f64a-Abstract.html",
        },
        bibtex={
            "source_kind": "official_export",
            "canonical_text": """@inproceedings{brown2020language,
 author = {Brown, Tom},
 title = {Language Models are Few-Shot Learners},
 url = {https://proceedings.neurips.cc/paper_files/paper/2020/file/1457c0d6bfcb4967418bfb8ac142f64a-Paper.pdf},
 year = {2020}
}
""",
        },
        resolver={},
        checked_at="2026-05-25",
    )

    url, source, reason = source_pdf_url_for_entry(entry)

    assert url == "https://proceedings.neurips.cc/paper_files/paper/2020/file/1457c0d6bfcb4967418bfb8ac142f64a-Paper.pdf"
    assert source == "neurips"
    assert reason is None


def test_source_download_derives_neurips_pdf_from_abstract_html_without_conference_suffix():
    entry = LockEntry(
        citation_key="brown2020language",
        short_title="Language Models are Few-Shot Learners",
        status="verified_official_bibtex",
        record={
            "title": "Language Models are Few-Shot Learners",
            "url": "https://proceedings.neurips.cc/paper/2020/hash/1457c0d6bfcb4967418bfb8ac142f64a-Abstract.html",
        },
        authority={"source": "neurips", "record_url": "https://proceedings.neurips.cc/paper/2020/hash/1457c0d6bfcb4967418bfb8ac142f64a-Abstract.html"},
        bibtex={"source_kind": "official_export"},
        resolver={},
        checked_at="2026-05-25",
    )

    url, source, reason = source_pdf_url_for_entry(entry)

    assert url == "https://proceedings.neurips.cc/paper_files/paper/2020/file/1457c0d6bfcb4967418bfb8ac142f64a-Paper.pdf"
    assert source == "neurips"
    assert reason is None


def test_source_download_derives_generic_official_html_pdf_urls():
    cases = [
        (
            "pmlr",
            "https://proceedings.mlr.press/v37/ioffe15.html",
            "https://proceedings.mlr.press/v37/ioffe15.pdf",
        ),
        (
            "acm",
            "https://dl.acm.org/doi/abs/10.1145/3544548.3581216",
            "https://dl.acm.org/doi/pdf/10.1145/3544548.3581216",
        ),
        (
            "jmlr",
            "https://www.jmlr.org/papers/v3/blei03a.html",
            "https://www.jmlr.org/papers/volume3/blei03a/blei03a.pdf",
        ),
        (
            "cvf",
            "https://openaccess.thecvf.com/content_cvpr_2016/html/He_Deep_Residual_Learning_CVPR_2016_paper.html",
            "https://openaccess.thecvf.com/content_cvpr_2016/papers/He_Deep_Residual_Learning_CVPR_2016_paper.pdf",
        ),
        (
            "springer",
            "https://link.springer.com/chapter/10.1007/978-3-319-46493-0_38",
            "https://link.springer.com/content/pdf/10.1007/978-3-319-46493-0_38.pdf",
        ),
        (
            "pnas",
            "https://www.pnas.org/doi/abs/10.1073/pnas.260000001",
            "https://www.pnas.org/doi/pdf/10.1073/pnas.260000001",
        ),
        (
            "science",
            "https://www.science.org/doi/full/10.1126/science.refgate001",
            "https://www.science.org/doi/pdf/10.1126/science.refgate001",
        ),
        (
            "frontiers",
            "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.00001/full",
            "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.00001/pdf",
        ),
        (
            "mdpi",
            "https://www.mdpi.com/2076-0000/26/1/1",
            "https://www.mdpi.com/2076-0000/26/1/1/pdf",
        ),
    ]

    for source_name, record_url, expected_pdf_url in cases:
        entry = LockEntry(
            citation_key=f"{source_name}paper",
            short_title="Fixture",
            status="verified_manual_fallback",
            record={"title": "Fixture Paper", "url": record_url},
            authority={"source": source_name, "record_url": record_url},
            bibtex={"source_kind": "publisher_metadata_manual_normalized"},
            resolver={},
            checked_at="2026-05-25",
        )

        url, source, reason = source_pdf_url_for_entry(entry)

        assert url == expected_pdf_url
        assert source == source_name
        assert reason is None


def test_source_download_labels_new_direct_pdf_sources():
    cases = [
        ("oxford", "https://academic.oup.com/refgate/article-pdf/1/1/1/9999999/refgate001.pdf"),
        ("cambridge", "https://www.cambridge.org/core/services/aop-cambridge-core/content/view/fixture.pdf"),
        ("lipics", "https://drops.dagstuhl.de/storage/00lipics/refgate/refgate001.pdf"),
    ]

    for source_name, record_url in cases:
        entry = LockEntry(
            citation_key=f"{source_name}paper",
            short_title="Fixture",
            status="verified_manual_fallback",
            record={"title": "Fixture Paper", "url": record_url},
            authority={"source": source_name, "record_url": record_url},
            bibtex={"source_kind": "publisher_metadata_manual_normalized"},
            resolver={},
            checked_at="2026-05-25",
        )

        url, source, reason = source_pdf_url_for_entry(entry)

        assert url == record_url
        assert source == source_name
        assert reason is None
