# Refgate Claude Code Guide

Refgate is a standalone CLI-first reference verification tool for academic
manuscripts. Treat the CLI output, lockfile, claim TSV, source map, review
bundle, and Markdown report as the source of truth.

## Command Runner

Prefer an installed command:

```bash
refgate --help
refgate paper-audit --help
```

If the command is unavailable and this source checkout is the current project,
use:

```bash
PYTHONPATH=src python3 -m refgate --help
```

## Operating Rules

- Keep core verification in the CLI. Do not move the workflow into a server
  layer.
- Never label generated or manually normalized BibTeX as an official export.
- Official record verification and official BibTeX export verification are
  separate gates.
- Discovery sources are not final authorities by default.
- Abstracts, summaries, and metadata snippets are weak evidence only. They must
  not make a citation-bearing claim checked.
- Prefer full-source body passages over title-like or abstract-like snippets
  when writing claim review results.
- Live network work is opt-in only.
- If a Refgate command returns `ok=false`, continue through the listed
  `next_actions` or report the remaining blocker clearly.
- Keep private manuscript material, local absolute paths, and credential
  material out of public repo artifacts.

## Common Paper Flow

For an ordinary paper repository with only `.tex` and `.bib`, run `paper-audit`
first. It creates starter lock and claim files, writes resolver work items, runs
the audit, and returns deterministic next actions.
The root TeX file may use `\input{...}` or `\include{...}`; Refgate resolves
those children and records source-file/line hints for claim review navigation.

Use `.claude/commands/refgate/*.md` project slash commands when working in
Claude Code. The command names are:

- `/refgate-paper-audit`
- `/refgate-reference-check`
- `/refgate-claim-review`
- `/refgate-run-next`
- `/refgate-final-audit`
- `/refgate-publish-check`
