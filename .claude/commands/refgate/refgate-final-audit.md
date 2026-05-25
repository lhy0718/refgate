---
description: Run a final Refgate submission audit
argument-hint: [tex] [bib] [lock] [claims] [source-dir]
---

Run final submission gates for a manuscript.

Inputs:

- TeX path: `$1`
- BibTeX path: `$2`
- lockfile path: `$3`
- reviewed claim TSV path: `$4`
- optional source directory: `$5`

Use `refgate` if installed. If not installed and this is a Refgate source
checkout, use `PYTHONPATH=src python3 -m refgate`.

Run the source-backed flow when sources exist:

```bash
refgate paper-audit --tex TEX --bib BIB --lock LOCK --claims CLAIMS --source-dir SOURCE_DIR --source-map-output refgate_source_map_final.tsv --claim-review-output refgate_claim_review_final.md --report refgate_audit_final.md --submission --json
```

Then run the frozen audit:

```bash
refgate audit --tex TEX --bib BIB --lock LOCK --claims CLAIMS --frozen --submission --report refgate_audit_final.md --json
```

Report every remaining blocker by citation key or claim id. Do not call the
paper ready if `ok=false`.
