# Reviewed Live Smoke Manifest

Default Refgate tests do not use the network. Live smoke is an operational
check for external endpoints and should be run only when explicitly requested.
The reviewed manifest records cache checksums so later checks can compare
endpoint behavior without turning live network into the default test path.

## Generate A Reviewed Manifest

Use a small live batch first:

```bash
refgate live-smoke-suite --queries refgate_queries.json --source arxiv --cache-root .refgate/cache --max-queries 3 --prefer-cache --min-interval-seconds 3 --retry 2 --retry-after-seconds 10 --write-manifest .refgate/cache_manifest.reviewed.json --live --json
```

Review the output before preserving the manifest:

- every query has the expected source and citation key;
- failures are understood as endpoint/rate-limit issues or real lookup gaps;
- cache paths point inside the paper repo's `.refgate/cache`;
- the manifest contains checksums, not private manuscript text or credentials.

Do not commit `.refgate/cache` or reviewed cache manifests to the public
Refgate repository. If a project needs durable evidence, store the reviewed
manifest in that project's private artifact store or attach it to a release
review outside the source tree.

## Compare Against A Reviewed Manifest

Checksum comparison is network-free:

```bash
refgate live-smoke-suite --queries refgate_queries.json --source arxiv --cache-root .refgate/cache --manifest .refgate/cache_manifest.reviewed.json --json
```

If comparison fails, inspect the changed cache entry and decide whether it is an
expected endpoint update, a parser regression, or a reference provenance
problem. Do not update a reviewed manifest just to make CI pass.

## Safety Boundary

- Live smoke does not make a manuscript submission-ready by itself.
- Fixture tests prove Refgate behavior; live smoke checks current endpoint
  availability and cache consistency.
- `reference-check` and claim/source audit still decide whether a specific
  paper's references and citation claims are verified.
