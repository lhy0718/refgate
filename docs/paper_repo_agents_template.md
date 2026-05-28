# Refgate Paper Repo AGENTS Template

Copy this section into a manuscript repository's `AGENTS.md`, then replace the
placeholder paths with that repository's actual files.

```markdown
## Refgate Reference Gate

Use Refgate before adding, editing, or finalizing references, BibTeX entries,
citation-bearing claims, or reference handoff artifacts.

### Refgate Artifacts

- Manuscript TeX: `PATH/TO/main.tex`
- Bibliography: `PATH/TO/references.bib`
- Refgate lockfile: `PATH/TO/refgate.lock.json`
- Claim table: `PATH/TO/refgate_claims.tsv`
- Audit report: `PATH/TO/refgate_audit.md`

Use this command form unless this repository defines another one:

```bash
python -m refgate
```

If this repository has only `.tex` and `.bib` and no Refgate artifacts yet,
run `paper-audit` first. It creates starter artifacts, writes resolver work
items, writes a Markdown report, and saves a deterministic next-action plan:

```bash
python -m refgate paper-audit --tex PATH/TO/main.tex --bib PATH/TO/references.bib --lock PATH/TO/refgate.lock.json --claims PATH/TO/refgate_claims.tsv --report PATH/TO/refgate_audit.md --resolver-output PATH/TO/refgate_queries.json --next-plan-output PATH/TO/.refgate/next_plan.json --submission --json
```

The generated lockfile is expected to block submission until each entry is
resolved to official BibTeX export, verified manual fallback, or arXiv fallback.

Inspect the saved plan before executing anything:

```bash
python -m refgate run-next --from PATH/TO/.refgate/next_plan.json --json
```

After reviewed official HTML, official BibTeX, or manual fallback files are
added, execute only the reviewed reference-check action:

```bash
python -m refgate run-next --from PATH/TO/.refgate/next_plan.json --command-field reference_check_command --allow-writes --allow-human-review --max-actions 1 --execute --write-run-log PATH/TO/.refgate/next_run_log.json --json
python -m refgate run-summary --input PATH/TO/.refgate/next_plan.json --input PATH/TO/.refgate/next_run_log.json --markdown PATH/TO/.refgate/next_summary.md --json
```

### Reference Rules

- Do not add or modify a bibliography entry without Refgate provenance.
- Never label generated, reconstructed, or manually normalized BibTeX as an
  official export.
- Official paper-record verification and official BibTeX export verification
  are separate gates.
- Discovery sources are not final authorities unless Refgate marks them as such.
- Default work must be network-free; live discovery is opt-in only.
- Do not commit private manuscripts, private reference-manager exports, local
  absolute paths, private notes, or credential material.

### Required Checks

After editing `.bib` or the lockfile:

```bash
python -m refgate sync-bibtex --bib PATH/TO/references.bib --lock PATH/TO/refgate.lock.json --json
python -m refgate audit-bib --bib PATH/TO/references.bib --lock PATH/TO/refgate.lock.json --submission --json
```

After adding or changing citation-bearing claims:

```bash
python -m refgate claim-stubs --tex PATH/TO/main.tex --output PATH/TO/refgate_claims.tsv --json
python -m refgate claim-consistency --claims PATH/TO/refgate_claims.tsv --submission --json
python -m refgate audit-claims --claims PATH/TO/refgate_claims.tsv --submission --json
```

Before submission or final handoff:

```bash
python -m refgate paper-audit --tex PATH/TO/main.tex --bib PATH/TO/references.bib --lock PATH/TO/refgate.lock.json --claims PATH/TO/refgate_claims.tsv --report PATH/TO/refgate_audit.md --source-dir PATH/TO/sources --source-map-output PATH/TO/refgate_source_map.tsv --claim-review-output PATH/TO/refgate_claim_review.md --submission --json
python -m refgate audit --tex PATH/TO/main.tex --bib PATH/TO/references.bib --lock PATH/TO/refgate.lock.json --claims PATH/TO/refgate_claims.tsv --frozen --submission --report PATH/TO/refgate_audit.md --json
```

To create a standalone reviewed handoff bundle:

```bash
python -m refgate export-handoff --bib PATH/TO/references.bib --lock PATH/TO/refgate.lock.json --output PATH/TO/refgate_handoff.json --submission --json
```

If any Refgate command returns `ok=false`, do not report the reference work as
complete. Resolve the blocking issue or report it explicitly as a remaining
blocker.
```

For CI, copy `examples/paper-repo/.github/workflows/refgate-paper-audit.yml`
and keep `paper-audit` as the entry point. Do not mask `ok=false`; upload the
generated artifacts and follow `next_actions`.
