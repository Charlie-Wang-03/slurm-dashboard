# Security

## Trust model

slurm-dashboard is a **single-user, no-authentication** tool by
design. Read this before deploying it anywhere.

| Boundary | What holds |
|----------|-----------|
| Remote access | The dashboard is loopback-only. `run_dashboard.sh` refuses non-loopback `HOST` values, the config loader accepts only loopback addresses / `localhost`, and every HTTP request rejects a non-loopback `Host` header. Remote use is via SSH port forwarding (`ssh -L 7860:127.0.0.1:7860 user@server`). |
| Local access | **Any local user on the host can reach the port.** There is no login, so anyone who can connect can view cluster status and submit / cancel jobs as the user who runs the dashboard. Loopback binding, a firewall and an authenticated reverse proxy only gate *network* access — none of them stop other local users, who can reach `127.0.0.1` directly and bypass any proxy. Run it only on a host where you trust every local user (your own laptop or a single-user server). On a shared login node there is **no configuration that protects the dashboard from other local users** — do not run it there unless every local user is trusted. |
| Browser cross-site attacks | The loopback `Host` guard blocks DNS-rebinding reads on every HTTP method. The `csrf_origin_guard` additionally rejects state-changing browser requests whose `Origin` does not match the loopback request `Host`. A narrow compatibility path accepts Chrome 151+'s literal `Origin: null` on same-origin form posts, but only when the `Host` is still loopback and browser-controlled Fetch Metadata reports `Sec-Fetch-Site: same-origin` (a header page JavaScript cannot set); `null` Origins carrying `cross-site` / `same-site` Fetch Metadata, or none at all, remain rejected. Responses deny framing (`frame-ancestors 'none'` / `X-Frame-Options: DENY`). Requests without an `Origin` (for example curl/scripts) are allowed only when their `Host` is loopback. |
| Command execution | SLURM commands run as the dashboard user via subprocess list arguments (no shell). Only the fixed SLURM/Linux command surfaces documented by the project are invoked; sbatch parameters are validated / allowlisted. Uploaded, pasted and workspace job scripts are capped at 1 MiB. Script contents themselves are intentionally executable as SLURM jobs, so anyone who can reach the dashboard effectively has the dashboard Unix user's job-submission capability. |
| Files | The dashboard reads/writes only the repository directory and the configured `workspace` (plus `/proc` and the fixed commands' output). Paths are resolved and checked against allowed roots; symlinked containment roots are rejected. Job output downloads and raw views validate numeric job IDs and use streaming file responses. |
| Data | Job records and GPU history live in `data/` (gitignored). The GPU collector records per-user process and job names — see README "What the GPU collector records (privacy)" before using it on a shared cluster. GPU-history API date windows are bounded before aggregation to avoid unbounded in-memory bucket creation. |
| API surface | The default FastAPI `/docs`, `/redoc` and `/openapi.json` endpoints are disabled. `/health` returns only `{"status":"ok"}`. |
| Repository privacy | `scripts/check_privacy.sh` scans the worktree and all reachable refs for privacy-oriented patterns; CI also runs a generic secret scanner and dependency audit. If a real credential is ever committed, revoke/rotate it first — deleting it from the current tree does not remove it from Git history. |

## Reporting a vulnerability

This project is a small teaching tool maintained by one person. If you
find a security issue:

- Prefer GitHub's **Security → Report a vulnerability** private-reporting
  flow when it is available.
- If private reporting is unavailable, open a minimal public issue asking
  the maintainer for a private reporting channel. **Do not include exploit
  details, credentials, server identifiers, or other sensitive evidence in
  the public issue.**
