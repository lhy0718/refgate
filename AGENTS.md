# Refgate Agent Notes

## Project Intent

Refgate is a standalone, publishable reference verification tool for academic
manuscripts. Keep it independent from any private paper repository.

## Immediate Continuation Point

Start with:

```bash
cd ~/Refgate
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

If `pytest` is not installed, run:

```bash
PYTHONPATH=src python3 -m refgate resolve --query tests/fixtures/official_query.json --candidates tests/fixtures/official_candidates.json --json
PYTHONPATH=src python3 -m refgate audit-bib --bib tests/fixtures/sample.bib --lock tests/fixtures/refgate.lock.json --submission --json
```

## Non-Negotiable Rules

- Never label generated or manual BibTeX as official export.
- Official record verification and official BibTeX export verification are
  separate gates.
- Discovery sources are not final authorities by default.
- Network adapters must have fixture-backed tests.
- Live network tests must be opt-in.
- Keep Refgate CLI-first. Do not move core verification into a server layer.
- Agent behavior belongs in Skills or project instructions that call the CLI.
- Do not add private paper drafts, private reference-manager exports, local
  absolute paths, or private note-system content to this public repo.

## Preferred Next Work

1. Keep fixture-backed tests ahead of live adapter changes.
2. Expand the minimal BibTeX parser only as tests require.
3. Run opt-in live smoke checks and save reviewed cache checksum evidence.
4. Use `monitor-official-records` to find project-page/preprint rows whose
   official venue records may now be available.
5. Expand PDF extraction fixtures and optional dependency packaging guidance.
6. Use `resolver-assist` after generic paper bootstrap to create lookup work
   items from unresolved starter lock entries.
7. Use `evidence-suggest-bundle` when multiple reviewed source texts or PDFs
   are available for claim evidence matching.
8. Run `publish-check --root . --json` before staging files for a public push.

## Current Validation Commands

```bash
.venv/bin/python -m pytest -q
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate resolve --query tests/fixtures/official_query.json --candidates tests/fixtures/official_candidates.json --json
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate audit-bib --bib tests/fixtures/sample.bib --lock tests/fixtures/refgate.lock.json --submission --json
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate audit --tex tests/fixtures/manuscript.tex --bib tests/fixtures/sample.bib --lock tests/fixtures/refgate.lock.json --claims tests/fixtures/claims_checked.tsv --frozen --submission --report examples/reference-fixture/sample_refgate_audit.md --json
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate claim-stubs --tex tests/fixtures/manuscript_claims.tex --output examples/reference-fixture/refgate_claims.tsv --json
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate claim-report --claims tests/fixtures/claims_unchecked.tsv --output examples/reference-fixture/refgate_claim_review.md --json
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate resolver-assist --lock tests/fixtures/refgate.lock.json --json
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate claim-consistency --claims tests/fixtures/claims_checked.tsv --json
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate validate-source-text --text tests/fixtures/source_excerpt.txt --json
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate export-handoff --bib tests/fixtures/sample.bib --lock tests/fixtures/refgate.lock.json --output .tmp/refgate_handoff.json --submission --json
PATH=.venv/bin:$PATH PYTHONPATH=src python3 -m refgate publish-check --root . --json
```
