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

A third kind, any other hook that refuses and advises `--no-verify` alongside
/git-squash, is replaced too. Any other pre-push hook is left alone, and so is
a repo without one. Without --apply nothing is changed.

When the hook file is tracked by the repo (a .githooks directory), the
replacement is committed on the repo's base branch, that file only, in a
checkout of that branch: a working tree on another branch is not touched, and
its copy of the hook changes when that branch next includes the base branch.
A tracked hook with uncommitted changes on the checked-out base branch is
skipped. Nothing is pushed.

Output: one line per repo, then SUMMARY.
    REPLACE=<repo> hook=<path> kind=<old kind> tracked=<yes|no>     (REPLACED with --apply,
                         plus committed=<sha> on=<base branch> for a tracked hook)
    SKIPPED=<repo> reason=<why>   a tracked hook that could not be committed safely
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


_project = str(Path(__file__).resolve().parent.parent / "project")
if _project not in sys.path:
    sys.path.insert(0, _project)

COMMIT_MESSAGE = ("chore: pre-push hook checks linear history only\n\n"
                  "Replaces the retired hook that refused pushes and advised bypassing it.\n\n"
                  "no-issue: tooling")


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
    if "--no-verify" in text and "/git-squash" in text:
        return "bypass-advice"
    return "other"


def commit_on_base(repo: Path, hook: Path) -> tuple[str, str]:
    """Commit the replacement of a tracked hook on the repo's base branch.

    Returns (sha, base branch), or ("", reason) when it was not done. Works in
    canonical_sync.checked_out, so a working tree on another branch is never
    touched, and commits that one path only.
    """
    import canonical_sync
    rel = hook.resolve().relative_to(repo.resolve()).as_posix()
    try:
        base = canonical_sync.locate(repo).base
        with canonical_sync.checked_out(repo, base) as tree:
            tree = Path(tree)
            target = tree / rel
            if not target.is_file():
                return "", f"{rel} is not on {base}"
            if classify(target) in ("current",):
                return "", f"{rel} on {base} is already the current hook"
            if _git(tree, "status", "--porcelain", "--", rel):
                return "", f"{rel} has uncommitted changes on {base}"
            target.write_bytes(SOURCE.read_bytes())
            target.chmod(0o755)
            subprocess.run(["git", "-C", str(tree), "add", "--", rel],
                           capture_output=True, text=True)
            done = subprocess.run(
                ["git", "-C", str(tree), "commit", "-q", "-m", COMMIT_MESSAGE, "--", rel],
                capture_output=True, text=True)
            if done.returncode != 0:
                subprocess.run(["git", "-C", str(tree), "reset", "-q", "--", rel],
                               capture_output=True, text=True)
                subprocess.run(["git", "-C", str(tree), "checkout", "-q", "--", rel],
                               capture_output=True, text=True)
                return "", "commit refused: " + " ".join((done.stderr or done.stdout).split())[:200]
            return _git(tree, "rev-parse", "--short", "HEAD"), base
    except canonical_sync.SyncError as error:
        return "", error.detail


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
                if apply and tracked == "yes":
                    sha, where = commit_on_base(repo, hook)
                    if sha:
                        action = "REPLACED"
                        detail += f" committed={sha} on={where}"
                    else:
                        action, detail = "SKIPPED", f" reason={where}"
                elif apply:
                    hook.write_bytes(SOURCE.read_bytes())
                    hook.chmod(0o755)
                    action = "REPLACED"
            print(f"{action}={repo}{detail}")
            counts[action] = counts.get(action, 0) + 1
    print("SUMMARY=" + (", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "no repos"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
