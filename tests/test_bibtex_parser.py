from refgate.bibtex import parse_bibtex_file, rekey_bibtex_entry


def test_bibtex_parser_preserves_nested_brace_field():
    parsed = parse_bibtex_file(
        """@article{smith2026nested,
  title = {A {Nested} Title, With Comma},
  author = {Ada Smith and Bert Lee},
  journal = {Journal of Fixtures},
  year = {2026}
}
"""
    )

    entry = parsed["smith2026nested"]
    assert entry["title"] == "A {Nested} Title, With Comma"
    assert entry["author"] == "Ada Smith and Bert Lee"


def test_bibtex_parser_accepts_quoted_comma_values():
    parsed = parse_bibtex_file(
        """@misc{smith2026quoted,
  title = "A quoted, comma title",
  howpublished = "arXiv preprint",
  year = 2026
}
"""
    )

    entry = parsed["smith2026quoted"]
    assert entry["title"] == "A quoted, comma title"
    assert entry["howpublished"] == "arXiv preprint"


def test_bibtex_parser_expands_string_macros_and_skips_comments():
    parsed = parse_bibtex_file(
        """@string{pmlr = {Proceedings of Machine Learning Research}}
@comment{ignored}
@inproceedings{smith2026macro,
  title = {Macro Fixture},
  booktitle = pmlr,
  year = 2026
}
"""
    )

    assert parsed["smith2026macro"]["booktitle"] == "Proceedings of Machine Learning Research"


def test_bibtex_parser_normalizes_publisher_doi_and_pages():
    parsed = parse_bibtex_file(
        """@inproceedings{smith2026publisher,
  title = {Publisher Fixture},
  doi = {https://doi.org/10.1145/1234567.8901234},
  pages = {1-12},
  publisher = {Association for Computing Machinery},
  year = {2026}
}
@article{lee2026ieee,
  title = {IEEE Fixture},
  doi = {DOI: 10.1109/TEST.2026.12345},
  pages = {13–25},
  publisher = {IEEE},
  year = {2026}
}
"""
    )

    assert parsed["smith2026publisher"]["doi"] == "10.1145/1234567.8901234"
    assert parsed["smith2026publisher"]["pages"] == "1--12"
    assert parsed["smith2026publisher"]["publisher"] == "ACM"
    assert parsed["lee2026ieee"]["doi"] == "10.1109/test.2026.12345"
    assert parsed["lee2026ieee"]["pages"] == "13--25"


def test_rekey_bibtex_entry_preserves_body_with_new_citation_key():
    text = """@inproceedings{official-key,
  title = {Official Title},
  year = {2026}
}
"""

    rekeyed = rekey_bibtex_entry(text, "manuscriptKey2026")
    parsed = parse_bibtex_file(rekeyed)

    assert "manuscriptKey2026" in parsed
    assert parsed["manuscriptKey2026"]["title"] == "Official Title"
