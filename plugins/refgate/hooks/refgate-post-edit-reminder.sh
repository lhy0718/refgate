#!/usr/bin/env sh
set -eu

project_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$project_dir"

changed_files="$(git diff --name-only 2>/dev/null || true)"

case "$changed_files" in
  *".tex"*|*".bib"*|*"refgate.lock.json"*|*"refgate_claims.tsv"*|*"refgate_source_map.tsv"*)
    printf '%s\n' "Refgate reminder: manuscript, bibliography, lock, claim, or source-map files changed. Run /refgate-paper-audit or /refgate-final-audit before reporting completion."
    ;;
esac
