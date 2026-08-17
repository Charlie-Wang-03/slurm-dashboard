# AGENTS.md — working rules for AI agents

This file tells AI coding agents (Claude Code, Codex, Cursor, …) how to
work safely on slurm-dashboard. Human contributors can skim it too.

## What this project is

A small teaching dashboard for people who are new to SLURM and Linux.
Pages: Cluster Status (with a 5-minute GPU history monitor — day /
week / month / year charts), Jobs (list + detail), Submit Job (paste /
workspace picker / upload; `.py` files get wrapped into an sbatch
automatically), Environment Check. A first-run wizard asks where to
store scripts and outputs. The UI is bilingual (English default,
Simplified Chinese) — switchable via `?lang=` in the nav bar, or
detected from `ui_lang` config / Accept-Language.

## Non-negotiables

1. **Bind 127.0.0.1 only.** The config loader rejects `0.0.0.0`, `::`
   and `*`. Never "fix" this to allow remote access — access is via SSH
   port forwarding.
2. **No arbitrary command execution.** No page may run a user-supplied
   command. SLURM submission parameters are whitelisted
   (partition / gres / cpus / mem / time / name); script files must have
   a `.sh`/`.sbatch`/`.py` extension and no directory components.
   Python files are wrapped into an sbatch with a shlex-quoted
   `python3 <script>` line — the job runs on the compute node, where the
   dashboard's `.venv` does not exist, so the wrapper uses the node's
   own `python3` (see `app/slurm.py::build_python_wrapper`).
3. **subprocess uses list arguments, never `shell=True`.**
4. **Path safety.** User-supplied paths are resolved with
   `Path.expanduser().resolve()` and checked against allowed roots
   (`app/security.py`); system directories are rejected
   (`app/config.py::_reject_dangerous_root`).
5. **Runtime data never enters git.** `config.local.json`, `data/`,
   `logs/`, `workspace/` are gitignored. Before any publish, run
   `scripts/check_privacy.sh` (scans working tree + git history).
6. **`.venv/` is the only Python environment.** Use
   `.venv/bin/python`, `.venv/bin/pip`, `.venv/bin/uvicorn`. Never the
   system `python3`.

## Architecture map

```
app/
  main.py          FastAPI app, first-run guard + csrf_origin_guard + language_switch middleware
  config.py        Settings dataclass, whitelist validation, reload_settings()
  i18n.py          en/zh string dictionaries, language detection
  security.py      allowed-roots and path checks
  slurm.py         sbatch/squeue/sacct/scancel wrappers (whitelisted)
  database.py      SQLite jobs table + legacy migration
  job_store.py     job record CRUD
  cluster_status.py  read-only status collectors (sinfo/squeue/df/free/nvidia-smi)
  env_check.py     tool availability + config summary
  gpu_history.py   aggregation for the GPU history charts (data/gpu_history/)
  routers/         home, status, jobs, submit, env_check, setup
  templates/       Jinja2, i18n via {{ strings['key'] }}
  static/app.css   theming (light/dark/system)
  static/vendor/   vendored Chart.js (no CDN)
tests/             pytest suite — keep green: .venv/bin/python -m pytest tests/ -x -q
tools/             gpu_monitor.py (crontab collector)
scripts/           check_privacy.sh (publish gate), make_snapshot.sh
```

## Workflows

### Fixing a bug

1. Reproduce it; write a failing test first when the behaviour is
   testable.
2. Fix, run the full suite, start a dev instance on **7861** (never the
   production 7860) and verify the page.
3. Commit with an English message.

### Adding UI text

All visible strings live in `app/i18n.py` under `en` and `zh`. Add both
languages; page titles come from the strings dictionary
(`strings['<page>.title']`). Command outputs stay in their original
language — only chrome (headers, labels, hints) is translated.

Language resolution: cookie `dashboard_lang` (set by `?lang=en|zh`)
→ `ui_lang` config → Accept-Language → English. When adding UI text,
also check whether it appears in chart labels — canvas charts get their
strings via the `GPU_I18N` JSON embedded in `status.html`, and overlay
bucket labels come from `gpu_history.py` (`_get_overlay_buckets`).

### Adding a route

Register it in `app/main.py` under `app.include_router(...)`. Keep the
first-run guard in mind: routes other than `/setup`, `/health` and
`/static` are only reachable once a workspace is configured.

### Publishing (maintainers only)

1. `.venv/bin/python -m pytest tests/ -x -q` — green
2. `scripts/check_privacy.sh` — passes (working tree + history)
3. `scripts/make_snapshot.sh` — bundle/tarball artifact
4. The repo is **public open source** (MIT). Never commit personal data:
   `config.local.json`, `data/`, `logs/`, `workspace/` stay gitignored;
   keep internal deployment details (systemd units, host paths) out of
   the repo.
