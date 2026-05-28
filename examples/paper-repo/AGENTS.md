# Refgate Paper Reference Gate

Use Refgate before changing references, BibTeX entries, citation keys, or
citation-bearing claims.

## Paths

- Manuscript TeX: `paper.tex`
- Bibliography: `references.bib`
- Refgate lockfile: `refgate.lock.json`
- Claim table: `refgate_claims.tsv`
- Audit report: `refgate_audit.md`

## Default Entry Point

Run `paper-audit` first for ordinary paper repositories. It creates missing
starter artifacts, writes resolver work items, writes the Markdown report, and
saves a deterministic next-action plan.

```bash
refgate paper-audit --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --report refgate_audit.md --resolver-output refgate_queries.json --next-plan-output .refgate/next_plan.json --submission --json
```

Inspect the plan before executing anything:

```bash
refgate run-next --from .refgate/next_plan.json --json
```

If reviewed official HTML, official BibTeX, or manual fallback files have been
added, execute the reference-check action only after inspecting the plan:

```bash
refgate run-next --from .refgate/next_plan.json --command-field reference_check_command --allow-writes --allow-human-review --max-actions 1 --execute --write-run-log .refgate/next_run_log.json --json
refgate run-summary --input .refgate/next_plan.json --input .refgate/next_run_log.json --markdown .refgate/next_summary.md --json
```

## Required Checks

After editing `.bib` or the lockfile:

```bash
refgate sync-bibtex --bib references.bib --lock refgate.lock.json --json
refgate audit-bib --bib references.bib --lock refgate.lock.json --submission --json
```

After adding or changing citation-bearing claims:

```bash
refgate claim-stubs --tex paper.tex --output refgate_claims.tsv --json
refgate claim-consistency --claims refgate_claims.tsv --submission --json
refgate audit-claims --claims refgate_claims.tsv --submission --json
```

When citation-key named source files exist under `sources/`:

```bash
refgate paper-audit --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --report refgate_audit.md --source-dir sources --source-map-output refgate_source_map.tsv --claim-review-output refgate_claim_review.md --submission --json
```

Before submission or final handoff:

```bash
refgate audit --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --frozen --submission --report refgate_audit.md --json
```

## Rules

- Generated or manually normalized BibTeX is never an official export.
- Discovery sources are not final authorities unless Refgate marks them as such.
- Live network checks are opt-in.
- Abstracts, summaries, and metadata snippets are weak evidence only.
- Keep final claim status in the TSV; evidence suggestions require review.
- If a Refgate command returns `ok=false`, report the blocker or keep following
  safe next actions; do not call the paper verified.
