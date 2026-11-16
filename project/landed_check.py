"""Whether the work at a commit is on a base branch.

One check for every caller that has to decide "did this land?" (archive-slot,
close verification). It compares every file, not only source code, and passes
only on proof:

  ancestry          the commit is reachable from the base branch
  patch_equivalent  every commit has a patch-identical commit on base (rebase)
  paths_identical   every path the work touched is byte-identical on base
  content_in_history every path that differs today held the work's exact content
                    on base at some point since the fork (landed, base moved on)
  squash_equivalent the whole of the work equals one commit on base (squash)
  nothing_to_land   the work touched only lifecycle files

A commit subject that also appears on base proves nothing and is not consulted.
Lifecycle files are never compared: the close ceremony strips them by design.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from git_util import git

LIFECYCLE_FILES = (
    "JOURNAL.md", ".close-state", ".execute-progress",
    ".land-ledger.jsonl", ".artifacts-promoted", ".squash-plan",
    ".close-progress", ".close-report.json",
    ".close-log.jsonl", ".wrap-log.jsonl", ".work-progress",
)


@dataclass(frozen=True)
class LandedResult:
    landed: bool
    method: str = ""
    reason: str = ""
    missing: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.landed:
            return self.method
        if self.missing:
            shown = ", ".join(self.missing[:5])
            more = len(self.missing) - 5
            return f"{self.reason}: {shown}" + (f" (+{more} more)" if more > 0 else "")
        return self.reason


def _excludes(ignore: tuple[str, ...]) -> list[str]:
    return [".", *[f":(exclude,glob)**/{name}" for name in ignore]]


def _names(repo: Path, a: str, b: str, ignore: tuple[str, ...]) -> set[str] | None:
    result = git(repo, "diff", "--name-only", "--no-renames", "-z", a, b,
                 "--", *_excludes(ignore))
    if result.returncode != 0:
        return None
    return {name for name in result.stdout.split("\0") if name}


def _patch_ids(repo: Path, diff_args: list[str]) -> set[str] | None:
    diff = subprocess.run(["git", "-C", str(repo), *diff_args],
                          capture_output=True, timeout=120)
    if diff.returncode != 0:
        return None
    ids = subprocess.run(["git", "-C", str(repo), "patch-id", "--stable"],
                         input=diff.stdout, capture_output=True, timeout=120)
    if ids.returncode != 0:
        return None
    return {line.split()[0] for line in ids.stdout.decode().splitlines() if line.strip()}


def _run(repo: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, timeout=300)
    if result.returncode != 0:
        return None
    return result.stdout.decode(errors="surrogateescape")


def _never_on_base(repo: Path, fork: str, sha: str, base: str,
                   paths: list[str]) -> list[str] | None:
    """Paths whose content at `sha` base has never held since `fork`.

    A path deleted at `sha` counts as held once base has deleted it.
    """
    tree = _run(repo, "ls-tree", "-r", "-z", sha)
    history = _run(repo, "log", "--format=", "--raw", "--no-abbrev",
                   "--no-renames", "-z", f"{fork}..{base}")
    if tree is None or history is None:
        return None
    wanted: dict[str, str] = {}
    for entry in tree.split("\0"):
        if "\t" in entry:
            meta, path = entry.split("\t", 1)
            wanted[path] = meta.split()[2]
    held: dict[str, set[str]] = {}
    tokens = history.split("\0")
    for index, token in enumerate(tokens):
        meta = token.lstrip("\n")
        if not meta.startswith(":") or index + 1 >= len(tokens):
            continue
        fields = meta.split()
        if len(fields) < 5:
            continue
        held.setdefault(tokens[index + 1], set()).add(
            "deleted" if fields[4].startswith("D") else fields[3])
    return [path for path in paths
            if wanted.get(path, "deleted") not in held.get(path, set())]


def content_on_base(repo: Path | str, sha: str, base: str = "main",
                    ignore: tuple[str, ...] = LIFECYCLE_FILES) -> LandedResult:
    repo = Path(repo)
    if git(repo, "rev-parse", "--verify", "-q", f"{sha}^{{commit}}").returncode != 0:
        return LandedResult(False, reason=f"commit {sha[:12]} not found in {repo.name}")
    if git(repo, "rev-parse", "--verify", "-q", f"{base}^{{commit}}").returncode != 0:
        return LandedResult(False, reason=f"base branch {base} not found in {repo.name}")

    if git(repo, "merge-base", "--is-ancestor", sha, base).returncode == 0:
        return LandedResult(True, method="ancestry")

    merge_base = git(repo, "merge-base", sha, base)
    fork = merge_base.stdout.strip()
    if merge_base.returncode != 0 or not fork:
        return LandedResult(
            False, reason=f"{sha[:12]} shares no history with {base}")

    cherry = git(repo, "cherry", base, sha)
    marks = [line[:1] for line in cherry.stdout.splitlines() if line.strip()]
    if cherry.returncode == 0 and marks and all(m == "-" for m in marks):
        return LandedResult(True, method="patch_equivalent")

    touched = _names(repo, fork, sha, ignore)
    differing = _names(repo, base, sha, ignore)
    if touched is None or differing is None:
        return LandedResult(False, reason=f"could not compare {sha[:12]} with {base}")
    if not touched:
        return LandedResult(True, method="nothing_to_land")
    missing = sorted(touched & differing)
    if not missing:
        return LandedResult(True, method="paths_identical")

    never = _never_on_base(repo, fork, sha, base, missing)
    if never is not None and not never:
        return LandedResult(True, method="content_in_history")
    if never:
        missing = never

    whole = _patch_ids(repo, ["diff", "--binary", "--no-renames", fork, sha,
                              "--", *_excludes(ignore)])
    on_base = _patch_ids(repo, ["log", "-p", "--binary", "--no-renames",
                                "--no-merges", f"{fork}..{base}",
                                "--", *_excludes(ignore)])
    if whole and on_base and whole <= on_base:
        return LandedResult(True, method="squash_equivalent")

    return LandedResult(False, reason=f"{sha[:12]} not on {base}; differs in",
                        missing=missing)
