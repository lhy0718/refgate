# Codex Plugin Distribution

Refgate can be packaged as a Codex plugin because the official plugin structure
uses a `.codex-plugin/plugin.json` manifest plus optional `skills/`, hooks,
apps, MCP config, and assets. This repository includes a repo-local plugin at
`plugins/refgate-reference-gate` and a repo-local marketplace catalog at
`.agents/plugins/marketplace.json`.

The plugin is an agent UX package, not the verification engine. It teaches
Codex how to run Refgate safely. The deterministic source of truth remains the
`refgate` CLI, `refgate.lock.json`, `refgate_claims.tsv`, and generated audit
reports.

## Skill vs Plugin

- Skill: the procedural instructions Codex loads when a manuscript reference,
  BibTeX, citation claim, or source-evidence task needs Refgate.
- Plugin: the installable package that contains the skill, catalog metadata,
  icon, preview asset, and manifest.
- CLI: the executable verifier. The plugin assumes users have installed
  Refgate or are working from a source checkout where `python -m refgate` works.

The plugin intentionally does not add an MCP server. Core verification should
stay reproducible from shell, CI, and agent sessions.

## Local Verification

1. Install or verify the CLI. From GitHub, use:

   ```bash
   python -m pip install git+https://github.com/lhy0718/refgate.git
   refgate --help
   ```

   From a source checkout, use:

   ```bash
   python -m pip install -e ".[dev]"
   refgate --help
   ```

2. Verify this repository:

   ```bash
   python -m pytest -q
   python -m refgate publish-check --root . --json
   ```

3. Verify the plugin package files:

   ```bash
   python -m pytest tests/test_plugin_packaging.py -q
   ```

4. In Codex, add or open the repo-local marketplace catalog:

   ```text
   .agents/plugins/marketplace.json
   ```

5. Install `Refgate Reference Gate` from the `Refgate Local` catalog.
6. Ask Codex to bootstrap or audit a manuscript with ordinary `.tex` and `.bib`
   files. The skill should start with `paper-audit`, inspect `next_actions`,
   and keep `ok=false` blockers visible instead of treating them as success.

## Public Distribution Readiness

Before sharing beyond local testing:

- keep homepage and repository URLs pointed at `https://github.com/lhy0718/refgate`;
- add a stable version and release tag;
- ensure the released CLI version and plugin manifest version match;
- review the included icon and CLI screenshot under
  `plugins/refgate-reference-gate/assets/`;
- keep the plugin skill free of local absolute paths;
- keep private manuscripts, downloaded PDFs, reviewed live caches, and local
  agent artifacts out of the plugin package;
- run `refgate publish-check --root . --json`;
- run the standard test suite.
- verify `examples/paper-repo/AGENTS.md` and
  `examples/paper-repo/.github/workflows/refgate-paper-audit.yml` still use
  `paper-audit` as the first command.

## Expected Alpha Behavior

The plugin should help Codex:

- bootstrap `refgate.lock.json` and `refgate_claims.tsv` from `.tex` and `.bib`;
- run `audit-bib`, `paper-audit`, `reference-check`, `download-sources`,
  `export-review-bundle`, and `import-review` in the right order;
- require explicit opt-in for live network commands;
- keep generated/manual BibTeX separate from official exports;
- treat source-title mismatches and unchecked/too-strong claims as blockers;
- report remaining blockers honestly rather than rewriting artifacts to pass.

It does not promise to make a manuscript submission-ready without reviewed
source provenance and claim evidence.

## Paper Repo Setup Prompt

After installing the plugin, a good first instruction to Codex in a manuscript
repository is:

```text
Use Refgate to audit this TeX/BibTeX paper. Start with paper-audit, save the
next-action plan, inspect blockers, and do not use live network unless I
explicitly approve it.
```

The plugin should then produce or inspect:

- `refgate.lock.json`
- `refgate_claims.tsv`
- `refgate_audit.md`
- `refgate_queries.json`
- `.refgate/next_plan.json`

## Official Documentation Checked

OpenAI's Codex plugin docs describe repo and personal marketplace catalogs, the
required plugin manifest, marketplace metadata, Git-backed sources, and local
install verification. The current public path is:

https://developers.openai.com/codex/plugins/build
