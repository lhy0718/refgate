---
description: Execute or summarize deterministic Refgate next actions
argument-hint: [paper-audit-json]
---

Inspect Refgate `next_actions` from a saved JSON response and execute only safe,
explicitly allowed actions.

Input:

- saved paper-audit JSON path: `$1`

Use `refgate` if installed. If not installed and this is a Refgate source
checkout, use `PYTHONPATH=src python3 -m refgate`.

First inspect without execution:

```bash
refgate run-next --from PAPER_AUDIT_JSON --output-plan .refgate/next_plan.json --json
```

Read `recommended_next`, `agent_hint`, `skip_reason`, and
`available_command_fields` before executing. Prefer the command field that
matches the reviewed input you actually have, such as
`reference_check_command` for offline official HTML/BibTeX review.

Execute only if the action metadata and user request allow it. For write-only
actions:

```bash
refgate run-next --from PAPER_AUDIT_JSON --allow-writes --max-actions 1 --execute --write-run-log .refgate/next_run_log.json --json
refgate run-summary --input .refgate/next_plan.json --input .refgate/next_run_log.json --markdown .refgate/next_summary.md --json
```

Do not enable live network or human-review actions unless the user explicitly
requested that scope.
