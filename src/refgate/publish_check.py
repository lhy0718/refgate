from __future__ import annotations

from pathlib import Path
from typing import Any


SCAN_TERMS = [
    "/" + "Users/",
    "Obs" + "idian",
    "API " + "key",
    "to" + "ken",
    "pass" + "word",
    "sec" + "ret",
]

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "dist", "build"}
SKIP_PREFIXES = {(".refgate", "cache")}
GENERATED_NAMES = {"__pycache__", ".pytest_cache"}
GENERATED_SUFFIXES = {".pyc", ".pyo"}
SAFE_STRUCTURAL_MATCHES = {
    (Path(".github/workflows/release.yml"), "to" + "ken", "id-" + "to" + "ken: write"),
}


def run_publish_check(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    findings = []
    generated = []

    for path in sorted(root_path.rglob("*")):
        rel = path.relative_to(root_path)
        parts = set(rel.parts)
        if parts & SKIP_DIRS:
            continue
        if any(rel.parts[: len(prefix)] == prefix for prefix in SKIP_PREFIXES):
            continue
        if path.name in GENERATED_NAMES or path.suffix in GENERATED_SUFFIXES or path.name.endswith(".egg-info"):
            generated.append(str(rel))
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for term in SCAN_TERMS:
            if term in text:
                safe_matches = [
                    line
                    for safe_path, safe_term, line in SAFE_STRUCTURAL_MATCHES
                    if rel == safe_path and term == safe_term
                ]
                reduced = text
                for line in safe_matches:
                    reduced = reduced.replace(line, "")
                if term not in reduced:
                    continue
                findings.append({"path": str(rel), "match": term})

    return {
        "ok": not findings,
        "findings": findings,
        "generated_artifacts": generated,
    }
