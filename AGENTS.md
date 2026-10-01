# AGENTS.md

## Project Purpose

This repository is a self-hosted, teaching-first SLURM dashboard for people learning Linux servers and HPC workflows. It is read-mostly, not read-only: the application can submit and cancel real SLURM jobs, write workspace scripts, maintain local SQLite state, and collect local GPU history.

Project-local security and trust boundaries take precedence over generic engineering preferences.

## Read First

Before substantive changes, read the smallest relevant set:

1. `README.md` or `README.zh-CN.md` for user-facing behavior and tested scope;
2. `SECURITY.md` for the trust model;
3. `docs/architecture.md` for configuration, routes, submission, storage, and security mechanisms;
4. `docs/testing.md` when changing behavior that affects real SLURM usage or manual acceptance.

## Security Invariants

Do not weaken these without explicit maintainer approval:

- the dashboard remains loopback-only;
- loopback does not imply isolation from other local users;
- the project makes no multi-user authentication or authorization claim;
- SLURM and Linux subprocesses use argument lists, not shell interpolation;
- sbatch parameters and file paths remain bounded and validated;
- browser-origin and Host protections remain intact;
- runtime state and cluster-derived history stay out of the public repository.

Do not describe documentation or agent instructions as security mechanisms. Security claims must map to actual code, configuration, OS, or network boundaries.

## Real Side Effects

Treat job submission and cancellation as real external mutations.

Changes affecting `sbatch`, `scancel`, workspace writes, uploads, job-output access, or runtime data handling require extra review. Do not introduce unbounded retries, fan-out, polling, or submission loops.

The dashboard may be observational most of the time, but its mutation authority must remain explicit.

## Runtime and Private Data

Gitignored runtime paths include local configuration, database state, logs, workspace contents, and GPU history. Do not add private cluster identifiers, usernames, job contents, server paths, credentials, or locally collected runtime data to tracked files.

Use `scripts/check_privacy.sh` before publication-sensitive changes.

## Validation

Before declaring work complete:

1. inspect the resulting diff;
2. run the relevant pytest suite;
3. run `scripts/check_privacy.sh` for privacy-sensitive changes;
4. preserve the CI-tested Python 3.10-3.12 support claim;
5. use `docs/testing.md` for behavior that requires real SLURM / GPU / browser acceptance.

Mocked or simulated tests are not evidence of real-cluster compatibility. Keep simulated, automated, and real-environment evidence clearly distinguished.

## Bilingual Surface

Keep `README.md` and `README.zh-CN.md` factually aligned when public behavior, security claims, setup, or tested scope changes.

## High-Risk Changes

Require explicit maintainer approval before:

- broadening the bind or network trust model;
- adding or changing authentication / authorization claims;
- weakening subprocess, path, origin, privacy, or local-user protections;
- destructive data migration;
- repository visibility, release, ruleset, permission, or history changes.

## Definition of Done

A change is complete when it remains truthful about the trust model, preserves bounded mutation authority, passes relevant automated checks, and does not overstate what was validated on real HPC infrastructure.
