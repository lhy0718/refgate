---
name: refgate
description: Use when working on academic manuscripts, bibliographies, BibTeX, citation claims, source evidence, source PDFs, or reference verification with the Refgate CLI.
metadata:
  short-description: Gate manuscript references with Refgate
---

# refgate

## When to use

Use this skill when a task touches academic manuscript references, BibTeX,
citation keys, citation-bearing claims, source evidence, or reference handoff
artifacts.

## Goal

Run Refgate as a deterministic evidence gate for manuscript references and
citation-bearing claims. A default run should produce actionable triage
artifacts and clear blockers, not silently perform live lookup, source
downloads, claim approvals, or manuscript edits.

Refgate is CLI-first. Treat JSON CLI outputs, `refgate.lock.json`,
`refgate_claims.tsv`, source maps, review bundles, and Markdown reports as the
source of truth. Do not invent an MCP or server workflow for core verification.

## Procedure

1. Identify the manuscript `.tex` file and bibliography `.bib` file.
2. Locate a usable Refgate CLI.
3. Run the one-command triage pass for ordinary paper repositories.
4. Read the generated audit report, claim table, resolver queries, and next
   plan before editing bibliography or claim artifacts.
5. Execute only deterministic follow-up commands that are already allowed by
   the user's request and action metadata.
6. Stop at opt-in gates for live network checks, source downloads, final claim
   approval, and manuscript or BibTeX edits unless the user explicitly requests
   that step.
7. Report `ok=false` as "audit completed with blockers" when artifacts were
   generated successfully; do not call it a command failure.

## Command Form

Use the installed command when available. Verify it with `refgate --help` if the
environment is unclear:

```bash
refgate ...
```

If `refgate` is not on `PATH`, check common local checkout entry points before
giving up:

```bash
$HOME/Refgate/.venv/bin/refgate --help
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
3. Read `ok`, `blocking_issues`, `warnings`,
   `accepted_provenance_notes`, and `next_actions` from JSON output before
   editing bibliography or claim artifacts.
4. Execute only deterministic follow-up commands that are allowed by the user's
   request and action metadata. Network work requires explicit opt-in.
5. If a command returns `ok=false`, report the blocker and continue the
   correction loop only when the next action is safe and scoped.
6. Treat `warnings` as unresolved review work. Treat
   `accepted_provenance_notes` as verified provenance records, such as reviewed
   arXiv fallback or reviewed DOI absence. Verified arXiv fallback can still
   produce an `ARXIV_OFFICIAL_RECORD_MONITOR_REQUIRED` warning; that warning
   means the entry should be refreshed against official venue records before
   submission.
7. Do not treat fixture-only tests as proof that a real paper's references or
   claims have been externally verified.

## One-Command Triage Pass

For a normal paper repository, a "run Refgate" request should perform the full
deterministic triage loop:

1. Run `paper-audit` with paths for the lockfile, claim TSV, audit report,
   resolver output, and next-plan output.
2. Read the JSON result and the generated Markdown/TSV artifacts.
3. Run `run-next` on the generated next plan in dry-run mode and, when useful,
   write a compact `run-summary` Markdown file.
4. Report the generated files, phase statuses, blockers, warnings,
   `accepted_provenance_notes`, and recommended next action.

This default loop may create Refgate audit artifacts inside the manuscript
repository, but it must not use the network, download sources, mark claims as
checked, or rewrite manuscript/BibTeX files.

Example:

```bash
refgate paper-audit --tex MANUSCRIPT_TEX --bib PAPER_BIB --lock .refgate/refgate.lock.json --claims .refgate/refgate_claims.tsv --report .refgate/refgate_audit.md --resolver-output .refgate/refgate_queries.json --next-plan-output .refgate/next_plan.json --submission --json
refgate run-next --from .refgate/next_plan.json --json
refgate run-summary --input .refgate/next_plan.json --markdown .refgate/next_summary.md --json
```

If `paper-audit` returns `ok=false` because starter provenance or claim stubs
need review, treat the run as successful triage with blockers. The presence of
blocking issues is the gate result, not an execution failure.

## Post-Audit Fix Guidance

After every `paper-audit`, `run-next`, or `run-summary` pass, include a
reader-facing "What to modify next" section. This section should translate
Refgate blockers into concrete manuscript work without pretending that gated
actions have already been approved or completed.

Group the guidance by edit surface:

- Manuscript prose: source file and line when available, citation key or claim
  row, why the claim is unsupported or too broad, and the safest wording or
  deletion scope to consider.
- BibTeX and reference provenance: citation key, missing or weak provenance
  type, official export/manual fallback/arXiv fallback action needed, and
  whether `references.bib` should wait for provenance before changing.
- Claim evidence artifacts: claim row, mapped source requirement, review bundle
  or source-map step needed, and whether source-evidence review is required before marking
  anything `checked`.
- Refgate artifacts: lockfile, claim TSV, resolver output, next plan, source
  map, or review bundle updates that are safe to make before manuscript edits.
- Opt-in actions not run: live lookup, source downloads, final claim approval,
  or direct manuscript/BibTeX rewrites that require explicit approval.

Do not merely repeat raw blocker names such as `claim_unchecked` or
`missing_bibtex_provenance`. Explain the paper consequence and the next safe
action. If the correct next action is evidence or provenance review, say that no
manuscript or BibTeX edit is justified yet.

## Opt-In Boundaries

Do not run these steps as part of the default triage pass:

- live network `reference-check`, `live-smoke`, or `monitor-official-records`;
- source PDF/text downloads, especially `download-sources --live`;
- final claim status changes such as marking claims `checked`;
- direct edits to `main.tex`, `references.bib`, source maps, or lockfile
  provenance fields beyond the explicitly requested Refgate artifact creation.

Run them only when the user explicitly asks for that class of work or when the
current action metadata is ready and the required allow flags are intentionally
set:

```bash
refgate run-next --from .refgate/next_plan.json --command-field reference_check_command --allow-writes --allow-review --max-actions 1 --execute --write-run-log .refgate/next_run_log.json --json
refgate run-next --from .refgate/next_plan.json --command-field live_reference_check_command --allow-network --allow-writes --allow-review --max-actions 1 --execute --write-run-log .refgate/next_run_log.json --json
```

When applying Refgate findings to manuscript prose or BibTeX, first propose the
exact changes or patch scope, then edit only after the user has requested
application. After any edit, rerun `latexmk`, `pdftotext`, Refgate audit, and
layout/log checks appropriate to the paper.

## Generic Paper Bootstrap

For a manuscript repository that only has `.tex` and `.bib`, create starter
artifacts. Prefer `paper-audit` first because it also writes the report and
resolver work items:

```bash
refgate paper-audit --tex MANUSCRIPT_TEX --bib PAPER_BIB --lock REFGATE_LOCK_JSON --claims REFGATE_CLAIMS_TSV --report REFGATE_AUDIT_MD --resolver-output REFGATE_QUERIES_JSON --next-plan-output .refgate/next_plan.json --submission --json
refgate paper-audit --tex MAIN_TEX --extra-tex SUPPLEMENTARY_TEX --bib PAPER_BIB --lock REFGATE_LOCK_JSON --claims REFGATE_CLAIMS_TSV --submission --json
refgate bootstrap-paper --tex MANUSCRIPT_TEX --bib PAPER_BIB --lock-output REFGATE_LOCK_JSON --claims-output REFGATE_CLAIMS_TSV --json
refgate resolver-assist --lock REFGATE_LOCK_JSON --output REFGATE_QUERIES_JSON --json
```

`paper-audit` is the preferred first pass for ordinary paper repos: it creates
missing starter artifacts, updates claim stubs, writes resolver work items, runs
the audit, and writes the Markdown report. The starter lockfile is intentionally
blocking until every entry has official export provenance, arXiv fallback
provenance, or a manual fallback explicitly allowed by the lockfile audit
policy. For submission workflows that require publisher or venue BibTeX, set
`audit_policy.allow_manual_fallback` to `false`; Refgate will then block
publisher-metadata manual fallback entries until they are replaced by
`official_export` provenance.
If the root manuscript uses `\input{...}` or `\include{...}`, Refgate resolves
those children relative to the root TeX directory. Use the source-file and line
hints in generated claim rows and reports when navigating the manuscript.
If main and supplementary files are standalone roots, repeat `--extra-tex` on
`paper-audit` or `claim-stubs`; citation consistency and claim-stub generation
use the union of all supplied TeX source graphs.

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
refgate run-summary --input .refgate/next_plan.json --markdown .refgate/next_summary.md --json
```

Read the top-level `recommended_next` field and each action's `agent_hint`
before executing. They explain whether the next command is ready, blocked by
missing reviewed inputs, or gated by network/write/review permissions.

Only execute `run-next --execute` when the action metadata and user intent allow
it. Enable `--allow-network`, `--allow-writes`, or `--allow-review` only
for the corresponding action types that are safe in the current manuscript repo.
For dogfood or meta-harness loops, write a run log and summarize it:

```bash
refgate run-next --from PAPER_AUDIT_OUTPUT_JSON --execute --write-run-log .refgate/next_run_log.json --json
refgate run-summary --input .refgate/next_plan.json --input .refgate/next_run_log.json --markdown .refgate/next_summary.md --json
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
refgate scholar-official-bridge --lock REFGATE_LOCK_JSON --scholar-html-dir .refgate/scholar-html --candidate-dir .refgate/reference-candidates --live-scholar --live-official --write-candidates --write-lock REFGATE_LOCK_JSON --fetch-official-bibtex --json
refgate sync-bibtex --bib PAPER_BIB --lock REFGATE_LOCK_JSON --json
```

If live lookup fails because a publisher blocks automated fetches, use the
`ADD_OFFICIAL_HTML_FIXTURE` action. Save the official record HTML as
`citationkey.source.html` or `citationkey.html`, then rerun the action command.
This verifies the official record without pretending that manual BibTeX is an
official export.
If `ADD_OFFICIAL_BIBTEX_FIXTURE` includes
`manual_official_bibtex_instructions`, give the user the listed official record
or export URL, accepted fixture filenames, and "do not use" list. Ask them to
paste or save only the publisher or venue BibTeX export; Google Scholar,
Crossref-generated, handwritten, or model-generated BibTeX must not be recorded
as `official_export`.
If `scholar-official-bridge` returns `SCHOLAR_CAPTCHA_REVIEW_REQUIRED`, do not
try to bypass or solve CAPTCHA automatically. Open the provided Scholar URL in a
browser, then either save the resolved result HTML to the reported
`<citation_key>.google_scholar.html` path or paste one official venue/publisher
URL per line into the reported `<citation_key>.official_urls.txt` path. Rerun
the bridge so Refgate can fetch official-source records and continue through
`reference-check`.

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
refgate check-source-titles --lock REFGATE_LOCK_JSON --source-map REFGATE_SOURCE_MAP_TSV --title-review SOURCE_TITLE_REVIEW_JSONL --json
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
`check-source-titles` directly when auditing an existing source map. When an
official record title and source first-page title intentionally differ, pass a
reviewed source-title JSONL file with `--title-review`; accepted lines must
include the current `citation_key`, `decision`, `expected_title`, and
`source_title`, with optional `source_text`, `reviewer`, and `notes`.
If a PDF-backed source check returns `PDF_TEXT_EXTRA_MISSING`, rerun in a
runtime with `pypdf` installed or install the extra with
`python -m pip install "refgate[pdf]"`.

For Codex-assisted claim review, export a review bundle after source mapping.
The bundle includes multiple deterministic evidence candidates per mapped source;
increase `--max-candidates-per-source` when the first candidate is title-like or
too short. Treat `confidence=low` candidates as review warnings, not support.
Read each claim against the mapped source text/PDF, then write one
JSON object per claim to `.refgate/codex_review_result.jsonl`. Use
`import-review` to create a reviewed claim TSV. By default imported supported
claims remain `needs_review`; use `--allow-checked` only when the user has
explicitly approved final claim status, and never mark weak abstract/metadata
evidence as checked.
Prefer full-source body passages over title-like, abstract-like, or
metadata-like snippets when writing Codex review JSONL. Treat the main
`refgate_audit.md` `Claim Source Check` section as a compact blocker index, then
open `refgate_claim_review.md` or the Codex review bundle for the evidence
queue.

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
refgate live-smoke-suite --queries REFGATE_QUERIES_JSON --per-query-source --cache-root .refgate/cache --max-queries 3 --live --json
refgate live-smoke-suite --queries REFGATE_QUERIES_JSON --source arxiv --cache-root .refgate/cache --manifest .refgate/cache_manifest.reviewed.json --json
```

Use `--per-query-source` for mixed venue batches from resolver-assist output.
It reads `source`, `live_smoke_source`, or the first `recommended_sources`
entry from each query/work item, with `--source` as fallback. `--manifest`
comparison is network-free and does not require `--live`.
`--write-manifest` writes only after every selected live query succeeds; if a
live endpoint returns an error or no candidates, report the blocker and rerun a
smaller or cached probe before preserving reviewed live evidence.
Read `failure_code`, `failure_summary`, and `next_actions` on failed live
checks. For `LIVE_SMOKE_RATE_LIMITED`, execute the suggested slower
single-citation retry or report the rate-limit blocker; do not claim external
verification from a partial live-smoke suite.

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
  submission, or record an accepted official/source title mismatch with
  `--title-review` after provenance review.

## Rules

- Never label generated or manually normalized BibTeX as official export.
- Discovery sources are not final authorities by default.
- Abstracts, summaries, and metadata snippets are weak evidence only; they must
  not make a claim `checked`.
- Title-like or abstract-like evidence candidates are review hints; prefer
  fuller body passages for support decisions.
- Live network checks are opt-in only.
- Evidence suggestions may include PDF page labels, but they still require
  source-evidence review before a claim is marked checked.
- Official BibTeX is matched by citation-key filename first and exact normalized
  title second; when the authority has a DOI, a missing or mismatched fixture
  DOI is blocking.
- Official/arXiv metadata and mapped PDF first-page titles must agree, or the
  mismatch remains a source integrity blocker until reviewed.
- If a Refgate command returns `ok=false`, report the blocker instead of
  claiming completion.
- Keep private manuscripts, private reference-manager exports, local absolute
  paths, and credentials out of public plugin, repo, and audit artifacts.

## Reporting

When reporting Refgate work, include changed manuscript, `.bib`, lockfile, claim
TSV, report files, commands run, `ok=true` or blockers, provenance source kinds,
and remaining review items. For public repos, run `publish-check` and a
plain text hygiene scan before finalizing.

## Output Format

- Commands run
- Artifacts created or updated
- `ok` status and phase statuses
- Blocking issues
- Warnings
- Accepted provenance notes
- Recommended next action
- What to modify next, grouped by manuscript, BibTeX/provenance, claim evidence,
  and Refgate artifacts, with file/line or citation-key references where
  available
- Actions deliberately not run because they require live network, source
  download, review, or manuscript/BibTeX edit approval

## Common Failure Modes

- Treating `ok=false` from a successful `paper-audit` as a shell failure rather
  than a blocker report.
- Running live lookup or source downloads without explicit opt-in.
- Marking claims checked from abstracts, summaries, metadata, or title-like
  snippets.
- Labeling generated or manually normalized BibTeX as an official export.
- Applying Refgate-suggested manuscript or BibTeX changes without preserving
  the author's claim boundary and rerendering the paper.
- Reporting fixture-only checks as external reference verification.

## Update Rule

Update this skill when Refgate adds new CLI actions, new action metadata fields,
or new safety gates around live lookup, source downloads, claim approval,
BibTeX provenance, or manuscript patch application.
