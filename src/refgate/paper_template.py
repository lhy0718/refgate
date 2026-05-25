from __future__ import annotations

from pathlib import Path
from typing import Any


def render_paper_agents_template(
    *,
    tex: str,
    bib: str,
    lock: str,
    claims: str,
    report: str,
    command: str = "python -m refgate",
) -> str:
    return f"""# Refgate Paper Reference Gate

Use Refgate before changing references, BibTeX entries, citation keys, or citation-bearing claims.

## Paths

- Manuscript TeX: `{tex}`
- Bibliography: `{bib}`
- Refgate lockfile: `{lock}`
- Claim table: `{claims}`
- Audit report: `{report}`

## Commands

Run `paper-audit` first for ordinary paper repositories. It creates missing
starter artifacts, writes resolver work items, writes the Markdown report, and
saves a deterministic next-action plan:

```bash
{command} paper-audit --tex {tex} --bib {bib} --lock {lock} --claims {claims} --report {report} --resolver-output refgate_queries.json --next-plan-output .refgate/next_plan.json --submission --json
```

Inspect the plan without executing it:

```bash
{command} run-next --from .refgate/next_plan.json --json
```

If reviewed official HTML, official BibTeX, or manual fallback files have been
added, execute the reference-check action only after inspecting the plan:

```bash
{command} run-next --from .refgate/next_plan.json --command-field reference_check_command --allow-writes --allow-human-review --max-actions 1 --execute --write-run-log .refgate/next_run_log.json --json
{command} run-summary --input .refgate/next_plan.json --input .refgate/next_run_log.json --json
```

After provenance updates, plan a lockfile-backed bibliography synchronization:

```bash
{command} sync-bibtex --bib {bib} --lock {lock} --json
```

Run the source-backed submission gate when citation-key named source files are
available under `sources/`:

```bash
{command} paper-audit --tex {tex} --bib {bib} --lock {lock} --claims {claims} --report {report} --source-dir sources --source-map-output refgate_source_map.tsv --claim-review-output refgate_claim_review.md --submission --json
```

Run the frozen final gate:

```bash
{command} audit --tex {tex} --bib {bib} --lock {lock} --claims {claims} --frozen --submission --report {report} --json
```

## CI Entry Point

Use `paper-audit` as the CI smoke gate and upload generated artifacts for
review. CI may return non-zero while provenance or claim evidence is incomplete;
that is a real blocker, not noise.

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
          --tex {tex}
          --bib {bib}
          --lock {lock}
          --claims {claims}
          --report {report}
          --resolver-output refgate_queries.json
          --next-plan-output .refgate/next_plan.json
          --submission
          --json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: refgate-audit
          path: |
            {lock}
            {claims}
            {report}
            refgate_queries.json
            .refgate/next_plan.json
```

## Rules

- Generated or manually normalized BibTeX is never an official export.
- Discovery sources are not final authorities unless Refgate marks them as such.
- Live network checks are opt-in.
- Abstracts, summaries, and metadata snippets are weak evidence only.
- Keep final claim status in the TSV; evidence suggestions require human review.
- If a Refgate command returns `ok=false`, report the blocker or keep following
  safe next actions; do not call the paper verified.
"""


def write_paper_agents_template(
    output_path: str | Path,
    *,
    tex: str,
    bib: str,
    lock: str,
    claims: str,
    report: str,
    command: str = "python -m refgate",
) -> dict[str, Any]:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = render_paper_agents_template(
        tex=tex,
        bib=bib,
        lock=lock,
        claims=claims,
        report=report,
        command=command,
    )
    target.write_text(text, encoding="utf-8")
    return {"output": str(target), "bytes": len(text.encode("utf-8"))}
