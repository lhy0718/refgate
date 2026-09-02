# Claude Code Integration

Refgate ships its Claude Code surface as a single plugin, `plugins/refgate`,
plus a project `CLAUDE.md`. This integration keeps Refgate CLI-first: Claude
Code receives workflow prompts, while the executable verification engine remains
the `refgate` command.

The plugin is the only supported Claude Code surface. Do not copy the command
Markdown files into a project-level `.claude/commands/refgate/` directory; that
duplicates every command under the same `refgate:` namespace. The same applies
to a project-level copy of the reminder hook, which would fire twice.
`tests/test_claude_code_plugin.py` fails if those superseded paths reappear.

Official Claude Code references:

- Plugins: https://docs.anthropic.com/en/docs/claude-code/plugins
- Custom slash commands: https://docs.anthropic.com/en/docs/claude-code/slash-commands
- Hooks: https://docs.anthropic.com/en/docs/claude-code/hooks
- Settings: https://docs.anthropic.com/en/docs/claude-code/settings

## Included Files

- `CLAUDE.md`: project guidance for Claude Code.
- `.claude-plugin/marketplace.json`: repo-local marketplace catalog.
- `plugins/refgate/.claude-plugin/plugin.json`: plugin manifest.
- `plugins/refgate/commands/refgate-paper-audit.md`
- `plugins/refgate/commands/refgate-reference-check.md`
- `plugins/refgate/commands/refgate-claim-review.md`
- `plugins/refgate/commands/refgate-run-next.md`
- `plugins/refgate/commands/refgate-final-audit.md`
- `plugins/refgate/commands/refgate-publish-check.md`
- `plugins/refgate/skills/refgate/SKILL.md`
- `plugins/refgate/hooks/hooks.json`
- `plugins/refgate/hooks/refgate-post-edit-reminder.sh`

Claude Code namespaces plugin slash commands as `/<plugin>:<file-stem>`. The
commands are therefore:

- `/refgate:refgate-paper-audit`
- `/refgate:refgate-reference-check`
- `/refgate:refgate-claim-review`
- `/refgate:refgate-run-next`
- `/refgate:refgate-final-audit`
- `/refgate:refgate-publish-check`

## Installing The Plugin

Add the marketplace catalog, then install:

```bash
claude plugin marketplace add lhy0718/refgate
claude plugin install refgate@refgate-local
```

From a local checkout, point the marketplace at the checkout directory instead
of the GitHub repository:

```bash
claude plugin marketplace add ./path/to/refgate
```

Installation copies `plugins/refgate` into a version-pinned cache directory. The
cache is a snapshot, not a symlink, so edits under `plugins/refgate` take effect
only after reinstalling or updating the plugin. Bump `version` in
`plugins/refgate/.claude-plugin/plugin.json` when changing plugin contents.

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

Then install the `refgate` plugin as above. The plugin is installed per user, so
its commands, skill, and hook are available in every manuscript repository
without copying files. Copy only `CLAUDE.md` into the manuscript repository when
that repository needs the Refgate operating rules in its own project guidance.

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
refgate run-next --from .refgate/next_plan.json --command-field reference_check_command --allow-writes --allow-review --max-actions 1 --execute --write-run-log .refgate/next_run_log.json --json
refgate run-summary --input .refgate/next_plan.json --input .refgate/next_run_log.json --markdown .refgate/next_summary.md --json
```

Multi-file manuscripts are supported through `\input{...}` and
`\include{...}` from the root TeX file. Claude Code should treat source-file
and line hints in `refgate_claims.tsv`, `refgate_audit.md`, and
`.refgate/codex_review_bundle.md` as the navigation surface for claim review.

For CI, copy `examples/paper-repo/.github/workflows/refgate-paper-audit.yml`
and keep `paper-audit` as the default entry point.

## Post-Edit Reminder Hook

The plugin registers a `PostToolUse` hook through
`plugins/refgate/hooks/hooks.json`. Installing the plugin is the opt-in step;
no settings file needs to be copied. Disabling or uninstalling the plugin
removes the hook.

After edits to manuscript, bibliography, lock, claim, or source-map files, the
hook prints a reminder to rerun the relevant Refgate command. The hook is a
reminder, not an automatic verifier: it never runs `refgate`, never writes
files, and never blocks a tool call.

## Safety Rules

- Live network checks remain opt-in.
- `ok=false` is not failure noise; it is a deterministic blocker report.
- Manual or generated BibTeX must never be marked as official export.
- Abstracts, summaries, and metadata snippets are weak evidence only.
- Title-like and abstract-like snippets are review hints; prefer full-source
  body passages when writing Codex review JSONL.
- Final claim status requires full-source evidence and review.
