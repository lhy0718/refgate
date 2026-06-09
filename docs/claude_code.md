# Claude Code Integration

Refgate includes a Claude Code command pack, a project `CLAUDE.md`, and an
opt-in hook example. This integration keeps Refgate CLI-first: Claude Code
receives workflow prompts, while the executable verification engine remains the
`refgate` command.

Official Claude Code references:

- Custom slash commands: https://docs.anthropic.com/en/docs/claude-code/slash-commands
- Hooks: https://docs.anthropic.com/en/docs/claude-code/hooks
- Settings: https://docs.anthropic.com/en/docs/claude-code/settings

## Included Files

- `CLAUDE.md`: project guidance for Claude Code.
- `.claude/commands/refgate/refgate-paper-audit.md`
- `.claude/commands/refgate/refgate-reference-check.md`
- `.claude/commands/refgate/refgate-claim-review.md`
- `.claude/commands/refgate/refgate-run-next.md`
- `.claude/commands/refgate/refgate-final-audit.md`
- `.claude/commands/refgate/refgate-publish-check.md`
- `.claude/hooks/refgate-post-edit-reminder.sh`
- `.claude/settings.refgate.example.json`

Claude Code derives project slash command names from Markdown filenames. The
commands are therefore:

- `/refgate-paper-audit`
- `/refgate-reference-check`
- `/refgate-claim-review`
- `/refgate-run-next`
- `/refgate-final-audit`
- `/refgate-publish-check`

## Using In A Paper Repository

Install or expose the CLI first:

```bash
python -m pip install git+https://github.com/lhy0718/refgate.git
refgate --help
```

For source-checkout use, install from the Refgate repository:

```bash
python -m pip install -e ".[dev]"
```

Then copy the command files and `CLAUDE.md` into a manuscript repository, or
keep them in Refgate and ask Claude Code to call the installed `refgate`
command from the paper repository.

For a generic `.tex` plus `.bib` repository, start with:

```bash
refgate paper-audit --tex paper.tex --bib references.bib --lock refgate.lock.json --claims refgate_claims.tsv --report refgate_audit.md --resolver-output refgate_queries.json --next-plan-output .refgate/next_plan.json --submission --json
```

The first run may intentionally return `ok=false`; that is the gate showing
which references lack provenance and which claims still need source evidence.
Do not mask that result. Treat `warnings` as unresolved review work, but treat
`accepted_provenance_notes` as verified provenance records such as reviewed
arXiv fallback or reviewed DOI absence. Read `.refgate/next_plan.json` with:

```bash
refgate run-next --from .refgate/next_plan.json --json
```

When reviewed offline provenance inputs are ready, use the command field the
plan provides:

```bash
refgate run-next --from .refgate/next_plan.json --command-field reference_check_command --allow-writes --allow-human-review --max-actions 1 --execute --write-run-log .refgate/next_run_log.json --json
refgate run-summary --input .refgate/next_plan.json --input .refgate/next_run_log.json --markdown .refgate/next_summary.md --json
```

Multi-file manuscripts are supported through `\input{...}` and
`\include{...}` from the root TeX file. Claude Code should treat source-file
and line hints in `refgate_claims.tsv`, `refgate_audit.md`, and
`.refgate/codex_review_bundle.md` as the navigation surface for claim review.

For CI, copy `examples/paper-repo/.github/workflows/refgate-paper-audit.yml`
and keep `paper-audit` as the default entry point.

## Optional Hook

The included hook is a reminder, not an automatic verifier. To opt in, copy the
example settings file to the project-local Claude Code settings file:

```bash
cp .claude/settings.refgate.example.json .claude/settings.local.json
chmod +x .claude/hooks/refgate-post-edit-reminder.sh
```

After edits to manuscript, bibliography, lock, claim, or source-map files, the
hook prints a reminder to rerun the relevant Refgate command.

## Safety Rules

- Live network checks remain opt-in.
- `ok=false` is not failure noise; it is a deterministic blocker report.
- Manual or generated BibTeX must never be marked as official export.
- Abstracts, summaries, and metadata snippets are weak evidence only.
- Title-like and abstract-like snippets are review hints; prefer full-source
  body passages when writing Codex review JSONL.
- Final claim status requires full-source evidence and review.
