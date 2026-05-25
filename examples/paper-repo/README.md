# Refgate Paper Repo Example

This directory contains copyable, path-placeholder templates for a manuscript
repository that starts with ordinary `paper.tex` and `references.bib` files.

Use these files in a paper repository, not in the Refgate source checkout:

- `AGENTS.md`: agent instructions that make `paper-audit` the default entry.
- `.github/workflows/refgate-paper-audit.yml`: GitHub Actions example that runs
  the same `paper-audit` gate and uploads review artifacts.

Replace the placeholder paths with the manuscript repository's actual TeX,
BibTeX, lockfile, claim table, and report paths.
