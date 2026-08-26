# Architecture — slurm-dashboard implementation spec

Version 2 (open-source teaching edition). This document is the
authoritative description of the current implementation. Keep it in
sync when behaviour changes.

## 1. Purpose

A self-hosted, read-mostly dashboard that teaches SLURM and basic Linux
server skills. Every block on screen shows the real command behind it
and offers a copy button, so learners can reproduce the view in a
terminal.

## 2. Configuration model

`app/config.py` defines `Settings` (frozen dataclass). Values come from
`config.local.json` (gitignored) merged over `DEFAULT_CONFIG`.
Unknown keys raise `ConfigError` — there is no silent ignore.

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `workspace_root` | str (path) | `""` (unconfigured) | `~` expanded, resolved, created; system directories rejected. The first-run wizard pre-fills `<repo>/workspace` (derived from the actual project location, not a fixed home path) |
| `slurm_partition` | str | `""` (no flag) | empty = omit `--partition` (SLURM native default); non-empty must be in `allowed_partitions` |
| `allowed_partitions` | list[str] | `[]` | whitelist shown in the submit form (may be empty) |
| `default_gres` | str | `""` (no flag) | empty = omit `--gres` (SLURM native default); non-empty must be in `allowed_gres` |
| `allowed_gres` | list[str] | `[]` | whitelist (may be empty) |
| `default_cpus` | int | `4` | 1..32 |
| `default_mem` | str | `"16G"` | must match `^[0-9]+[GM]$` |
| `default_time` | str | `"00:30:00"` | `HH:MM:SS` or `D-HH:MM:SS`, minutes/seconds < 60 |
| `server_bind_host` | str | `"127.0.0.1"` | `0.0.0.0` / `::` / `*` rejected |
| `server_port` | int | `7860` | 1..65535 |
| `ui_lang` | str | `"auto"` | `auto` = detect from cookie / Accept-Language; `en`/`zh` force |

`config.reload_settings()` re-reads the file and refreshes module-level
constants (`WORKSPACE_ROOT`, …) so the first-run wizard takes effect
without a restart. Routers access these through `app.config` module
attributes, never imported bindings.

## 3. First-run wizard

- `app/main.py` middleware `first_run_guard`: while `WORKSPACE_ROOT is
  None`, every path except `/setup`, `/health`, `/favicon.ico` and
  `/static/*` gets a 303 to `/setup`.
- `/setup` GET renders the form; POST validates the path
  (`resolve_workspace_path`: expand `~`, reject system roots, mkdir),
  writes `config.local.json` atomically (tmp + replace), then
  `reload_settings()`. The user lands on `/submit` with a success
  message.
- The wizard is reachable again any time from the Settings nav item.

## 4. Route table

| Method | Path | Handler | Notes |
|--------|------|---------|-------|
| GET | `/health` | `routers/home` | JSON `{"status":"ok"}` |
| GET | `/` | `routers/home` | 302 → `/status` |
| GET | `/status` | `routers/status` | status page (read-only collectors + GPU overview cards) |
| GET | `/status/gpu-history` | `routers/status` | GPU history JSON for the charts (`scale`, `mode`, `start`, `end`; overlay mode requires `start`+`end`) |
| GET | `/jobs` | `routers/jobs` | squeue active + DB records (limit 200) |
| GET | `/jobs/{job_id}` | `routers/jobs` | record + sacct + output tail (100 lines) |
| POST | `/jobs/{job_id}/cancel` | `routers/jobs` | scancel; 303 back with message |
| GET | `/jobs/{job_id}/download` | `routers/jobs` | output file, path-checked |
| GET | `/jobs/{job_id}/raw` | `routers/jobs` | plain-text output |
| GET/POST | `/submit` | `routers/submit` | paste / workspace script picker / upload (sh, sbatch, py) |
| GET | `/env-check` | `routers/env_check` | tool availability + config summary |
| GET | `/diagnostics` | `routers/env_check` | 302 → `/env-check` |
| GET/POST | `/setup` | `routers/setup` | first-run wizard |
| GET | `/static/*` | mounted StaticFiles | `app/static/` |

`job_id` on the URLs is not path-validated by FastAPI but is used only
as a subprocess list argument (never shell interpolation) and as a
template value under autoescape.

## 5. Submission model

`app/slurm.py::submit_script`:

1. Validate whitelist fields (job name `^[A-Za-z0-9_.-]+$`,
   partition ∈ allowed, gres ∈ allowed, cpus 1..32, mem `^[0-9]+[GM]$`,
   time `HH:MM:SS`, script filename `^[A-Za-z0-9_.-]+\.(sh|sbatch|py)$`
   with **no directory components**).
2. The submit form has three channels: pasted script text, a script
   picked from `<workspace>/scripts/` (`.sh` / `.sbatch` / `.py`), or an
   uploaded file (same extensions).
3. `.py` files are wrapped into an sbatch: a `#!/usr/bin/env bash`
   header with `python3 <script>` (shlex-quoted) is prepended. The job
   runs on a compute node, so the wrapper uses the node's own `python3`,
   not the dashboard's `.venv`.
4. Store the script under `<workspace>/scripts/` with a unique name.
5. Prepend `#!/usr/bin/env bash` if no shebang.
6. Run `sbatch --chdir=<workspace> --cpus-per-task=... --mem=...
   --time=... --job-name=... --output=slurm-%j.out
   --error=slurm-%j.err <script>` with list arguments. `--partition`
   and `--gres` are only appended when the corresponding config value
   is non-empty — unconfigured means "let SLURM use its native
   default". The working directory is `<workspace>`, so outputs land as
   `slurm-<jobid>.out` / `slurm-<jobid>.err`.
7. Record the job in SQLite (`source`: `paste` | `upload` | `external`).

Job status: `get_active_jobs_status` uses `squeue`, falling back to
`sacct` for jobs already finished.

## 6. Database

`data/dashboard.sqlite3` (gitignored). Single `jobs` table:

```
id INTEGER PRIMARY KEY AUTOINCREMENT
job_id, job_name, script_name, source, submit_time,
partition, gres, cpus_per_task, mem, time_limit, status,
workspace_path, output_path
```

Legacy v1 databases (per-project records) are migrated **in place**:
`ALTER TABLE jobs RENAME TO jobs_legacy` → create v2 table → copy mapped
columns → drop the legacy table (rollback restores it on failure). The
legacy `operations` table is left untouched. User data is preserved,
never deleted.

## 7. i18n

`app/i18n.py`: `STRINGS["en"|"zh"]` dictionaries. Resolution order:
cookie `dashboard_lang` (set by `?lang=en|zh`) → explicit `ui_lang`
(`en`/`zh`) → `Accept-Language` starting with `zh` → English.
`get_strings(lang)` returns the dictionary; templates use
`{{ strings['key'] }}`. Strings that embed HTML are rendered with
`| safe` **only** when they are static; user-supplied values (e.g.
`job_id`) are interpolated outside the safe fragments.

The language switch is a no-JS mechanism: `app/main.py` middleware
`language_switch` intercepts GET `?lang=en|zh` (non-static paths), sets
a year-long `dashboard_lang` cookie and 303-redirects to the clean URL.
JSON APIs read the same cookie, so chart labels follow the UI language.

Data-driven keys: cluster-status group titles/descriptions and status
labels are looked up by their English value
(`{{ strings.get(group.title, group.title) }}`).

## 8. Teaching features

- **Copy buttons**: every command block has `data-copy` + the global
  `copyText()` helper (clipboard API with execCommand fallback).
- **Command cheat sheet** (`templates/_cheat_sheet.html`, included on
  status and jobs pages): `squeue -u $USER`, `sinfo`, `sacct -u $USER`,
  `sbatch run.sbatch`, `df -h`, `free -h`, `nvidia-smi`, plus
  `tar | openssl` encrypt/decrypt recipes.
- **Equivalent command** on the submit page shows the exact sbatch
  invocation the dashboard will run.
- Theme toggle (light/dark/system) is stored under `dashboard-theme`.

## 9. GPU history

- `tools/gpu_monitor.py` (crontab, every 5 minutes) samples `nvidia-smi`
  plus CPU/memory from `/proc` and appends to
  `data/gpu_history/gpu_history.jsonl` (gitignored). See README "GPU
  history collection". Per-process records include usernames, PIDs,
  process names and SLURM job ids/names — privacy implications are
  documented in README "What the GPU collector records (privacy)".
- **Timestamps** are ISO 8601 with the server's local UTC offset
  (`datetime.now().astimezone().isoformat(timespec="seconds")`), so the
  data is timezone-portable. `app/gpu_history.py` parses any offset —
  including the `+08:00` suffix written by v0.1.0 collectors — and
  treats naive timestamps as server-local. Chart windows and bucket
  boundaries use the server's local timezone; there is no fixed
  timezone anywhere.
- **Process → GPU attribution** is by PCI bus id. The collector queries
  `bus_id` per GPU (index) and per compute-app process, then
  `attach_processes_to_gpus()` matches them (exact or full/short-form
  suffix). Processes whose GPU cannot be determined are recorded under
  `unmatched_processes` and are never attributed to a GPU — in
  particular never defaulted to GPU 0, which v0.1.0 did for every
  process it could not match. The dashboard does not chart
  `unmatched_processes` (no GPU to attribute them to); the data is kept
  in the record rather than dropped.
- `app/gpu_history.py::aggregate_gpu_data(scale, mode, start, end, lang)`
  serves the charts:
  - `scale`: `day` | `week` | `month` | `year`; date params use the
    matching format (`2026-07-25`, `2026-W30`, `2026-07`, `2026`).
  - `mode=linear`: averaged timeline over the current scale window.
  - `mode=overlay`: period-aligned buckets (288 per day, 7 per week,
    31 per month, 52 per year); memory is summed, utilization averaged.
    Bucket labels follow the UI language (`Mon..Sun` / `1..31` / `W1..W52`
    vs `周一` / `1日` / `第N周`). Requires `start` + `end`.
  - `/status` renders the overview cards (GPU count, active users, avg
    utilization) from the latest-day summary; the charts fetch their own
    data from `/status/gpu-history`.
- Chart.js 4.4.1 is vendored under `app/static/vendor/` (no CDN). Canvas
  colors are theme-aware in JS because canvas ignores CSS variables.

## 10. Security model

| Concern | Mechanism |
|---------|-----------|
| Network exposure | binds 127.0.0.1 only; SSH port forwarding for remote access |
| Local trust boundary | loopback binding, firewalls and authenticated reverse proxies stop *remote* access only — any local user can reach the port directly and bypass any proxy; no authentication by design, documented in README / SECURITY.md |
| CSRF | `csrf_origin_guard` middleware rejects cross-origin state-changing POSTs (Origin must match Host and be loopback; requests without Origin — curl, scripts — are allowed) |
| Command injection | subprocess list args; no `shell=True`; no command pages |
| Resource abuse | sbatch parameter whitelists; script extension + no-directory check |
| Path traversal | `ensure_path_under_root` / `allowed_roots` on downloads |
| Data loss | workspace + DB are gitignored; check_privacy.sh publish gate |
| XSS | Jinja2 autoescape; user values never inside `| safe` fragments; no user values in JS handlers (confirm text moves through a `data-*` attribute) |
