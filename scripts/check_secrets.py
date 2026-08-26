#!/usr/bin/env python3
"""Fail-closed high-confidence secret scan for worktree + reachable Git history.

This is intentionally small and dependency-free so the release gate can run
under restrictive GitHub Actions policies that allow only GitHub-owned Actions.
It complements (rather than replaces) GitHub Secret Scanning when that product
feature is enabled for the repository.

The scanner prints only affected paths / historical object locations, never the
matching line, so a real credential is not copied into CI logs.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: str


# Keep regex literals in this scanner out of its own scan target below.
RULES = [
    Rule("private-key", r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    Rule("github-token", r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    Rule("aws-access-key", r"AKIA[0-9A-Z]{16}"),
    Rule("openai-style-key", r"sk-[A-Za-z0-9_-]{20,}"),
    Rule("anthropic-key", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    Rule("google-api-key", r"AIza[0-9A-Za-z_-]{35}"),
    Rule("slack-token", r"xox[baprs]-[0-9A-Za-z-]{20,}"),
    Rule(
        "generic-assigned-secret",
        r"(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password)"
        r"[[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9_./+=:-]{16,}",
    ),
]

EXCLUDED_PATH = "scripts/check_secrets.py"


def _run_git_grep(rule: Rule, commits: list[str] | None) -> tuple[int, list[str]]:
    # -e is required because some credential signatures (notably PEM markers)
    # start with '-' and must never be parsed by git grep as command options.
    args = ["git", "grep", "-lI", "-E", "-e", rule.pattern]
    if commits:
        args.extend(commits)
    args.extend(["--", ".", f":(exclude){EXCLUDED_PATH}"])
    completed = subprocess.run(args, capture_output=True, text=True)
    hits = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return completed.returncode, hits


def _reachable_commits() -> list[str]:
    completed = subprocess.run(
        ["git", "rev-list", "--all"], capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git rev-list --all failed")
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def main() -> int:
    try:
        commits = _reachable_commits()
    except RuntimeError as exc:
        print(f"FAIL: secret history scan could not enumerate commits: {exc}", file=sys.stderr)
        return 1

    failures: list[tuple[str, str, list[str]]] = []
    for scope, scope_commits in [("worktree", None), ("history", commits)]:
        for rule in RULES:
            rc, hits = _run_git_grep(rule, scope_commits)
            if rc not in (0, 1):
                print(
                    f"FAIL: {scope} secret scan errored for rule {rule.name} (git grep rc={rc})",
                    file=sys.stderr,
                )
                return 1
            if hits:
                failures.append((scope, rule.name, hits))

    if failures:
        for scope, rule_name, hits in failures:
            print(f"FAIL: possible {rule_name} in {scope}:")
            for hit in sorted(set(hits))[:50]:
                print(f"  {hit}")
        print("== check_secrets: FAILED ==")
        return 1

    print("== check_secrets: PASS ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
