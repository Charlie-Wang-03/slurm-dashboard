# SLURM Dashboard

<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="SLURM Dashboard — a self-hosted web dashboard that teaches SLURM by showing the real command behind every data block (sinfo, squeue, sbatch, nvidia-smi)">
</p>

[中文版 README](README.zh-CN.md)

> A self-hosted, read-mostly web dashboard for people who are new to
> SLURM clusters and Linux servers.

<p align="center">
  <img src="./docs/screenshots/cluster-status-en.png" width="800" alt="SLURM Dashboard cluster status page: partitions, per-user GPU utilization and jobs, with the exact command behind every section">
</p>

*Cluster Status: per-user GPU utilization history, basic info, and the exact commands behind every section — squeue, sinfo, nvidia-smi.*

## What it does

Every page shows the **real command** behind the data with a copy
button — so you can reproduce everything in your own terminal:

| Page | What you see | Command behind it |
|------|--------------|-------------------|
| Cluster Status | partitions, your queue **and the full cluster queue**, GPU, disk, memory | `sinfo`, `squeue -u $USER`, `squeue`, `nvidia-smi`, `df -h`, `free -h` |
| GPU monitor | 5-minute resource history with day / week / month / year charts (timeline or period-aligned overlay) | `nvidia-smi`, `nvidia-smi --query-compute-apps` |
| Jobs | active queue + dashboard-local submission records | `squeue -u $USER`, local SQLite records |
| Job detail | accounting + output tail + download | `sacct -j <id>`, `cat slurm-<id>.out` |
| Submit Job | paste an sbatch script, pick one from the workspace, or upload `.sh` / `.sbatch` / `.py` (Python files are wrapped into an sbatch automatically) | `sbatch --chdir=<workspace> ... run.sbatch` |
| Env Check | SLURM toolchain availability + config summary | tool-specific version / query checks such as `sbatch --version`, `squeue --version`, `nvidia-smi --query-gpu=...` (the page shows the exact command for each tool) |

Plus a command **cheat sheet** (including `tar | openssl` encrypt /
decrypt recipes) and a **first-run setup wizard** that asks one
question: where should scripts and outputs live?

## Why this project is different

Every data block shows the exact command that produced it, with a copy
button — the UI doubles as a guided tour of `sinfo`, `squeue`,
`sbatch`, `sacct` and `nvidia-smi`.

- **Teaching-first**: every block shows its command; copy buttons
  everywhere; cheat sheet with common commands and the
  `tar | openssl` encryption recipes.
- **Bilingual**: English and Simplified Chinese, switchable from a
  button in the nav bar (`?lang=en|zh` sets a cookie that survives
  reloads). Without an explicit choice the language comes from the
  browser (`Accept-Language`) or the `ui_lang` config (`en` | `zh` |
  `auto`).
- **Safe by default**: loopback-only bind and Host validation,
  list-argument subprocess calls (no shell injection), allowlisted
  sbatch parameters, path-checked files, bounded script inputs and
  browser hardening headers.
- **Lightweight**: FastAPI + Jinja2 + SQLite. No Node, no build step.
- **Dark theme** included (light / dark / system toggle).

## Quick start

```bash
git clone https://github.com/Charlie-Wang-03/slurm-dashboard.git slurm-dashboard
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

> **Security notes.** Loopback binding blocks *remote* connections, and
> the app also rejects non-loopback HTTP `Host` headers (DNS-rebinding
> defense). That does **not** stop another local user on the same host:
> there is no authentication, and loopback binding, a firewall and an
> authenticated reverse proxy only gate *network* access. Run the
> dashboard only where you trust every local user (typically your own
> laptop or a single-user server); on a shared login node there is **no
> configuration that protects it from other local users**. Browser
> state-changing requests are same-origin checked, responses deny
> framing, and `run_dashboard.sh` plus the config loader refuse
> non-loopback bind hosts — do not work around that. Full trust model:
> [SECURITY.md](SECURITY.md).

On the first visit you are guided to choose a workspace directory —
that's the only setup step.

## Requirements

- Linux with Python 3.10+ (3.11 recommended)
- SLURM client tools for real job submission: `sbatch`, `squeue`,
  `sacct`, `scancel`, `sinfo`
- `sacct` depends on your cluster's accounting configuration; when
  accounting is unavailable, accounting detail is unavailable, but
  dashboard-local submission records still work.
- `nvidia-smi` (optional, for the GPU blocks; the history collector
  needs it too)
- No cluster? The dashboard still runs — status blocks show "command
  not available" and you can still learn the commands from the cheat
  sheet.

## What it is not

- **Not a multi-user web service.** There is no authentication or
  authorization — anyone who can reach the port (any local user on the
  same host) can see the dashboard and submit jobs as you.
- **Not an enterprise HPC platform.** No LDAP/SSO, no role-based access
  control, no audit trail, no web shell.
- **Not a SLURM replacement.** It only runs the whitelisted commands
  shown on each page, under your own user account, from one workspace
  directory.

## GPU monitoring

The GPU charts are fed by a collector that samples `nvidia-smi` every
5 minutes and appends to `data/gpu_history/gpu_history.jsonl`
(gitignored). Add one line to your crontab to keep history growing:

```cron
*/5 * * * * cd /path/to/slurm-dashboard && .venv/bin/python tools/gpu_monitor.py >> logs/gpu_monitor.log 2>&1
```

Without it, the dashboard still works — the GPU section just shows an
empty state until data arrives. The history file grows as long as the
collector runs; prune it yourself if disk space matters. Dashboard API
queries over this history are bounded to finite date windows before
aggregation so a malformed request cannot create an unbounded bucket
list in memory.

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

- The runtime data stays on your server and is excluded from git.
  `scripts/check_privacy.sh` scans the worktree and reachable Git
  history before publishing, and CI also runs a generic secret scan.
- The dashboard charts show **per-user** GPU usage, so on a shared
  cluster the GPU section may show other users' usernames and job
  names — the same information `nvidia-smi` displays in a terminal.
  Check your cluster's policy before running the collector there.
- The history file grows as long as the collector runs (its size
  depends on your GPU count and how many processes use them); delete
  it any time, or remove the crontab line to stop collection entirely.

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
  "server_bind_host": "127.0.0.1",   // only loopback addresses / localhost are accepted
  "server_port": 7860,
  "ui_lang": "auto"            // auto | en | zh
}
```

When a partition or GRES value is set, it must be on the matching
allowlist — there is no silent fallback. Uploaded, pasted and existing
workspace scripts submitted through the UI are limited to 1 MiB.

## Tested scope and compatibility

- **Automated tests** — the full test suite runs on GitHub CI with
  Python 3.10, 3.11 and 3.12.
- **Manually tested** — one real Linux + SLURM + NVIDIA GPU environment:
  fresh install, first-run setup, real job submission and output,
  SSH port forwarding, Chrome browser acceptance.
- **Simulated degradation** — the no-SLURM / no-GPU paths were exercised
  on real HPC Linux via process-local `PATH` isolation. This is a
  simulation of a machine without SLURM, not a full test on a plain
  non-HPC Linux host.
- **Not claimed** — this does not claim compatibility with every Linux
  distribution, every SLURM version or configuration, every cluster
  accounting setup, public-network deployment, multi-user
  authentication environments, or enterprise-level guarantees.

See [docs/testing.md](docs/testing.md) for the manual acceptance
walk-through.

## Development

```bash
.venv/bin/python -m pytest tests/ -x -q        # test suite
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 7861   # dev instance
scripts/check_privacy.sh                       # worktree + reachable-history privacy gate
```

CI additionally runs a generic secret scanner and Python dependency
audit.

- Architecture and route table: [docs/architecture.md](docs/architecture.md)
- Manual acceptance walk-through: [docs/testing.md](docs/testing.md)

## Upgrading

The dashboard stores runtime state in gitignored paths
(`config.local.json`, `data/`, `logs/`, `workspace/`, `.venv/`). These
paths are not tracked by this project, and a normal fast-forward update
is intended to leave them in place. Back up important runtime data
before upgrading.

The dashboard is a single `uvicorn` process started by
`run_dashboard.sh`. Stop it with Ctrl-C (foreground) or `kill <pid>`;
restart it with `./run_dashboard.sh`. Jobs already submitted to SLURM
are **not** affected — SLURM keeps running them; only the dashboard
stops.

To upgrade:

1. Stop the dashboard (see above).
2. If you added the GPU collector crontab line, temporarily pause it
   during the dependency update (comment it out or remove it from
   `crontab -e`).
3. `git pull --ff-only`
4. `./install.sh`
5. Restore the collector crontab line if you paused it.
6. Start with `./run_dashboard.sh`.

This is a safe fast-forward update:

- The runtime paths above are intentionally untracked by this project.
  A normal `git pull --ff-only` is expected to leave them in place, but
  ignored files are not a backup; keep a copy of important local data.
- `git pull --ff-only` refuses to run when your local branch has
  diverged from upstream; it never rewrites history. If it fails,
  inspect the situation yourself (stash or rebase local work) instead
  of forcing a reset.
- A workspace directory you placed outside the repository is never
  deleted or managed by Git or the dashboard.

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
