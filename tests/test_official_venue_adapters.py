from pathlib import Path

from refgate.adapters.venues import ADAPTERS, OpenReviewAdapter, PmlrAdapter, candidate_from_venue_html
from refgate.models import PaperQuery


FIXTURES = Path(__file__).parent / "fixtures"


def test_generic_official_venue_adapter_finds_bibtex_endpoint():
    html = (FIXTURES / "pmlr_authority.html").read_text(encoding="utf-8")
    candidate = candidate_from_venue_html("pmlr", "https://proceedings.mlr.press/v999/smith26.html", html)

    authority = PmlrAdapter().fetch_authority(candidate)
    endpoints = PmlrAdapter().find_export_endpoints(authority)

    assert candidate.source == "pmlr"
    assert candidate.is_official_record is True
    assert candidate.bibtex_url == "https://proceedings.mlr.press/v999/fixture-learning.bib"
    assert endpoints[0].is_official is True


def test_pmlr_adapter_reads_inline_bibtex_export():
    html = (FIXTURES / "pmlr_inline_bibtex_authority.html").read_text(encoding="utf-8")
    url = "https://proceedings.mlr.press/v999/smith26.html"
    candidate = PmlrAdapter(fetcher=lambda _url: html).candidate_from_html(url, html)
    authority = PmlrAdapter(fetcher=lambda _url: html).fetch_authority(candidate)
    endpoints = PmlrAdapter(fetcher=lambda _url: html).find_export_endpoints(authority)

    bibtex = PmlrAdapter(fetcher=lambda _url: html).fetch_bibtex(authority, endpoints[0])

    assert candidate.bibtex_url == url
    assert endpoints[0].discovered_by == "inline_bibtex_code"
    assert bibtex.source_kind == "official_export"
    assert bibtex.citation_key == "pmlr-v999-smith26"


def test_openreview_official_record_can_lack_official_bibtex_export():
    html = (FIXTURES / "openreview_authority.html").read_text(encoding="utf-8")
    candidate = OpenReviewAdapter().candidate_from_html("https://openreview.net/forum?id=fixture", html)

    assert candidate.source == "openreview"
    assert candidate.is_official_record is True
    assert candidate.bibtex_url is None
    assert candidate.raw["official_bibtex_status"] == "not_discovered"


def test_openreview_adapter_reads_embedded_forum_note_metadata_without_marking_official_bibtex():
    html = r'''
    <html><head><meta property="og:title" content="Adam: A Method for Stochastic Optimization"></head>
    <script>
    self.__next_f.push([1,"forumNote\":{\"content\":{\"venue\":\"ICLR (Poster) 2015\",\"_bibtex\":\"@inproceedings{DBLP:journals/corr/KingmaB14,\n  author={Diederik P. Kingma and Jimmy Ba},\n  title={Adam: A Method for Stochastic Optimization},\n  year={2015},\n  url={http://arxiv.org/abs/1412.6980},\n  booktitle={ICLR (Poster)}\n}\n\",\"authors\":[\"Diederik P. Kingma\",\"Jimmy Ba\"],\"html\":\"http://arxiv.org/abs/1412.6980\",\"title\":\"Adam: A Method for Stochastic Optimization\",\"pdf\":\"http://arxiv.org/pdf/1412.6980v9\"}}"])
    </script></html>
    '''

    candidate = OpenReviewAdapter().candidate_from_html("https://openreview.net/forum?id=8gmWwjFyLj", html)

    assert candidate.title == "Adam: A Method for Stochastic Optimization"
    assert candidate.authors == ["Diederik P. Kingma", "Jimmy Ba"]
    assert candidate.year == 2015
    assert candidate.venue == "ICLR (Poster) 2015"
    assert candidate.arxiv_id == "1412.6980"
    assert candidate.bibtex_url is None
    assert candidate.raw["embedded_bibtex_present"] is True


def test_generic_official_html_unescapes_bibtex_anchor_href():
    html = '<html><a href="https://citation-needed.springer.com/v2/references/10.1007/example?format=bibtex&amp;flavour=citation">BibTeX</a></html>'
    candidate = candidate_from_venue_html("springer", "https://link.springer.com/chapter/10.1007/example", html)

    authority = ADAPTERS["springer"]().fetch_authority(candidate)
    endpoints = ADAPTERS["springer"]().find_export_endpoints(authority)

    assert endpoints[0].url == "https://citation-needed.springer.com/v2/references/10.1007/example?format=bibtex&flavour=citation"


def test_acm_adapter_reads_json_ld_and_derives_official_export_url():
    html = """
    <html><head><script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ScholarlyArticle",
      "name": "ACM Fixture Paper from JSON-LD",
      "doi": "10.1145/3544548.3581216",
      "datePublished": "2023-04-19",
      "isPartOf": {"name": "Proceedings of the 2023 CHI Conference on Human Factors in Computing Systems"},
      "author": [
        {"@type": "Person", "name": "Fixture Author"},
        {"@type": "Person", "name": "Second Author"}
      ]
    }
    </script></head></html>
    """

    candidate = candidate_from_venue_html("acm", "https://dl.acm.org/doi/10.1145/3544548.3581216", html)
    authority = ADAPTERS["acm"]().fetch_authority(candidate)
    endpoints = ADAPTERS["acm"]().find_export_endpoints(authority)

    assert candidate.title == "ACM Fixture Paper from JSON-LD"
    assert candidate.authors == ["Fixture Author", "Second Author"]
    assert candidate.year == 2023
    assert candidate.venue == "Proceedings of the 2023 CHI Conference on Human Factors in Computing Systems"
    assert candidate.doi == "10.1145/3544548.3581216"
    assert candidate.bibtex_url == (
        "https://dl.acm.org/action/exportCiteProcCitation?"
        "dois=10.1145%2F3544548.3581216&targetFile=custom-bibtex&format=bibTex"
    )
    assert endpoints[0].is_official is True


def test_acm_adapter_derives_doi_from_record_url_when_metadata_is_sparse():
    candidate = candidate_from_venue_html("acm", "https://dl.acm.org/doi/abs/10.1145/3544548.3581216", "<html></html>")

    assert candidate.doi == "10.1145/3544548.3581216"
    assert candidate.bibtex_url.endswith("dois=10.1145%2F3544548.3581216&targetFile=custom-bibtex&format=bibTex")


def test_generic_venue_adapters_discover_from_preferred_record_urls():
    cases = [
        (
            "acm",
            "https://dl.acm.org/doi/10.1145/refgate.acm",
            "acm_authority.html",
            "Refgate Fixture: ACM Official Record",
            "10.1145/refgate.acm",
            "https://dl.acm.org/action/exportCiteProcCitation?dois=10.1145%2Frefgate.acm&targetFile=custom-bibtex&format=bibTex",
        ),
        (
            "aaai",
            "https://ojs.aaai.org/index.php/AAAI/article/view/1",
            "aaai_authority.html",
            "Refgate Fixture: AAAI Official Record",
            "10.1609/refgate.aaai",
            "https://ojs.aaai.org/index.php/AAAI/citationstylelanguage/download/bibtex?submissionId=1",
        ),
        (
            "elsevier",
            "https://www.sciencedirect.com/science/article/pii/S000000000000001",
            "elsevier_authority.html",
            "Refgate Fixture: Elsevier Official Record",
            "10.1016/j.refgate.2026.01.001",
            None,
        ),
        (
            "cvf",
            "https://openaccess.thecvf.com/content/CVPR2026/html/Smith_Refgate_Fixture_CVF_Official_Record_CVPR_2026_paper.html",
            "cvf_authority.html",
            "Refgate Fixture: CVF Official Record",
            None,
            "https://openaccess.thecvf.com/content/CVPR2026/html/Smith_Refgate_Fixture_CVF_Official_Record_CVPR_2026_paper.html",
        ),
        (
            "ieee",
            "https://ieeexplore.ieee.org/document/1234567",
            "ieee_authority.html",
            "Refgate Fixture: IEEE Official Record",
            "10.1109/REFGATE.2026.00001",
            None,
        ),
        (
            "jmlr",
            "https://www.jmlr.org/papers/v27/smith26a.html",
            "jmlr_authority.html",
            "Refgate Fixture: JMLR Official Record",
            None,
            "https://www.jmlr.org/papers/v27/smith26a.bib",
        ),
        (
            "nature",
            "https://www.nature.com/articles/s42256-026-00001-2",
            "nature_authority.html",
            "Refgate Fixture: Nature Official Record",
            "10.1038/s42256-026-00001-2",
            None,
        ),
        (
            "springer",
            "https://link.springer.com/chapter/10.1007/refgate-springer",
            "springer_authority.html",
            "Refgate Fixture: Springer Official Record",
            "10.1007/refgate-springer",
            None,
        ),
        (
            "wiley",
            "https://onlinelibrary.wiley.com/doi/10.1002/refgate.2026.001",
            "wiley_authority.html",
            "Refgate Fixture: Wiley Official Record",
            "10.1002/refgate.2026.001",
            None,
        ),
        (
            "sage",
            "https://journals.sagepub.com/doi/10.1177/0000000026000001",
            "sage_authority.html",
            "Refgate Fixture: SAGE Official Record",
            "10.1177/0000000026000001",
            None,
        ),
        (
            "taylorfrancis",
            "https://www.tandfonline.com/doi/full/10.1080/00000000.2026.0000001",
            "taylorfrancis_authority.html",
            "Refgate Fixture: Taylor & Francis Official Record",
            "10.1080/00000000.2026.0000001",
            None,
        ),
        (
            "usenix",
            "https://www.usenix.org/conference/refgate26/presentation/smith",
            "usenix_authority.html",
            "Refgate Fixture: USENIX Official Record",
            None,
            "https://www.usenix.org/conference/refgate26/presentation/smith/bibtex",
        ),
    ]

    for source, url, fixture, title, doi, bibtex_url in cases:
        adapter = ADAPTERS[source](fetcher=lambda _url, fixture=fixture: (FIXTURES / fixture).read_text(encoding="utf-8"))

        candidates = adapter.discover(PaperQuery(query_id=source, title=title, preferred_venues=[url]))

        assert len(candidates) == 1
        assert candidates[0].source == source
        assert candidates[0].title == title
        assert candidates[0].doi == doi
        assert candidates[0].bibtex_url == bibtex_url
        assert adapter.fetch_authority(candidates[0]) is not None


def test_generic_venue_adapters_ignore_unmatched_preferred_urls():
    adapter = ADAPTERS["acm"](fetcher=lambda _url: (FIXTURES / "acm_authority.html").read_text(encoding="utf-8"))

    candidates = adapter.discover(
        PaperQuery(
            query_id="acm",
            title="Refgate Fixture: ACM Official Record",
            preferred_venues=["https://example.org/not-acm"],
        )
    )

    assert candidates == []


def test_ieee_adapter_reads_script_metadata_when_citation_meta_is_sparse():
    html = (FIXTURES / "ieee_script_authority.html").read_text(encoding="utf-8")
    candidate = ADAPTERS["ieee"]().candidate_from_html("https://ieeexplore.ieee.org/document/7780459", html)

    assert candidate.title == "Deep Residual Learning for Image Recognition"
    assert candidate.authors == ["Kaiming He", "Xiangyu Zhang"]
    assert candidate.year == 2016
    assert candidate.venue == "2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)"
    assert candidate.doi == "10.1109/CVPR.2016.90"


def test_cvf_adapter_fetches_inline_official_bibtex():
    html = (FIXTURES / "cvf_authority.html").read_text(encoding="utf-8")
    url = "https://openaccess.thecvf.com/content/CVPR2026/html/Smith_Refgate_Fixture_CVF_Official_Record_CVPR_2026_paper.html"
    adapter = ADAPTERS["cvf"](fetcher=lambda _url: html)

    candidate = adapter.discover(PaperQuery(query_id="cvf", title="Refgate Fixture: CVF Official Record", preferred_venues=[url]))[0]
    authority = adapter.fetch_authority(candidate)
    endpoints = adapter.find_export_endpoints(authority)
    bibtex = adapter.fetch_bibtex(authority, endpoints[0])

    assert candidate.source == "cvf"
    assert candidate.venue == "Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition"
    assert endpoints[0].discovered_by == "inline_bibtex_code"
    assert bibtex.source_kind == "official_export"
    assert bibtex.citation_key == "Smith_2026_CVPR"


def test_jmlr_adapter_fetches_relative_official_bibtex_link():
    html = (FIXTURES / "jmlr_authority.html").read_text(encoding="utf-8")
    bibtex_text = (FIXTURES / "jmlr_official.bib").read_text(encoding="utf-8")
    url = "https://www.jmlr.org/papers/v27/smith26a.html"

    def fetcher(fetch_url: str) -> str:
        if fetch_url.endswith(".bib"):
            return bibtex_text
        return html

    adapter = ADAPTERS["jmlr"](fetcher=fetcher)
    candidate = adapter.discover(PaperQuery(query_id="jmlr", title="Refgate Fixture: JMLR Official Record", preferred_venues=[url]))[0]
    authority = adapter.fetch_authority(candidate)
    endpoints = adapter.find_export_endpoints(authority)
    bibtex = adapter.fetch_bibtex(authority, endpoints[0])

    assert candidate.source == "jmlr"
    assert candidate.venue == "Journal of Machine Learning Research"
    assert endpoints[0].url == "https://www.jmlr.org/papers/v27/smith26a.bib"
    assert bibtex.source_kind == "official_export"
    assert bibtex.citation_key == "smith26a"


def test_nature_adapter_verifies_official_record_without_bibtex_export():
    html = (FIXTURES / "nature_authority.html").read_text(encoding="utf-8")
    url = "https://www.nature.com/articles/s42256-026-00001-2"
    adapter = ADAPTERS["nature"](fetcher=lambda _url: html)

    candidate = adapter.discover(PaperQuery(query_id="nature", title="Refgate Fixture: Nature Official Record", preferred_venues=[url]))[0]
    authority = adapter.fetch_authority(candidate)
    endpoints = adapter.find_export_endpoints(authority)

    assert candidate.source == "nature"
    assert candidate.is_official_record is True
    assert candidate.venue == "Nature Machine Intelligence"
    assert candidate.doi == "10.1038/s42256-026-00001-2"
    assert candidate.bibtex_url is None
    assert endpoints == []


def test_subscription_publisher_adapters_keep_missing_bibtex_as_manual_boundary():
    cases = [
        (
            "wiley",
            "https://onlinelibrary.wiley.com/doi/10.1002/refgate.2026.001",
            "wiley_authority.html",
            "Refgate Fixture: Wiley Official Record",
            "Journal of Refgate Studies",
        ),
        (
            "sage",
            "https://journals.sagepub.com/doi/10.1177/0000000026000001",
            "sage_authority.html",
            "Refgate Fixture: SAGE Official Record",
            "SAGE Refgate Review",
        ),
        (
            "taylorfrancis",
            "https://www.tandfonline.com/doi/full/10.1080/00000000.2026.0000001",
            "taylorfrancis_authority.html",
            "Refgate Fixture: Taylor & Francis Official Record",
            "Taylor & Francis Refgate Letters",
        ),
    ]

    for source, url, fixture, title, venue in cases:
        html = (FIXTURES / fixture).read_text(encoding="utf-8")
        adapter = ADAPTERS[source](fetcher=lambda _url, html=html: html)
        candidate = adapter.discover(PaperQuery(query_id=source, title=title, preferred_venues=[url]))[0]
        authority = adapter.fetch_authority(candidate)
        endpoints = adapter.find_export_endpoints(authority)

        assert candidate.source == source
        assert candidate.is_official_record is True
        assert candidate.title == title
        assert candidate.venue == venue
        assert candidate.bibtex_url is None
        assert endpoints == []


def test_new_official_venue_adapters_are_fixture_backed_and_keep_export_boundary():
    cases = [
        (
            "oxford",
            "https://academic.oup.com/refgate/article/1/1/1/9999999",
            "oxford_authority.html",
            "Refgate Fixture: Oxford Official Record",
            "10.1093/refgate/fixture001",
            None,
        ),
        (
            "cambridge",
            "https://www.cambridge.org/core/journals/refgate/article/fixture",
            "cambridge_authority.html",
            "Refgate Fixture: Cambridge Official Record",
            "10.1017/refgate.2026.1",
            None,
        ),
        (
            "pnas",
            "https://www.pnas.org/doi/abs/10.1073/pnas.260000001",
            "pnas_authority.html",
            "Refgate Fixture: PNAS Official Record",
            "10.1073/pnas.260000001",
            "https://www.pnas.org/doi/bibtex/10.1073/pnas.260000001",
        ),
        (
            "science",
            "https://www.science.org/doi/abs/10.1126/science.refgate001",
            "science_authority.html",
            "Refgate Fixture: Science Official Record",
            "10.1126/science.refgate001",
            None,
        ),
        (
            "frontiers",
            "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.00001/full",
            "frontiers_authority.html",
            "Refgate Fixture: Frontiers Official Record",
            "10.3389/frai.2026.00001",
            "https://www.frontiersin.org/articles/10.3389/frai.2026.00001/bibtex",
        ),
        (
            "mdpi",
            "https://www.mdpi.com/2076-0000/26/1/1",
            "mdpi_authority.html",
            "Refgate Fixture: MDPI Official Record",
            "10.3390/refgate26010001",
            "https://www.mdpi.com/2076-0000/26/1/1/bibtex",
        ),
        (
            "lipics",
            "https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.Refgate.2026.1",
            "lipics_authority.html",
            "Refgate Fixture: LIPIcs Official Record",
            "10.4230/LIPIcs.Refgate.2026.1",
            "https://drops.dagstuhl.de/bibtex/10.4230/LIPIcs.Refgate.2026.1",
        ),
    ]

    for source, url, fixture, title, doi, bibtex_url in cases:
        html = (FIXTURES / fixture).read_text(encoding="utf-8")
        adapter = ADAPTERS[source](fetcher=lambda _url, html=html: html)
        candidate = adapter.discover(PaperQuery(query_id=source, title=title, preferred_venues=[url]))[0]
        authority = adapter.fetch_authority(candidate)
        endpoints = adapter.find_export_endpoints(authority)

        assert candidate.source == source
        assert candidate.is_official_record is True
        assert candidate.title == title
        assert candidate.doi == doi
        assert candidate.bibtex_url == bibtex_url
        if bibtex_url:
            assert endpoints[0].is_official is True
        else:
            assert endpoints == []


def test_new_official_venue_adapter_fetches_verified_endpoint_but_not_missing_exports():
    html = (FIXTURES / "mdpi_authority.html").read_text(encoding="utf-8")
    bib = (FIXTURES / "generic_new_venue_official.bib").read_text(encoding="utf-8")

    def fetch(url: str) -> str:
        return bib if url.endswith("/bibtex") else html

    adapter = ADAPTERS["mdpi"](fetcher=fetch)
    candidate = adapter.discover(
        PaperQuery(
            query_id="mdpi",
            title="Refgate Fixture: MDPI Official Record",
            preferred_venues=["https://www.mdpi.com/2076-0000/26/1/1"],
        )
    )[0]
    authority = adapter.fetch_authority(candidate)
    bibtex = adapter.fetch_bibtex(authority, adapter.find_export_endpoints(authority)[0])

    assert bibtex.source_kind == "official_export"
    assert bibtex.citation_key == "refgateNewVenue2026"

    science_html = (FIXTURES / "science_authority.html").read_text(encoding="utf-8")
    science = ADAPTERS["science"](fetcher=lambda _url: science_html)
    science_candidate = science.discover(
        PaperQuery(
            query_id="science",
            title="Refgate Fixture: Science Official Record",
            preferred_venues=["https://www.science.org/doi/abs/10.1126/science.refgate001"],
        )
    )[0]
    science_authority = science.fetch_authority(science_candidate)
    assert science.find_export_endpoints(science_authority) == []
