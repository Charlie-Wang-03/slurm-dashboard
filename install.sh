#!/usr/bin/env bash
# install.sh — create the repo .venv and install dependencies.
#
#   ./install.sh                 # uses python3
#   PYTHON_BIN=python3.11 ./install.sh
#
# The dashboard must never use the system Python directly; everything
# runs from .venv/ after this script completes.

set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "== slurm-dashboard install =="
echo "Python: $("$PYTHON_BIN" --version 2>&1)"

# Runtime state can contain usernames, job metadata and GPU history.
# Keep these directories private even on systems whose default umask is 022.
mkdir -p data logs
chmod 700 data logs

if [ ! -d .venv ]; then
  echo "== creating .venv =="
  "$PYTHON_BIN" -m venv .venv
fi

echo "== installing dependencies =="
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

echo "== dependency check =="
.venv/bin/python -c "import fastapi, jinja2, uvicorn, multipart; print('deps OK')"

echo "== SLURM tool check (optional — dashboard still runs without) =="
for tool in sbatch squeue sacct scancel sinfo; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "  $tool: OK"
  else
    echo "  $tool: missing"
  fi
done

echo
echo "== install complete =="
echo "Start the dashboard with: ./run_dashboard.sh"
