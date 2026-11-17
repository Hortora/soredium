#!/usr/bin/env python3
"""Replace old soredium pre-push hooks with the one that checks linear history only (#515).

    install_linear_pre_push.py <directory> [<directory> ...] [--apply]

Looks at every git repo directly inside each directory (and the directory itself
when it is a repo). Two old hooks are replaced:

  - the "squash candidates" hook, which refused a push when commit subjects
    matched a list of patterns;
  - the "always prompt for /git-squash" hook, which refused every push.

Both stop `canonical_sync.py publish`, which pushes without --no-verify. History
is reviewed before landing now (work-end/close.py), not at push time.

Any other pre-push hook is left alone, and so is a repo without one. Without
--apply nothing is changed. When the hook file is tracked by the repo (a
.githooks directory), replacing it leaves a modification for that repo's owner
to commit; this script never commits.

Output: one line per repo, then SUMMARY.
    REPLACE=<repo> hook=<path> kind=<old kind> tracked=<yes|no>     (REPLACED with --apply)
    OK=<repo>            already the current hook
    OTHER_LEFT=<repo>    some other hook; not touched
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "git-squash" / "hooks" / "pre-push"
CURRENT_MARK = "a base branch stays linear and is never rewritten"
OLD_KINDS = (
    ("squash-candidates", "SQUASH_PATTERNS"),
    ("always-prompt", "always prompt for /git-squash"),
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def hook_path(repo: Path) -> Path:
    """The repo's own pre-push hook: under its own core.hooksPath when it sets one,
    otherwise .git/hooks. A machine-wide core.hooksPath (a hook dispatcher) is not
    the repo's own and is never touched."""
    configured = _git(repo, "config", "--local", "core.hooksPath")
    if configured:
        path = Path(configured).expanduser()
        return (path if path.is_absolute() else repo / path) / "pre-push"
    return repo / ".git" / "hooks" / "pre-push"


def classify(hook: Path) -> str:
    if not hook.is_file():
        return "none"
    text = hook.read_text(errors="replace")
    if CURRENT_MARK in text:
        return "current"
    for kind, mark in OLD_KINDS:
        if mark in text:
            return kind
    return "other"


def repos_in(directory: Path) -> list[Path]:
    found = [directory] if (directory / ".git").is_dir() else []
    found += sorted(child for child in directory.iterdir()
                    if child.is_dir() and not child.is_symlink() and (child / ".git").is_dir())
    return found


def is_tracked(repo: Path, hook: Path) -> bool:
    try:
        rel = hook.resolve().relative_to(repo.resolve())
    except ValueError:
        return False
    return bool(_git(repo, "ls-files", "--", rel.as_posix()))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in args
    directories = [Path(a) for a in args if a != "--apply"]
    if not directories or not all(d.is_dir() for d in directories):
        print("usage: install_linear_pre_push.py <directory> [<directory> ...] [--apply]",
              file=sys.stderr)
        return 2
    print("MODE=" + ("apply" if apply else "dry-run"))
    counts: dict[str, int] = {}
    seen: set[Path] = set()
    for directory in directories:
        for repo in repos_in(directory):
            if repo.resolve() in seen:
                continue
            seen.add(repo.resolve())
            hook = hook_path(repo)
            kind = classify(hook)
            if kind == "none":
                counts["NONE"] = counts.get("NONE", 0) + 1
                continue
            if kind == "current":
                action, detail = "OK", ""
            elif kind == "other":
                action, detail = "OTHER_LEFT", ""
            else:
                tracked = "yes" if is_tracked(repo, hook) else "no"
                action = "REPLACE"
                detail = f" hook={hook} kind={kind} tracked={tracked}"
                if apply:
                    hook.write_bytes(SOURCE.read_bytes())
                    hook.chmod(0o755)
                    action = "REPLACED"
            print(f"{action}={repo}{detail}")
            counts[action] = counts.get(action, 0) + 1
    print("SUMMARY=" + (", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "no repos"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
