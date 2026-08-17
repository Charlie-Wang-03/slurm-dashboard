# slurm-dashboard maintenance — discovery entry

Entry point for maintaining this repository. Read order:

| Doc | Path | Purpose |
|-----|------|---------|
| Agent rules | [AGENTS.md](AGENTS.md) | AI-agent hard constraints, workflows, output format |
| Implementation spec | [SPEC.md](SPEC.md) | Current architecture, route table, DB schema |
| Acceptance tests | [SMOKE_TEST.md](SMOKE_TEST.md) | Manual walk-through + security regression |
| Project intro | [README.md](README.md) | Purpose, quick start, usage flow |
| Agent entry | [CLAUDE.md](CLAUDE.md) | Environment and hard rules for this repo |

## Flow

1. Read `SPEC.md` for the current architecture before touching code.
2. Follow the security rules in `AGENTS.md` (no shell=True, no arbitrary
   command execution, whitelist-only sbatch parameters, 127.0.0.1 binding).
3. Run `tests/` after any change: `.venv/bin/python -m pytest tests/ -x -q`.
4. Before any publish, run `scripts/check_privacy.sh`.
