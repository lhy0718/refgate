---
description: Resolve and verify Refgate reference provenance
argument-hint: [lock] [candidate-dir] [bibtex-dir] [official-bibtex-dir]
---

Verify bibliography provenance for a Refgate lockfile.

Inputs, if supplied:

- lockfile path: `$1`
- reviewed candidate directory: `$2`
- reviewed manual fallback BibTeX directory: `$3`
- reviewed official export BibTeX fixture directory: `$4`

Prefer fixture-backed or reviewed local candidate files. Use live network lookup
only when the user explicitly asks for it.

Use `refgate` if installed. If not installed and this is a Refgate source
checkout, use `PYTHONPATH=src python3 -m refgate`.

For reviewed local material, run:

```bash
refgate reference-check --lock LOCK --candidate-dir CANDIDATE_DIR --bibtex-dir REVIEWED_FALLBACK_BIBTEX_DIR --official-bibtex-dir OFFICIAL_BIBTEX_DIR --write-lock LOCK --json
refgate audit-bib --bib REFERENCES_BIB --lock LOCK --submission --json
```

Use `--official-bibtex-dir` only for reviewed publisher/export fixtures such as
`citationkey.SOURCE.bib`, `citationkey.source.bib`, or `citationkey.bib`.
Keep manual or reconstructed BibTeX in `--bibtex-dir`, with a fallback reason
when it is not an official export.

For explicit live review, start with a small batch and preserve cache evidence:

```bash
refgate reference-check --lock LOCK --source arxiv --cache-root .refgate/cache --max-entries 3 --fetch-official-bibtex --write-lock LOCK --live --json
```

Never mark manual or generated BibTeX as `official_export`.
