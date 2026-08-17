# Changelog

All notable changes are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
