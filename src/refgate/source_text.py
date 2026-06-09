from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PDF_EXTRA_INSTALL_COMMAND = 'python -m pip install "refgate[pdf]"'


def pdf_text_extraction_available() -> bool:
    try:
        import pypdf  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def pdf_text_extra_missing_issue(paths: list[str | Path]) -> dict[str, Any]:
    pdf_paths = [str(path) for path in paths if Path(path).suffix.lower() == ".pdf"]
    return {
        "code": "PDF_TEXT_EXTRA_MISSING",
        "message": "PDF source text extraction requires the optional pypdf dependency.",
        "evidence": [
            f"pdf_count={len(pdf_paths)}",
            f"install={PDF_EXTRA_INSTALL_COMMAND}",
            *pdf_paths[:5],
        ],
    }


def read_source_text(path: str | Path) -> str:
    target = Path(path)
    if target.suffix.lower() == ".pdf":
        return read_pdf_text(target)
    return target.read_text(encoding="utf-8")


def read_pdf_text(path: str | Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            f"PDF text extraction requires the optional pypdf package. Install with: {PDF_EXTRA_INSTALL_COMMAND}"
        ) from exc

    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[page {index}]\n{text.strip()}")
    return "\n\n".join(pages)


def validate_source_text(paths: list[str | Path], *, min_chars: int = 80) -> dict[str, Any]:
    results = []
    blocking = []
    pdf_paths = [path for path in paths if Path(path).suffix.lower() == ".pdf"]
    if pdf_paths and not pdf_text_extraction_available():
        return {
            "min_chars": min_chars,
            "results": [
                {
                    "path": str(path),
                    "kind": "pdf" if Path(path).suffix.lower() == ".pdf" else "text",
                    "char_count": 0,
                    "page_marker_count": 0,
                    "ok": False if Path(path).suffix.lower() == ".pdf" else None,
                    "error": "pypdf_missing" if Path(path).suffix.lower() == ".pdf" else None,
                }
                for path in paths
            ],
            "ok": False,
            "blocking_issues": [pdf_text_extra_missing_issue(pdf_paths)],
        }
    for path in paths:
        target = Path(path)
        try:
            text = read_source_text(target)
            char_count = len(text.strip())
            ok = char_count >= min_chars
            result = {
                "path": str(path),
                "kind": "pdf" if target.suffix.lower() == ".pdf" else "text",
                "char_count": char_count,
                "page_marker_count": len(re.findall(r"(?im)^\[page\s+[^\]]+\]", text)),
                "ok": ok,
            }
            if not ok:
                blocking.append(
                    {
                        "code": "SOURCE_TEXT_TOO_SHORT",
                        "message": "Extracted source text is shorter than the configured minimum.",
                        "evidence": [str(path)],
                    }
                )
        except Exception as exc:
            result = {
                "path": str(path),
                "kind": "pdf" if target.suffix.lower() == ".pdf" else "text",
                "char_count": 0,
                "ok": False,
                "error": f"{exc.__class__.__name__}: {exc}",
            }
            blocking.append(
                {
                    "code": "SOURCE_TEXT_READ_FAILED",
                    "message": "Source text could not be read or extracted.",
                    "evidence": [str(path), result["error"]],
                }
            )
        results.append(result)
    return {
        "min_chars": min_chars,
        "results": results,
        "ok": not blocking,
        "blocking_issues": blocking,
    }


def build_vision_extraction_plan(
    pdf_path: str | Path,
    *,
    citation_key: str | None = None,
    source_label: str | None = None,
    image_dir: str | Path | None = None,
    pages: list[int] | None = None,
) -> dict[str, Any]:
    target = Path(pdf_path)
    page_numbers = pages or []
    page_text_counts: dict[int, int] = {}
    warnings: list[dict[str, Any]] = []

    if target.suffix.lower() != ".pdf":
        return {
            "ok": False,
            "pdf": str(target),
            "blocking_issues": [
                {
                    "code": "VISION_EXTRACTION_REQUIRES_PDF",
                    "message": "Vision extraction planning currently expects a PDF input.",
                    "evidence": [str(target)],
                }
            ],
            "warnings": [],
        }

    if not target.exists():
        return {
            "ok": False,
            "pdf": str(target),
            "blocking_issues": [
                {
                    "code": "PDF_MISSING",
                    "message": "PDF file does not exist.",
                    "evidence": [str(target)],
                }
            ],
            "warnings": [],
        }

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(target))
        if not page_numbers:
            page_numbers = list(range(1, len(reader.pages) + 1))
        for page_number in page_numbers:
            if page_number < 1 or page_number > len(reader.pages):
                page_text_counts[page_number] = 0
                continue
            text = reader.pages[page_number - 1].extract_text() or ""
            page_text_counts[page_number] = len(text.strip())
    except ImportError:
        if not page_numbers:
            warnings.append(
                {
                    "code": "PYPDF_NOT_AVAILABLE",
                    "message": "pypdf is not installed; provide --page values to create a page-level vision plan.",
                }
            )
    except Exception as exc:
        warnings.append(
            {
                "code": "PDF_PAGE_INSPECTION_FAILED",
                "message": "PDF page inspection failed; the vision plan can still be used with rendered images.",
                "evidence": [f"{exc.__class__.__name__}: {exc}"],
            }
        )

    image_root = Path(image_dir) if image_dir else None
    page_items = []
    for page_number in page_numbers:
        image_path = image_root / f"page-{page_number:03d}.png" if image_root else None
        text_char_count = page_text_counts.get(page_number, 0)
        page_items.append(
            {
                "page": page_number,
                "page_label": f"page {page_number}",
                "text_char_count": text_char_count,
                "needs_vision": text_char_count == 0,
                "image_path": str(image_path) if image_path else None,
                "image_exists": bool(image_path and image_path.exists()),
                "expected_transcript_location": f"[page {page_number}]",
            }
        )

    return {
        "ok": True,
        "schema_version": "refgate.vision_extract_plan.v1",
        "pdf": str(target),
        "citation_key": citation_key,
        "source_label": source_label or target.name,
        "mode": "codex_vision_handoff",
        "can_refgate_call_codex_directly": False,
        "instructions": [
            "Render or attach the listed page images to a vision-capable Codex session.",
            "Transcribe only visible text from each page and preserve page labels such as [page 1].",
            "Save the reviewed transcript as a .txt source file, then map it with claim-source-check.",
        ],
        "source_map_row_template": {
            "citation_key": citation_key or "CITATION_KEY",
            "source_text": "TRANSCRIPT_TXT",
            "source_label": source_label or target.name,
            "evidence_kind": "source_text",
        },
        "pages": page_items,
        "blocking_issues": [],
        "warnings": warnings,
    }
