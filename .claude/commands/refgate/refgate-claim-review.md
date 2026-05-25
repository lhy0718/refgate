---
description: Export and import a source-backed Refgate claim review bundle
argument-hint: [tex] [bib] [lock] [claims] [source-dir]
---

Review citation-bearing claims against mapped source text or PDFs.

Inputs:

- TeX path: `$1`
- BibTeX path: `$2`
- lockfile path: `$3`
- claim TSV path: `$4`
- source directory: `$5`

Use citation-key named source files such as `smith2026.pdf` or `smith2026.txt`.
Do not use abstracts, summaries, titles, or metadata snippets as final evidence
for checked claims.

Use `refgate` if installed. If not installed and this is a Refgate source
checkout, use `PYTHONPATH=src python3 -m refgate`.

Run:

```bash
refgate paper-audit --tex TEX --bib BIB --lock LOCK --claims CLAIMS --source-dir SOURCE_DIR --source-map-output refgate_source_map.tsv --claim-review-output refgate_claim_review.md --submission --json
refgate export-review-bundle --tex TEX --bib BIB --lock LOCK --claims CLAIMS --source-dir SOURCE_DIR --source-map-output refgate_source_map.tsv --output .refgate/codex_review_bundle.json --markdown .refgate/codex_review_bundle.md --json
```

Read the bundle and write one JSONL review object per claim to
`.refgate/codex_review_result.jsonl`. Mark only full-source supported claims as
supported. Then run:

```bash
refgate import-review --claims CLAIMS --review .refgate/codex_review_result.jsonl --output refgate_claims.reviewed.tsv --json
```

Use `--allow-checked` only when final checked status is explicitly approved.
