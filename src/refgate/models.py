from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Status = Literal[
    "verified_official_bibtex",
    "verified_manual_fallback",
    "official_record_pending",
    "arxiv_fallback_verified",
    "ambiguous",
    "unresolved",
    "missing_bibtex_provenance",
    "claim_unchecked",
    "blocked",
]

SourceKind = Literal[
    "official_export",
    "publisher_metadata_manual_normalized",
    "arxiv_manual_normalized",
    "generated_unverified",
    "unknown",
]


@dataclass
class PaperQuery:
    query_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    citation_key: str | None = None
    preferred_venues: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperQuery":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateRecord:
    source: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    is_official_record: bool = False
    bibtex_url: str | None = None
    source_priority: int = 5
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuthorityRecord:
    source: str
    record_url: str
    record_type: str
    source_priority: int
    bibtex_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BibtexRecord:
    entry_type: str
    citation_key: str
    source_kind: SourceKind
    raw_text: str
    raw_sha256: str
    normalized_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditIssue:
    code: str
    message: str
    severity: Literal["blocking", "warning"]
    citation_key: str | None = None
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolverDecision:
    query_id: str
    decision: Literal["selected", "blocked"]
    status: Status
    authority: AuthorityRecord | None
    resolver_score: int
    blocking_issues: list[AuditIssue] = field(default_factory=list)
    warnings: list[AuditIssue] = field(default_factory=list)
    decision_trace: list[str] = field(default_factory=list)
    selected_candidate: CandidateRecord | None = None

    @property
    def ok(self) -> bool:
        return self.decision == "selected" and not self.blocking_issues

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


@dataclass
class LockEntry:
    citation_key: str
    short_title: str
    status: Status
    record: dict[str, Any]
    authority: dict[str, Any]
    bibtex: dict[str, Any]
    resolver: dict[str, Any]
    checked_at: str
    checked_by: str = "refgate"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LockEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Lockfile:
    schema_version: str = "refgate.lock.v1"
    project: str | None = None
    generated_at: str | None = None
    entries: list[LockEntry] = field(default_factory=list)
    audit_policy: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Lockfile":
        entries = [LockEntry.from_dict(entry) for entry in data.get("entries", [])]
        return cls(
            schema_version=data.get("schema_version", "refgate.lock.v1"),
            project=data.get("project"),
            generated_at=data.get("generated_at"),
            entries=entries,
            audit_policy=data.get("audit_policy", {}),
        )

    def by_citation_key(self) -> dict[str, LockEntry]:
        return {entry.citation_key: entry for entry in self.entries}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
