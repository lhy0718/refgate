from __future__ import annotations

import argparse
import getpass
import json
import shlex
from pathlib import Path
from typing import Any

from .assist import build_resolver_assist
from .audit import audit_bibliography
from .auth import AUTH_SOURCES, auth_doctor, auth_status, save_auth_value, select_auth_sources
from .bibtex import parse_bibtex_entry, sha256_text
from .bibtex_sync import sync_bibtex
from .bootstrap import bootstrap_lock_from_bib, bootstrap_paper
from .claim_audit import audit_claims_table, audit_tex_bib_consistency, render_claim_review_report, suggest_claim_evidence, suggest_claim_evidence_bundle, update_claim_stub_file_from_sources
from .claim_consistency import review_claim_consistency
from .claim_source_check import run_claim_source_check
from .codex_review import import_codex_review, write_codex_review_bundle
from .fixture_matrix import validate_fixture_matrix
from .handoff import write_handoff
from .live_smoke import (
    LiveSmokeQueryItem,
    cache_manifest,
    compare_cache_manifest,
    run_live_smoke,
    run_live_smoke_suite,
    run_live_smoke_suite_items,
)
from .lockfile import build_lock_entry, load_lockfile, merge_lock_entry, write_lockfile
from .models import AuditIssue, AuthorityRecord, BibtexRecord, CandidateRecord, Lockfile, PaperQuery, ResolverDecision
from .next_actions import (
    build_next_actions_result,
    render_next_action_summary_markdown,
    run_next_actions,
    summarize_next_action_manifests,
    write_next_actions_result,
)
from .official_monitor import OFFICIAL_MONITOR_SOURCES, run_official_monitor
from .paper_template import write_paper_agents_template
from .paper_flow import build_source_map_from_dir, run_paper_audit
from .publish_check import run_publish_check
from .reference_check import run_reference_check
from .reports import render_markdown_report
from .resolver import resolve
from .source_text import build_vision_extraction_plan, validate_source_text
from .source_title import check_source_titles, source_title_next_actions
from .source_download import download_sources
from .tex import load_tex_document
from .adapters.acl import AclAdapter, candidate_from_acl_html
from .adapters.arxiv import ArxivAdapter
from .adapters.crossref import CrossrefAdapter
from .adapters.iclr import IclrAdapter, candidate_from_iclr_html
from .adapters.neurips import NeuripsAdapter, candidate_from_neurips_html
from .adapters.openalex import OpenAlexAdapter
from .adapters.semantic_scholar import SemanticScholarAdapter
from .adapters.venues import ADAPTERS as VENUE_ADAPTERS, candidate_from_venue_html


DISCOVERY_SOURCES = [
    "aaai",
    "acl",
    "acm",
    "arxiv",
    "cambridge",
    "crossref",
    "cvf",
    "elsevier",
    "frontiers",
    "iclr",
    "ieee",
    "jmlr",
    "lipics",
    "mdpi",
    "nature",
    "neurips",
    "openalex",
    "openreview",
    "oxford",
    "pmlr",
    "pnas",
    "sage",
    "science",
    "semantic_scholar",
    "springer",
    "taylorfrancis",
    "usenix",
    "wiley",
]
OFFICIAL_BIBTEX_SOURCES = [
    "aaai",
    "acl",
    "acm",
    "arxiv",
    "cambridge",
    "cvf",
    "elsevier",
    "frontiers",
    "iclr",
    "ieee",
    "jmlr",
    "lipics",
    "mdpi",
    "nature",
    "neurips",
    "openreview",
    "oxford",
    "pmlr",
    "pnas",
    "sage",
    "science",
    "springer",
    "taylorfrancis",
    "usenix",
    "wiley",
]


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def envelope(
    status: str,
    data: Any = None,
    blocking_issues: list | None = None,
    warnings: list | None = None,
    next_actions: list | None = None,
) -> dict:
    blocking_issues = blocking_issues or []
    warnings = warnings or []
    return {
        "ok": not blocking_issues,
        "status": status,
        "data": data,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "next_actions": next_actions or [],
    }


def summarize_issue_dicts(issues: list[dict[str, Any]], *, sample_limit: int = 10) -> list[dict[str, Any]]:
    summaries: dict[tuple[str, str], dict[str, Any]] = {}
    for issue in issues:
        key = (issue.get("code", ""), issue.get("severity", ""))
        summary = summaries.setdefault(
            key,
            {
                "code": issue.get("code", ""),
                "message": issue.get("message", ""),
                "count": 0,
                "citation_key_sample": [],
            },
        )
        summary["count"] += 1
        citation_key = issue.get("citation_key")
        if citation_key and citation_key not in summary["citation_key_sample"]:
            summary["citation_key_sample"].append(citation_key)
    for summary in summaries.values():
        keys = summary["citation_key_sample"]
        summary["omitted_citation_key_count"] = max(0, len(keys) - sample_limit)
        summary["citation_key_sample"] = keys[:sample_limit]
    return list(summaries.values())


def load_query_from_args(args: argparse.Namespace) -> PaperQuery:
    if getattr(args, "query", None):
        return PaperQuery.from_dict(load_json(args.query))
    if not getattr(args, "title", None):
        raise ValueError("--title or --query is required")
    authors = []
    for item in getattr(args, "author", []) or []:
        authors.extend(part.strip() for part in item.split(",") if part.strip())
    return PaperQuery(
        query_id=getattr(args, "query_id", None) or getattr(args, "citation_key", None) or "query",
        title=args.title,
        authors=authors,
        year=getattr(args, "year", None),
        doi=getattr(args, "doi", None),
        arxiv_id=getattr(args, "arxiv_id", None),
        citation_key=getattr(args, "citation_key", None),
        preferred_venues=getattr(args, "preferred_venue", []) or [],
    )


def candidate_from_path(path: str | Path) -> CandidateRecord:
    data = load_json(path)
    if isinstance(data, list):
        if len(data) != 1:
            raise ValueError("Candidate file must contain one candidate object, or a one-item candidate list.")
        data = data[0]
    return CandidateRecord.from_dict(data)


def authority_from_dict(data: dict[str, Any]) -> AuthorityRecord:
    return AuthorityRecord(**{key: data.get(key) for key in AuthorityRecord.__dataclass_fields__})


def decision_from_dict(data: dict[str, Any]) -> ResolverDecision:
    authority = authority_from_dict(data["authority"]) if data.get("authority") else None
    candidate = CandidateRecord.from_dict(data["selected_candidate"]) if data.get("selected_candidate") else None
    return ResolverDecision(
        query_id=data["query_id"],
        decision=data["decision"],
        status=data["status"],
        authority=authority,
        resolver_score=data["resolver_score"],
        decision_trace=data.get("decision_trace", []),
        selected_candidate=candidate,
    )


def cmd_discover(args: argparse.Namespace) -> int:
    query: PaperQuery | None = None
    candidates: list[CandidateRecord] = []
    try:
        if args.fixture:
            query = load_query_from_args(args)
            fixture_data = load_json(args.fixture)
            candidates = [CandidateRecord.from_dict(item) for item in fixture_data]
        elif args.source == "arxiv":
            query = load_query_from_args(args)
            if not args.live:
                write_json(envelope("network_disabled", blocking_issues=[{"code": "LIVE_MODE_REQUIRED", "message": "arXiv discovery requires --live or --fixture."}]))
                return 1
            candidates = ArxivAdapter().discover(query)
        elif args.source == "acl":
            if args.url:
                if args.fixture_html:
                    html = Path(args.fixture_html).read_text(encoding="utf-8")
                elif args.live:
                    html = AclAdapter().fetcher(args.url)
                else:
                    write_json(envelope("network_disabled", blocking_issues=[{"code": "LIVE_MODE_REQUIRED", "message": "ACL URL discovery requires --live or --fixture-html."}]))
                    return 1
                candidates = [candidate_from_acl_html(args.url, html)]
            elif args.live:
                query = load_query_from_args(args)
                candidates = AclAdapter().discover(query)
            else:
                write_json(envelope("network_disabled", blocking_issues=[{"code": "DISCOVERY_INPUT_MISSING", "message": "Provide --fixture, --url with --fixture-html, or --live."}]))
                return 1
        elif args.source in {"iclr", "neurips"}:
            adapter_cls = IclrAdapter if args.source == "iclr" else NeuripsAdapter
            candidate_factory = candidate_from_iclr_html if args.source == "iclr" else candidate_from_neurips_html
            if args.url:
                if args.fixture_html:
                    html = Path(args.fixture_html).read_text(encoding="utf-8")
                elif args.live:
                    html = adapter_cls().fetcher(args.url)
                else:
                    write_json(envelope("network_disabled", blocking_issues=[{"code": "LIVE_MODE_REQUIRED", "message": f"{args.source} URL discovery requires --live or --fixture-html."}]))
                    return 1
                candidates = [candidate_factory(args.url, html)]
            elif args.live:
                query = load_query_from_args(args)
                candidates = adapter_cls().discover(query)
            else:
                write_json(envelope("network_disabled", blocking_issues=[{"code": "DISCOVERY_INPUT_MISSING", "message": "Provide --fixture, --url with --fixture-html, or --live."}]))
                return 1
        elif args.source in VENUE_ADAPTERS:
            adapter = VENUE_ADAPTERS[args.source]()
            if args.url:
                if args.fixture_html:
                    html = Path(args.fixture_html).read_text(encoding="utf-8")
                elif args.live:
                    html = adapter.fetcher(args.url)
                else:
                    write_json(envelope("network_disabled", blocking_issues=[{"code": "LIVE_MODE_REQUIRED", "message": f"{args.source} URL discovery requires --live or --fixture-html."}]))
                    return 1
                candidates = [candidate_from_venue_html(args.source, args.url, html)]
            else:
                write_json(envelope("discovery_input_missing", blocking_issues=[{"code": "DISCOVERY_INPUT_MISSING", "message": f"{args.source} discovery requires --url with --fixture-html or --live."}]))
                return 1
        elif args.source in {"crossref", "semantic_scholar", "openalex"}:
            query = load_query_from_args(args)
            if not args.live:
                write_json(envelope("network_disabled", blocking_issues=[{"code": "LIVE_MODE_REQUIRED", "message": f"{args.source} discovery requires --live or --fixture."}]))
                return 1
            adapter_map = {
                "crossref": CrossrefAdapter(),
                "semantic_scholar": SemanticScholarAdapter(),
                "openalex": OpenAlexAdapter(),
            }
            candidates = adapter_map[args.source].discover(query)
        else:
            write_json(envelope("unsupported_source", blocking_issues=[{"code": "UNSUPPORTED_SOURCE", "message": f"Unsupported source {args.source}."}]))
            return 1
    except Exception as exc:
        write_json(
            envelope(
                "discovery_failed",
                blocking_issues=[
                    {
                        "code": "DISCOVERY_FAILED",
                        "message": f"{exc.__class__.__name__}: {exc}",
                    }
                ],
            )
        )
        return 1

    write_json(
        envelope(
            "candidates_found" if candidates else "no_candidates",
            data={"query": query.to_dict() if query else None, "candidates": [candidate.to_dict() for candidate in candidates]},
            blocking_issues=[] if candidates else [{"code": "NO_CANDIDATES", "message": "No candidates were found."}],
        )
    )
    return 0 if candidates else 1


def cmd_resolve(args: argparse.Namespace) -> int:
    query = load_query_from_args(args)
    candidates_data = load_json(args.candidates)
    candidates = [CandidateRecord.from_dict(item) for item in candidates_data]
    decision = resolve(query, candidates)
    write_json(decision.to_dict())
    return 0 if decision.ok else 1


def cmd_fetch_bibtex(args: argparse.Namespace) -> int:
    decision = decision_from_dict(load_json(args.resolved)) if args.resolved else None
    candidate = candidate_from_path(args.candidate) if args.candidate else (decision.selected_candidate if decision else None)
    authority = authority_from_dict(load_json(args.authority)) if args.authority else (decision.authority if decision else None)
    if candidate is None or authority is None:
        write_json(envelope("invalid_input", blocking_issues=[{"code": "MISSING_RESOLUTION", "message": "Provide --resolved or both --candidate and --authority."}]))
        return 2

    bibtex: BibtexRecord | None = None
    if args.bibtex_file:
        raw_text = Path(args.bibtex_file).read_text(encoding="utf-8")
        parsed = parse_bibtex_entry(raw_text)
        bibtex = BibtexRecord(
            entry_type=parsed["entry_type"],
            citation_key=parsed["citation_key"],
            source_kind="official_export" if authority.bibtex_url else args.source_kind,
            raw_text=raw_text,
            raw_sha256=sha256_text(raw_text),
            normalized_sha256=sha256_text(raw_text.strip() + "\n"),
        )
    elif args.source == "acl":
        endpoints = AclAdapter().find_export_endpoints(authority)
        if not endpoints or not args.live:
            write_json(envelope("network_disabled", blocking_issues=[{"code": "LIVE_MODE_OR_BIBTEX_FILE_REQUIRED", "message": "Official ACL fetch requires --live or --bibtex-file."}]))
            return 1
        bibtex = AclAdapter().fetch_bibtex(authority, endpoints[0])
    elif args.source == "arxiv":
        bibtex = ArxivAdapter(accessed_at=candidate.raw.get("accessed_at")).build_manual_bibtex(candidate, args.citation_key or candidate.raw.get("citation_key"))
    elif args.source in {"iclr", "neurips"}:
        adapter = IclrAdapter() if args.source == "iclr" else NeuripsAdapter()
        endpoints = adapter.find_export_endpoints(authority)
        if not endpoints or not args.live:
            write_json(envelope("network_disabled", blocking_issues=[{"code": "LIVE_MODE_OR_BIBTEX_FILE_REQUIRED", "message": f"Official {args.source} fetch requires --live or --bibtex-file."}]))
            return 1
        bibtex = adapter.fetch_bibtex(authority, endpoints[0])
    elif args.source in VENUE_ADAPTERS:
        adapter = VENUE_ADAPTERS[args.source]()
        endpoints = adapter.find_export_endpoints(authority)
        if not endpoints or not args.live:
            write_json(envelope("network_disabled", blocking_issues=[{"code": "LIVE_MODE_OR_BIBTEX_FILE_REQUIRED", "message": f"Official {args.source} fetch requires --live or --bibtex-file."}]))
            return 1
        bibtex = adapter.fetch_bibtex(authority, endpoints[0])
    else:
        write_json(envelope("unsupported_source", blocking_issues=[{"code": "UNSUPPORTED_SOURCE", "message": f"Unsupported source {args.source}."}]))
        return 1

    if bibtex is None:
        write_json(envelope("bibtex_not_found", blocking_issues=[{"code": "BIBTEX_NOT_FOUND", "message": "No BibTeX could be fetched or normalized."}]))
        return 1

    data: dict[str, Any] = {"bibtex": bibtex.to_dict()}
    data["bibtex"].pop("raw_text", None)
    if args.write_lock:
        if decision is None:
            decision = ResolverDecision(
                query_id=args.citation_key or bibtex.citation_key,
                decision="selected",
                status="verified_official_bibtex" if bibtex.source_kind == "official_export" else "verified_manual_fallback",
                authority=authority,
                resolver_score=95,
                selected_candidate=candidate,
                decision_trace=["lock entry built from fetch-bibtex inputs"],
            )
        lock_entry = build_lock_entry(decision, bibtex, fallback_reason=args.fallback_reason)
        lockfile = merge_lock_entry(load_lockfile(args.write_lock), lock_entry)
        write_lockfile(lockfile, args.write_lock)
        data["lock_path"] = args.write_lock
        data["lock_entry"] = lock_entry.to_dict()
    write_json(envelope("bibtex_ready", data=data))
    return 0


def cmd_normalize_bibtex(args: argparse.Namespace) -> int:
    candidate = candidate_from_path(args.candidate)
    if args.source_kind == "arxiv_manual_normalized":
        bibtex = ArxivAdapter(accessed_at=candidate.raw.get("accessed_at")).build_manual_bibtex(candidate, args.citation_key)
    else:
        authors = " and ".join(candidate.authors)
        fields = [
            f"  title = {{{candidate.title}}},",
            f"  author = {{{authors}}},",
        ]
        if candidate.year:
            fields.append(f"  year = {{{candidate.year}}},")
        if candidate.venue:
            fields.append(f"  howpublished = {{{candidate.venue}}},")
        if candidate.doi:
            fields.append(f"  doi = {{{candidate.doi}}},")
        if candidate.url:
            fields.append(f"  url = {{{candidate.url}}},")
        raw_text = f"@misc{{{args.citation_key},\n" + "\n".join(fields) + "\n}\n"
        bibtex = BibtexRecord(
            entry_type="misc",
            citation_key=args.citation_key,
            source_kind=args.source_kind,
            raw_text=raw_text,
            raw_sha256=sha256_text(raw_text),
            normalized_sha256=sha256_text(raw_text.strip() + "\n"),
        )
    data = bibtex.to_dict()
    write_json(envelope("manual_bibtex_normalized", data=data))
    return 0


def cmd_audit_bib(args: argparse.Namespace) -> int:
    bib_text = Path(args.bib).read_text(encoding="utf-8")
    lockfile = load_lockfile(args.lock)
    issues = audit_bibliography(bib_text, lockfile, submission=args.submission)
    result = {
        "ok": not any(issue.severity == "blocking" for issue in issues),
        "blocking_issues": [issue.to_dict() for issue in issues if issue.severity == "blocking"],
        "warnings": [issue.to_dict() for issue in issues if issue.severity == "warning"],
    }
    write_json(result)
    return 0 if result["ok"] else 1


def cmd_sync_bibtex(args: argparse.Namespace) -> int:
    if args.in_place and args.output:
        write_json(
            envelope(
                "invalid_input",
                blocking_issues=[
                    {
                        "code": "OUTPUT_CONFLICT",
                        "message": "Use either --output or --in-place, not both.",
                    }
                ],
            )
        )
        return 2
    result = sync_bibtex(
        bib=args.bib,
        lock=args.lock,
        output=args.output,
        citation_keys=args.citation_key,
        add_missing=args.add_missing,
        in_place=args.in_place,
    )
    status = "bibtex_sync_complete" if result["wrote"] else "bibtex_sync_plan_ready"
    next_actions: list[dict[str, Any]] = []
    if result["ok"] and not result["wrote"] and result["change_count"]:
        command_parts = [
            "python -m refgate",
            "sync-bibtex",
            "--bib",
            shlex.quote(str(args.bib)),
            "--lock",
            shlex.quote(str(args.lock)),
            "--output",
            shlex.quote(str(args.output or "references.refgate.bib")),
            "--json",
        ]
        if args.add_missing:
            command_parts.insert(-1, "--add-missing")
        for citation_key in args.citation_key or []:
            command_parts.extend(["--citation-key", shlex.quote(citation_key)])
        next_actions.append(
            {
                "code": "WRITE_SYNCED_BIBTEX",
                "kind": "bibtex_sync_write",
                "message": "Write the planned BibTeX synchronization to an output file.",
                "command": " ".join(command_parts),
                "network_required": False,
                "requires_human_review": False,
                "writes_files": True,
            }
        )
    canonical_missing = [
        action
        for action in result["actions"]
        if action.get("action") == "blocked"
        and action.get("reason") == "canonical_bibtex_text_missing"
        and action.get("source_kind") == "official_export"
    ]
    if canonical_missing:
        command_parts = [
            "python -m refgate",
            "reference-check",
            "--lock",
            shlex.quote(str(args.lock)),
            "--write-lock",
            shlex.quote(str(args.lock)),
            "--fetch-official-bibtex",
            "--live",
            "--json",
        ]
        for action in canonical_missing:
            command_parts.extend(["--citation-key", shlex.quote(str(action["citation_key"]))])
        next_actions.append(
            {
                "code": "REFRESH_LOCK_CANONICAL_BIBTEX",
                "kind": "lockfile_reference_refresh",
                "message": "Refresh official-export lock entries so sync-bibtex has canonical BibTeX text.",
                "command": " ".join(command_parts),
                "network_required": True,
                "requires_human_review": False,
                "writes_files": True,
            }
        )
    manual_canonical_missing = [
        action
        for action in result["actions"]
        if action.get("action") == "blocked"
        and action.get("reason") == "canonical_bibtex_text_missing"
        and action.get("source_kind") != "official_export"
    ]
    if manual_canonical_missing:
        command_parts = [
            "python -m refgate",
            "reference-check",
            "--lock",
            shlex.quote(str(args.lock)),
            "--bibtex-dir",
            "REVIEWED_FALLBACK_BIBTEX_DIR",
            "--write-lock",
            shlex.quote(str(args.lock)),
            "--json",
        ]
        for action in manual_canonical_missing:
            command_parts.extend(["--citation-key", shlex.quote(str(action["citation_key"]))])
        next_actions.append(
            {
                "code": "BACKFILL_MANUAL_CANONICAL_BIBTEX",
                "kind": "lockfile_reference_refresh",
                "message": "Add reviewed fallback BibTeX files and refresh lock entries so sync-bibtex has canonical text.",
                "command": " ".join(command_parts),
                "network_required": False,
                "requires_human_review": True,
                "writes_files": True,
            }
        )
    write_json(
        envelope(
            status,
            data={key: value for key, value in result.items() if key not in {"blocking_issues", "warnings"}},
            blocking_issues=result["blocking_issues"],
            warnings=result["warnings"],
            next_actions=next_actions,
        )
    )
    return 0 if result["ok"] else 1


def cmd_audit_claims(args: argparse.Namespace) -> int:
    issues = audit_claims_table(args.claims, submission=args.submission)
    result = {
        "ok": not any(issue.severity == "blocking" for issue in issues),
        "blocking_issues": [issue.to_dict() for issue in issues if issue.severity == "blocking"],
        "warnings": [issue.to_dict() for issue in issues if issue.severity == "warning"],
    }
    write_json(result)
    return 0 if result["ok"] else 1


def cmd_claim_consistency(args: argparse.Namespace) -> int:
    results, issues = review_claim_consistency(
        args.claims,
        min_overlap=args.min_overlap,
        require_passing_status=args.submission,
    )
    blocking = [issue for issue in issues if issue.severity == "blocking"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    write_json(
        envelope(
            "claim_consistency_reviewed",
            data={
                "claims": args.claims,
                "min_overlap": args.min_overlap,
                "results": [result.to_dict() for result in results],
            },
            blocking_issues=[issue.to_dict() for issue in blocking],
            warnings=[issue.to_dict() for issue in warnings],
        )
    )
    return 0 if not blocking else 1


def cmd_claim_source_check(args: argparse.Namespace) -> int:
    output = args.output or args.claims
    result = run_claim_source_check(
        args.claims,
        args.source_map,
        output_path=output,
        min_overlap=args.min_overlap,
        require_passing_status=args.submission,
        rerank=args.rerank,
    )
    write_json(
        envelope(
            "claim_source_check_complete",
            data={
                key: value
                for key, value in result.items()
                if key not in {"blocking_issues", "warnings", "ok"}
                and (args.include_consistency or key != "consistency")
            },
            blocking_issues=result["blocking_issues"] if args.include_issues else summarize_issue_dicts(result["blocking_issues"]),
            warnings=result["warnings"] if args.include_issues else summarize_issue_dicts(result["warnings"]),
        )
    )
    return 0 if result["ok"] else 1


def cmd_claim_stubs(args: argparse.Namespace) -> int:
    tex_document = load_tex_document(args.tex)
    stubs = update_claim_stub_file_from_sources(
        [{"source_file": source.display_path, "text": source.text} for source in tex_document.sources],
        args.output,
    )
    write_json(
        envelope(
            "claim_stubs_written",
            data={
                "output": args.output,
                "tex_sources": [source.display_path for source in tex_document.sources],
                "created": len(stubs),
                "stubs": [stub.to_row() for stub in stubs],
            },
            warnings=[issue.to_dict() for issue in tex_document.issues],
        )
    )
    return 0


def cmd_claim_report(args: argparse.Namespace) -> int:
    report = render_claim_review_report(args.claims)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    elif not args.json:
        print(report)
    if args.json:
        write_json(envelope("claim_report_ready", data={"output": args.output, "report": None if args.output else report}))
    return 0


def cmd_evidence_suggest(args: argparse.Namespace) -> int:
    output = args.output or args.claims
    result = suggest_claim_evidence(
        args.claims,
        args.text,
        output_path=output,
        citation_key=args.citation_key,
        source_label=args.source_label,
        max_quote_chars=args.max_quote_chars,
        rerank=args.rerank,
    )
    write_json(envelope("evidence_suggestions_written", data=result))
    return 0


def cmd_evidence_suggest_bundle(args: argparse.Namespace) -> int:
    output = args.output or args.claims
    result = suggest_claim_evidence_bundle(
        args.claims,
        args.text,
        output_path=output,
        citation_key=args.citation_key,
        max_quote_chars=args.max_quote_chars,
        rerank=args.rerank,
    )
    write_json(envelope("evidence_bundle_suggestions_written", data=result))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    bib_text = Path(args.bib).read_text(encoding="utf-8")
    lockfile = load_lockfile(args.lock)
    issues = audit_bibliography(bib_text, lockfile, submission=args.submission)
    if args.tex:
        tex_document = load_tex_document(args.tex, submission=args.submission)
        issues.extend(tex_document.issues)
        issues.extend(audit_tex_bib_consistency(tex_document.combined_text, bib_text, submission=args.submission))
    if args.claims:
        issues.extend(audit_claims_table(args.claims, submission=args.submission))
    elif args.submission:
        issues.append(
            AuditIssue(
                code="CLAIM_TABLE_MISSING",
                message="Submission audit requires a claim-to-source table.",
                severity="blocking",
            )
        )

    if args.report:
        Path(args.report).write_text(render_markdown_report(lockfile, issues), encoding="utf-8")
    blocking = [issue for issue in issues if issue.severity == "blocking"]
    result = {
        "ok": not blocking,
        "blocking_issues": [issue.to_dict() for issue in issues if issue.severity == "blocking"],
        "warnings": [issue.to_dict() for issue in issues if issue.severity == "warning"],
        "report": args.report,
    }
    write_json(result)
    return 0 if result["ok"] else 1


def cmd_export_handoff(args: argparse.Namespace) -> int:
    bib_text = Path(args.bib).read_text(encoding="utf-8")
    lockfile = load_lockfile(args.lock)
    issues = audit_bibliography(bib_text, lockfile, submission=args.submission)
    blocking = [issue for issue in issues if issue.severity == "blocking"]
    if blocking and not args.allow_blocking:
        write_json(
            envelope(
                "handoff_blocked",
                blocking_issues=[issue.to_dict() for issue in blocking],
                warnings=[issue.to_dict() for issue in issues if issue.severity == "warning"],
            )
        )
        return 1
    result = write_handoff(lockfile, bib_text, args.output, export_format=args.format)
    write_json(
        envelope(
            "handoff_exported",
            data=result,
            blocking_issues=[issue.to_dict() for issue in blocking],
            warnings=[issue.to_dict() for issue in issues if issue.severity == "warning"],
        )
    )
    return 0 if not blocking else 1


def cmd_render_report(args: argparse.Namespace) -> int:
    lockfile = load_lockfile(args.lock)
    report = render_markdown_report(lockfile)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


def cmd_bootstrap_lock(args: argparse.Namespace) -> int:
    result = bootstrap_lock_from_bib(args.bib, args.output, project=args.project)
    write_json(envelope("starter_lock_written", data=result))
    return 0


def cmd_bootstrap_paper(args: argparse.Namespace) -> int:
    result = bootstrap_paper(args.tex, args.bib, args.lock_output, args.claims_output, project=args.project)
    write_json(envelope("paper_bootstrapped", data=result))
    return 0


def cmd_resolver_assist(args: argparse.Namespace) -> int:
    result = build_resolver_assist(args.lock, args.output, include_verified=args.include_verified)
    write_json(envelope("resolver_assist_ready", data=result))
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    if args.auth_command == "status":
        write_json(envelope("auth_status", data=auth_status()))
        return 0
    if args.auth_command == "doctor":
        diagnosis = auth_doctor()
        write_json(envelope("auth_doctor", data=diagnosis["status"], warnings=diagnosis["warnings"]))
        return 0
    if args.auth_command == "set":
        value = args.value
        if value is None:
            value = getpass.getpass(f"Enter value for {AUTH_SOURCES[args.source].label}: ")
        path = save_auth_value(args.source, value, path=args.config)
        write_json(envelope("auth_value_saved", data={"source": args.source, "config_path": str(path), "configured": True}))
        return 0
    if args.auth_command == "setup":
        selected = args.source or select_auth_sources()
        saved = []
        for source in selected:
            value = args.value
            if value is None:
                value = getpass.getpass(f"Enter value for {AUTH_SOURCES[source].label}: ")
            path = save_auth_value(source, value, path=args.config)
            saved.append({"source": source, "config_path": str(path), "configured": True})
        write_json(envelope("auth_setup_complete", data={"saved": saved, "count": len(saved)}))
        return 0
    write_json(envelope("invalid_auth_command", blocking_issues=[{"code": "INVALID_AUTH_COMMAND", "message": f"Unsupported auth command {args.auth_command}."}]))
    return 2


def cmd_fixture_matrix(args: argparse.Namespace) -> int:
    queries_data = load_json(args.queries)
    candidates_data = load_json(args.candidates)
    result = validate_fixture_matrix(queries_data, candidates_data)
    write_json(envelope("fixture_matrix_validated", data=result, blocking_issues=[] if result["ok"] else [{"code": "FIXTURE_MATRIX_INCOMPLETE", "message": "Fixture matrix has missing or blocking rows."}]))
    return 0 if result["ok"] else 1


def cmd_reference_check(args: argparse.Namespace) -> int:
    result = run_reference_check(
        args.lock,
        candidate_dir=args.candidate_dir,
        bibtex_dir=args.bibtex_dir,
        official_bibtex_dir=args.official_bibtex_dir,
        fixture_html_dir=args.fixture_html_dir,
        live=args.live,
        sources=args.source,
        cache_root=args.cache_root,
        prefer_cache=args.prefer_cache,
        write_lock=args.write_lock,
        fallback_reason=args.fallback_reason,
        max_entries=args.max_entries,
        fetch_official_bibtex=args.fetch_official_bibtex,
        citation_keys=args.citation_key,
    )
    write_json(
        envelope(
            "reference_check_complete",
            data={key: value for key, value in result.items() if key not in {"blocking_issues", "ok", "next_actions"}},
            blocking_issues=result["blocking_issues"],
            next_actions=result.get("next_actions", []),
        )
    )
    return 0 if result["ok"] else 1


def cmd_monitor_official_records(args: argparse.Namespace) -> int:
    result = run_official_monitor(
        args.lock,
        sources=args.source,
        cache_root=args.cache_root,
        prefer_cache=args.prefer_cache,
        write_lock=args.write_lock,
        fetch_official_bibtex=not args.no_fetch_official_bibtex,
        max_entries=args.max_entries,
        live=args.live,
    )
    write_json(
        envelope(
            "official_monitor_complete" if args.live else "official_monitor_ready",
            data={
                "plan": result["plan"],
                "reference_check": result["reference_check"],
            },
            blocking_issues=result["blocking_issues"],
            next_actions=result["next_actions"],
        )
    )
    return 0 if result["ok"] else 1


def cmd_run_next(args: argparse.Namespace) -> int:
    if args.output_plan:
        plan = run_next_actions(
            args.from_json,
            allow_network=args.allow_network,
            allow_writes=args.allow_writes,
            allow_human_review=args.allow_human_review,
            max_actions=args.max_actions,
            command_field=args.command_field,
            execute=False,
        )
        write_next_actions_result(args.output_plan, plan)
    result = run_next_actions(
        args.from_json,
        allow_network=args.allow_network,
        allow_writes=args.allow_writes,
        allow_human_review=args.allow_human_review,
        max_actions=args.max_actions,
        command_field=args.command_field,
        execute=args.execute,
    )
    if args.write_run_log:
        write_next_actions_result(args.write_run_log, result)
    write_json(
        envelope(
            "next_actions_executed" if args.execute else "next_actions_planned",
            data=result,
            blocking_issues=[] if result["ok"] else [{"code": "NEXT_ACTION_FAILED", "message": "One or more executed next actions failed."}],
        )
    )
    return 0 if result["ok"] else 1


def cmd_run_summary(args: argparse.Namespace) -> int:
    result = summarize_next_action_manifests(args.input)
    if args.markdown:
        target = Path(args.markdown)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_next_action_summary_markdown(result), encoding="utf-8")
    write_json(
        envelope(
            "next_action_summary",
            data=result,
            blocking_issues=[] if result["ok"] else [{"code": "NEXT_ACTIONS_REMAINING", "message": "One or more next actions still require execution, review, permission, or repair."}],
        )
    )
    return 0 if result["ok"] else 1


def cmd_live_smoke(args: argparse.Namespace) -> int:
    if args.write_manifest:
        manifest = cache_manifest(args.cache_root)
        Path(args.write_manifest).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write_manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_json(envelope("cache_manifest_written", data={"manifest": args.write_manifest, "cache": manifest}))
        return 0
    if args.manifest:
        if not Path(args.manifest).exists():
            write_json(
                envelope(
                    "manifest_missing",
                    blocking_issues=[
                        {
                            "code": "CACHE_MANIFEST_MISSING",
                            "message": "Cache manifest file does not exist.",
                            "evidence": [args.manifest],
                        }
                    ],
                )
            )
            return 1
        actual = cache_manifest(args.cache_root)
        expected = load_json(args.manifest)
        comparison = compare_cache_manifest(actual, expected)
        write_json(envelope("cache_manifest_compared", data={"actual": actual, "comparison": comparison}, blocking_issues=[] if comparison["ok"] else [{"code": "CACHE_MANIFEST_MISMATCH", "message": "Cached live response checksums differ from expected manifest."}]))
        return 0 if comparison["ok"] else 1
    if not args.live:
        write_json(envelope("network_disabled", blocking_issues=[{"code": "LIVE_MODE_REQUIRED", "message": "live-smoke requires --live unless --manifest is provided."}]))
        return 1
    query = load_query_from_args(args)
    try:
        result = run_live_smoke(
            args.source,
            query,
            cache_root=args.cache_root,
            prefer_cache=args.prefer_cache,
            min_interval_seconds=args.min_interval_seconds,
            retry=args.retry,
            retry_after_seconds=args.retry_after_seconds,
        )
    except Exception as exc:
        write_json(
            envelope(
                "live_smoke_failed",
                blocking_issues=[
                    {
                        "code": "LIVE_SMOKE_FAILED",
                        "message": f"{exc.__class__.__name__}: {exc}",
                    }
                ],
            )
        )
        return 1
    write_json(envelope("live_smoke_complete", data=result, blocking_issues=[] if result["ok"] else [{"code": "NO_CANDIDATES", "message": "Live smoke produced no candidates."}]))
    return 0 if result["ok"] else 1


def _load_queries(path: str | Path) -> list[PaperQuery]:
    data = load_json(path)
    if isinstance(data, dict) and "work_items" in data:
        return [PaperQuery.from_dict(item["query"]) for item in data.get("work_items", []) if item.get("query")]
    if isinstance(data, dict):
        return [PaperQuery.from_dict(data)]
    return [PaperQuery.from_dict(item) for item in data]


def _live_smoke_source_from_payload(
    payload: dict[str, Any],
    *,
    default_source: str,
    per_query_source: bool,
) -> str:
    if not per_query_source:
        return default_source
    source = payload.get("live_smoke_source") or payload.get("source")
    if not source:
        recommended = payload.get("recommended_sources") or []
        if isinstance(recommended, list) and recommended:
            source = recommended[0]
    return str(source or default_source)


def _live_smoke_query_item_from_payload(
    payload: dict[str, Any],
    *,
    default_source: str,
    per_query_source: bool,
) -> LiveSmokeQueryItem | None:
    query_payload = payload.get("query") if isinstance(payload.get("query"), dict) else payload
    if not isinstance(query_payload, dict):
        return None
    source = _live_smoke_source_from_payload(payload, default_source=default_source, per_query_source=per_query_source)
    if per_query_source and source == default_source:
        source = _live_smoke_source_from_payload(query_payload, default_source=default_source, per_query_source=True)
    return LiveSmokeQueryItem(source=source, query=PaperQuery.from_dict(query_payload))


def _load_live_smoke_query_items(
    path: str | Path,
    *,
    default_source: str,
    per_query_source: bool,
) -> list[LiveSmokeQueryItem]:
    data = load_json(path)
    if isinstance(data, dict) and "work_items" in data:
        payloads = [item for item in data.get("work_items", []) if item.get("query")]
    elif isinstance(data, dict):
        payloads = [data]
    else:
        payloads = list(data)
    items = [
        item
        for item in (
            _live_smoke_query_item_from_payload(payload, default_source=default_source, per_query_source=per_query_source)
            for payload in payloads
            if isinstance(payload, dict)
        )
        if item is not None
    ]
    return items


def cmd_live_smoke_suite(args: argparse.Namespace) -> int:
    if args.manifest:
        if not Path(args.manifest).exists():
            write_json(
                envelope(
                    "manifest_missing",
                    blocking_issues=[
                        {
                            "code": "CACHE_MANIFEST_MISSING",
                            "message": "Cache manifest file does not exist.",
                            "evidence": [args.manifest],
                        }
                    ],
                )
            )
            return 1
        actual = cache_manifest(args.cache_root)
        expected = load_json(args.manifest)
        comparison = compare_cache_manifest(actual, expected)
        write_json(
            envelope(
                "cache_manifest_compared",
                data={"actual": actual, "comparison": comparison},
                blocking_issues=[]
                if comparison["ok"]
                else [
                    {
                        "code": "CACHE_MANIFEST_MISMATCH",
                        "message": "Cached live response checksums differ from expected manifest.",
                    }
                ],
            )
        )
        return 0 if comparison["ok"] else 1
    if not args.live:
        write_json(
            envelope(
                "network_disabled",
                blocking_issues=[
                    {
                        "code": "LIVE_MODE_REQUIRED",
                        "message": "live-smoke-suite requires --live.",
                    }
                ],
            )
        )
        return 1
    if args.per_query_source:
        items = _load_live_smoke_query_items(args.queries, default_source=args.source, per_query_source=True)
        unsupported_sources = sorted({item.source for item in items if item.source not in DISCOVERY_SOURCES})
        if unsupported_sources:
            write_json(
                envelope(
                    "unsupported_source",
                    blocking_issues=[
                        {
                            "code": "UNSUPPORTED_SOURCE",
                            "message": "One or more per-query live smoke sources are unsupported.",
                            "evidence": unsupported_sources,
                        }
                    ],
                )
            )
            return 1
        result = run_live_smoke_suite_items(
            items,
            cache_root=args.cache_root,
            prefer_cache=args.prefer_cache,
            min_interval_seconds=args.min_interval_seconds,
            retry=args.retry,
            retry_after_seconds=args.retry_after_seconds,
            max_queries=args.max_queries,
            default_source=args.source,
        )
    else:
        queries = _load_queries(args.queries)
        result = run_live_smoke_suite(
            queries,
            source=args.source,
            cache_root=args.cache_root,
            prefer_cache=args.prefer_cache,
            min_interval_seconds=args.min_interval_seconds,
            retry=args.retry,
            retry_after_seconds=args.retry_after_seconds,
            max_queries=args.max_queries,
        )
    warnings = []
    if args.write_manifest and result["ok"]:
        manifest = cache_manifest(args.cache_root)
        Path(args.write_manifest).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write_manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result["manifest"] = {"path": args.write_manifest, "record_count": len(manifest.get("records", [])), "written": True}
    elif args.write_manifest:
        result["manifest"] = {
            "path": args.write_manifest,
            "record_count": 0,
            "written": False,
            "reason": "suite_failed",
        }
        warnings.append(
            {
                "code": "CACHE_MANIFEST_NOT_WRITTEN",
                "message": "Live smoke suite failed, so the reviewed cache manifest was not written.",
                "evidence": [args.write_manifest],
            }
        )
    write_json(
        envelope(
            "live_smoke_suite_complete",
            data=result,
            blocking_issues=[] if result["ok"] else [{"code": "LIVE_SMOKE_SUITE_FAILED", "message": "One or more live smoke queries failed."}],
            warnings=warnings,
        )
    )
    return 0 if result["ok"] else 1


def cmd_validate_source_text(args: argparse.Namespace) -> int:
    result = validate_source_text(args.text, min_chars=args.min_chars)
    write_json(envelope("source_text_validated", data=result, blocking_issues=result["blocking_issues"]))
    return 0 if result["ok"] else 1


def cmd_check_source_titles(args: argparse.Namespace) -> int:
    result = check_source_titles(args.lock, args.source_map, title_review_path=args.title_review)
    write_json(
        envelope(
            "source_titles_checked",
            data=result,
            blocking_issues=result["blocking_issues"],
            warnings=result.get("warnings", []),
            next_actions=source_title_next_actions(result),
        )
    )
    return 0 if result["ok"] else 1


def cmd_download_sources(args: argparse.Namespace) -> int:
    result = download_sources(
        args.lock,
        source_dir=args.source_dir,
        citation_keys=args.citation_key,
        live=args.live,
        overwrite=args.overwrite,
    )
    blocking = result.get("blocking_issues", [])
    warnings = result.get("warnings", [])
    next_actions = []
    if not args.live and any(item.get("url") for item in result.get("items", [])):
        command_parts = [
            "python",
            "-m",
            "refgate",
            "download-sources",
            "--lock",
            str(args.lock),
            "--source-dir",
            str(args.source_dir),
        ]
        for citation_key in args.citation_key or []:
            command_parts.extend(["--citation-key", citation_key])
        command_parts.extend(["--live", "--json"])
        next_actions.append(
            {
                "code": "DOWNLOAD_SOURCES_LIVE",
                "kind": "source_download",
                "requires_human_review": False,
                "writes_files": True,
                "network_required": True,
                "message": "Run the same command with --live to download planned source PDFs.",
                "command": " ".join(shlex.quote(part) for part in command_parts),
            }
        )
    write_json(
        envelope(
            "source_download_complete" if args.live else "source_download_plan_ready",
            data={key: value for key, value in result.items() if key not in {"blocking_issues", "warnings", "ok"}},
            blocking_issues=blocking,
            warnings=warnings,
            next_actions=next_actions,
        )
    )
    return 0 if result.get("ok", False) else 1


def cmd_vision_extract_plan(args: argparse.Namespace) -> int:
    result = build_vision_extraction_plan(
        args.pdf,
        citation_key=args.citation_key,
        source_label=args.source_label,
        image_dir=args.image_dir,
        pages=args.page,
    )
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_json(
        envelope(
            "vision_extraction_plan_ready",
            data={**result, "written_to": args.output},
            blocking_issues=result.get("blocking_issues", []),
            warnings=result.get("warnings", []),
        )
    )
    return 0 if result["ok"] else 1


def cmd_export_review_bundle(args: argparse.Namespace) -> int:
    active_source_map = args.source_map
    source_map_build = None
    if args.source_dir:
        source_map_output = args.source_map_output or str(Path(args.output).with_suffix(".source_map.tsv"))
        source_map_build = build_source_map_from_dir(
            source_dir=args.source_dir,
            claims_path=args.claims,
            output_path=source_map_output,
        )
        active_source_map = source_map_build["output"]
    result = write_codex_review_bundle(
        tex=args.tex,
        bib=args.bib,
        lock=args.lock,
        claims=args.claims,
        source_map=active_source_map,
        output=args.output,
        markdown=args.markdown,
        max_quote_chars=args.max_quote_chars,
        max_candidates_per_source=args.max_candidates_per_source,
    )
    if source_map_build:
        result["source_map"] = source_map_build
    write_json(envelope("codex_review_bundle_exported", data=result))
    return 0


def cmd_import_review(args: argparse.Namespace) -> int:
    result = import_codex_review(
        claims=args.claims,
        review=args.review,
        output=args.output,
        allow_checked=args.allow_checked,
    )
    write_json(
        envelope(
            "codex_review_imported",
            data={key: value for key, value in result.items() if key not in {"blocking_issues", "warnings", "ok"}},
            blocking_issues=result["blocking_issues"],
            warnings=result["warnings"],
        )
    )
    return 0 if result["ok"] else 1


def cmd_paper_agents_template(args: argparse.Namespace) -> int:
    result = write_paper_agents_template(
        args.output,
        tex=args.tex,
        bib=args.bib,
        lock=args.lock,
        claims=args.claims,
        report=args.report,
        command=args.command,
    )
    write_json(envelope("paper_agents_template_written", data=result))
    return 0


def cmd_paper_audit(args: argparse.Namespace) -> int:
    result = run_paper_audit(
        tex=args.tex,
        bib=args.bib,
        lock=args.lock,
        claims=args.claims,
        report=args.report,
        resolver_output=args.resolver_output,
        handoff_output=args.handoff,
        csl_output=args.csl,
        source_map=args.source_map,
        source_dir=args.source_dir,
        source_map_output=args.source_map_output,
        claim_review_output=args.claim_review_output,
        source_title_review=args.source_title_review,
        project=args.project,
        submission=args.submission,
        allow_blocking_handoff=args.allow_blocking_handoff,
        update_claims=args.update_claims,
        include_work_items=args.include_work_items,
    )
    if args.next_plan_output:
        plan = build_next_actions_result(
            result.get("next_actions", []),
            input_label="paper-audit",
            execute=False,
        )
        write_next_actions_result(args.next_plan_output, plan)
    write_json(
        envelope(
            "paper_audit_complete",
            data={
                key: value
                for key, value in result.items()
                if key not in {"blocking_issues", "warnings", "ok", "next_actions"}
            },
            blocking_issues=result["blocking_issues"] if args.include_issues else result["issue_summary"]["blocking"],
            warnings=result["warnings"] if args.include_issues else result["issue_summary"]["warnings"],
            next_actions=result.get("next_actions", []),
        )
    )
    return 0 if result["ok"] else 1


def cmd_publish_check(args: argparse.Namespace) -> int:
    result = run_publish_check(args.root)
    warnings = []
    if result["generated_artifacts"]:
        warnings.append(
            {
                "code": "GENERATED_ARTIFACTS_PRESENT",
                "message": "Generated local artifacts are present; keep them out of commits.",
                "evidence": result["generated_artifacts"][:20],
            }
        )
    write_json(
        envelope(
            "publish_check_complete",
            data=result,
            blocking_issues=[] if result["ok"] else [{"code": "PUBLISH_CHECK_FAILED", "message": "Publish check found files that need review."}],
            warnings=warnings,
        )
    )
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refgate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser("discover")
    discover_parser.add_argument("--query")
    discover_parser.add_argument("--query-id")
    discover_parser.add_argument("--title")
    discover_parser.add_argument("--author", action="append")
    discover_parser.add_argument("--year", type=int)
    discover_parser.add_argument("--doi")
    discover_parser.add_argument("--arxiv-id")
    discover_parser.add_argument("--citation-key")
    discover_parser.add_argument("--preferred-venue", action="append")
    discover_parser.add_argument(
        "--source",
        choices=DISCOVERY_SOURCES,
        default="arxiv",
    )
    discover_parser.add_argument("--fixture")
    discover_parser.add_argument("--url")
    discover_parser.add_argument("--fixture-html")
    discover_parser.add_argument("--live", action="store_true")
    discover_parser.add_argument("--json", action="store_true")
    discover_parser.set_defaults(func=cmd_discover)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--query")
    resolve_parser.add_argument("--query-id")
    resolve_parser.add_argument("--title")
    resolve_parser.add_argument("--author", action="append")
    resolve_parser.add_argument("--year", type=int)
    resolve_parser.add_argument("--doi")
    resolve_parser.add_argument("--arxiv-id")
    resolve_parser.add_argument("--citation-key")
    resolve_parser.add_argument("--preferred-venue", action="append")
    resolve_parser.add_argument("--candidates", required=True)
    resolve_parser.add_argument("--json", action="store_true", help="Kept for stable agent interface")
    resolve_parser.set_defaults(func=cmd_resolve)

    fetch_parser = subparsers.add_parser("fetch-bibtex")
    fetch_parser.add_argument("--resolved")
    fetch_parser.add_argument("--candidate")
    fetch_parser.add_argument("--authority")
    fetch_parser.add_argument("--bibtex-file")
    fetch_parser.add_argument("--source", choices=OFFICIAL_BIBTEX_SOURCES, default="acl")
    fetch_parser.add_argument("--source-kind", default="publisher_metadata_manual_normalized")
    fetch_parser.add_argument("--citation-key")
    fetch_parser.add_argument("--fallback-reason")
    fetch_parser.add_argument("--write-lock")
    fetch_parser.add_argument("--live", action="store_true")
    fetch_parser.add_argument("--json", action="store_true")
    fetch_parser.set_defaults(func=cmd_fetch_bibtex)

    normalize_parser = subparsers.add_parser("normalize-bibtex")
    normalize_parser.add_argument("--candidate", required=True)
    normalize_parser.add_argument("--citation-key", required=True)
    normalize_parser.add_argument(
        "--source-kind",
        choices=["publisher_metadata_manual_normalized", "arxiv_manual_normalized"],
        default="publisher_metadata_manual_normalized",
    )
    normalize_parser.add_argument("--json", action="store_true")
    normalize_parser.set_defaults(func=cmd_normalize_bibtex)

    audit_parser = subparsers.add_parser("audit-bib")
    audit_parser.add_argument("--bib", required=True)
    audit_parser.add_argument("--lock", required=True)
    audit_parser.add_argument("--submission", action="store_true")
    audit_parser.add_argument("--json", action="store_true", help="Kept for stable agent interface")
    audit_parser.set_defaults(func=cmd_audit_bib)

    sync_bibtex_parser = subparsers.add_parser("sync-bibtex")
    sync_bibtex_parser.add_argument("--bib", required=True)
    sync_bibtex_parser.add_argument("--lock", required=True)
    sync_bibtex_parser.add_argument("--output")
    sync_bibtex_parser.add_argument("--in-place", action="store_true")
    sync_bibtex_parser.add_argument("--citation-key", action="append")
    sync_bibtex_parser.add_argument("--add-missing", action="store_true")
    sync_bibtex_parser.add_argument("--json", action="store_true")
    sync_bibtex_parser.set_defaults(func=cmd_sync_bibtex)

    claims_parser = subparsers.add_parser("audit-claims")
    claims_parser.add_argument("--claims", required=True)
    claims_parser.add_argument("--submission", action="store_true")
    claims_parser.add_argument("--json", action="store_true")
    claims_parser.set_defaults(func=cmd_audit_claims)

    claim_consistency_parser = subparsers.add_parser("claim-consistency")
    claim_consistency_parser.add_argument("--claims", required=True)
    claim_consistency_parser.add_argument("--min-overlap", type=int, default=2)
    claim_consistency_parser.add_argument("--submission", action="store_true")
    claim_consistency_parser.add_argument("--json", action="store_true")
    claim_consistency_parser.set_defaults(func=cmd_claim_consistency)

    claim_source_parser = subparsers.add_parser("claim-source-check")
    claim_source_parser.add_argument("--claims", required=True)
    claim_source_parser.add_argument("--source-map", required=True)
    claim_source_parser.add_argument("--output")
    claim_source_parser.add_argument("--min-overlap", type=int, default=2)
    claim_source_parser.add_argument("--rerank", choices=["lexical", "semantic-lite"], default="lexical")
    claim_source_parser.add_argument("--submission", action="store_true")
    claim_source_parser.add_argument("--include-consistency", action="store_true")
    claim_source_parser.add_argument("--include-issues", action="store_true")
    claim_source_parser.add_argument("--json", action="store_true")
    claim_source_parser.set_defaults(func=cmd_claim_source_check)

    claim_stubs_parser = subparsers.add_parser("claim-stubs")
    claim_stubs_parser.add_argument("--tex", required=True)
    claim_stubs_parser.add_argument("--output", required=True)
    claim_stubs_parser.add_argument("--json", action="store_true")
    claim_stubs_parser.set_defaults(func=cmd_claim_stubs)

    claim_report_parser = subparsers.add_parser("claim-report")
    claim_report_parser.add_argument("--claims", required=True)
    claim_report_parser.add_argument("--output")
    claim_report_parser.add_argument("--json", action="store_true")
    claim_report_parser.set_defaults(func=cmd_claim_report)

    evidence_parser = subparsers.add_parser("evidence-suggest")
    evidence_parser.add_argument("--claims", required=True)
    evidence_parser.add_argument("--text", required=True)
    evidence_parser.add_argument("--output")
    evidence_parser.add_argument("--citation-key")
    evidence_parser.add_argument("--source-label")
    evidence_parser.add_argument("--max-quote-chars", type=int, default=320)
    evidence_parser.add_argument("--rerank", choices=["lexical", "semantic-lite"], default="lexical")
    evidence_parser.add_argument("--json", action="store_true")
    evidence_parser.set_defaults(func=cmd_evidence_suggest)

    evidence_bundle_parser = subparsers.add_parser("evidence-suggest-bundle")
    evidence_bundle_parser.add_argument("--claims", required=True)
    evidence_bundle_parser.add_argument("--text", action="append", required=True)
    evidence_bundle_parser.add_argument("--output")
    evidence_bundle_parser.add_argument("--citation-key")
    evidence_bundle_parser.add_argument("--max-quote-chars", type=int, default=320)
    evidence_bundle_parser.add_argument("--rerank", choices=["lexical", "semantic-lite"], default="lexical")
    evidence_bundle_parser.add_argument("--json", action="store_true")
    evidence_bundle_parser.set_defaults(func=cmd_evidence_suggest_bundle)

    full_audit_parser = subparsers.add_parser("audit")
    full_audit_parser.add_argument("--tex")
    full_audit_parser.add_argument("--bib", required=True)
    full_audit_parser.add_argument("--lock", required=True)
    full_audit_parser.add_argument("--claims")
    full_audit_parser.add_argument("--frozen", action="store_true")
    full_audit_parser.add_argument("--submission", action="store_true")
    full_audit_parser.add_argument("--report")
    full_audit_parser.add_argument("--json", action="store_true")
    full_audit_parser.set_defaults(func=cmd_audit)

    handoff_parser = subparsers.add_parser("export-handoff")
    handoff_parser.add_argument("--lock", required=True)
    handoff_parser.add_argument("--bib", required=True)
    handoff_parser.add_argument("--output", required=True)
    handoff_parser.add_argument("--format", choices=["refgate-json", "csl-json"], default="refgate-json")
    handoff_parser.add_argument("--submission", action="store_true")
    handoff_parser.add_argument("--allow-blocking", action="store_true")
    handoff_parser.add_argument("--json", action="store_true")
    handoff_parser.set_defaults(func=cmd_export_handoff)

    bootstrap_lock_parser = subparsers.add_parser("bootstrap-lock")
    bootstrap_lock_parser.add_argument("--bib", required=True)
    bootstrap_lock_parser.add_argument("--output", required=True)
    bootstrap_lock_parser.add_argument("--project")
    bootstrap_lock_parser.add_argument("--json", action="store_true")
    bootstrap_lock_parser.set_defaults(func=cmd_bootstrap_lock)

    bootstrap_paper_parser = subparsers.add_parser("bootstrap-paper")
    bootstrap_paper_parser.add_argument("--tex", required=True)
    bootstrap_paper_parser.add_argument("--bib", required=True)
    bootstrap_paper_parser.add_argument("--lock-output", required=True)
    bootstrap_paper_parser.add_argument("--claims-output", required=True)
    bootstrap_paper_parser.add_argument("--project")
    bootstrap_paper_parser.add_argument("--json", action="store_true")
    bootstrap_paper_parser.set_defaults(func=cmd_bootstrap_paper)

    resolver_assist_parser = subparsers.add_parser("resolver-assist")
    resolver_assist_parser.add_argument("--lock", required=True)
    resolver_assist_parser.add_argument("--output")
    resolver_assist_parser.add_argument("--include-verified", action="store_true")
    resolver_assist_parser.add_argument("--json", action="store_true")
    resolver_assist_parser.set_defaults(func=cmd_resolver_assist)

    fixture_matrix_parser = subparsers.add_parser("fixture-matrix")
    fixture_matrix_parser.add_argument("--queries", required=True)
    fixture_matrix_parser.add_argument("--candidates", required=True)
    fixture_matrix_parser.add_argument("--json", action="store_true")
    fixture_matrix_parser.set_defaults(func=cmd_fixture_matrix)

    reference_check_parser = subparsers.add_parser("reference-check")
    reference_check_parser.add_argument("--lock", required=True)
    reference_check_parser.add_argument("--candidate-dir")
    reference_check_parser.add_argument("--bibtex-dir")
    reference_check_parser.add_argument("--official-bibtex-dir")
    reference_check_parser.add_argument("--fixture-html-dir")
    reference_check_parser.add_argument("--source", choices=DISCOVERY_SOURCES, action="append")
    reference_check_parser.add_argument("--cache-root", default=".refgate/cache")
    reference_check_parser.add_argument("--prefer-cache", action="store_true")
    reference_check_parser.add_argument("--write-lock")
    reference_check_parser.add_argument("--fallback-reason")
    reference_check_parser.add_argument("--max-entries", type=int)
    reference_check_parser.add_argument("--citation-key", action="append")
    reference_check_parser.add_argument("--fetch-official-bibtex", action="store_true")
    reference_check_parser.add_argument("--live", action="store_true")
    reference_check_parser.add_argument("--json", action="store_true")
    reference_check_parser.set_defaults(func=cmd_reference_check)

    monitor_parser = subparsers.add_parser("monitor-official-records")
    monitor_parser.add_argument("--lock", required=True)
    monitor_parser.add_argument("--source", choices=OFFICIAL_MONITOR_SOURCES, action="append")
    monitor_parser.add_argument("--cache-root", default=".refgate/cache")
    monitor_parser.add_argument("--prefer-cache", action="store_true")
    monitor_parser.add_argument("--write-lock")
    monitor_parser.add_argument("--no-fetch-official-bibtex", action="store_true")
    monitor_parser.add_argument("--max-entries", type=int)
    monitor_parser.add_argument("--live", action="store_true")
    monitor_parser.add_argument("--json", action="store_true")
    monitor_parser.set_defaults(func=cmd_monitor_official_records)

    run_next_parser = subparsers.add_parser("run-next")
    run_next_parser.add_argument("--from", dest="from_json", required=True)
    run_next_parser.add_argument("--allow-network", action="store_true")
    run_next_parser.add_argument("--allow-writes", action="store_true")
    run_next_parser.add_argument("--allow-human-review", action="store_true")
    run_next_parser.add_argument("--max-actions", type=int)
    run_next_parser.add_argument("--command-field", default="command")
    run_next_parser.add_argument("--execute", action="store_true")
    run_next_parser.add_argument("--output-plan")
    run_next_parser.add_argument("--write-run-log")
    run_next_parser.add_argument("--json", action="store_true")
    run_next_parser.set_defaults(func=cmd_run_next)

    run_summary_parser = subparsers.add_parser("run-summary")
    run_summary_parser.add_argument("--input", action="append", required=True)
    run_summary_parser.add_argument("--markdown")
    run_summary_parser.add_argument("--json", action="store_true")
    run_summary_parser.set_defaults(func=cmd_run_summary)

    live_smoke_parser = subparsers.add_parser("live-smoke")
    live_smoke_parser.add_argument("--source", choices=DISCOVERY_SOURCES, default="arxiv")
    live_smoke_parser.add_argument("--query")
    live_smoke_parser.add_argument("--query-id")
    live_smoke_parser.add_argument("--title")
    live_smoke_parser.add_argument("--author", action="append")
    live_smoke_parser.add_argument("--year", type=int)
    live_smoke_parser.add_argument("--doi")
    live_smoke_parser.add_argument("--arxiv-id")
    live_smoke_parser.add_argument("--citation-key")
    live_smoke_parser.add_argument("--preferred-venue", action="append")
    live_smoke_parser.add_argument("--cache-root", default=".refgate/cache")
    live_smoke_parser.add_argument("--manifest")
    live_smoke_parser.add_argument("--write-manifest")
    live_smoke_parser.add_argument("--prefer-cache", action="store_true")
    live_smoke_parser.add_argument("--min-interval-seconds", type=float, default=0)
    live_smoke_parser.add_argument("--retry", type=int, default=0)
    live_smoke_parser.add_argument("--retry-after-seconds", type=float, default=0)
    live_smoke_parser.add_argument("--live", action="store_true")
    live_smoke_parser.add_argument("--json", action="store_true")
    live_smoke_parser.set_defaults(func=cmd_live_smoke)

    live_smoke_suite_parser = subparsers.add_parser("live-smoke-suite")
    live_smoke_suite_parser.add_argument("--source", choices=DISCOVERY_SOURCES, default="arxiv")
    live_smoke_suite_parser.add_argument("--queries", required=True)
    live_smoke_suite_parser.add_argument("--cache-root", default=".refgate/cache")
    live_smoke_suite_parser.add_argument("--manifest")
    live_smoke_suite_parser.add_argument("--write-manifest")
    live_smoke_suite_parser.add_argument("--per-query-source", action="store_true")
    live_smoke_suite_parser.add_argument("--prefer-cache", action="store_true")
    live_smoke_suite_parser.add_argument("--min-interval-seconds", type=float, default=0)
    live_smoke_suite_parser.add_argument("--retry", type=int, default=0)
    live_smoke_suite_parser.add_argument("--retry-after-seconds", type=float, default=0)
    live_smoke_suite_parser.add_argument("--max-queries", type=int)
    live_smoke_suite_parser.add_argument("--live", action="store_true")
    live_smoke_suite_parser.add_argument("--json", action="store_true")
    live_smoke_suite_parser.set_defaults(func=cmd_live_smoke_suite)

    validate_source_text_parser = subparsers.add_parser("validate-source-text")
    validate_source_text_parser.add_argument("--text", action="append", required=True)
    validate_source_text_parser.add_argument("--min-chars", type=int, default=80)
    validate_source_text_parser.add_argument("--json", action="store_true")
    validate_source_text_parser.set_defaults(func=cmd_validate_source_text)

    source_title_parser = subparsers.add_parser("check-source-titles")
    source_title_parser.add_argument("--lock", required=True)
    source_title_parser.add_argument("--source-map", required=True)
    source_title_parser.add_argument("--title-review")
    source_title_parser.add_argument("--json", action="store_true")
    source_title_parser.set_defaults(func=cmd_check_source_titles)

    vision_plan_parser = subparsers.add_parser("vision-extract-plan")
    vision_plan_parser.add_argument("--pdf", required=True)
    vision_plan_parser.add_argument("--citation-key")
    vision_plan_parser.add_argument("--source-label")
    vision_plan_parser.add_argument("--image-dir")
    vision_plan_parser.add_argument("--page", type=int, action="append")
    vision_plan_parser.add_argument("--output")
    vision_plan_parser.add_argument("--json", action="store_true")
    vision_plan_parser.set_defaults(func=cmd_vision_extract_plan)

    review_bundle_parser = subparsers.add_parser("export-review-bundle")
    review_bundle_parser.add_argument("--tex", required=True)
    review_bundle_parser.add_argument("--bib", required=True)
    review_bundle_parser.add_argument("--lock", required=True)
    review_bundle_parser.add_argument("--claims", required=True)
    review_bundle_parser.add_argument("--source-map")
    review_bundle_parser.add_argument("--source-dir")
    review_bundle_parser.add_argument("--source-map-output")
    review_bundle_parser.add_argument("--output", required=True)
    review_bundle_parser.add_argument("--markdown")
    review_bundle_parser.add_argument("--max-quote-chars", type=int, default=500)
    review_bundle_parser.add_argument("--max-candidates-per-source", type=int, default=5)
    review_bundle_parser.add_argument("--json", action="store_true")
    review_bundle_parser.set_defaults(func=cmd_export_review_bundle)

    import_review_parser = subparsers.add_parser("import-review")
    import_review_parser.add_argument("--claims", required=True)
    import_review_parser.add_argument("--review", required=True)
    import_review_parser.add_argument("--output", required=True)
    import_review_parser.add_argument("--allow-checked", action="store_true")
    import_review_parser.add_argument("--json", action="store_true")
    import_review_parser.set_defaults(func=cmd_import_review)

    paper_template_parser = subparsers.add_parser("paper-agents-template")
    paper_template_parser.add_argument("--tex", required=True)
    paper_template_parser.add_argument("--bib", required=True)
    paper_template_parser.add_argument("--lock", required=True)
    paper_template_parser.add_argument("--claims", required=True)
    paper_template_parser.add_argument("--report", required=True)
    paper_template_parser.add_argument("--output", required=True)
    paper_template_parser.add_argument("--command", default="python -m refgate")
    paper_template_parser.add_argument("--json", action="store_true")
    paper_template_parser.set_defaults(func=cmd_paper_agents_template)

    paper_audit_parser = subparsers.add_parser("paper-audit")
    paper_audit_parser.add_argument("--tex", required=True)
    paper_audit_parser.add_argument("--bib", required=True)
    paper_audit_parser.add_argument("--lock", default="refgate.lock.json")
    paper_audit_parser.add_argument("--claims", default="refgate_claims.tsv")
    paper_audit_parser.add_argument("--report", default="refgate_audit.md")
    paper_audit_parser.add_argument("--resolver-output", default="refgate_queries.json")
    paper_audit_parser.add_argument("--handoff")
    paper_audit_parser.add_argument("--csl")
    paper_audit_parser.add_argument("--source-map")
    paper_audit_parser.add_argument("--source-dir")
    paper_audit_parser.add_argument("--source-map-output")
    paper_audit_parser.add_argument("--claim-review-output")
    paper_audit_parser.add_argument("--source-title-review")
    paper_audit_parser.add_argument("--project")
    paper_audit_parser.add_argument("--frozen", action="store_true", help="Compatibility flag; paper-audit always audits against the supplied lockfile.")
    paper_audit_parser.add_argument("--submission", action="store_true")
    paper_audit_parser.add_argument("--allow-blocking-handoff", action="store_true")
    paper_audit_parser.add_argument("--update-claims", action="store_true")
    paper_audit_parser.add_argument("--include-work-items", action="store_true")
    paper_audit_parser.add_argument("--include-issues", action="store_true")
    paper_audit_parser.add_argument("--next-plan-output")
    paper_audit_parser.add_argument("--json", action="store_true")
    paper_audit_parser.set_defaults(func=cmd_paper_audit)

    download_sources_parser = subparsers.add_parser("download-sources")
    download_sources_parser.add_argument("--lock", required=True)
    download_sources_parser.add_argument("--source-dir", default=".refgate/sources")
    download_sources_parser.add_argument("--citation-key", action="append")
    download_sources_parser.add_argument("--live", action="store_true")
    download_sources_parser.add_argument("--overwrite", action="store_true")
    download_sources_parser.add_argument("--json", action="store_true")
    download_sources_parser.set_defaults(func=cmd_download_sources)

    publish_check_parser = subparsers.add_parser("publish-check")
    publish_check_parser.add_argument("--root", default=".")
    publish_check_parser.add_argument("--json", action="store_true")
    publish_check_parser.set_defaults(func=cmd_publish_check)

    report_parser = subparsers.add_parser("render-report")
    report_parser.add_argument("--lock", required=True)
    report_parser.add_argument("--output")
    report_parser.set_defaults(func=cmd_render_report)

    auth_parser = subparsers.add_parser("auth")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)
    auth_status_parser = auth_subparsers.add_parser("status")
    auth_status_parser.add_argument("--json", action="store_true")
    auth_status_parser.set_defaults(func=cmd_auth)
    auth_doctor_parser = auth_subparsers.add_parser("doctor")
    auth_doctor_parser.add_argument("--json", action="store_true")
    auth_doctor_parser.set_defaults(func=cmd_auth)
    auth_set_parser = auth_subparsers.add_parser("set")
    auth_set_parser.add_argument("source", choices=sorted(AUTH_SOURCES))
    auth_set_parser.add_argument("--value")
    auth_set_parser.add_argument("--config")
    auth_set_parser.add_argument("--json", action="store_true")
    auth_set_parser.set_defaults(func=cmd_auth)
    auth_setup_parser = auth_subparsers.add_parser("setup")
    auth_setup_parser.add_argument("--source", action="append", choices=sorted(AUTH_SOURCES))
    auth_setup_parser.add_argument("--value")
    auth_setup_parser.add_argument("--config")
    auth_setup_parser.add_argument("--json", action="store_true")
    auth_setup_parser.set_defaults(func=cmd_auth)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
