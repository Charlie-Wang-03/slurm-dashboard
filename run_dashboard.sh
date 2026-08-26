#!/usr/bin/env bash
# run_dashboard.sh — serve slurm-dashboard from the repo .venv.
#
#   ./run_dashboard.sh            # 127.0.0.1:7860
#   PORT=7861 ./run_dashboard.sh  # dev instance
#
# Binds 127.0.0.1 only; access from elsewhere via SSH port forwarding.

set -euo pipefail
cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-7860}"

# The dashboard has no authentication and is designed for loopback
# access only (SSH port forwarding). Refuse anything else so a simple
# `HOST=0.0.0.0` cannot silently expose it to the network.
case "$HOST" in
  127.* | localhost | "::1" | "0:0:0:0:0:0:0:1") ;;
  *)
    echo "error: refusing to bind to '$HOST' — the dashboard is loopback-only." >&2
    echo "       See README \"Security notes\". For remote access use:" >&2
    echo "       ssh -L 7860:127.0.0.1:7860 user@your-server" >&2
    exit 1
    ;;
esac

if [ ! -x .venv/bin/uvicorn ]; then
  echo "error: .venv not found — run ./install.sh first" >&2
  exit 1
fi

echo "serving slurm-dashboard on http://${HOST}:${PORT}"
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT"
