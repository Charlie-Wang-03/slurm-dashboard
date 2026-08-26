# Changelog

All notable changes are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-26

### Added

- Bug report and pull request templates for contributors.
- A privacy-safe synthetic Cluster Status screenshot at the top of both
  the English and Chinese READMEs.
- A documented, tested upgrade flow for existing installs.

### Changed

- Jobs: the active queue now scopes to the current user
  (`squeue -u $USER`) instead of listing every user's jobs.
- Jobs: recent records are now truthfully labeled as dashboard-local
  SQLite history; SLURM accounting (`sacct`) is a separate source,
  shown on Job Detail when accounting is available.
- Env Check: command descriptions now match the commands actually run
  (`sbatch --version`, `squeue --version`, `nvidia-smi --query-gpu=...`).
- GPU monitor: the empty state no longer claims automatic collection is
  already configured; it now points to the README crontab instructions.
- Documentation: a "Tested scope and compatibility" section now
  distinguishes automated CI tests (Python 3.10–3.12), manual testing
  on one real SLURM + NVIDIA GPU environment, and simulated no-SLURM /
  no-GPU degradation; nothing beyond that is claimed.
- Test dependency: Starlette TestClient now uses httpx2 (plain httpx
  remains a deprecated fallback).
- Regression coverage expanded to 150 automated tests.

### Fixed

- Submit Job page: fixed a rendering crash (HTTP 500) in the page
  description and HTML-escaped the interpolated partition flag.
- Clone commands in Quick Start and CONTRIBUTING now point to the
  direct repository URL and run as written.

### Security

- Re-established the public repository on a clean-history baseline
  after a controlled release-hardening and privacy review; privacy,
  secret-scanning, and dependency-audit gates now run in CI.
- Browser-origin protection: loopback form POSTs with Chrome 151's
  literal `Origin: null` are now accepted, but only when browser-
  controlled Fetch Metadata reports `Sec-Fetch-Site: same-origin` and
  the Host remains loopback. Cross-site `null`-Origin requests stay
  rejected.

> The `0.1.0` and `0.1.1` entries below are retained as historical
> milestones from before a controlled repository-history rewrite. Their
> original tags and GitHub Releases were retired during that rewrite
> and are not available from this repository's tag list.

## [0.1.1] - 2026-08-21

Repository hygiene and portability pass.

### Changed

- Root layout: `SPEC.md` -> `docs/architecture.md`, `SMOKE_TEST.md` ->
  `docs/testing.md`; removed redundant root documentation indexes and
  updated in-repo documentation links.
- Timezone: removed the fixed `BEIJING_TZ` / `+08:00` assumptions from
  the GPU collector and chart aggregation. Timestamps are now ISO 8601
  with the server's local UTC offset; parsing accepts any offset,
  including v0.1.0 `+08:00` history data (unchanged, still readable).
- Workspace default: the first-run wizard now pre-fills
  `<repo>/workspace` (derived from the actual project location) instead
  of `~/slurm-dashboard/workspace`; clone-location assumptions removed
  from README / config example / uninstall docs.
- Partition and GRES are now optional: empty means the `--partition` /
  `--gres` sbatch flags are omitted (SLURM's native default). When
  configured, the allowlist is still strictly enforced — no silent
  fallback.
- GPU process -> GPU attribution now uses the real PCI bus id
  (`nvidia-smi --query-gpu=... pci.bus_id` + compute-apps `gpu_bus_id`).
  Processes whose GPU cannot be determined are recorded under
  `unmatched_processes` instead of being dumped onto GPU 0 (v0.1.0
  misattributed every unmatchable process to GPU 0).
- SECURITY.md / README trust model: clarified that loopback binding,
  firewalls and authenticated reverse proxies only gate network access
  and do not protect against other local users; on a shared login node
  there is no configuration that makes the dashboard safe from
  untrusted local users.
- Removed the environment-specific "~30 KB/day" history-size claim.
- Tests: 23 new (multi-GPU mapping regression, timezone parsing
  including legacy `+08:00` and cross-offset equivalence, and the
  optional-partition/GRES semantics). The suite no longer depends on
  any `config.local.json` or a GPU-enabled host: every test patches the
  allowlists it needs, so a fresh clone with an empty config passes.

## [0.1.0] - 2026-08-18

First open-source release — a teaching dashboard for SLURM / Linux
beginners.

### Added

- Four-page UI: Cluster Status (sinfo / squeue / df / free / GPU),
  Jobs (list + detail with output tail), Submit Job (paste / workspace
  picker / upload), Env Check.
- GPU history monitor (`tools/gpu_monitor.py`, crontab-driven) with
  day / week / month / year charts in linear and overlay modes.
- Teaching-first features: real command shown on every block with copy
  buttons, command cheat sheet with `tar | openssl` encrypt/decrypt
  recipes.
- First-run setup wizard for the workspace directory.
- Bilingual UI (English default, Simplified Chinese) with cookie /
  `ui_lang` / Accept-Language resolution.
- Light / dark / system theme toggle.

### Security

- Loopback-only binding; `0.0.0.0` / `::` / `*` rejected at config
  load, non-loopback `HOST` rejected by `run_dashboard.sh`.
- CSRF origin guard on state-changing requests; XSS-hardened job
  detail confirm dialog.
- Whitelisted sbatch parameters; subprocess list arguments only;
  path checks on downloads and workspace files.
- `scripts/check_privacy.sh` publish gate (working tree + git history).

### Packaging

- `install.sh` (repo-local `.venv`) and `run_dashboard.sh`.
- Chart.js 4.4.1 vendored (no CDN); see THIRD_PARTY_NOTICES.md.
- 92 automated tests; GitHub Actions CI (pytest on Python 3.10–3.12).
