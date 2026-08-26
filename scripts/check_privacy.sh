#!/usr/bin/env bash
# check_privacy.sh — publish gate for slurm-dashboard.
#
# Scans the working tree and all reachable Git refs for common personal
# identifiers and environment-specific paths. Exit code 0 = clean;
# 1 = findings (list them and stop the publish).
#
# Usage:
#   scripts/check_privacy.sh                  # working tree + reachable history
#   scripts/check_privacy.sh --worktree-only  # skip the git history scan
#
# scripts/check_secrets.py complements this with credential-oriented patterns.
# Fail-closed: if a scan itself errors, the gate FAILS.

set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-full}"

escape_regex() {
  printf '%s' "$1" | sed 's/[][\\.^$*+?(){}|]/\\&/g'
}

PATTERNS=(
  '[[:alnum:]._%+-]+@[[:alnum:].-]+\.[A-Za-z]{2,}'
  # Generic home-like mount detection: matches any <mount>home/<user>
  # style path without naming a specific server mount layout.
  # Require at least two username characters to avoid the intentionally
  # synthetic /home/u/... fixture used by legacy migration tests.
  '/[A-Za-z0-9._-]*home/[A-Za-z0-9._-]{2,}'
  '[A-Za-z]:\\\\Users\\\\[A-Za-z0-9._-]{2,}'
)

# On a maintainer workstation, derive local identifiers at runtime instead of
# committing personal values to the repository. Do not add CI runner identity
# (for example generic runner usernames/hostnames) because that creates noisy
# false positives unrelated to the maintainer's environment.
if [ "${CI:-}" != "true" ]; then
  for value in "${USER:-}" "${HOME:-}" "$(hostname 2>/dev/null || true)"; do
    case "$value" in
      ""|root|runner|ubuntu) continue ;;
    esac
    if [ "${#value}" -ge 4 ]; then
      PATTERNS+=("$(escape_regex "$value")")
    fi
  done
fi

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
  echo "== check_privacy: git history (all reachable refs) =="
  commits=$(git rev-list --all 2>/dev/null || true)
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
    echo "  (no reachable commits found)"
  fi
fi

if [ "$failures" -ne 0 ]; then
  echo "== check_privacy: FAILED =="
  exit 1
fi
echo "== check_privacy: PASS =="
