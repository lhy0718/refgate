from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from .models import AuditIssue


MAX_TEX_INCLUDE_DEPTH = 20


@dataclass(frozen=True)
class TexSource:
    path: Path
    display_path: str
    text: str


@dataclass(frozen=True)
class TexDocument:
    root: Path
    sources: list[TexSource]
    issues: list[AuditIssue]

    @property
    def combined_text(self) -> str:
        return "\n\n".join(source.text for source in self.sources)


def _strip_tex_comment(line: str) -> str:
    escaped = False
    for index, char in enumerate(line):
        if char == "%" and not escaped:
            return line[:index]
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    return line


def _include_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw_line in text.splitlines():
        line = _strip_tex_comment(raw_line)
        for match in re.finditer(r"\\(?:input|include)\s*\{([^{}]+)\}", line):
            target = match.group(1).strip()
            if target:
                targets.append(target)
    return targets


def _resolve_include(root_dir: Path, target: str) -> Path:
    path = Path(target)
    if not path.suffix:
        path = path.with_suffix(".tex")
    if path.is_absolute():
        return path
    return root_dir / path


def load_tex_document(
    tex_path: str | Path,
    *,
    submission: bool = False,
    max_depth: int = MAX_TEX_INCLUDE_DEPTH,
) -> TexDocument:
    root = Path(tex_path)
    root_dir = root.parent
    sources: list[TexSource] = []
    issues: list[AuditIssue] = []
    visiting: set[Path] = set()
    visited: set[Path] = set()

    def severity() -> str:
        return "blocking" if submission else "warning"

    def display(path: Path) -> str:
        try:
            return str(path.relative_to(root_dir))
        except ValueError:
            return str(path)

    def visit(path: Path, depth: int) -> None:
        resolved = path.resolve(strict=False)
        if depth > max_depth:
            issues.append(
                AuditIssue(
                    code="TEX_INCLUDE_DEPTH_EXCEEDED",
                    message="TeX include recursion exceeded the configured depth limit.",
                    severity=severity(),
                    evidence=[display(path), str(max_depth)],
                )
            )
            return
        if resolved in visiting:
            issues.append(
                AuditIssue(
                    code="TEX_INCLUDE_CYCLE",
                    message="TeX include graph contains a cycle.",
                    severity=severity(),
                    evidence=[display(path)],
                )
            )
            return
        if resolved in visited:
            return
        if not path.exists():
            issues.append(
                AuditIssue(
                    code="TEX_INCLUDE_MISSING",
                    message="Referenced TeX include file is missing.",
                    severity=severity(),
                    evidence=[display(path)],
                )
            )
            return

        visiting.add(resolved)
        text = path.read_text(encoding="utf-8")
        sources.append(TexSource(path=path, display_path=display(path), text=text))
        for target in _include_targets(text):
            visit(_resolve_include(root_dir, target), depth + 1)
        visiting.remove(resolved)
        visited.add(resolved)

    visit(root, 0)
    return TexDocument(root=root, sources=sources, issues=issues)
