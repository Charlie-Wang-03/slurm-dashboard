# SLURM Dashboard

> Learn SLURM the easy way — a self-hosted, read-mostly web dashboard
> for people who are new to SLURM clusters and Linux servers.

[中文版 README](README.zh-CN.md)

## What it does

Every page shows the **real command** behind the data with a copy
button — so you can reproduce everything in your own terminal:

| Page | What you see | Command behind it |
|------|--------------|-------------------|
| Cluster Status | partitions, your queue **and the full cluster queue**, GPU, disk, memory | `sinfo`, `squeue -u $USER`, `squeue`, `nvidia-smi`, `df -h`, `free -h` |
| GPU monitor | 5-minute resource history with day / week / month / year charts (timeline or period-aligned overlay) | `nvidia-smi`, `nvidia-smi --query-compute-apps` |
| Jobs | active jobs + history | `squeue -u $USER`, `sacct` |
| Job detail | accounting + output tail + download | `sacct -j <id>`, `cat slurm-<id>.out` |
| Submit Job | paste an sbatch script, pick one from the workspace, or upload `.sh` / `.sbatch` / `.py` (Python files are wrapped into an sbatch automatically) | `sbatch --chdir=<workspace> ... run.sbatch` |
| Env Check | SLURM toolchain availability + config summary | `which sbatch`, … |

Plus a command **cheat sheet** (including `tar | openssl` encrypt /
decrypt recipes) and a **first-run setup wizard** that asks one
question: where should scripts and outputs live?

## What it is not

- **Not a multi-user web service.** There is no authentication or
  authorization — anyone who can reach the port (any local user on the
  same host) can see the dashboard and submit jobs as you.
- **Not an enterprise HPC platform.** No LDAP/SSO, no role-based access
  control, no audit trail, no web shell.
- **Not a SLURM replacement.** It only runs the whitelisted commands
  shown on each page, under your own user account, from one workspace
  directory.

## Quick start

```bash
git clone <this-repo> slurm-dashboard
cd slurm-dashboard
./install.sh                 # creates .venv and installs dependencies
./run_dashboard.sh           # serves on http://127.0.0.1:7860
```

The service binds to `127.0.0.1` only. To use it from your laptop, use
SSH port forwarding:

```bash
ssh -L 7860:127.0.0.1:7860 user@your-server
# then open http://127.0.0.1:7860 in your local browser
```

> **Security notes.** Binding to `127.0.0.1` stops *remote* access, but
> any **local user on the same host can reach the port** — loopback
> binding, a firewall and an authenticated reverse proxy only gate
> *network* access; none of them stop other local users, who can reach
> `127.0.0.1` directly and bypass any proxy. Websites you visit while
> the tunnel is open can also attempt cross-site form posts (the
> dashboard rejects cross-origin requests). There is no authentication
> — run it only on a machine where you trust every local user
> (typically your own laptop or a single-user server). On a shared
> login node there is **no configuration that protects the dashboard
> from other local users** — do not run it there unless every local
> user is trusted. `run_dashboard.sh` refuses any `HOST` that is not
> loopback — do not work around that. Full trust model:
> [SECURITY.md](SECURITY.md).

On the first visit you are guided to choose a workspace directory.
That's the only setup step.

### GPU history collection

The GPU charts are fed by a collector that samples `nvidia-smi` every
5 minutes and appends to `data/gpu_history/gpu_history.jsonl`
(gitignored). Add one line to your crontab to keep history growing:

```cron
*/5 * * * * cd /path/to/slurm-dashboard && .venv/bin/python tools/gpu_monitor.py >> logs/gpu_monitor.log 2>&1
```

Without it, the dashboard still works — the GPU section just shows an
empty state until data arrives. The history file grows as long as the
collector runs; prune it yourself if disk space matters.

### What the GPU collector records (privacy)

`tools/gpu_monitor.py` runs every 5 minutes (via your crontab) and
records **only on this machine**, appended to
`data/gpu_history/gpu_history.jsonl` (gitignored, never committed):

- per-GPU utilization, memory and temperature (`nvidia-smi`);
- for every process using a GPU: PID, process name, memory used, the
  **username** that owns it (`ps`) and, if it belongs to a SLURM job,
  the **job id and job name** (`squeue` / `scontrol`);
- CPU utilization, load average and memory (`/proc`).

What that means for you:

- The data never leaves your server and never enters git
  (`scripts/check_privacy.sh` enforces this at publish time).
- The dashboard charts show **per-user** GPU usage, so on a shared
  cluster the GPU section may show other users' usernames and job
  names — the same information `nvidia-smi` displays in a terminal.
  Check your cluster's policy before running the collector there.
- The history file grows as long as the collector runs (its size
  depends on your GPU count and how many processes use them); delete
  it any time, or remove the crontab line to stop collection entirely.

## Features

- **Bilingual**: English and Simplified Chinese, switchable from a
  button in the nav bar (`?lang=en|zh` sets a cookie that survives
  reloads). Without an explicit choice the language comes from the
  browser (`Accept-Language`) or the `ui_lang` config (`en` | `zh` |
  `auto`).
- **Teaching-first**: every block shows its command; copy buttons
  everywhere; cheat sheet with common commands and the
  `tar | openssl` encryption recipes.
- **Safe by default**: binds 127.0.0.1 only, subprocess calls use list
  arguments (no shell injection), sbatch parameters are whitelisted,
  downloads are path-checked.
- **Lightweight**: FastAPI + Jinja2 + SQLite. No Node, no build step.
- **Dark theme** included (light / dark / system toggle).

## Configuration

All settings live in `config.local.json` (gitignored). See
[docs/architecture.md](docs/architecture.md#2-configuration-model) for
every key. The important ones:

```jsonc
{
  "workspace_root": "",        // empty = unset; the first-run wizard asks
                               // (it pre-fills <repo>/workspace — scripts
                               // and job outputs live here)
  "slurm_partition": "",       // empty = no --partition flag, SLURM's
                               // native default applies
  "allowed_partitions": [],    // picklist in the submit form (may be empty)
  "default_gres": "",          // empty = no --gres flag, SLURM default
  "allowed_gres": [],
  "server_bind_host": "127.0.0.1",   // 0.0.0.0 / :: / * are rejected
  "server_port": 7860,
  "ui_lang": "auto"            // auto | en | zh
}
```

When a partition or GRES value is set, it must be on the matching
allowlist — there is no silent fallback.

## Development

```bash
.venv/bin/python -m pytest tests/ -x -q        # test suite
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 7861   # dev instance
scripts/check_privacy.sh                       # publish gate
```

- Architecture and route table: [docs/architecture.md](docs/architecture.md)
- AI-agent rules: [AGENTS.md](AGENTS.md)
- Manual acceptance walk-through: [docs/testing.md](docs/testing.md)

## Requirements

- Linux with Python 3.10+ (3.11 recommended)
- SLURM client tools for real job submission: `sbatch`, `squeue`,
  `sacct`, `scancel`, `sinfo`
- `nvidia-smi` (optional, for the GPU blocks; the history collector
  needs it too)
- No cluster? The dashboard still runs — status blocks show "command
  not available" and you can still learn the commands from the cheat
  sheet.

## Shutting down and restarting

The dashboard is a single `uvicorn` process started by
`run_dashboard.sh`. Stop it with Ctrl-C (foreground) or `kill <pid>`;
restart it with `./run_dashboard.sh`. Jobs already submitted to SLURM
are **not** affected — SLURM keeps running them; only the dashboard
stops.

## Uninstalling

1. Stop the dashboard (see above).
2. Remove the repository directory you cloned into (it contains the
   `.venv`, the SQLite database and any collected GPU history):
   `rm -rf <path-to-repo>` (e.g. `rm -rf ~/slurm-dashboard`).
3. Remove the crontab line that runs `tools/gpu_monitor.py` (`crontab
   -e`) if you added one.
4. Jobs you submitted keep running on the cluster — cancel them with
   `scancel <job-id>` if desired. The workspace directory is inside the
   repo by default (`<repo>/workspace`); if you chose another path,
   remove that too.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE). Bundled third-party software is listed
with its license in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Security notes and vulnerability reporting:
[SECURITY.md](SECURITY.md).
