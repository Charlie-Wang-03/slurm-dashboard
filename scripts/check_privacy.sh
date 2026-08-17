#!/usr/bin/env bash
# check_privacy.sh — publish gate for slurm-dashboard.
#
# Scans the working tree and the `main` branch history for personal
# identifiers: usernames, emails, absolute paths, hostnames.
# Exit code 0 = clean; 1 = findings (list them and stop the publish).
#
# Usage:
#   scripts/check_privacy.sh                  # working tree + main history
#   scripts/check_privacy.sh --worktree-only  # skip the git history scan
#
# Scope notes:
# - The history scan covers `main` only. Snapshots and pushes are
#   main-only (see make_snapshot.sh); local rollback chains (dev-wip,
#   legacy, stale personal branches) never leave this machine.
# - Fail-closed: if a scan itself errors, the gate FAILS — an
#   unverifiable check is never treated as a pass.

set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-full}"
# Patterns are assembled from fragments so this script itself does not
# contain the personal identifiers it scans for.
PATTERNS=(
  'charli'"ewang"
  'Kinghorse'"YMPC"
  'nisho'"me"
  '/home/'"charli""ewang"
  '@users\.noreply\.github\.com'
  "$(hostname)"
)

# Runtime directories never enter git; skip them in the worktree scan.
EXCLUDED_DIRS=(.git .venv data logs workspace tmp_downloads .pytest_cache .code-review-graph node_modules)
exclude_args=()
for d in "${EXCLUDED_DIRS[@]}"; do
  exclude_args+=( --exclude-dir="$d" )
done
# Local private config files are gitignored and never published.
exclude_args+=( --exclude='config.local.json' --exclude='dashboard.config.json' --exclude='*.local.json' )

pattern_regex=$(IFS='|'; echo "${PATTERNS[*]}")

failures=0
report() { echo "FAIL: $1"; failures=1; }

echo "== check_privacy: working tree =="
worktree_hits=$(mktemp)
rc=0
grep -rniIlE "$pattern_regex" . "${exclude_args[@]}" > "$worktree_hits" || rc=$?
if [ "$rc" -gt 1 ]; then
  report "worktree scan errored (grep rc=$rc) — cannot verify, treating as FAIL"
fi
while IFS= read -r hit; do
  [ -n "$hit" ] || continue
  report "personal identifier in: $hit"
done < "$worktree_hits"
rm -f "$worktree_hits"

if [ "$MODE" != "--worktree-only" ]; then
  echo "== check_privacy: git history (main) =="
  commits=$(git rev-list main 2>/dev/null || true)
  if [ -n "$commits" ]; then
    hist_hits=$(mktemp)
    rc=0
    git grep -niIlE "$pattern_regex" $commits > "$hist_hits" || rc=$?
    if [ "$rc" -gt 1 ]; then
      report "history scan errored (git grep rc=$rc) — cannot verify, treating as FAIL"
    fi
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      report "history: $line"
    done < "$hist_hits"
    rm -f "$hist_hits"
  else
    echo "  (no commits on main yet)"
  fi
fi

if [ "$failures" -ne 0 ]; then
  echo "== check_privacy: FAILED =="
  exit 1
fi
echo "== check_privacy: PASS =="
