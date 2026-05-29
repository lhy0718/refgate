# Refgate CLI Interface Draft

Refgate is a CLI-first gate. The CLI is the source of truth for agent workflows,
CI, local shell use, lockfile generation, and submission audits. Agent
integrations should call the CLI and parse JSON output rather than moving core
logic into a server process.

The JSON-first CLI surface is organized as small operations:

- `discover`
- `paper-audit`
- `bootstrap-lock`
- `bootstrap-paper`
- `resolver-assist`
- `resolve`
- `fetch-bibtex`
- `normalize-bibtex`
- `sync-bibtex`
- `audit-bib`
- `audit-claims`
- `claim-consistency`
- `claim-source-check`
- `claim-stubs`
- `claim-report`
- `evidence-suggest`
- `evidence-suggest-bundle`
- `export-review-bundle`
- `import-review`
- `audit`
- `export-handoff`
- `auth`
- `reference-check`
- `fixture-matrix`
- `live-smoke`
- `live-smoke-suite`
- `run-next`
- `run-summary`
- `validate-source-text`
- `check-source-titles`
- `download-sources`
- `publish-check`
- `paper-agents-template`
- `render-report`

Every JSON command should return or embed:

```json
{
  "ok": true,
  "status": "verified_official_bibtex",
  "data": {},
  "blocking_issues": [],
  "warnings": [],
  "next_actions": []
}
```

For `paper-audit`, `next_actions` is actionable rather than decorative. It may
include commands such as `resolver-assist`, a rerun with `--source-dir`, claim
review pointers, or `export-handoff` when the audit is clean. Agents should
prefer these returned actions over inventing follow-up commands from scratch.
Each action includes `kind`, `requires_human_review`, `writes_files`, and
`network_required` so agents can decide whether to execute, ask for review, or
request network permission.
Reference-provenance actions include both an offline reviewed-input command and
an opt-in live command so plugin/skill agents can choose the safest available
path. The offline path includes `fixture_html_dir`, `fixture_html_naming`, and
`reviewed_bibtex_dir` fields for saved official publisher pages and reviewed
fallback BibTeX.
`run-next --from OUTPUT.json --json` reads those actions and returns an
execution plan without running anything. Add `--execute` plus the relevant
allow flags (`--allow-network`, `--allow-writes`, `--allow-human-review`) to run
selected safe actions. Commands with unresolved placeholders such as
`PAPER_BIB`, `SOURCES_DIR`, `OFFICIAL_BIBTEX_DIR`, or
`REVIEWED_FALLBACK_BIBTEX_DIR` are reported as `skip_reason=input_required`
rather than selected for execution. `run-next` normally uses the `command`
field, but `--command-field reference_check_command` can promote a reviewed
auxiliary command when its fixture/input directories are populated. Use
`--output-plan PLAN.json` to persist the dry-run decision manifest and
`--write-run-log RUN.json` to persist the command results after planning or
execution.
Each planned action includes `agent_hint`, `ready_to_execute`, and the top-level
`recommended_next` object so agents can explain why an action is blocked or
which command is ready without rereading the whole action list.
Publisher-specific reference actions also retain compact `action_summary`,
`official_bibtex_url`, and `source_guidance_summary` fields in `run-next` and
`run-summary` output.
`run-summary --input PLAN.json --input RUN.json --json` reads those manifests
and reports only remaining actions: failed commands, skipped actions, or
planned actions that have not yet been executed. Add `--markdown SUMMARY.md`
to write a compact human-reviewable summary alongside the JSON response.

Network-backed tools should accept fixture or cached raw responses during tests.
Live checks are opt-in and must not run in the default validation suite.

Skill-level agent rules should decide when to call these commands:

- do not edit `.bib` when `ok=false`;
- do not hand off bibliography artifacts while blocking issues remain;
- treat warnings as reportable review items;
- keep lockfile and Markdown report as the persistent evidence layer.

Current CLI coverage:

- `discover`
- `paper-audit`
- `bootstrap-lock`
- `bootstrap-paper`
- `resolver-assist`
- `resolve`
- `fetch-bibtex`
- `normalize-bibtex`
- `sync-bibtex`
- `audit-bib`
- `audit-claims`
- `claim-consistency`
- `claim-stubs`
- `claim-report`
- `evidence-suggest`
- `evidence-suggest-bundle`
- `export-review-bundle`
- `import-review`
- `audit`
- `export-handoff`
- `auth`
- `fixture-matrix`
- `live-smoke`
- `live-smoke-suite`
- `run-next`
- `run-summary`
- `validate-source-text`
- `check-source-titles`
- `download-sources`
- `reference-check`
- `publish-check`
- `paper-agents-template`
- `render-report`

Current fixture-backed adapter coverage:

- arXiv
- ACL Anthology
- NeurIPS proceedings
- ICLR proceedings
- Crossref
- Semantic Scholar
- OpenAlex
- PMLR
- ACM
- CVF Open Access
- JMLR
- Nature Portfolio
- Wiley
- SAGE
- Taylor & Francis
- IEEE
- Springer
- Elsevier
- USENIX
- AAAI
- Oxford Academic
- Cambridge Core
- PNAS
- Science
- Frontiers
- MDPI
- LIPIcs
- OpenReview-style official pages

The generic official venue adapters are URL-backed authority adapters. They
discover records from preferred venue URLs such as `dl.acm.org`,
`ieeexplore.ieee.org`, `link.springer.com`, `sciencedirect.com`,
`usenix.org`, `aaai.org`, `proceedings.mlr.press`,
`openaccess.thecvf.com`, `jmlr.org`, `nature.com`,
`onlinelibrary.wiley.com`, `journals.sagepub.com`, `tandfonline.com`,
`academic.oup.com`, `cambridge.org`, `pnas.org`, `science.org`,
`frontiersin.org`, `mdpi.com`, `drops.dagstuhl.de`, and `openreview.net`.
They can verify an official record without an official BibTeX endpoint; in that
case manual fallback provenance remains manual and must not be labeled as an
official export. Sources such as PMLR may expose publisher-provided BibTeX
inside the official HTML page rather than through a separate `.bib` URL; ACM
records can derive the official export URL from the DOI when the record page
metadata does not advertise a direct BibTeX link;
`reference-check --fetch-official-bibtex` routes those cases through the source
adapter instead of parsing the HTML page as raw BibTeX.
When `--fallback-reason` is present, reviewed BibTeX files are recorded as
manual fallback provenance even if the official HTML advertises a BibTeX export
URL; `audit-bib --submission` then keeps the entry blocking until the real
official export is fetched or the policy is explicitly changed.
Use `--official-bibtex-dir` for reviewed offline official-export fixtures
(`citationkey.SOURCE.bib`, `citationkey.source.bib`, or `citationkey.bib`).
Refgate records these as `official_export` only when the selected authority
record advertises a BibTeX export URL and the fixture passes title/DOI checks.
For publishers that block live fetches, save the official record HTML under
`citationkey.source.html` or `citationkey.html` and pass `--fixture-html-dir`.
This is a reviewed offline authority input, not a generated candidate record.

Local auth commands:

- `auth status --json`
- `auth set semantic-scholar`
- `auth set crossref-mailto`
- `auth set openalex-mailto`
- `auth setup`
- `auth doctor --json`

Configured values must live in environment variables or the user-local Refgate
auth config. CLI output must mask configured values and must not write them to
lockfiles, fixtures, reports, or repo docs.

Claim evidence commands:

- `evidence-suggest --claims refgate_claims.tsv --text extracted.txt --output refgate_claims.suggested.tsv --json`
- `evidence-suggest-bundle --claims refgate_claims.tsv --text source-a.txt --text source-b.pdf --output refgate_claims.suggested.tsv --json`
- `claim-source-check --claims refgate_claims.tsv --source-map source_map.tsv --output refgate_claims.review.tsv --submission --json`
- `claim-source-check --claims refgate_claims.tsv --source-map source_map.tsv --output refgate_claims.review.tsv --rerank semantic-lite --json`
- `claim-source-check --claims refgate_claims.tsv --source-map source_map.tsv --include-consistency --include-issues --json`
- `claim-consistency --claims refgate_claims.tsv --submission --json`
- `check-source-titles --lock refgate.lock.json --source-map source_map.tsv --json`
- `download-sources --lock refgate.lock.json --source-dir sources --json`
- `download-sources --lock refgate.lock.json --source-dir sources --citation-key smith2026 --live --json`
- `sync-bibtex --bib references.bib --lock refgate.lock.json --json`
- `sync-bibtex --bib references.bib --lock refgate.lock.json --output references.refgate.bib --json`
- `vision-extract-plan --pdf scanned.pdf --citation-key smith2026 --image-dir rendered-pages --output .refgate/vision_extract_plan.json --json`
- `export-review-bundle --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --source-dir sources --output .refgate/codex_review_bundle.json --markdown .refgate/codex_review_bundle.md --json`
- `import-review --claims refgate_claims.tsv --review .refgate/codex_review_result.jsonl --output refgate_claims.reviewed.tsv --json`

`evidence-suggest` may fill source location and quote candidates, but it must
not mark a claim as `checked`. Human review remains the final gate.
`claim-source-check` is the higher-level direct verification entry point for
real manuscripts: the source map links each citation key to reviewed extracted
text or PDFs, then Refgate fills evidence candidates and blocks submission
until the claim status is final.
Use `--rerank semantic-lite` for deterministic phrase/coverage-aware evidence
ranking. It does not call an external model and still leaves final claim status
to human review.
The source map may include `evidence_kind` (or `source_kind`) for each source.
Weak kinds such as `abstract`, `summary`, `metadata_summary`,
`semantic_scholar_abstract`, `openalex_abstract`, and `arxiv_summary` are
allowed only as review hints. Refgate writes them as
`needs_review_weak_evidence`; if a claim is later marked `checked` while still
using weak evidence, `audit-claims --submission` and
`claim-consistency --submission` raise `CLAIM_WEAK_EVIDENCE_NOT_CHECKABLE`.
By default it returns a compact consistency summary; use
`--include-consistency` for the full per-claim lexical review and
`--include-issues` for the full issue list.
`claim-consistency` is deterministic and lexical: it flags missing evidence,
low claim/evidence overlap, non-final claim status, and over-strong claim
wording that needs careful source support during submission mode.
`evidence-suggest-bundle` chooses the best source block across multiple
reviewed text/PDF files and still leaves claims in human-review status. For
extractable PDFs, source locations preserve page labels when the text extractor
provides them.
Evidence ranking is deterministic and demotes title-like or abstract-like
matches when a fuller body passage has comparable lexical support. Suggestions
include overlap, coverage, matched/missing terms, page-aware location, and
evidence-quality hints for agent review.
`check-source-titles` compares the lockfile/BibTeX title with first-page title
candidates from citation-key mapped source files. `paper-audit --source-dir`
and `paper-audit --source-map` run the same gate and block on
`SOURCE_TITLE_MISMATCH` when a PDF/text source is for a different title than the
reference record. Mismatches include a `REVIEW_SOURCE_TITLE_MISMATCH`
next-action so agents do not treat lexical evidence overlap as sufficient when
the mapped source appears to be the wrong paper. A reviewed metadata/source
title mismatch can be accepted with `--title-review REVIEW.jsonl`; each JSONL
object must include `citation_key`, an accepted `decision`, `expected_title`,
and `source_title`, and may include `source_text`, `reviewer`, and `notes`.
The gate still blocks if the review does not match the current lock title and
current first-page source title.
`download-sources` is network-free by default: it derives citation-key PDF
targets from lockfile URLs, arXiv IDs, ACL Anthology records, or known venue PDF
URL patterns and returns a plan. Add `--live` only when the user has opted into
network access and file writes. Downloaded PDFs are inputs for later
source-map/title/evidence review; they are not official BibTeX exports.
`sync-bibtex` is the agent-facing `.bib` rewrite surface after provenance has
been filled. It reads only the lockfile's canonical BibTeX text, returns a
dry-run JSON action list by default, and writes only with `--output` or
`--in-place`. It blocks instead of reconstructing a bibliography entry when the
lockfile lacks canonical text or has a non-passing provenance status.
`export-review-bundle` is the Codex handoff surface for claim-to-source review.
It packages claim rows, lockfile provenance summaries, citation-key source
paths, multiple deterministic evidence candidates per mapped source, and a
JSONL result template. Use `--max-candidates-per-source` when Codex needs a
broader passage queue than the default top five candidates. It does not call
Codex, a local LLM, or any external model. `import-review` validates that JSONL
result and writes a new claim TSV. Supported claims remain `needs_review` by
default; `--allow-checked` is required before non-weak evidence can become
`checked`, and weak evidence kinds still remain `needs_review_weak_evidence`.

Generic paper bootstrap commands:

- `paper-audit --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --report refgate_audit.md --resolver-output refgate_queries.json --next-plan-output .refgate/next_plan.json --submission --json`
- `paper-audit --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --source-dir sources --source-map-output refgate_source_map.tsv --claim-review-output refgate_claim_review.md --submission --json`
- `paper-audit --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --frozen --submission --json`
- `bootstrap-paper --tex paper.tex --bib references.bib --lock-output refgate.lock.json --claims-output refgate_claims.tsv --json`
- `bootstrap-lock --bib references.bib --output refgate.lock.json --json`
- `resolver-assist --lock refgate.lock.json --output refgate_queries.json --json`
- `paper-agents-template --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --report refgate_audit.md --output AGENTS.refgate.md --json`
- `export-review-bundle --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --source-dir sources --output .refgate/codex_review_bundle.json --markdown .refgate/codex_review_bundle.md --json`
- `import-review --claims refgate_claims.tsv --review .refgate/codex_review_result.jsonl --output refgate_claims.reviewed.tsv --json`

These commands are for the common case where a manuscript repository has only
`.tex` and `.bib`. The generated lockfile is intentionally blocking and marks
entries as missing provenance until they are resolved to an official export,
verified manual fallback, or arXiv fallback.
`resolver-assist` turns unresolved starter lock entries into query work items
that agents can pass to discovery and resolution commands.
`paper-audit` is the high-level command for the common `.tex` + `.bib` case: it
creates missing starter artifacts, updates claim stubs, writes resolver-assist
work items, runs the audit, and writes the Markdown report.
The `--tex` path is treated as a root file. `\input{...}` and `\include{...}`
children are resolved relative to the root TeX directory with a recursion limit
of 20; omitted `.tex` suffixes are added automatically. Missing includes warn in
ordinary mode and block in submission mode.
Use `--next-plan-output` to write a dry-run `next_actions` manifest directly
from the paper audit result, so an agent can continue with `run-next` or
`run-summary` without first saving the whole command response.
If `--source-dir` is present, it also builds a deterministic source map from
`.txt` and `.pdf` files whose stem exactly matches a citation key, writes
relative paths to `--source-map-output` or a default `refgate_source_map.tsv`,
then runs `claim-source-check` and source-title validation before the final
audit. Use `--source-map` when a reviewed citation-key to source-text/PDF map
already exists. When source
checking runs, it writes a claim review Markdown report to
`--claim-review-output` or a default `refgate_claim_review.md`, including
queues for evidence suggestions, missing source files, and mapped sources with
no matching evidence block.
The main audit report also includes a compact `Claim Source Check` section so
agents can see claim/source blockers without opening the auxiliary claim review
report first.
By default its JSON response keeps resolver work items and issue lists compact:
it reports counts, samples, and output artifact paths. Use
`--include-work-items` when an agent needs inline resolver work items instead of
reading `--resolver-output`, and `--include-issues` when a reviewer needs the
full per-entry issue list in the command response.

Fixture and live-smoke commands:

- `reference-check --lock refgate.lock.json --candidate-dir candidates --official-bibtex-dir official-bibtex --max-entries 3 --write-lock refgate.lock.json --json`
- `reference-check --lock refgate.lock.json --fixture-html-dir official-html --source acm --bibtex-dir manual-bibtex --write-lock refgate.lock.json --fallback-reason "Reviewed saved official HTML; manual BibTeX fallback retained because no official BibTeX endpoint was verified." --json`
- `reference-check --lock refgate.lock.json --fixture-html-dir official-html --source aaai --official-bibtex-dir official-bibtex --write-lock refgate.lock.json --json`
- `reference-check --lock refgate.lock.json --source iclr --cache-root .refgate/cache --citation-key citationkey2026 --fetch-official-bibtex --write-lock refgate.lock.json --live --json`
- `reference-check --lock refgate.lock.json --source acm --source ieee --source openreview --cache-root .refgate/cache --write-lock refgate.lock.json --live --json`
- `monitor-official-records --lock refgate.lock.json --json`
- `monitor-official-records --lock refgate.lock.json --cache-root .refgate/cache --write-lock refgate.lock.json --live --json`
- `fixture-matrix --queries reference_priority_queries.json --candidates reference_priority_candidates.json --json`
- `live-smoke --source arxiv --title "..." --live --json`
- `live-smoke-suite --queries refgate_queries.json --source arxiv --cache-root .refgate/cache --max-queries 3 --prefer-cache --min-interval-seconds 3 --retry 2 --retry-after-seconds 10 --write-manifest reviewed-cache-manifest.json --live --json`
- `live-smoke --cache-root .refgate/cache --write-manifest reviewed-cache-manifest.json --json`
- `live-smoke --cache-root .refgate/cache --manifest expected-cache-manifest.json --json`
- `validate-source-text --text extracted.txt --json`
- `publish-check --root . --json`

`reference-check` verifies lockfile references against fixture or opt-in live
candidate records. When an official BibTeX file is provided, it can update
lockfile provenance; generated/manual fallback BibTeX must not be labeled as an
official export.
Use repeated `--citation-key` flags to constrain a live run or write-lock update
to reviewed entries. With `--fetch-official-bibtex`, a selected live official
record can fetch its own BibTeX export URL directly; Refgate validates title and
DOI before writing provenance and turns fetch failures into blocking issues.
`--fixture-html-dir` adds an offline reviewed official-record path for saved
publisher HTML. It can verify the authority record without network access and,
when the official page contains inline publisher BibTeX, can feed
`--fetch-official-bibtex` without live network.
If live lookup fails, `reference-check` returns `ADD_OFFICIAL_HTML_FIXTURE` as
a follow-up action alongside the retry/cache action, which gives agents a
deterministic fallback instead of guessing how to proceed.
For publisher-specific blocked-fetch cases, next actions may include
`source_guidance` with reviewed fixture filenames, source URL patterns, and
known official export/PDF URL patterns. If the selected authority advertises an
official BibTeX URL and `--fetch-official-bibtex` has not been tried,
`FETCH_OFFICIAL_BIBTEX_EXPORT` is emitted before manual fallback suggestions.
If an official export fetch fails, `ADD_OFFICIAL_BIBTEX_FIXTURE` tells agents
where to save the reviewed publisher export for an offline rerun.
Official BibTeX provenance is matched by `citation_key.bib`/`.bibtex` first and
then by exact normalized title across the BibTeX directory. Before a lockfile
update, official exports are checked against the selected authority title and
DOI when available; mismatches become blocking issues.
`monitor-official-records` scans a lockfile for arXiv fallback or
official-record-pending entries and emits citation-key scoped
`reference-check` actions against final-authority sources. The command is
network-free unless `--live` is present.
Its `next_actions` field reports follow-up work such as adding
`citation_key.json` candidate files, reviewing low-confidence or preprint-only
candidates, adding `citation_key.bib` provenance files, retrying live lookup
with cache preference, writing the lockfile, or rerunning `audit-bib` after a
successful update.
`live-smoke` must not access the network unless `--live` is present. Manifest
comparison is network-free and compares cached response checksums.
`live-smoke-suite` is also live-gated and accepts either a query list or the
output of `resolver-assist`.
Use `--prefer-cache` with reviewed cache records to reduce repeated live calls;
`--min-interval-seconds`, `--retry`, and `--retry-after-seconds` provide basic
rate-limit backoff.
`claim-source-check` suggestions include lexical overlap score, claim coverage,
matched terms, missing terms, and source locations that preserve PDF page labels
when the source text extractor emits page markers.
For scanned PDFs, `vision-extract-plan` creates a Codex/vision handoff manifest
with page labels, expected rendered page image paths, and a source-map row
template. Refgate does not send images to Codex directly; an agent or reviewer
must attach rendered page images, save the reviewed transcript, then run
`claim-source-check`.

Standalone handoff commands:

- `export-handoff --bib references.bib --lock refgate.lock.json --output refgate_handoff.json --submission --json`
- `export-handoff --bib references.bib --lock refgate.lock.json --output references.csl.json --format csl-json --json`

`export-handoff` runs the bibliography audit before writing. Blocking issues
prevent export unless `--allow-blocking` is explicitly provided.
