from refgate import source_text


def test_validate_source_text_reports_missing_pdf_extra_once(tmp_path, monkeypatch):
    pdf_one = tmp_path / "one.pdf"
    pdf_two = tmp_path / "two.pdf"
    pdf_one.write_bytes(b"%PDF fixture one")
    pdf_two.write_bytes(b"%PDF fixture two")
    monkeypatch.setattr(source_text, "pdf_text_extraction_available", lambda: False)

    result = source_text.validate_source_text([pdf_one, pdf_two])

    assert result["ok"] is False
    assert len(result["blocking_issues"]) == 1
    assert result["blocking_issues"][0]["code"] == "PDF_TEXT_EXTRA_MISSING"
    assert 'refgate[pdf]' in result["blocking_issues"][0]["evidence"][1]
