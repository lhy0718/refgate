# Release Process

Refgate can be installed directly from GitHub. PyPI publication is optional.
The default GitHub release workflow tests the package, runs publish hygiene, and
builds distribution artifacts. It does not publish to a package index.

## Preflight

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m compileall src tests
PYTHONPATH=src python3 -m refgate publish-check --root . --json
python -m build
```

Also check the agent packaging surfaces before tagging:

```bash
python -m pytest tests/test_plugin_packaging.py tests/test_claude_code_pack.py tests/test_docs_examples.py -q
```

If build isolation is unavailable in a locked-down environment, first install
the `dev` extra above and run `python -m build --no-isolation`. Do not add
long-lived package-index credentials to the repository to work around local
network restrictions.

## Paper Repo Template Check

The release should include a copyable paper-repo entry point:

- `examples/paper-repo/AGENTS.md`
- `examples/paper-repo/.github/workflows/refgate-paper-audit.yml`
- `docs/paper_repo_ci.md`

The workflow must run `refgate paper-audit` directly and upload Refgate
artifacts. Do not hide `ok=false` with shell fallbacks; a non-zero result is the
submission gate reporting unresolved provenance or claim evidence.

## Reviewed Live Smoke Evidence

Live smoke is not part of the default test suite. Before a release candidate,
optionally run a small live batch and review the manifest outside the public
source tree:

```bash
refgate live-smoke-suite --queries refgate_queries.json --source arxiv --cache-root .refgate/cache --max-queries 3 --prefer-cache --min-interval-seconds 3 --retry 2 --retry-after-seconds 10 --write-manifest .refgate/cache_manifest.reviewed.json --live --json
```

Keep `.refgate/cache` and reviewed manifests out of the public repository. See
`docs/live_smoke_reviewed_manifest.md` for the operating procedure.

## Release Candidate Tag

Tag a release candidate only after the preflight succeeds:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The GitHub workflow builds `dist/*` for the tag and uploads it as a workflow
artifact. Publish to a package index only after the project name and external
publisher settings are reviewed outside the repository.

## Optional PyPI Publication

1. Create or claim the `refgate` project on PyPI.
2. Review package metadata and the workflow artifact from a tagged build.
3. Publish from the reviewed artifact using the package index's recommended
   identity-based flow.

Do not store long-lived package-index credentials in this repository.

## Agent Package Distribution

Codex plugin distribution and Claude Code command packs are release-adjacent,
not replacements for the CLI. Before announcing them:

- ensure `plugins/refgate-reference-gate/.codex-plugin/plugin.json` version
  matches `pyproject.toml`;
- run `python -m pytest tests/test_plugin_packaging.py -q`;
- check `docs/codex_plugin_distribution.md`;
- check `docs/claude_code.md`;
- confirm command examples still start with `paper-audit`, preserve `ok=false`
  blockers, and keep live network checks opt-in.
