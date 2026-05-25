---
name: refgate-reference-gate
description: Use when working on academic manuscripts, bibliographies, BibTeX, citation claims, source evidence, source PDFs, or reference verification with the Refgate CLI.
metadata:
  short-description: Gate manuscript references with Refgate
---

# Refgate Reference Gate

Use this skill when a task touches academic manuscript references, BibTeX,
citation keys, citation-bearing claims, source evidence, or reference handoff
artifacts.

Refgate is CLI-first. Treat JSON CLI outputs, `refgate.lock.json`,
`refgate_claims.tsv`, source maps, review bundles, and Markdown reports as the
source of truth. Do not invent an MCP or server workflow for core verification.

## Command Form

Use the installed command when available. Verify it with `refgate --help` if the
environment is unclear:

```bash
refgate ...
```

If the command is missing but the Refgate source checkout is the active
workspace, use:

```bash
PYTHONPATH=src python3 -m refgate ...
```

If neither form works, report that the Refgate CLI is not installed or not in
the active checkout. The plugin provides Codex workflow instructions; the CLI is
the executable verification engine.

## Operator Workflow

1. Identify the manuscript `.tex` file and bibliography `.bib` file.
2. Run `paper-audit` as the first pass for ordinary paper repositories.
3. Read `ok`, `blocking_issues`, `warnings`, and `next_actions` from JSON
   output before editing bibliography or claim artifacts.
4. Execute only deterministic follow-up commands that are allowed by the user's
   request and action metadata. Network work requires explicit opt-in.
5. If a command returns `ok=false`, report the blocker and continue the
   correction loop only when the next action is safe and scoped.
6. Do not treat fixture-only tests as proof that a real paper's references or
   claims have been externally verified.

## Generic Paper Bootstrap

For a manuscript repository that only has `.tex` and `.bib`, create starter
artifacts. Prefer `paper-audit` first because it also writes the report and
resolver work items:

```bash
refgate paper-audit --tex MANUSCRIPT_TEX --bib PAPER_BIB --lock REFGATE_LOCK_JSON --claims REFGATE_CLAIMS_TSV --report REFGATE_AUDIT_MD --resolver-output REFGATE_QUERIES_JSON --next-plan-output .refgate/next_plan.json --submission --json
refgate bootstrap-paper --tex MANUSCRIPT_TEX --bib PAPER_BIB --lock-output REFGATE_LOCK_JSON --claims-output REFGATE_CLAIMS_TSV --json
refgate resolver-assist --lock REFGATE_LOCK_JSON --output REFGATE_QUERIES_JSON --json
```

`paper-audit` is the preferred first pass for ordinary paper repos: it creates
missing starter artifacts, updates claim stubs, writes resolver work items, runs
the audit, and writes the Markdown report. The starter lockfile is intentionally
blocking until every entry has official export provenance, verified manual
fallback, or arXiv fallback provenance.

For reference provenance, prefer the commands embedded in the
`RESOLVE_REFERENCE_PROVENANCE` action:

- `reference_check_command`: reviewed offline path using saved official HTML and
  reviewed BibTeX inputs.
- `live_reference_check_command`: opt-in live lookup path.
- `fixture_html_dir`, `fixture_html_naming`, and `reviewed_bibtex_dir`: where to
  place saved publisher HTML and reviewed fallback BibTeX.

Inspect follow-up actions without executing them:

```bash
refgate run-next --from PAPER_AUDIT_OUTPUT_JSON --json
refgate run-next --from PAPER_AUDIT_OUTPUT_JSON --output-plan .refgate/next_plan.json --json
refgate run-summary --input .refgate/next_plan.json --json
```

Read the top-level `recommended_next` field and each action's `agent_hint`
before executing. They explain whether the next command is ready, blocked by
missing reviewed inputs, or gated by network/write/human-review permissions.

Only execute `run-next --execute` when the action metadata and user intent allow
it. Enable `--allow-network`, `--allow-writes`, or `--allow-human-review` only
for the corresponding action types that are safe in the current manuscript repo.
For dogfood or meta-harness loops, write a run log and summarize it:

```bash
refgate run-next --from PAPER_AUDIT_OUTPUT_JSON --execute --write-run-log .refgate/next_run_log.json --json
refgate run-summary --input .refgate/next_plan.json --input .refgate/next_run_log.json --json
```

## Reference Checks

After changing `.bib` or the lockfile:

```bash
refgate audit-bib --bib PAPER_BIB --lock REFGATE_LOCK_JSON --submission --json
```

For real provenance review, use `reference-check` with reviewed fixture files or
explicit live sources. Keep official record verification and official BibTeX
export verification separate:

```bash
refgate reference-check --lock REFGATE_LOCK_JSON --candidate-dir CANDIDATE_DIR --official-bibtex-dir OFFICIAL_BIBTEX_DIR --write-lock REFGATE_LOCK_JSON --json
refgate reference-check --lock REFGATE_LOCK_JSON --fixture-html-dir OFFICIAL_HTML_DIR --source acm --bibtex-dir REVIEWED_FALLBACK_BIBTEX_DIR --write-lock REFGATE_LOCK_JSON --fallback-reason "Reviewed saved official HTML; manual BibTeX fallback retained because no official BibTeX endpoint was verified." --json
refgate reference-check --lock REFGATE_LOCK_JSON --source arxiv --cache-root .refgate/cache --citation-key CITATION_KEY --fetch-official-bibtex --write-lock REFGATE_LOCK_JSON --live --json
refgate monitor-official-records --lock REFGATE_LOCK_JSON --json
refgate sync-bibtex --bib PAPER_BIB --lock REFGATE_LOCK_JSON --json
```

If live lookup fails because a publisher blocks automated fetches, use the
`ADD_OFFICIAL_HTML_FIXTURE` action. Save the official record HTML as
`citationkey.source.html` or `citationkey.html`, then rerun the action command.
This verifies the official record without pretending that manual BibTeX is an
official export.

Before final handoff:

```bash
refgate audit --tex MANUSCRIPT_TEX --bib PAPER_BIB --lock REFGATE_LOCK_JSON --claims REFGATE_CLAIMS_TSV --frozen --submission --report REFGATE_AUDIT_MD --json
refgate export-handoff --bib PAPER_BIB --lock REFGATE_LOCK_JSON --output REFGATE_HANDOFF_JSON --submission --json
```

## Claim Evidence

Use evidence commands only to propose evidence. Do not auto-mark claims as
checked.

```bash
refgate validate-source-text --text SOURCE_TEXT_OR_PDF --json
refgate check-source-titles --lock REFGATE_LOCK_JSON --source-map REFGATE_SOURCE_MAP_TSV --json
refgate download-sources --lock REFGATE_LOCK_JSON --source-dir SOURCES_DIR --json
refgate download-sources --lock REFGATE_LOCK_JSON --source-dir SOURCES_DIR --citation-key CITATION_KEY --live --json
refgate evidence-suggest-bundle --claims REFGATE_CLAIMS_TSV --text SOURCE_TEXT_OR_PDF --output SUGGESTED_CLAIMS_TSV --json
refgate export-review-bundle --tex MANUSCRIPT_TEX --bib PAPER_BIB --lock REFGATE_LOCK_JSON --claims REFGATE_CLAIMS_TSV --source-dir SOURCES_DIR --output .refgate/codex_review_bundle.json --markdown .refgate/codex_review_bundle.md --json
refgate import-review --claims REFGATE_CLAIMS_TSV --review .refgate/codex_review_result.jsonl --output REFGATE_CLAIMS_REVIEWED_TSV --json
refgate claim-consistency --claims SUGGESTED_CLAIMS_TSV --submission --json
refgate claim-report --claims SUGGESTED_CLAIMS_TSV --output REFGATE_CLAIM_REVIEW_MD --json
```

When using source files, do not stop at claim overlap. The mapped PDF/text
source must also have a first-page title that matches the lockfile/BibTeX
title. `paper-audit --source-dir` runs this gate automatically; use
`check-source-titles` directly when auditing an existing source map.

For Codex-assisted claim review, export a review bundle after source mapping.
The bundle includes multiple deterministic evidence candidates per mapped source;
increase `--max-candidates-per-source` when the first candidate is title-like or
too short. Read each claim against the mapped source text/PDF, then write one
JSON object per claim to `.refgate/codex_review_result.jsonl`. Use
`import-review` to create a reviewed claim TSV. By default imported supported
claims remain `needs_review`; use `--allow-checked` only when the user has
explicitly approved final claim status, and never mark weak abstract/metadata
evidence as checked.

For scanned or image-only PDFs, Refgate creates a deterministic vision handoff
plan but does not send images anywhere:

```bash
refgate vision-extract-plan --pdf SCANNED_SOURCE_PDF --citation-key CITATION_KEY --image-dir RENDERED_PAGE_IMAGE_DIR --output .refgate/vision_extract_plan.json --json
```

Use a vision-capable Codex session to transcribe the listed page images, save a
reviewed transcript as source text, then rerun source mapping and claim checks.
Transcribe only visible text, preserve page labels, mark illegible spans, and
report the output as a reviewed transcript rather than an official source export.

## Live And Fixture Checks

Default Refgate tests and ordinary bootstrap commands are network-free. That
does not mean reference verification is approximate; it means regression tests
are deterministic. When the user asks for a real-paper dogfood loop, meta
harness, or verification/fix loop, run both layers:

1. Network-free regression gates: pytest, fixture matrix, CLI smoke, publish
   hygiene, and deterministic audit commands.
2. Real-paper verification gates: opt-in live lookup with `--live` where needed,
   cache or manifest capture, `reference-check` against reviewed candidates or
   official BibTeX, and `claim-source-check` against actual extracted source
   text/PDF maps.

If network access is blocked by the environment, request permission instead of
silently substituting fixture-only checks. Fixture-only dogfood proves the tool
works; it does not prove that the current manuscript's references and claims are
externally verified.

For live dogfood, start with a small probe such as `--max-queries 3` or
`--max-entries 3` before a full batch. If the probe hits rate limits or hangs,
report that as a live verification blocker and avoid claiming external
verification for unqueried references.

Use live smoke only when explicitly requested:

```bash
refgate live-smoke --source arxiv --title "Attention Is All You Need" --live --json
refgate live-smoke-suite --queries REFGATE_QUERIES_JSON --source arxiv --cache-root .refgate/cache --max-queries 3 --prefer-cache --min-interval-seconds 3 --retry 2 --retry-after-seconds 10 --write-manifest .refgate/cache_manifest.reviewed.json --live --json
```

## Next Actions

Use `next_actions` as the handoff contract. Common action kinds:

- `reference_provenance`: collect candidate records or run explicit live
  lookup.
- `official_html_fixture_input`: save reviewed publisher HTML when live fetch is
  blocked.
- `source_download`: write citation-key named PDFs only when `--live` is
  approved.
- `codex_claim_review_bundle`: export claim/source bundles for Codex review.
- `claim_evidence_review`: inspect evidence and keep unsupported claims blocked.
- `source_integrity_review`: resolve source-title mismatches before final
  submission.

## Rules

- Never label generated or manually normalized BibTeX as official export.
- Discovery sources are not final authorities by default.
- Abstracts, summaries, and metadata snippets are weak evidence only; they must
  not make a claim `checked`.
- Live network checks are opt-in only.
- Evidence suggestions may include PDF page labels, but they still require
  human review before a claim is marked checked.
- Official BibTeX is matched by citation-key filename first and exact normalized
  title second; title or DOI mismatches are blocking.
- Official/arXiv metadata and mapped PDF first-page titles must agree, or the
  mismatch remains a source integrity blocker until reviewed.
- If a Refgate command returns `ok=false`, report the blocker instead of
  claiming completion.
- Keep private manuscripts, private reference-manager exports, local absolute
  paths, and credentials out of public plugin, repo, and audit artifacts.

## Reporting

When reporting Refgate work, include changed manuscript, `.bib`, lockfile, claim
TSV, report files, commands run, `ok=true` or blockers, provenance source kinds,
and remaining human review items. For public repos, run `publish-check` and a
plain text hygiene scan before finalizing.
