# Contributing to slurm-dashboard

Thanks for helping! This project is a teaching tool, so clarity beats
cleverness: every change should make the dashboard easier to
understand for a SLURM beginner.

## Ground rules

- **English only** in code, commit messages and comments (the UI
  strings live in `app/i18n.py` — add both `en` and `zh` entries).
- **No personal data in the repo.** `config.local.json`, `data/`,
  `logs/`, `workspace/` are gitignored. Before any publish run
  `scripts/check_privacy.sh`.
- Keep the security model intact:
  127.0.0.1 binding, list-argument subprocess, whitelisted sbatch
  parameters, path checks. PRs that weaken these will be sent back.

## Getting started

```bash
git clone https://github.com/Charlie-Wang-03/slurm-dashboard.git slurm-dashboard
cd slurm-dashboard
./install.sh
.venv/bin/python -m pytest tests/ -x -q        # baseline must be green
```

## Making changes

1. Create a branch: `git checkout -b feat/your-change`.
2. Implement, with tests when the behaviour is testable
   (`tests/`, run with `.venv/bin/python -m pytest tests/ -x -q`).
3. Verify the UI on a dev instance:
   `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 7861`.
4. Update docs that describe what you changed: `docs/architecture.md`
   (route table, config model) is the authoritative one.
5. Commit with an English message, e.g.
   `feat: add partition hint to the submit form`.

## Submitting

- Open a PR against `main`.
- Describe what changed and why, and how you verified it (tests,
  smoke test section run).
- Screenshots are welcome for UI changes.

## Review checklist

- [ ] Tests green (`pytest tests/ -x -q`)
- [ ] `scripts/check_privacy.sh` passes
- [ ] `en` and `zh` strings both updated when UI text changed
- [ ] No `shell=True`, no `0.0.0.0`, no new command-execution surface
- [ ] Docs updated (`docs/architecture.md` at minimum)
