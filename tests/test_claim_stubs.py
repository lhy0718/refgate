from pathlib import Path

from refgate.claim_audit import generate_claim_stubs, update_claim_stub_file
import csv


FIXTURES = Path(__file__).parent / "fixtures"


def test_generate_claim_stubs_marks_important_benchmark_claim():
    tex_text = (FIXTURES / "manuscript_claims.tex").read_text(encoding="utf-8")

    stubs = generate_claim_stubs(tex_text)

    assert len(stubs) == 1
    assert stubs[0].citation_key == "debenedetti2024agentdojo"
    assert stubs[0].importance == "important"
    assert stubs[0].claim_type == "benchmark_or_result"


def test_update_claim_stub_file_is_idempotent(tmp_path):
    tex_text = (FIXTURES / "manuscript_claims.tex").read_text(encoding="utf-8")
    output = tmp_path / "claims.tsv"

    first = update_claim_stub_file(tex_text, output)
    second = update_claim_stub_file(tex_text, output)

    assert len(first) == 1
    assert second == []
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 1
    assert rows[0]["citation_key"] == "debenedetti2024agentdojo"


def test_generate_claim_stubs_splits_multi_citation_sentence_into_local_claims():
    tex_text = (
        "Tool-use benchmarks expose prompt-injection attacks \\cite{alpha2024}, "
        "while policy benchmarks cover permission misuse \\cite{beta2025}."
    )

    stubs = generate_claim_stubs(tex_text)

    assert [stub.citation_key for stub in stubs] == ["alpha2024", "beta2025"]
    assert stubs[0].claim_text == "Tool-use benchmarks expose prompt-injection attacks"
    assert stubs[1].claim_text == "policy benchmarks cover permission misuse"


def test_generate_claim_stubs_uses_previous_wrapped_line_for_citation_context():
    tex_text = (
        "Modern tool-using agents extend language models into interactive environments,\n"
        "which makes prompt injection and source integrity failures more consequential\n"
        "\\cite{debenedetti2024agentdojo}.\n"
    )

    stubs = generate_claim_stubs(tex_text)

    assert len(stubs) == 1
    assert stubs[0].manuscript_location == "line 3"
    assert stubs[0].citation_key == "debenedetti2024agentdojo"
    assert stubs[0].claim_text == "which makes prompt injection and source integrity failures more consequential"


def test_generate_claim_stubs_keeps_serial_list_tail_with_final_conjunction():
    tex_text = (
        "The FAIR principles emphasize findability, accessibility, interoperability, "
        "and reuse of digital assets \\cite{wilkinson2016fair}."
    )

    stubs = generate_claim_stubs(tex_text)

    assert len(stubs) == 1
    assert stubs[0].claim_text == "The FAIR principles emphasize findability, accessibility, interoperability, and reuse of digital assets"
