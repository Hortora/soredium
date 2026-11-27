"""Git clone infrastructure for slot management.

Clone creation, remote configuration, hooks, alternates.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from slot_core import (
    run_cmd, resolve_canonical_repo,
    _IDE_ARTIFACTS, get_all_slot_repos,
    _cleanup_remnant_dir, SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME,
)

_work_end = Path(__file__).parent.parent / "work-end"
if _work_end.exists():
    sys.path.insert(0, str(_work_end))
try:
    from common import detect_topology as _detect_topology
except ImportError:
    _detect_topology = None


def configure_slot_remotes(clone_path: Path, canonical_path: Path) -> dict[str, str]:
    """Give a fresh slot clone one remote: `local`, its canonical repo.

    A slot never talks to GitHub. Work reaches the canonical repo with `work
    end`, and only the canonical repo publishes (Landing Rules), so a clone has
    no `origin` or `upstream`: there is nowhere for a stray push to go. The
    clone's base branch tracks `local/<base>`.

    Returns {"local": <canonical path>, "origin": "", "upstream": ""}; the two
    empty keys are kept for callers that still read them.
    """
    rc, existing, _ = run_cmd(["git", "-C", str(clone_path), "remote"])
    names = existing.split() if rc == 0 else []
    if "local" not in names and "origin" in names:
        run_cmd(["git", "-C", str(clone_path), "remote", "rename", "origin", "local"])
    elif "local" not in names:
        run_cmd(["git", "-C", str(clone_path), "remote", "add", "local", str(canonical_path)])
    rc, existing, _ = run_cmd(["git", "-C", str(clone_path), "remote"])
    for stray in ("origin", "upstream"):
        if rc == 0 and stray in existing.split():
            run_cmd(["git", "-C", str(clone_path), "remote", "remove", stray])
    run_cmd(["git", "-C", str(clone_path), "fetch", "-q", "local"])
    for base in ("main", "master"):
        rc, _, _ = run_cmd(["git", "-C", str(clone_path), "rev-parse", "--verify", "-q",
                            f"refs/heads/{base}"])
        if rc == 0:
            run_cmd(["git", "-C", str(clone_path), "branch",
                     f"--set-upstream-to=local/{base}", base])
            break
    return {"origin": "", "upstream": "", "local": str(canonical_path)}


_OLD_PUSH_HOOK = "#!/bin/sh\ngit push -u origin HEAD 2>/dev/null || true\n"


def _canonical_sync_script() -> str:
    override = os.environ.get("SOREDIUM_CANONICAL_SYNC")
    if override:
        return override
    return str(Path.home() / ".claude" / "skills" / "project" / "canonical_sync.py")


def install_post_commit_hook(clone_path: Path) -> None:
    """Install the post-commit hook that backs every commit up through canonical.

    A slot never pushes. The canonical repo takes a copy of the branch into
    refs/backup/<slot>/<branch> and sends that ref to the backup remote. A
    failure is printed to the committer and remembered in the clone's git
    directory; nothing is redirected away or swallowed.

    The earlier hook, which pushed the branch to origin and hid every failure,
    is replaced. Any other existing hook is left alone.
    """
    hooks_dir = clone_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / "post-commit"
    if hook_file.exists() and hook_file.read_text() != _OLD_PUSH_HOOK:
        return
    script = _canonical_sync_script()
    hook_file.write_text(
        "#!/bin/sh\n"
        "# soredium slot backup hook: canonical takes a copy of every commit.\n"
        f"python3 '{script}' backup \"$(git rev-parse --show-toplevel)\" offsite=yes >/dev/null\n"
    )
    hook_file.chmod(0o755)


def sync_main(repo_path: str) -> None:
    """Fetch and fast-forward local main so git clone --shared --branch main
    starts from the latest remote state.

    git clone --branch main reads the LOCAL main ref, not origin/main.
    Without fast-forwarding, clones inherit stale or unpushed state.
    """
    rc, _, _ = run_cmd(["git", "-C", repo_path, "fetch", "origin"])
    if rc != 0:
        print(f"WARN=fetch_failed repo={repo_path}")
        return
    rc, _, _ = run_cmd(["git", "-C", repo_path, "remote", "get-url", "upstream"])
    if rc == 0:
        run_cmd(["git", "-C", repo_path, "fetch", "upstream"])

    rc, current, _ = run_cmd(["git", "-C", repo_path, "branch", "--show-current"])
    if rc != 0:
        return
    current = current.strip()

    if current == "main":
        rc, _, _ = run_cmd(["git", "-C", repo_path, "merge", "--ff-only", "origin/main"])
        if rc != 0:
            print(f"WARN=main_ff_failed repo={repo_path}")
    else:
        rc, _, _ = run_cmd(["git", "-C", repo_path, "fetch", ".", "origin/main:main"])
        if rc != 0:
            print(f"WARN=main_update_failed repo={repo_path}")


def _cleanup_inherited_symlinks(clone_path: Path, slot_dir: Path) -> list[str]:
    """Remove absolute symlinks inherited from git clone that resolve outside the slot boundary."""
    if not clone_path.is_dir():
        return []
    slot_abs = str(slot_dir.resolve())
    removed: list[str] = []
    for entry in sorted(clone_path.iterdir()):
        if entry.name == ".git":
            continue
        if not entry.is_symlink():
            continue
        target = str(entry.resolve()) if entry.exists() else os.readlink(str(entry))
        if target.startswith("/") and not target.startswith(slot_abs):
            entry.unlink()
            removed.append(entry.name)
    return removed


_EXCLUDE_ENTRIES = {"wksp", "proj", ".claude",
                    ".work-progress", ".wrap-log.jsonl",
                    ".land-ledger.jsonl", ".close-state", ".workspace"}


def _exclude_symlinks(clone_path: Path) -> None:
    exclude_file = clone_path / ".git" / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    entries = set(_EXCLUDE_ENTRIES)
    if exclude_file.exists():
        existing_lines = {
            line.strip() for line in exclude_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        entries -= existing_lines
    if entries:
        with open(exclude_file, "a") as f:
            for entry in sorted(entries):
                f.write(f"{entry}\n")



def _repack_broken_alternates(slot_dir: Path, family_root: Path) -> int:
    """Scan sibling slots for git alternates referencing slot_dir; repack to sever."""
    slot_prefix = str(slot_dir) + "/"
    slots_root = slot_dir.parent
    repacked = 0

    for sibling in sorted(slots_root.iterdir()):
        if not sibling.is_dir() or sibling.name == "attic" or sibling == slot_dir:
            continue
        for repo_dir in sorted(sibling.iterdir()):
            alt_file = repo_dir / ".git" / "objects" / "info" / "alternates"
            if not alt_file.exists():
                continue
            lines = alt_file.read_text().strip().splitlines()
            remaining = [ln for ln in lines if not ln.startswith(slot_prefix)]
            if len(remaining) == len(lines):
                continue
            rc, _, err = run_cmd(
                ["git", "repack", "-a", "-d", "-l"],
                cwd=str(repo_dir),
            )
            if rc != 0:
                print(f"WARN=repack_failed repo={repo_dir} err={err.strip()}")
                continue
            if remaining:
                alt_file.write_text("\n".join(remaining) + "\n")
            else:
                alt_file.unlink()
            repacked += 1
            print(f"REPACKED={repo_dir.relative_to(slots_root)} (severed alternate to slot {slot_dir.name})")

    return repacked


