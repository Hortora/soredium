#!/usr/bin/env python3
"""
audit_duplicate_commits.py — Scan repos for duplicate commits.

Finds commits with identical content (same patch-id) but different SHAs
on the same branch. These result from rebase-then-merge sequences.

Usage:
    python3 scripts/audit_duplicate_commits.py <repo_path>
    python3 scripts/audit_duplicate_commits.py <family_root> --all-repos

Output: KEY=VALUE lines. Exit 0 = clean, 1 = duplicates found.
"""

import subprocess
import sys
from pathlib import Path


def _git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True,
    )
    return result.returncode == 0, result.stdout.strip()


def _patch_id_for_sha(repo, sha):
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff-tree", "-p", sha],
        capture_output=True, text=True,
    )
    if diff.returncode != 0 or not diff.stdout.strip():
        return None
    pid = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=diff.stdout, capture_output=True, text=True,
    )
    if pid.returncode == 0 and pid.stdout.strip():
        return pid.stdout.strip().split()[0]
    return None


def audit_repo(repo_path: str) -> list[tuple[str, str, str]]:
    ok, log = _git(repo_path, "log", "main", "--format=%H %s")
    if not ok or not log:
        return []

    by_subject: dict[str, list[str]] = {}
    for line in log.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            by_subject.setdefault(parts[1], []).append(parts[0])

    pairs = []
    for subj, shas in by_subject.items():
        if len(shas) < 2:
            continue
        pid_map: dict[str, list[str]] = {}
        for sha in shas:
            pid = _patch_id_for_sha(repo_path, sha)
            if pid:
                pid_map.setdefault(pid, []).append(sha)
        for pid, matching in pid_map.items():
            if len(matching) >= 2:
                for i in range(len(matching) - 1):
                    pairs.append((matching[i], matching[i + 1], subj))
    return pairs


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    target = Path(sys.argv[1])
    all_repos = "--all-repos" in sys.argv

    if all_repos:
        repos = sorted(p.parent for p in target.rglob(".git") if p.is_dir())
    else:
        repos = [target]

    total_pairs = 0
    has_dupes = False

    for repo in repos:
        found = audit_repo(str(repo))
        name = repo.name
        print(f"REPO={name}")
        print(f"PAIRS={len(found)}")
        for local, remote, subj in found:
            print(f"PAIR={local[:12]}:{remote[:12]}:{subj[:60]}")
        total_pairs += len(found)
        if found:
            has_dupes = True

    print(f"TOTAL_PAIRS={total_pairs}")
    print(f"STATUS={'dirty' if has_dupes else 'clean'}")
    sys.exit(1 if has_dupes else 0)


if __name__ == "__main__":
    main()
