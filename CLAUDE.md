# CLAUDE.md — slurm-dashboard

Teaching dashboard for SLURM/Linux beginners. FastAPI + Jinja2 + SQLite.
Binds to 127.0.0.1 only; access via SSH port forwarding.

## Environment

- `.venv/` is the **only** Python environment for this repo
- Never use the system `python3` for repo commands

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 7861   # dev instance
.venv/bin/python -m pytest tests/ -x -q --tb=short             # tests
.venv/bin/pip install -r requirements.txt                      # deps
.venv/bin/python tools/gpu_monitor.py                          # history collector
```

## Hard rules

- Bind `127.0.0.1` only. `0.0.0.0` / `::` / `*` are rejected at config load.
- subprocess calls use list arguments — never `shell=True`.
- No arbitrary command-execution pages; sbatch parameters are whitelisted.
- `config.local.json`, `data/`, `logs/`, `workspace/` never enter git.
- Run `scripts/check_privacy.sh` before any publish (working tree + git history).

## Reading order for this codebase

| Doc | Purpose |
|-----|---------|
| [AGENTS.md](AGENTS.md) | AI-agent rules, workflows, output conventions |
| [docs/architecture.md](docs/architecture.md) | Architecture, configuration model, route table, DB schema |
| [docs/testing.md](docs/testing.md) | Manual acceptance walk-through and security regression |
| [README.md](README.md) | What the project is and how to run it |
