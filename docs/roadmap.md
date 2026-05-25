# Refgate Roadmap

Refgate is a CLI-first reference verification gate for academic manuscripts.
The core product is not a server integration layer. The durable interface is:

- JSON-first CLI commands
- `refgate.lock.json`
- `refgate_claims.tsv`
- Markdown audit reports
- project instructions or Skills that tell agents when to call the CLI

## Direction

Keep verification logic in the CLI. This makes Refgate usable from local shell,
CI, and agent sessions without depending on one agent platform.

Use Skills or project instructions for agent behavior:

- run Refgate before adding or changing a bibliography entry;
- block `.bib` edits when `ok=false`;
- require claim-to-source evidence for important related-work and benchmark
  claims;
- preserve warnings in reports for human review.

Do not add a server roadmap to the core project. If a future external client
needs integration, it should call the CLI as an external wrapper and must not
become the source of truth.

## Implemented Baseline

- Lockfile merge/update mode for `fetch-bibtex --write-lock`
- End-to-end `paper-audit` command for common `.tex` + `.bib` repositories
- Generic `.tex` + `.bib` bootstrap for starter lockfile and claim TSV
- Golden audit report output
- Claim TSV stub generation from `.tex`
- Markdown claim review report
- Crossref DOI exact lookup adapter
- Semantic Scholar and OpenAlex discovery/cross-check adapters
- Generic official-HTML venue adapters for PMLR, ACM, CVF Open Access, JMLR,
  Nature Portfolio, Wiley, SAGE, Taylor & Francis, IEEE, Springer, Elsevier,
  USENIX, AAAI, and OpenReview-style records
- Source-specific ACL Anthology, ICLR, and NeurIPS adapters with official
  BibTeX endpoint handling
- Targeted `reference-check --citation-key` reruns for reviewed subsets
- Live official BibTeX export fetch via `reference-check --fetch-official-bibtex`
- Official-record monitor for arXiv fallback and official-record-pending rows
- Local auth status/set/setup/doctor flow for live discovery values
- Extracted-text evidence suggestion flow for claim TSV review
- Citation-local claim stub generation for multi-citation sentences
- Network-free source download planning, with live PDF downloads behind an
  explicit `--live` flag
- Page-aware PDF evidence source locations
- Optional PDF text extraction hook for `evidence-suggest`
- Public ten-paper fixture matrix validator
- Opt-in live smoke command with cache checksum manifest comparison
- Cache manifest write mode for reviewed live-smoke evidence
- Field-level check storage in lockfile entries
- Cache write/read helpers
- Structured JSON errors for missing live-smoke manifests and failed live discovery
- Resolver-assist query work items from starter lockfiles
- Resolver-assist source recommendations and source-specific command templates
- `run-next` support for both raw command JSON responses and saved
  `next_actions` plan manifests
- Agent-friendly `run-next` hints and top-level recommended next command
- Deterministic claim/evidence consistency review
- Deterministic over-strong claim wording warning in claim/evidence review
- Source bundle evidence suggestion across multiple reviewed text/PDF inputs
- Codex review bundle export/import for claim-to-source review assistance
- Batch live-smoke suite with reviewed manifest write support
- Reviewed-cache-first live smoke, retry, and interval controls for rate limits
- Source text validation command for extracted text and optional PDF paths
- Venue labeling for direct public PDF URLs in source download plans
- Wrapped-title continuation handling for source-title checks on real PDFs
- Source-title mismatch next-actions and audit report section
- Persistent claim-evidence review next-actions while mapped claims remain in
  review status
- Standalone handoff export in Refgate JSON and CSL-JSON formats
- Richer CSL-JSON mapping for common BibTeX fields
- Paper repo instruction template generator
- CI workflow for pytest and compile checks
- Publish check for public-repo hygiene review
- Repo-local Codex plugin package and marketplace catalog
- Plugin icon and CLI preview assets for broader catalog distribution
- Optional PyPI release workflow using Trusted Publishing
- Publisher-mixed synthetic paper dogfood covering `paper-audit`,
  fixture-backed `reference-check`, BibTeX sync, source-title checks, Codex
  review bundle import, and final handoff export

## Future Maintenance

No blocking implementation work remains for the current CLI-first reference
gate. Recent real-paper dogfood covered the common `.tex` + `.bib` path through
bootstrap, resolver work items, source PDF planning/download, source maps, PDF
text extraction, source-title validation, and claim-evidence review handoff.
The remaining items are maintenance triggers, not queued feature work:

1. Add source-specific adapters only when a real manuscript needs behavior
   beyond the generic official-HTML adapter.
2. Add small public fixtures when real PDFs expose title-detection, page
   extraction, or evidence-ranking limits.
3. Consider an optional mature BibTeX dependency only if real bibliographies
   expose parser limits that are not worth maintaining locally.
4. Keep live cache manifests, downloaded PDFs, and private manuscript artifacts
   out of the public repository unless explicitly curated as public fixtures.
