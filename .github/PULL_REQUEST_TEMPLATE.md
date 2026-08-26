Please read [CONTRIBUTING.md](https://github.com/Charlie-Wang-03/slurm-dashboard/blob/main/CONTRIBUTING.md) before submitting.

## What changed?

Briefly describe the change.

## Why?

Why this change is needed.

## Verification

List the tests / smoke checks you actually ran, e.g.:

- [ ] `.venv/bin/python -m pytest tests/ -q`
- [ ] `scripts/check_privacy.sh --worktree-only`
- [ ] `.venv/bin/python scripts/check_secrets.py`
- [ ] dev instance smoke test (`./run_dashboard.sh`, or `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 7861`)

## Checklist

- [ ] `.venv/bin/python -m pytest tests/ -q` passes
- [ ] `scripts/check_privacy.sh --worktree-only` passes
- [ ] `.venv/bin/python scripts/check_secrets.py` passes
- [ ] English and Chinese UI/docs were updated together when relevant
- [ ] I did not intentionally weaken the documented security model
- [ ] Documentation was updated if behavior changed

## Security-sensitive changes

If this PR touches subprocess calls, sbatch/scancel, paths, uploads/downloads, Host/Origin handling, or the workspace, describe the security impact in the PR body.
