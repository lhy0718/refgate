from __future__ import annotations

import csv
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from .bibtex import parse_bibtex_file
from .evidence_policy import is_weak_evidence_kind
from .models import AuditIssue
from .source_text import read_source_text


PASSING_CLAIM_STATUSES = {"checked", "checked_arxiv"}
BLOCKING_CLAIM_STATUSES = {
    "too_strong",
    "wrong_source",
    "delete_or_rewrite",
    "claim_unchecked",
    "needs_review",
    "needs_review_weak_evidence",
}
CLAIM_COLUMNS = [
    "claim_id",
    "manuscript_location",
    "source_file",
    "claim_text",
    "citation_key",
    "source_location",
    "quote_or_evidence",
    "evidence_kind",
    "status",
    "notes",
    "claim_type",
    "importance",
]

HEADING_COMMAND_RE = re.compile(
    r"\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph)"
    r"\*?(?:\[[^\]]*\])?\{[^{}]*\}"
)

STOP_TERMS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "and",
    "are",
    "because",
    "been",
    "before",
    "between",
    "both",
    "can",
    "cite",
    "does",
    "for",
    "from",
    "has",
    "have",
    "into",
    "its",
    "may",
    "more",
    "not",
    "our",
    "over",
    "paper",
    "show",
    "shows",
    "such",
    "than",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "through",
    "using",
    "was",
    "were",
    "which",
    "with",
}


@dataclass
class ClaimStub:
    claim_id: str
    manuscript_location: str
    claim_text: str
    citation_key: str
    source_file: str = ""
    source_location: str = ""
    quote_or_evidence: str = ""
    status: str = "claim_unchecked"
    notes: str = ""
    claim_type: str = "citation_context"
    importance: str = "normal"

    def to_row(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "manuscript_location": self.manuscript_location,
            "source_file": self.source_file,
            "claim_text": self.claim_text,
            "citation_key": self.citation_key,
            "source_location": self.source_location,
            "quote_or_evidence": self.quote_or_evidence,
            "evidence_kind": "",
            "status": self.status,
            "notes": self.notes,
            "claim_type": self.claim_type,
            "importance": self.importance,
        }


def extract_citation_keys(tex_text: str) -> set[str]:
    keys: set[str] = set()
    for match in re.finditer(r"\\cite[a-zA-Z*]*\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]+)\}", tex_text):
        for key in re.split(r"[,;\s]+", match.group(1)):
            if key.strip():
                keys.add(key.strip())
    return keys


def _strip_tex_commands(text: str) -> str:
    text = re.sub(r"%.*", "", text)
    text = HEADING_COMMAND_RE.sub(" ", text)
    text = re.sub(r"\\(textbf|emph)\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\2", text)
    return re.sub(r"\s+", " ", text).strip()


def _paragraph_spans(tex_text: str) -> list[tuple[str, list[int]]]:
    spans: list[tuple[str, list[int]]] = []
    text_parts: list[str] = []
    line_map: list[int] = []

    def flush() -> None:
        nonlocal text_parts, line_map
        paragraph = "".join(text_parts).strip()
        if paragraph:
            spans.append((paragraph, line_map[: len("".join(text_parts))]))
        text_parts = []
        line_map = []

    for line_number, raw_line in enumerate(tex_text.splitlines(), start=1):
        line = re.sub(r"%.*", "", raw_line).strip()
        if not line:
            flush()
            continue
        if HEADING_COMMAND_RE.search(line):
            flush()
            line = HEADING_COMMAND_RE.sub(" ", line).strip()
            if not line:
                continue
        if text_parts:
            text_parts.append(" ")
            line_map.append(line_number)
        text_parts.append(line)
        line_map.extend([line_number] * len(line))
    flush()
    return spans


def _sentence_fragments(text: str) -> list[tuple[int, str]]:
    fragments: list[tuple[int, str]] = []
    start = 0
    for boundary in re.finditer(r"(?<=[.!?])\s+", text):
        fragment = text[start : boundary.start()]
        if fragment.strip():
            fragments.append((start, fragment))
        start = boundary.end()
    fragment = text[start:]
    if fragment.strip():
        fragments.append((start, fragment))
    return fragments


def _sentence_spans(tex_text: str) -> list[tuple[int, str]]:
    spans: list[tuple[int, str]] = []
    for paragraph, line_map in _paragraph_spans(tex_text):
        for start, fragment in _sentence_fragments(paragraph):
            citation_offset = fragment.find("\\cite")
            if citation_offset < 0:
                continue
            absolute_offset = start + citation_offset
            line_number = line_map[absolute_offset] if absolute_offset < len(line_map) else line_map[0]
            spans.append((line_number, _strip_tex_commands(fragment)))
    return spans


def _citation_matches(sentence: str) -> list[re.Match[str]]:
    return list(re.finditer(r"\\cite[a-zA-Z*]*\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]+)\}", sentence))


def _strip_citation_commands(text: str) -> str:
    text = re.sub(r"\\cite[a-zA-Z*]*\s*(?:\[[^\]]*\]\s*){0,2}\{[^}]+\}", " ", text)
    text = re.sub(r"^[\s,;:.-]*(and|while|whereas|but|however|also)\b[\s,;:.-]*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\s,;:.-]+$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _nearest_clause_boundary(text: str) -> int:
    boundaries = [text.rfind(boundary_marker) for boundary_marker in [".", ";", ":", "?", "!"]]
    comma = text.rfind(",")
    comma_tail = text[comma + 1 :].strip().lower() if comma >= 0 else ""
    if comma >= 0 and len(text) - comma > 24 and not re.match(r"(and|or)\b", comma_tail):
        boundaries.append(comma)
    return max(boundaries)


def _claim_text_for_citation(sentence: str, match_index: int, matches: list[re.Match[str]]) -> str:
    citation = matches[match_index]
    previous_end = matches[match_index - 1].end() if match_index else 0
    prefix = sentence[previous_end : citation.start()]
    boundary = _nearest_clause_boundary(prefix)
    if boundary >= 0:
        prefix = prefix[boundary + 1 :]
    claim_text = _strip_citation_commands(prefix)
    if len(claim_text.split()) >= 3:
        return claim_text
    return _strip_citation_commands(sentence)


def infer_claim_importance(claim_text: str) -> str:
    lowered = claim_text.lower()
    important_terms = [
        "outperform",
        "state-of-the-art",
        "benchmark",
        "result",
        "achieve",
        "improve",
        "compare",
        "shows",
        "demonstrates",
    ]
    return "important" if any(term in lowered for term in important_terms) else "normal"


def infer_claim_type(claim_text: str) -> str:
    lowered = claim_text.lower()
    if any(term in lowered for term in ["benchmark", "result", "outperform", "accuracy", "score"]):
        return "benchmark_or_result"
    if any(term in lowered for term in ["method", "approach", "propose", "framework"]):
        return "method_description"
    return "related_work"


def generate_claim_stubs(
    tex_text: str,
    existing_claim_keys: set[tuple[str, str]] | None = None,
    *,
    source_file: str = "",
    starting_counter: int = 1,
) -> list[ClaimStub]:
    existing_claim_keys = existing_claim_keys or set()
    stubs: list[ClaimStub] = []
    counter = starting_counter
    for line_number, sentence in _sentence_spans(tex_text):
        citation_matches = _citation_matches(sentence)
        for citation_index, citation in enumerate(citation_matches):
            claim_text = _claim_text_for_citation(sentence, citation_index, citation_matches)
            keys = sorted(_row_citation_keys(citation.group(1)))
            for key in keys:
                identity = (claim_text, key)
                if identity in existing_claim_keys:
                    continue
                stubs.append(
                    ClaimStub(
                        claim_id=f"claim-{counter:04d}",
                        manuscript_location=f"{source_file}:line {line_number}" if source_file else f"line {line_number}",
                        source_file=source_file,
                        claim_text=claim_text,
                        citation_key=key,
                        claim_type=infer_claim_type(claim_text),
                        importance=infer_claim_importance(claim_text),
                    )
                )
                counter += 1
    return stubs


def read_claim_rows(path: str | Path) -> list[dict[str, str]]:
    target = Path(path)
    if not target.exists():
        return []
    with target.open(newline="", encoding="utf-8") as handle:
        rows = []
        for row in csv.DictReader(handle, delimiter="\t"):
            rows.append({column: value or "" for column, value in row.items() if column is not None})
        return rows


def write_claim_rows(path: str | Path, rows: list[dict[str, str]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=CLAIM_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in CLAIM_COLUMNS})


def _claim_terms(text: str) -> set[str]:
    normalized = re.sub(r"\\cite[a-zA-Z*]*\s*(?:\[[^\]]*\]\s*){0,2}\{[^}]+\}", " ", text)
    terms = {term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", normalized)}
    return {term for term in terms if term not in STOP_TERMS}


def _split_page_content(content: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return lines or ([content.strip()] if content.strip() else [])


def _text_blocks(text: str) -> list[tuple[str, str]]:
    page_matches = list(re.finditer(r"(?im)^\[page\s+([^\]]+)\]\s*$", text))
    if page_matches:
        blocks: list[tuple[str, str]] = []
        for page_index, match in enumerate(page_matches):
            page_label = f"page {match.group(1).strip()}"
            start = match.end()
            end = page_matches[page_index + 1].start() if page_index + 1 < len(page_matches) else len(text)
            page_blocks = _split_page_content(text[start:end])
            for block_index, block_text in enumerate(page_blocks, start=1):
                suffix = "" if len(page_blocks) == 1 else f" paragraph {block_index}"
                blocks.append((f"{page_label}{suffix}", re.sub(r"\s+", " ", block_text).strip()))
        return blocks

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if paragraphs:
        blocks = []
        for index, paragraph in enumerate(paragraphs, start=1):
            label = f"paragraph {index}"
            page_match = re.match(r"\[page\s+(\d+)\]\s*(.*)", paragraph, flags=re.IGNORECASE | re.DOTALL)
            if page_match:
                label = f"page {page_match.group(1)}"
                paragraph = page_match.group(2)
            blocks.append((label, re.sub(r"\s+", " ", paragraph).strip()))
        return blocks
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [(f"line {index}", re.sub(r"\s+", " ", line)) for index, line in enumerate(lines, start=1)]


def evidence_match_score(claim_text: str, evidence_text: str) -> dict[str, Any]:
    claim_terms = _claim_terms(claim_text)
    evidence_terms = _claim_terms(evidence_text)
    shared_terms = sorted(claim_terms & evidence_terms)
    missing_terms = sorted(claim_terms - evidence_terms)
    coverage = len(shared_terms) / len(claim_terms) if claim_terms else 0.0
    return {
        "overlap_score": len(shared_terms),
        "claim_term_count": len(claim_terms),
        "evidence_term_count": len(evidence_terms),
        "coverage": round(coverage, 4),
        "matched_terms": shared_terms,
        "missing_terms": missing_terms,
    }


def _section_heading(block_text: str) -> str | None:
    first_line = re.sub(r"\s+", " ", block_text.strip().splitlines()[0] if block_text.strip() else "").strip()
    lowered = first_line.lower().rstrip(":")
    known_headings = {
        "abstract": "Abstract",
        "introduction": "Introduction",
        "related work": "Related Work",
        "background": "Background",
        "method": "Method",
        "methods": "Methods",
        "experiments": "Experiments",
        "evaluation": "Evaluation",
        "results": "Results",
        "discussion": "Discussion",
        "conclusion": "Conclusion",
    }
    if lowered in known_headings:
        return known_headings[lowered]
    if 1 <= len(first_line.split()) <= 6 and first_line.istitle() and not first_line.endswith("."):
        return first_line
    return None


def _evidence_quality(block_label: str, block_text: str) -> dict[str, Any]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", block_text)
    word_count = len(words)
    stripped = block_text.strip()
    has_sentence_punctuation = bool(re.search(r"[.!?]", stripped))
    section_heading = _section_heading(block_text)
    title_like = word_count <= 18 and not has_sentence_punctuation
    abstract_like = bool(section_heading and section_heading.lower() == "abstract") or stripped.lower().startswith("abstract ")
    body_like = word_count >= 35 and has_sentence_punctuation and not abstract_like
    quality = 0.0
    if body_like:
        quality += 1.0
    if word_count >= 20:
        quality += 0.35
    if title_like:
        quality -= 1.0
    if abstract_like:
        quality -= 0.45
    return {
        "section_heading": section_heading,
        "word_count": word_count,
        "title_like": title_like,
        "abstract_like": abstract_like,
        "body_like": body_like,
        "evidence_quality": round(quality, 4),
    }


def _term_bigrams(terms: set[str]) -> set[tuple[str, str]]:
    ordered = sorted(terms)
    return set(zip(ordered, ordered[1:]))


def _semantic_lite_score(claim_text: str, evidence_text: str, score: dict[str, Any]) -> float:
    claim_terms = _claim_terms(claim_text)
    evidence_terms = _claim_terms(evidence_text)
    claim_bigrams = _term_bigrams(claim_terms)
    evidence_bigrams = _term_bigrams(evidence_terms)
    bigram_overlap = len(claim_bigrams & evidence_bigrams)
    return round(float(score["overlap_score"]) + float(score["coverage"]) + bigram_overlap * 0.25, 4)


def _best_evidence_match(claim_text: str, source_text: str, *, rerank: str = "lexical") -> dict[str, Any] | None:
    if not _claim_terms(claim_text):
        return None
    best: dict[str, Any] | None = None
    for block_label, block_text in _text_blocks(source_text):
        score = evidence_match_score(claim_text, block_text)
        if score["overlap_score"] == 0:
            continue
        quality = _evidence_quality(block_label, block_text)
        candidate = {"block_label": block_label, "quote": block_text, **score, **quality}
        if rerank == "semantic-lite":
            candidate["semantic_lite_score"] = _semantic_lite_score(claim_text, block_text, score)
            candidate_rank = (
                candidate["semantic_lite_score"] + candidate["evidence_quality"],
                candidate["overlap_score"],
                candidate["coverage"],
                candidate["word_count"],
            )
            best_rank = (
                (best.get("semantic_lite_score", 0.0) or 0.0) + (best.get("evidence_quality", 0.0) if best else 0.0)
                if best
                else 0.0,
                best.get("overlap_score", 0) if best else 0,
                best.get("coverage", 0.0) if best else 0.0,
                best.get("word_count", 0) if best else 0,
            )
        else:
            candidate["semantic_lite_score"] = None
            candidate_rank = (
                candidate["overlap_score"],
                candidate["coverage"],
                candidate["evidence_quality"],
                candidate["word_count"],
            )
            best_rank = (
                best.get("overlap_score", 0) if best else 0,
                best.get("coverage", 0.0) if best else 0.0,
                best.get("evidence_quality", 0.0) if best else 0.0,
                best.get("word_count", 0) if best else 0,
            )
        if best is None or candidate_rank > best_rank:
            best = candidate
    return best


def _best_evidence_block(claim_text: str, source_text: str) -> tuple[str, str, int] | None:
    match = _best_evidence_match(claim_text, source_text)
    if match is None:
        return None
    return (match["block_label"], match["quote"], match["overlap_score"])


def suggest_claim_evidence(
    claims_path: str | Path,
    text_path: str | Path,
    output_path: str | Path | None = None,
    citation_key: str | None = None,
    source_label: str | None = None,
    max_quote_chars: int = 320,
    rerank: str = "lexical",
) -> dict[str, Any]:
    rows = read_claim_rows(claims_path)
    source_text = read_source_text(text_path)
    label = source_label or Path(text_path).name
    updated = 0
    suggestions: list[dict[str, str | int]] = []

    for row in rows:
        row_keys = set(_row_citation_keys(row.get("citation_key", "")))
        if citation_key and citation_key not in row_keys:
            continue
        if row.get("quote_or_evidence", "").strip():
            continue
        match = _best_evidence_match(row.get("claim_text", ""), source_text, rerank=rerank)
        if match is None:
            continue
        block_label = match["block_label"]
        quote = match["quote"]
        score = match["overlap_score"]
        clipped = quote if len(quote) <= max_quote_chars else quote[: max_quote_chars - 3].rstrip() + "..."
        row["quote_or_evidence"] = clipped
        row["source_location"] = row.get("source_location", "").strip() or f"{label}: {block_label}"
        if row.get("status", "").strip() in {"", "claim_unchecked"}:
            row["status"] = "needs_review"
        note = row.get("notes", "").strip()
        suggestion_note = (
            f"Refgate suggested source text overlap score {score}, coverage {match['coverage']:.2f}; "
            "human review required."
        )
        row["notes"] = f"{note} {suggestion_note}".strip() if note else suggestion_note
        updated += 1
        suggestions.append(
            {
                "claim_id": row.get("claim_id", ""),
                "citation_key": row.get("citation_key", ""),
                "source_location": row.get("source_location", ""),
                "overlap_score": score,
                "coverage": match["coverage"],
                "matched_terms": match["matched_terms"],
                "missing_terms": match["missing_terms"],
                "semantic_lite_score": match["semantic_lite_score"],
                "section_heading": match.get("section_heading"),
                "evidence_quality": match.get("evidence_quality"),
                "title_like": match.get("title_like"),
                "abstract_like": match.get("abstract_like"),
            }
        )

    if output_path:
        write_claim_rows(output_path, rows)
    return {"updated": updated, "output": str(output_path) if output_path else None, "suggestions": suggestions}


def suggest_claim_evidence_bundle(
    claims_path: str | Path,
    text_paths: list[str | Path],
    output_path: str | Path | None = None,
    citation_key: str | None = None,
    max_quote_chars: int = 320,
    rerank: str = "lexical",
) -> dict[str, Any]:
    rows = read_claim_rows(claims_path)
    sources = [
        {
            "path": str(path),
            "label": Path(path).name,
            "text": read_source_text(path),
        }
        for path in text_paths
    ]
    updated = 0
    suggestions: list[dict[str, str | int]] = []

    for row in rows:
        row_keys = set(_row_citation_keys(row.get("citation_key", "")))
        if citation_key and citation_key not in row_keys:
            continue
        if row.get("quote_or_evidence", "").strip():
            continue

        best: dict[str, Any] | None = None
        for source in sources:
            match = _best_evidence_match(row.get("claim_text", ""), source["text"], rerank=rerank)
            if match is None:
                continue
            if rerank == "semantic-lite":
                candidate_rank = (match["semantic_lite_score"], match["overlap_score"], match["coverage"])
                best_rank = (
                    best.get("semantic_lite_score", 0.0) if best else 0.0,
                    best.get("overlap_score", 0) if best else 0,
                    best.get("coverage", 0.0) if best else 0.0,
                )
            else:
                candidate_rank = (match["overlap_score"], match["coverage"])
                best_rank = (
                    best.get("overlap_score", 0) if best else 0,
                    best.get("coverage", 0.0) if best else 0.0,
                )
            if best is None or candidate_rank > best_rank:
                best = {**match, "source_label": source["label"]}
        if best is None:
            continue

        block_label = best["block_label"]
        quote = best["quote"]
        score = best["overlap_score"]
        label = best["source_label"]
        clipped = quote if len(quote) <= max_quote_chars else quote[: max_quote_chars - 3].rstrip() + "..."
        row["quote_or_evidence"] = clipped
        row["source_location"] = row.get("source_location", "").strip() or f"{label}: {block_label}"
        if row.get("status", "").strip() in {"", "claim_unchecked"}:
            row["status"] = "needs_review"
        note = row.get("notes", "").strip()
        suggestion_note = (
            f"Refgate source bundle overlap score {score}, coverage {best['coverage']:.2f}; "
            "human review required."
        )
        row["notes"] = f"{note} {suggestion_note}".strip() if note else suggestion_note
        updated += 1
        suggestions.append(
            {
                "claim_id": row.get("claim_id", ""),
                "citation_key": row.get("citation_key", ""),
                "source_location": row.get("source_location", ""),
                "overlap_score": score,
                "coverage": best["coverage"],
                "matched_terms": best["matched_terms"],
                "missing_terms": best["missing_terms"],
                "semantic_lite_score": best["semantic_lite_score"],
                "section_heading": best.get("section_heading"),
                "evidence_quality": best.get("evidence_quality"),
                "title_like": best.get("title_like"),
                "abstract_like": best.get("abstract_like"),
                "source_label": label,
            }
        )

    if output_path:
        write_claim_rows(output_path, rows)
    return {
        "updated": updated,
        "output": str(output_path) if output_path else None,
        "source_count": len(sources),
        "suggestions": suggestions,
    }


def update_claim_stub_file(tex_text: str, output_path: str | Path) -> list[ClaimStub]:
    existing_rows = read_claim_rows(output_path)
    existing_keys = {(row.get("claim_text", ""), row.get("citation_key", "")) for row in existing_rows}
    stubs = generate_claim_stubs(tex_text, existing_keys)
    rows = existing_rows + [stub.to_row() for stub in stubs]
    write_claim_rows(output_path, rows)
    return stubs


def update_claim_stub_file_from_sources(
    sources: list[dict[str, str]],
    output_path: str | Path,
) -> list[ClaimStub]:
    existing_rows = read_claim_rows(output_path)
    existing_keys = {(row.get("claim_text", ""), row.get("citation_key", "")) for row in existing_rows}
    stubs: list[ClaimStub] = []
    counter = 1
    for source in sources:
        created = generate_claim_stubs(
            source.get("text", ""),
            existing_keys,
            source_file=source.get("source_file", ""),
            starting_counter=counter,
        )
        stubs.extend(created)
        for stub in created:
            existing_keys.add((stub.claim_text, stub.citation_key))
        counter += len(created)
    rows = existing_rows + [stub.to_row() for stub in stubs]
    write_claim_rows(output_path, rows)
    return stubs


def render_claim_review_report(path: str | Path) -> str:
    rows = read_claim_rows(path)
    lines = [
        "# Refgate Claim Review",
        "",
        "## Summary",
        "",
        f"- Claims: {len(rows)}",
        f"- Checked: {sum(1 for row in rows if row.get('status') == 'checked')}",
        f"- Needs review: {sum(1 for row in rows if row.get('status') != 'checked')}",
        "",
        "## Claims",
        "",
    ]
    if not rows:
        lines.append("- None")
    for row in rows:
        claim_id = row.get("claim_id", "")
        key = row.get("citation_key", "")
        status = row.get("status", "")
        lines.extend(
            [
                f"### {claim_id} — `{key}`",
                "",
                f"- Status: `{status}`",
                f"- Location: {row.get('manuscript_location', '')}",
                f"- Source file: {row.get('source_file', '') or '(unknown)'}",
                f"- Type: {row.get('claim_type', '')}",
                f"- Importance: {row.get('importance', '')}",
                "",
                "Claim:",
                "",
                row.get("claim_text", ""),
                "",
                "Evidence:",
                "",
                row.get("quote_or_evidence", "") or "(missing)",
                "",
                f"Source location: {row.get('source_location', '') or '(missing)'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def audit_tex_bib_consistency(tex_text: str, bib_text: str, submission: bool = False) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    cited_keys = extract_citation_keys(tex_text)
    bib_keys = set(parse_bibtex_file(bib_text))

    for key in sorted(cited_keys - bib_keys):
        issues.append(
            AuditIssue(
                code="CITATION_NOT_IN_BIB",
                message="Citation key appears in manuscript but is missing from the BibTeX file.",
                severity="blocking",
                citation_key=key,
            )
        )

    for key in sorted(bib_keys - cited_keys):
        issues.append(
            AuditIssue(
                code="BIB_ENTRY_NOT_CITED",
                message="BibTeX entry is not cited in the manuscript.",
                severity="blocking" if submission else "warning",
                citation_key=key,
            )
        )
    return issues


def _row_citation_keys(value: str) -> list[str]:
    return [key for key in re.split(r"[,;\s]+", value) if key]


def audit_claims_table(path: str | Path, submission: bool = False) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"claim_id", "citation_key", "source_location", "status"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            return [
                AuditIssue(
                    code="CLAIM_TABLE_SCHEMA_INVALID",
                    message="Claim table is missing required columns.",
                    severity="blocking",
                    evidence=missing,
                )
            ]

        for row in reader:
            claim_id = row.get("claim_id", "").strip()
            status = row.get("status", "").strip() or "claim_unchecked"
            source_location = row.get("source_location", "").strip()
            quote_or_evidence = row.get("quote_or_evidence", "").strip()
            evidence_kind = row.get("evidence_kind", "").strip()
            citation_keys = _row_citation_keys(row.get("citation_key", ""))
            severity = "blocking" if submission or status in BLOCKING_CLAIM_STATUSES else "warning"

            normalized_status = status.replace("-", "_")
            if normalized_status not in PASSING_CLAIM_STATUSES:
                for key in citation_keys or [None]:
                    issues.append(
                        AuditIssue(
                            code="CLAIM_NOT_CHECKED",
                            message=f"Claim {claim_id or '(missing id)'} is marked {status}.",
                            severity=severity,
                            citation_key=key,
                        )
                    )
            elif not source_location:
                for key in citation_keys or [None]:
                    issues.append(
                        AuditIssue(
                            code="CLAIM_SOURCE_LOCATION_MISSING",
                            message=f"Claim {claim_id or '(missing id)'} is checked but has no source location.",
                            severity="blocking" if submission else "warning",
                            citation_key=key,
                        )
                    )
            elif not quote_or_evidence:
                for key in citation_keys or [None]:
                    issues.append(
                        AuditIssue(
                            code="CLAIM_EVIDENCE_MISSING",
                            message=f"Claim {claim_id or '(missing id)'} is checked but has no evidence text.",
                            severity="blocking" if submission else "warning",
                            citation_key=key,
                        )
                    )
            elif is_weak_evidence_kind(evidence_kind):
                for key in citation_keys or [None]:
                    issues.append(
                        AuditIssue(
                            code="CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE",
                            message=f"Claim {claim_id or '(missing id)'} is marked checked using weak evidence kind {evidence_kind}.",
                            severity="blocking",
                            citation_key=key,
                            evidence=[evidence_kind],
                        )
                    )
    return issues
