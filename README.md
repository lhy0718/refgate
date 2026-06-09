# Refgate

Refgate is a deterministic reference gate for academic manuscripts. It verifies
paper records, BibTeX provenance, and citation audit status before an agent or
author edits a bibliography.

The current version is fixture-first and network-free by default.

Refgate is intentionally CLI-first. The core verification logic should stay in
the CLI, lockfile, and report artifacts so it remains reproducible from shell,
CI, and agent sessions. Agent-specific behavior belongs in Skills or project
instructions that call the CLI.

## What Works

- JSON-first CLI surface
- Dataclass models for paper queries, candidate records, resolver decisions,
  lockfile entries, and audit issues
- `paper-audit`, `bootstrap-paper`, `bootstrap-lock`, `resolver-assist`, `discover`,
  `fetch-bibtex`, `normalize-bibtex`, `claim-stubs`, `claim-report`,
  `evidence-suggest`, `evidence-suggest-bundle`, `claim-consistency`, `audit-claims`, `audit`,
  `export-review-bundle`, `import-review`, `export-handoff`, `auth`,
  `validate-source-text`, `check-source-titles`, `download-sources`,
  `sync-bibtex`, `publish-check`, `paper-agents-template`, and `render-report`
  command surface
- `run-next` planner/executor for structured `next_actions` with dry-run by
  default and explicit gates for network, file writes, and human-review actions
- `run-summary` for compact next-action manifest review after dogfood or
  meta-harness runs
- Deterministic resolver for official records, arXiv fallback, and ambiguous
  conflicts
- BibTeX parser for audit/provenance checks, including nested brace, quoted
  field values, string macros, comments, and simple macro values
- Frozen bibliography, manuscript citation, and claim-to-source audit against a
  Refgate lockfile
- Claim TSV stub generation and Markdown claim review reports
- Extracted-text evidence suggestions for citation-bearing claims, including
  page-aware locations for extractable PDFs
- Direct claim-to-source checks from citation-key to source text/PDF maps
- Citation-key source PDF download planning, with live downloads behind an
  explicit `--live` flag
- Claim evidence-kind gate so abstracts, summaries, and metadata snippets can
  suggest review items but cannot make a claim `checked`
- Source bundle evidence suggestions across multiple text/PDF inputs
- Deterministic claim-consistency warnings for low overlap, non-final status,
  and over-strong claim wording that needs careful support
- Codex review bundle export/import for claim-to-source review assistance,
  without making Codex part of the deterministic core
- Direct reference checks from fixture/live candidate records, with optional
  official BibTeX lockfile provenance updates
- Multi-page public PDF fixture coverage for optional text extraction
- Crossref DOI metadata adapter plus Semantic Scholar/OpenAlex discovery-only
  adapters
- Local auth status/set/setup/doctor flow for Semantic Scholar access values
  and Crossref/OpenAlex mailto values, including an interactive terminal
  selector when available
- Fixture-backed ACL Anthology adapter for official `.bib` endpoint handling
- Fixture-backed NeurIPS and ICLR proceedings adapters for official BibTeX link
  discovery
- Fixture-backed generic official venue adapters for PMLR, ACM, CVF Open
  Access, JMLR, Nature Portfolio, Wiley, SAGE, Taylor & Francis, IEEE,
  Springer, Elsevier, USENIX, AAAI, Oxford Academic, Cambridge Core, PNAS,
  Science, Frontiers, MDPI, LIPIcs, and OpenReview-style records, including
  URL-backed discovery from lockfile/BibTeX `url` fields when live lookup is
  explicitly enabled
- Fixture-backed arXiv adapter for exact ID lookup, exact normalized-title
  confirmation, version/accessed-date preservation, and manual normalized
  BibTeX fallback
- Public ten-paper fixture matrix validator
- Opt-in live smoke command with cache checksum manifest comparison
- Cache manifest write mode for reviewed live-smoke evidence
- Batch live-smoke suite command for reviewed cache evidence generation
- Reviewed-cache-first live smoke, retry, and interval controls for rate limits
- Standalone handoff export in Refgate JSON or CSL-JSON format
- End-to-end `paper-audit` command for the common `.tex` + `.bib` manuscript
  repository path, including optional source text/PDF directory mapping for
  claim evidence suggestions
- Multi-file TeX support for `\input{...}` and `\include{...}` in
  `paper-audit`, `audit`, `claim-stubs`, and `export-review-bundle`, with
  source-file and line hints in generated claim TSV rows
- Expanded CSL-JSON field mapping for common BibTeX metadata
- Generic paper repo instruction template generator
- CI workflow for pytest and compile checks
- Repo-local Codex plugin package and marketplace catalog
- Claude Code command pack, project guidance, and opt-in hook example
- Plugin icon and CLI preview assets for broader catalog distribution
- Fixture tests that run without network

## Install For Local Development

```bash
cd ~/Refgate
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

To build a distribution archive locally:

```bash
python -m build
```

## CLI Examples

```bash
python -m refgate bootstrap-paper --tex path/to/main.tex --bib path/to/references.bib --lock-output path/to/refgate.lock.json --claims-output path/to/refgate_claims.tsv --json
python -m refgate paper-audit --tex path/to/main.tex --bib path/to/references.bib --lock path/to/refgate.lock.json --claims path/to/refgate_claims.tsv --report path/to/refgate_audit.md --resolver-output path/to/refgate_queries.json --next-plan-output path/to/.refgate/next_plan.json --submission --json
python -m refgate paper-audit --tex path/to/main.tex --bib path/to/references.bib --lock path/to/refgate.lock.json --claims path/to/refgate_claims.tsv --source-dir path/to/sources --source-map-output path/to/refgate_source_map.tsv --claim-review-output path/to/refgate_claim_review.md --submission --json
python -m refgate resolver-assist --lock path/to/refgate.lock.json --output path/to/refgate_queries.json --json
python -m refgate resolve --query tests/fixtures/official_query.json --candidates tests/fixtures/official_candidates.json --json
python -m refgate audit-bib --bib tests/fixtures/sample.bib --lock tests/fixtures/refgate.lock.json --json
python -m refgate audit --tex tests/fixtures/manuscript.tex --bib tests/fixtures/sample.bib --lock tests/fixtures/refgate.lock.json --claims tests/fixtures/claims_checked.tsv --frozen --submission --report examples/reference-fixture/sample_refgate_audit.md --json
python -m refgate claim-stubs --tex tests/fixtures/manuscript_claims.tex --output examples/reference-fixture/refgate_claims.tsv --json
python -m refgate claim-report --claims tests/fixtures/claims_unchecked.tsv --output examples/reference-fixture/refgate_claim_review.md --json
python -m refgate claim-source-check --claims tests/fixtures/claims_unchecked.tsv --source-map path/to/source_map.tsv --output .tmp/refgate_claims_review.tsv --rerank semantic-lite --submission --json
python -m refgate claim-source-check --claims tests/fixtures/claims_unchecked.tsv --source-map path/to/source_map.tsv --include-consistency --include-issues --json
python -m refgate evidence-suggest --claims tests/fixtures/claims_unchecked.tsv --text tests/fixtures/source_excerpt.txt --output .tmp/refgate_claims_suggested.tsv --json
python -m refgate evidence-suggest-bundle --claims tests/fixtures/claims_unchecked.tsv --text tests/fixtures/source_excerpt.txt --output .tmp/refgate_claims_suggested.tsv --json
python -m refgate claim-consistency --claims tests/fixtures/claims_checked.tsv --json
python -m refgate validate-source-text --text tests/fixtures/source_excerpt.txt --json
python -m refgate check-source-titles --lock path/to/refgate.lock.json --source-map path/to/source_map.tsv --json
python -m refgate check-source-titles --lock path/to/refgate.lock.json --source-map path/to/source_map.tsv --title-review path/to/source_title_review.jsonl --json
python -m refgate export-review-bundle --tex path/to/main.tex --bib path/to/references.bib --lock path/to/refgate.lock.json --claims path/to/refgate_claims.tsv --source-dir path/to/sources --output path/to/.refgate/codex_review_bundle.json --markdown path/to/.refgate/codex_review_bundle.md --json
python -m refgate import-review --claims path/to/refgate_claims.tsv --review path/to/.refgate/codex_review_result.jsonl --output path/to/refgate_claims.reviewed.tsv --json
python -m refgate download-sources --lock path/to/refgate.lock.json --source-dir path/to/sources --json
python -m refgate download-sources --lock path/to/refgate.lock.json --source-dir path/to/sources --citation-key debenedetti2024agentdojo --live --json
python -m refgate vision-extract-plan --pdf path/to/scanned.pdf --citation-key citationkey2026 --image-dir path/to/rendered-pages --output .refgate/vision_extract_plan.json --json
python -m refgate export-handoff --bib tests/fixtures/sample.bib --lock tests/fixtures/refgate.lock.json --output .tmp/refgate_handoff.json --submission --json
python -m refgate export-handoff --bib tests/fixtures/sample.bib --lock tests/fixtures/refgate.lock.json --output .tmp/references.csl.json --format csl-json --json
python -m refgate auth doctor --json
python -m refgate reference-check --lock refgate.lock.json --candidate-dir path/to/candidates --official-bibtex-dir path/to/official-bibtex --write-lock refgate.lock.json --json
python -m refgate reference-check --lock refgate.lock.json --fixture-html-dir path/to/official-html --source acm --bibtex-dir path/to/manual-bibtex --write-lock refgate.lock.json --fallback-reason "Reviewed saved official HTML; manual BibTeX fallback retained because no official BibTeX endpoint was verified." --json
python -m refgate reference-check --lock refgate.lock.json --fixture-html-dir path/to/official-html --source aaai --official-bibtex-dir path/to/official-bibtex --write-lock refgate.lock.json --json
python -m refgate reference-check --lock refgate.lock.json --source iclr --cache-root .refgate/cache --citation-key citationkey2026 --fetch-official-bibtex --write-lock refgate.lock.json --live --json
python -m refgate sync-bibtex --bib references.bib --lock refgate.lock.json --json
python -m refgate sync-bibtex --bib references.bib --lock refgate.lock.json --output references.refgate.bib --json
python -m refgate monitor-official-records --lock refgate.lock.json --json
python -m refgate monitor-official-records --lock refgate.lock.json --cache-root .refgate/cache --write-lock refgate.lock.json --live --json
python -m refgate run-next --from path/to/paper_audit.json --json
python -m refgate run-next --from path/to/paper_audit.json --output-plan .refgate/next_plan.json --json
python -m refgate run-next --from .refgate/next_plan.json --command-field reference_check_command --allow-writes --allow-human-review --json
python -m refgate run-next --from path/to/paper_audit.json --allow-writes --max-actions 1 --execute --json
python -m refgate run-next --from path/to/paper_audit.json --allow-writes --max-actions 1 --execute --write-run-log .refgate/next_run_log.json --json
python -m refgate run-summary --input .refgate/next_plan.json --input .refgate/next_run_log.json --markdown .refgate/next_summary.md --json
python -m refgate run-summary --input .refgate/next_plan.json --markdown .refgate/next_summary.md --json
python -m refgate fixture-matrix --queries tests/fixtures/reference_priority_queries.json --candidates tests/fixtures/reference_priority_candidates.json --json
python -m refgate live-smoke --cache-root .refgate/cache --manifest tests/fixtures/cache_manifest.example.json --json
python -m refgate live-smoke --cache-root .refgate/cache --write-manifest .refgate/cache_manifest.reviewed.json --json
python -m refgate live-smoke-suite --queries path/to/refgate_queries.json --source arxiv --cache-root .refgate/cache --max-queries 3 --write-manifest .refgate/cache_manifest.reviewed.json --live --json
python -m refgate live-smoke-suite --queries path/to/refgate_queries.json --per-query-source --cache-root .refgate/cache --max-queries 3 --live --json
python -m refgate live-smoke-suite --queries path/to/refgate_queries.json --source arxiv --cache-root .refgate/cache --prefer-cache --min-interval-seconds 3 --retry 2 --retry-after-seconds 10 --live --json
python -m refgate live-smoke-suite --queries path/to/refgate_queries.json --source arxiv --cache-root .refgate/cache --manifest .refgate/cache_manifest.reviewed.json --json
python -m refgate paper-agents-template --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --report refgate_audit.md --output AGENTS.refgate.md --json
python -m refgate publish-check --root . --json
python -m refgate render-report --lock tests/fixtures/refgate.lock.json --output examples/reference-fixture/sample_refgate_audit.md
```

`paper-audit` keeps its default JSON response compact for agent loops: resolver
work items are written to `--resolver-output`, and blocking issues are grouped
by code with citation-key samples. Add `--include-work-items` or
`--include-issues` when the full inline data is needed.
Unresolved bibliography warnings remain in `warnings`; verified provenance
records such as reviewed arXiv fallbacks or reviewed DOI absence are separated
into `accepted_provenance_notes` so agents do not treat them as new work.
Its `next_actions` field gives deterministic follow-up commands for the current
state, such as resolving reference provenance, adding citation-key named source
files, reviewing no-match claims, or exporting a handoff artifact after a clean
audit. Each action includes `kind`, `requires_human_review`, `writes_files`, and
`network_required` fields for agent execution planning.
For reference provenance, `paper-audit` also includes agent-ready follow-up
commands for both reviewed offline inputs and opt-in live lookup, including
`--fixture-html-dir` for saved official publisher pages.
Use `--next-plan-output` to save the first dry-run plan directly from
`paper-audit` without copying the JSON response to an intermediate file.
When `--source-dir` is provided, `paper-audit` builds a source map only from
`.txt` or `.pdf` files whose filename stem exactly matches a citation key, for
example `debenedetti2024agentdojo.pdf`. The generated source map stores
relative paths and then runs `claim-source-check` to fill review evidence
candidates. It still leaves claims in review status until a reviewer marks them
checked. When source evidence checking is active, `paper-audit` also writes a
claim review Markdown file by default, or to `--claim-review-output` when
provided; this report includes source-check queues for missing mapped sources
and mapped sources with no matching evidence block.
PDF extraction requires the optional `pypdf` dependency. If Refgate reports
`PDF_TEXT_EXTRA_MISSING`, install the PDF extra with
`python -m pip install "refgate[pdf]"` or use a runtime where that extra is
already available.
The same source mapping also runs a source-title gate: the first-page title
candidate from each mapped source file must match the lockfile/BibTeX title, or
submission mode blocks with `SOURCE_TITLE_MISMATCH`. Use `check-source-titles`
directly when you want to audit a reviewed source map without running the full
paper flow. If an official record and a mapped PDF/text source are intentionally
different because of an accepted publisher/arXiv metadata mismatch, keep the
gate blocking by default and pass a reviewed JSONL file with `--title-review`.
Each accepted line must name the citation key, accepted decision, current
lockfile title, and current first-page source title; stale or underspecified
reviews do not clear the blocker. Review paths may use the source-map label,
source-map path, an absolute path, or a cwd-relative path.
Use `download-sources` before source mapping when the lockfile contains a
deterministic official/arXiv/venue PDF location. Without `--live`, it only
returns a plan and follow-up action; with `--live`, it writes citation-key named
PDFs such as `debenedetti2024agentdojo.pdf` for later source-map review.
For multi-file manuscripts, the `--tex` root may include other files with
`\input{...}` or `\include{...}`. Refgate resolves those paths relative to the
root TeX directory, adds `.tex` when omitted, and records source-file/line hints
in generated claim rows. Missing includes block submission mode and warn in
non-submission mode.

`reference-check` and `claim-source-check` are for real manuscript verification,
not only tool regression tests. Use `reference-check` with reviewed candidate
records and official BibTeX files to fill lockfile provenance. Official BibTeX
files are matched by citation-key filename first and exact normalized title
second; title or DOI mismatches block lockfile updates. Use `claim-source-check`
with a TSV/JSON source map that links citation keys to extracted source text or
PDFs; it may fill evidence suggestions with overlap, coverage, matched terms,
missing terms, and page-aware source locations, but it leaves claims in
`needs_review` until a reviewer marks them `checked`. Add `--rerank
semantic-lite` to use deterministic phrase/coverage-aware reranking without
calling an external model.
`reference-check` also returns deterministic `next_actions` for missing
candidate files, low-confidence or preprint-only candidate review, live lookup
failures, missing BibTeX provenance inputs, and post-update bibliography audits.
When live lookup fails, it now suggests both a retry/cache path and a reviewed
official HTML fixture path for publishers that block automated fetches.
Publisher-specific actions may include `source_guidance` with reviewed fixture
filenames and known official export/PDF URL patterns. If an official BibTeX URL
is already known, Refgate suggests `FETCH_OFFICIAL_BIBTEX_EXPORT` before a
manual fallback; if that fetch fails, it suggests `ADD_OFFICIAL_BIBTEX_FIXTURE`
for an offline reviewed publisher export.
Use repeated `--citation-key` flags to limit live or write-lock work to a small
reviewed subset. Official venue sources such as `acm`, `ieee`, `springer`,
`elsevier`, `usenix`, `aaai`, `pmlr`, `oxford`, `cambridge`, `pnas`,
`science`, `frontiers`, `mdpi`, `lipics`, and `openreview` discover only from
record URLs already present in the lockfile query context or supplied as
preferred venue URLs; they do not promote discovery aggregators to final
authority records. If a publisher blocks live fetches, save the official record
HTML and pass `--fixture-html-dir`; Refgate looks for
`citationkey.source.html` or `citationkey.html` and parses it through the same
source adapter. When the selected official source exposes a BibTeX export URL
or publisher-provided inline BibTeX block, `--fetch-official-bibtex` fetches
that export through the source adapter and validates its title/DOI before
updating provenance. Fetch failures are reported as blocking issues rather than
silently downgrading generated/manual BibTeX to official export.
If a reviewed fallback file is supplied with `--fallback-reason`, it remains
manual fallback provenance even when the official record advertises a BibTeX
URL; submission audit will still block until that official export is fetched or
explicitly resolved.
Use `--official-bibtex-dir` for reviewed offline official-export fixtures, such
as `citationkey.SOURCE.bib`, `citationkey.source.bib`, or `citationkey.bib`.
Those files are accepted as `official_export` only when the selected authority
record advertises an official BibTeX URL and the fixture passes title/DOI
checks.
After lockfile provenance is filled, use `sync-bibtex` to produce an
agent-friendly synchronization plan or write a reviewed `.bib` output from the
lockfile canonical BibTeX text. It is network-free, JSON-first, dry-run by
default, and refuses to synthesize entries when the lockfile lacks canonical
BibTeX text. Written output preserves a blank line between BibTeX entries so
agents can review the candidate file before in-place replacement.
Use `monitor-official-records` on a lockfile to find arXiv fallback or
official-record-pending rows and generate targeted official-source
`reference-check` commands. It is network-free by default; add `--live` only
when you want Refgate to run those checks against opt-in live sources.
Use `run-next` to inspect these actions without executing them. It only executes
when `--execute` is present, and it skips actions unless the corresponding
`--allow-network`, `--allow-writes`, or `--allow-human-review` gate is enabled.
It also skips commands that still contain placeholders such as `PAPER_BIB`,
`SOURCES_DIR`, `OFFICIAL_BIBTEX_DIR`, or `REVIEWED_FALLBACK_BIBTEX_DIR` with
`skip_reason=input_required`; replace those with reviewed local paths before
execution.
Use `--command-field reference_check_command` when a previous `paper-audit`
action includes a reviewed follow-up command and the referenced official HTML /
BibTeX fixture directories have been populated.
Add `--output-plan` to preserve the dry-run decision manifest and
`--write-run-log` to preserve the actual execution result.
Read `recommended_next` and per-action `agent_hint` first when an agent needs a
compact explanation of the next command or the current blocker.
For publisher-specific reference actions, `run-next` preserves compact
`action_summary`, `official_bibtex_url`, and `source_guidance_summary` fields so
agents can see the fixture/export path without expanding the full action.
Use `run-summary` on those manifests to see only the failed, skipped, or
planned-but-not-executed actions that still need review.
If the source map marks an item as `evidence_kind=abstract`, `summary`,
`metadata_summary`, `semantic_scholar_abstract`, `openalex_abstract`, or
`arxiv_summary`, Refgate treats it as weak evidence: it can populate an evidence
candidate, but `audit-claims --submission` and `claim-consistency --submission`
block any claim marked `checked` from that evidence kind. Use full source text,
PDF-extracted passages, or explicitly reviewed source passages for final checks.
For scanned PDFs, `vision-extract-plan` creates an opt-in Codex/vision handoff
manifest. Refgate does not call Codex directly or send images itself; attach the
listed page images in a vision-capable Codex session, save the reviewed
transcript as `.txt`, then map it with `claim-source-check`.
For Codex-assisted claim review, use `export-review-bundle` after source files
are mapped. The bundle contains claim text, reference provenance summaries,
source paths, multiple deterministic evidence candidates per mapped source, and
a JSONL output contract for Codex. Use `--max-candidates-per-source` to tune how
many source passages are included for review. Refgate still does not call Codex
internally. After Codex writes one JSON object per reviewed claim, use
`import-review` to create a reviewed claim TSV. By default supported claims
remain `needs_review`; only `--allow-checked` promotes non-weak evidence to
`checked`, and weak evidence kinds remain `needs_review_weak_evidence`.

## Local Auth Setup

Live discovery can run without local auth values when the upstream service
allows anonymous requests. For more stable local use, configure values outside
the repository:

```bash
python -m refgate auth status --json
python -m refgate auth set semantic-scholar
python -m refgate auth setup
python -m refgate auth set crossref-mailto
python -m refgate auth set openalex-mailto
python -m refgate auth doctor --json
```

Environment variables are also supported:

```text
REFGATE_SEMANTIC_SCHOLAR_API_KEY
S2_API_KEY
REFGATE_CROSSREF_MAILTO
REFGATE_OPENALEX_MAILTO
```

The local config path can be overridden with `REFGATE_AUTH_CONFIG`. Command
output masks configured values.

## Optional Live Checks

Default tests do not use the network. To smoke-test the arXiv adapter against
the live API, opt in explicitly:

```bash
REFGATE_LIVE_ARXIV=1 python -m pytest tests/test_arxiv_adapter_live.py -q
```

The CLI also has an opt-in smoke command for all implemented adapters. It writes
raw-response cache records and can compare the cache against a checksum
manifest:

```bash
python -m refgate live-smoke --source arxiv --title "Attention Is All You Need" --live --json
python -m refgate live-smoke-suite --queries refgate_queries.json --source arxiv --cache-root .refgate/cache --prefer-cache --min-interval-seconds 3 --retry 2 --retry-after-seconds 10 --write-manifest .refgate/cache_manifest.reviewed.json --live --json
python -m refgate live-smoke-suite --queries refgate_queries.json --per-query-source --cache-root .refgate/cache --max-queries 3 --live --json
python -m refgate live-smoke-suite --queries refgate_queries.json --source arxiv --cache-root .refgate/cache --manifest .refgate/cache_manifest.reviewed.json --json
```

Use `--per-query-source` when `refgate_queries.json` contains mixed venue work
items. Each query or resolver-assist work item may set `source` or
`live_smoke_source`; resolver-assist output can also use the first
`recommended_sources` item. The normal `--source` value remains the fallback.
`live-smoke-suite --write-manifest` writes the reviewed manifest only when all
selected live queries succeed; partial endpoint failures keep the suite
blocking and skip the manifest.
Failed live checks include `failure_code`, `failure_summary`, and `next_actions`
so agents can distinguish rate limits from no-candidate lookups. For example,
an arXiv 429 yields a slower per-citation retry command with `--prefer-cache`,
larger `--min-interval-seconds`, and retry backoff.

Do not commit `.refgate/cache` or reviewed cache manifests to this public
repository. See `docs/live_smoke_reviewed_manifest.md` for the reviewed
manifest procedure.

## Codex Skill And Paper Repo Setup

Refgate is designed to be called by agents through project instructions or a
Codex Skill, while the CLI and audit artifacts remain the source of truth.
This repository also includes a local-alpha Codex plugin package named
`refgate` at `plugins/refgate`. The plugin packages the Refgate skill,
manifest metadata, icon, and CLI preview asset; it does not replace the CLI or
add a server layer.

For manuscript repositories, copy the template in
`docs/paper_repo_agents_template.md` into that repository's `AGENTS.md` and
replace the placeholder paths with the actual `.tex`, `.bib`, lockfile, claim
table, and report paths.
There is also a copyable paper-repo example under `examples/paper-repo/`,
including a GitHub Actions workflow that makes `paper-audit` the CI entry point.

You can also generate a paper-repo instruction snippet:

```bash
python -m refgate paper-agents-template --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --report refgate_audit.md --output AGENTS.refgate.md --json
```

For a manuscript repository that only has `.tex` and `.bib`, start with
`paper-audit` or `bootstrap-paper`. `paper-audit` creates missing lock/claim
artifacts, writes resolver work items, runs the frozen audit, and writes the
Markdown report in one pass. The generated lockfile is intentionally blocking:
each entry must later be resolved to an official export, verified manual
fallback, or arXiv fallback before submission.

## Design Rules

- Official BibTeX export and paper existence are separate gates.
- If an official BibTeX endpoint exists, preserve the raw export and checksum it.
- Manual fallback is allowed only when official export is unavailable.
- Manual fallback must never be labeled as official export.
- Discovery sources such as Semantic Scholar and OpenAlex are not final BibTeX
  authorities by default.
- Unresolved, ambiguous, generated-unverified, and claim-unchecked entries block
  submission.

## Future Maintenance

No blocking implementation work remains for the current CLI-first reference
gate. Future work should stay tied to real manuscript pressure:

1. Add source-specific official adapters when a real manuscript needs behavior
   beyond the generic official-HTML adapter.
2. Consider an optional mature BibTeX dependency only if real bibliographies
   expose parser limits that are not worth maintaining locally.

See `docs/roadmap.md` for the CLI + Skill implementation direction.
See `docs/release.md` for optional PyPI release steps.
See `docs/paper_repo_ci.md` for paper repository CI setup.
See `docs/live_smoke_reviewed_manifest.md` for reviewed live smoke evidence.
See `docs/codex_plugin_distribution.md` for the Codex plugin package and
marketplace notes.
See `docs/claude_code.md` for the Claude Code command pack and optional hook
setup.
