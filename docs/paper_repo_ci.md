# Paper Repository CI

Use `paper-audit` as the default Refgate entry point in manuscript
repositories. It works for the common starting point where a paper has only a
TeX file and a BibTeX file, then creates the starter lockfile, claim TSV,
resolver work items, audit report, and next-action manifest.

## Minimal GitHub Actions Example

Copy `examples/paper-repo/.github/workflows/refgate-paper-audit.yml` into a
paper repository and replace paths if the manuscript is not named `paper.tex`
and `references.bib`.

```yaml
name: refgate-paper-audit

on:
  pull_request:
  workflow_dispatch:

jobs:
  refgate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install git+https://github.com/lhy0718/refgate.git
      - run: mkdir -p .refgate
      - run: >
          refgate paper-audit
          --tex paper.tex
          --bib references.bib
          --lock refgate.lock.json
          --claims refgate_claims.tsv
          --report refgate_audit.md
          --resolver-output refgate_queries.json
          --next-plan-output .refgate/next_plan.json
          --submission
          --json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: refgate-audit
          path: |
            refgate.lock.json
            refgate_claims.tsv
            refgate_audit.md
            refgate_queries.json
            .refgate/next_plan.json
```

`ok=false` is expected for new papers until reference provenance and
claim-to-source evidence are filled. Treat it as a blocker report. Do not mask
the failure with `|| true`; upload the artifacts so a reviewer or agent can
follow `next_actions`.

## Agent Loop

After the CI artifact or local `paper-audit` run exists, inspect next actions:

```bash
refgate run-next --from .refgate/next_plan.json --json
```

Execute only reviewed actions. For offline provenance inputs, populate the
directories named in the action, then run:

```bash
refgate run-next --from .refgate/next_plan.json --command-field reference_check_command --allow-writes --allow-human-review --max-actions 1 --execute --write-run-log .refgate/next_run_log.json --json
refgate run-summary --input .refgate/next_plan.json --input .refgate/next_run_log.json --markdown .refgate/next_summary.md --json
```

Live network checks are separate from CI and require explicit opt-in.
