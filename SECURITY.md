# Security

## Trust model

slurm-dashboard is a **single-user, no-authentication** tool by
design. Read this before deploying it anywhere.

| Boundary | What holds |
|----------|-----------|
| Remote access | The dashboard binds `127.0.0.1` only. `run_dashboard.sh` refuses non-loopback `HOST` values; the config loader rejects `0.0.0.0` / `::` / `*`. Remote use is via SSH port forwarding (`ssh -L 7860:127.0.0.1:7860 user@server`). |
| Local access | **Any local user on the host can reach the port.** There is no login, so anyone who can connect can view cluster status and submit / cancel jobs as the user who runs the dashboard. Loopback binding, a firewall and an authenticated reverse proxy only gate *network* access — none of them stop other local users, who can reach `127.0.0.1` directly and bypass any proxy. Run it only on a host where you trust every local user (your own laptop or a single-user server). On a shared login node there is **no configuration that protects the dashboard from other local users** — do not run it there unless every local user is trusted. |
| Browser cross-site attacks | The `csrf_origin_guard` middleware rejects state-changing requests whose `Origin` does not match the request `Host` and is not loopback (defeats both cross-site form posts and DNS rebinding). Requests without an `Origin` (curl, scripts) are allowed. |
| Command execution | SLURM commands run as the dashboard user via subprocess list arguments (no shell). Only whitelisted commands (`sinfo`, `squeue`, `sacct`, `df`, `free`, `nvidia-smi`, `sbatch`, `scancel`, `scontrol`) with whitelisted parameters. No arbitrary command pages. |
| Files | The dashboard reads/writes only the repository directory and the configured `workspace` (plus `/proc` and the whitelisted commands' output). Paths are resolved and checked against allowed roots. |
| Data | Job records and GPU history live in `data/` (gitignored). The GPU collector records per-user process and job names — see README "What the GPU collector records (privacy)" before using it on a shared cluster. |

## Reporting a vulnerability

This project is a small teaching tool maintained by one person. If you
find a security issue:

- Open a private issue via GitHub's **Security → Report a
  vulnerability** flow if you are on GitHub.
- Otherwise, describe the issue in an issue with the `security` label,
  **without** including a working exploit in public, and give the
  maintainers a reasonable window (14 days) to respond before
  disclosing details.
