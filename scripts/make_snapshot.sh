#!/usr/bin/env bash
# make_snapshot.sh — publish gate + distributable snapshot.
#
#   1. check_privacy.sh (working tree + git history)
#   2. clean working tree check
#   3. git bundle + tarball into $SNAPSHOT_DIR
#
# The git bundle and tarball are the distributable artifacts. They are
# only produced when the privacy gate and the clean-tree check pass.

set -euo pipefail
cd "$(dirname "$0")/.."

SNAPSHOT_DIR="${SNAPSHOT_DIR:-$HOME/slurm-dashboard-snapshots}"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "== 1. privacy gate =="
scripts/check_privacy.sh

echo "== 2. clean tree =="
if [ -n "$(git status --porcelain)" ]; then
  echo "error: working tree is dirty, refusing to snapshot" >&2
  git status --porcelain | head -20
  exit 1
fi

mkdir -p "$SNAPSHOT_DIR"
echo "== 3. bundle + tarball =="
# Bundle the clean `main` branch only — legacy/dev-wip history stays local.
git bundle create "$SNAPSHOT_DIR/slurm-dashboard-$STAMP.bundle" main
git archive --format=tar.gz -o "$SNAPSHOT_DIR/slurm-dashboard-$STAMP.tar.gz" HEAD

echo
echo "snapshots written to $SNAPSHOT_DIR:"
ls -lh "$SNAPSHOT_DIR"/slurm-dashboard-$STAMP.*
