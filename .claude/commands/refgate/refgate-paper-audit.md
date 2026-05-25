---
description: Bootstrap or audit a TeX/BibTeX paper with Refgate
argument-hint: [tex] [bib] [artifact-dir]
---

Run the Refgate paper bootstrap/audit workflow for this manuscript.

Inputs, if supplied:

- TeX path: `$1`
- BibTeX path: `$2`
- artifact directory: `$3`

If arguments are missing, inspect the repository and choose the most plausible
main `.tex` and `.bib` files. Ask only if multiple choices would lead to
conflicting edits.

Use `refgate` if installed. If not installed and this is a Refgate source
checkout, use `PYTHONPATH=src python3 -m refgate`.

Run:

```bash
refgate paper-audit --tex TEX --bib BIB --lock ARTIFACT_DIR/refgate.lock.json --claims ARTIFACT_DIR/refgate_claims.tsv --report ARTIFACT_DIR/refgate_audit.md --resolver-output ARTIFACT_DIR/refgate_queries.json --next-plan-output ARTIFACT_DIR/.refgate/next_plan.json --submission --json
```

Read `ok`, `blocking_issues`, `warnings`, and `next_actions`. Do not hide an
`ok=false` result; starter artifacts are expected to block until provenance and
claim evidence are reviewed.
