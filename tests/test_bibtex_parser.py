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


_ENTRY_A = '@article{a,\n    title = "First",\n    year = "2020",\n}\n'
_ENTRY_B = '@article{b,\n    title = "Second",\n    year = "2021",\n}\n'


@pytest.mark.parametrize(
    "between",
    [
        "% a note explaining why the next entry is here\n",
        "%% doubled comment marker\n",
        "plain prose with no comment marker\n",
        "\n\n",
        "@comment{ignored}\n",
    ],
)
def test_text_between_entries_is_not_absorbed(between: str) -> None:
    parsed = parse_bibtex_file(f"{_ENTRY_A}\n{between}\n{_ENTRY_B}")
    assert sorted(parsed) == ["a", "b"]
    assert parsed["a"]["title"] == "First"
    assert parsed["b"]["title"] == "Second"


def test_trailing_comment_after_last_entry() -> None:
    parsed = parse_bibtex_file(f"{_ENTRY_A}\n{_ENTRY_B}\n% trailing note\n")
    assert sorted(parsed) == ["a", "b"]


def test_leading_comment_before_first_entry() -> None:
    parsed = parse_bibtex_file(f"% leading note\n{_ENTRY_A}\n{_ENTRY_B}")
    assert sorted(parsed) == ["a", "b"]


def test_braces_inside_a_value_do_not_end_the_entry() -> None:
    entry = '@article{accented,\n    author = "Just, Ren{\\\'e} and Doe, Jane",\n}\n'
    parsed = parse_bibtex_file(f"{entry}\n% note\n{_ENTRY_B}")
    assert sorted(parsed) == ["accented", "b"]


def test_parse_error_names_the_citation_key() -> None:
    with pytest.raises(ValueError, match="near citation key 'broken'"):
        parse_bibtex_file('@article{broken,\n    title = "x"\n')
