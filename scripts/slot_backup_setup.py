#!/usr/bin/env python3
"""Bring existing slots and workspace repos onto the canonical backup path (#515).

    slot_backup_setup.py hooks <family-root> [--apply]
        Every slot clone under <family-root>/slots/<N>/ whose post-commit hook is
        the old "git push -u origin HEAD || true" gets the backup hook instead
        (work-slot/slot_git.py install_post_commit_hook). A clone with no hook
        gets one. A custom hook is left alone. A clone that cannot name its
        canonical repo is left alone and reported: the backup would fail on
        every commit.

    slot_backup_setup.py remotes <root> [owner=<name>] [--apply]
        Every workspace repo (a git repo holding a .workspace marker) under
        <root> that has exactly one remote gets `soredium.backupRemote` set to
        it, so slot backups of that repo also leave the machine. Repos with a
        fork already send backups there and are not touched. With owner=<name>
        only remotes owned by that GitHub account are set; the rest are
        reported as OTHER_OWNER and left, so working branches are never sent
        to a remote other people share.

    slot_backup_setup.py detach <family-root> [--apply]
        Every slot clone under <family-root>/slots/<N>/ loses its GitHub remotes,
        so the only place its work can go is its canonical repo. Before a remote
        is removed, every local branch of the clone is copied into the canonical
        repo (refs/backup/<slot>/<branch>); if any copy fails the clone is left
        exactly as it is. A clone whose `origin` is a local path to its canonical
        repo and that has no `local` remote gets `origin` renamed to `local`.
        Remotes that are local paths or non-GitHub URLs are kept. A clone that
        cannot name a canonical repo is left alone and reported.

Without --apply nothing is changed: each line says what would be done.
Output is one KEY=value line per repo and a SUMMARY line. Remote URLs are
printed without any credentials embedded in them.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
for _sub in ("project", "work-slot"):
    if str(_root / _sub) not in sys.path:
        sys.path.insert(0, str(_root / _sub))

import canonical_sync  # noqa: E402
import slot_git  # noqa: E402

OLD_HOOK = slot_git._OLD_PUSH_HOOK
BACKUP_KEY = "soredium.backupRemote"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def safe_url(url: str) -> str:
    """The URL with any user, password or token removed."""
    return re.sub(r"(?<=://)[^/@]*@", "", url)


def url_owner(url: str) -> str:
    """The account a GitHub-style URL belongs to, "" when it cannot be read."""
    match = re.search(r"[:/]([^/:@]+)/[^/]+?(?:\.git)?/?$", safe_url(url))
    return match.group(1) if match else ""


def hook_state(clone: Path) -> str:
    hook = clone / ".git" / "hooks" / "post-commit"
    if not hook.exists():
        return "missing"
    text = hook.read_text()
    if text == OLD_HOOK:
        return "old"
    if "canonical_sync.py" in text and " backup " in text:
        return "current"
    return "custom"


def slot_clones(family_root: Path) -> list[Path]:
    slots = family_root / "slots"
    if not slots.is_dir():
        return []
    return [clone
            for slot in sorted(slots.iterdir(), key=lambda p: p.name)
            if slot.is_dir() and slot.name.isdigit()
            for clone in sorted(slot.iterdir())
            if (clone / ".git").is_dir()]


def cmd_hooks(family_root: Path, apply: bool) -> int:
    counts: dict[str, int] = {}
    for clone in slot_clones(family_root):
        label = f"{clone.parent.name}/{clone.name}"
        state = hook_state(clone)
        if state in ("old", "missing"):
            try:
                canonical_sync.locate(clone)
            except canonical_sync.SyncError as error:
                action = "NO_CANONICAL"
                print(f"{action}={label} hook={state} detail={error.detail}")
                counts[action] = counts.get(action, 0) + 1
                continue
            action = "REPLACE" if state == "old" else "INSTALL"
            if apply:
                slot_git.install_post_commit_hook(clone)
                action += "D" if action == "REPLACE" else "ED"
        elif state == "current":
            action = "OK"
        else:
            action = "CUSTOM_LEFT"
        print(f"{action}={label}")
        counts[action] = counts.get(action, 0) + 1
    print("SUMMARY=" + (", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "no slot clones"))
    return 0


def _is_hosted(url: str) -> bool:
    """A remote on a hosting service, as opposed to a path on this machine or a
    private transport. Only hosted remotes are removed from a slot clone."""
    return bool(re.match(r"^(https?://|git@|ssh://|git://)", url))


def _local_branches(clone: Path) -> list[str]:
    return [b for b in _git(clone, "for-each-ref", "--format=%(refname:short)",
                            "refs/heads").splitlines() if b]


def cmd_detach(family_root: Path, apply: bool) -> int:
    counts: dict[str, int] = {}

    def tally(action: str, line: str) -> None:
        print(line)
        counts[action] = counts.get(action, 0) + 1

    for clone in slot_clones(family_root):
        label = f"{clone.parent.name}/{clone.name}"
        remotes = {name: _git(clone, "remote", "get-url", name)
                   for name in _git(clone, "remote").split()}

        rename = False
        if "local" not in remotes:
            origin = remotes.get("origin", "")
            if origin and not _is_hosted(origin) and Path(origin).is_dir() \
                    and (Path(origin) / ".git").exists():
                rename = True
            else:
                tally("NO_CANONICAL", f"NO_CANONICAL={label} remotes={','.join(remotes) or 'none'}")
                continue

        hosted = sorted(name for name, url in remotes.items()
                        if name != "local" and _is_hosted(url) and not (rename and name == "origin"))
        if not hosted and not rename:
            tally("OK", f"OK={label}")
            continue

        plan = ([f"rename origin->local"] if rename else []) + [f"remove {name}" for name in hosted]
        if not apply:
            tally("DETACH", f"DETACH={label} {'; '.join(plan)} branches={len(_local_branches(clone))}")
            continue

        if rename:
            subprocess.run(["git", "-C", str(clone), "remote", "rename", "origin", "local"],
                           capture_output=True)
        failed = []
        for branch in _local_branches(clone):
            try:
                canonical_sync.backup(clone, branch)
            except canonical_sync.SyncError as error:
                failed.append(f"{branch}: {error.detail}")
        if failed:
            # Nothing is removed from a clone whose work is not safely in canonical.
            if rename:
                subprocess.run(["git", "-C", str(clone), "remote", "rename", "local", "origin"],
                               capture_output=True)
            tally("BACKUP_FAILED", f"BACKUP_FAILED={label} {failed[0]}")
            continue
        for name in hosted:
            subprocess.run(["git", "-C", str(clone), "remote", "remove", name], capture_output=True)
        base = canonical_sync.locate(clone).base
        subprocess.run(["git", "-C", str(clone), "fetch", "-q", "local"], capture_output=True)
        if _git(clone, "rev-parse", "--verify", "-q", f"refs/heads/{base}"):
            subprocess.run(["git", "-C", str(clone), "branch", f"--set-upstream-to=local/{base}", base],
                           capture_output=True)
        tally("DETACHED", f"DETACHED={label} {'; '.join(plan)}")
    print("SUMMARY=" + (", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "no slot clones"))
    return 0


def workspace_repos(root: Path, depth: int = 3) -> list[Path]:
    found: list[Path] = []

    def walk(directory: Path, remaining: int) -> None:
        if (directory / ".git").exists():
            if (directory / ".workspace").exists():
                found.append(directory)
        if remaining == 0:
            return
        for child in sorted(directory.iterdir()):
            if child.is_dir() and not child.is_symlink() and not child.name.startswith("."):
                walk(child, remaining - 1)

    walk(root, depth)
    return found


def cmd_remotes(root: Path, apply: bool, owner: str = "") -> int:
    counts: dict[str, int] = {}
    for repo in workspace_repos(root):
        label = str(repo.relative_to(root)) if repo != root else repo.name
        remotes = _git(repo, "remote").split()
        configured = _git(repo, "config", "--get", BACKUP_KEY)
        if configured:
            action, detail = "OK", f"remote={configured}"
        elif len(remotes) == 1:
            url = safe_url(_git(repo, "remote", "get-url", remotes[0]))
            action, detail = "SET", f"remote={remotes[0]} url={url}"
            if owner and url_owner(url).lower() != owner.lower():
                action = "OTHER_OWNER"
            elif apply:
                subprocess.run(["git", "-C", str(repo), "config", BACKUP_KEY, remotes[0]],
                               capture_output=True, check=True)
                action = "SET_DONE"
        elif not remotes:
            action, detail = "NO_REMOTE", "nothing to back up to"
        else:
            mirror = canonical_sync.locate(repo).mirror
            action, detail = ("FORK", f"remote={mirror}") if mirror else \
                ("AMBIGUOUS", f"remotes={','.join(remotes)}")
        print(f"{action}={label} {detail}")
        counts[action] = counts.get(action, 0) + 1
    print("SUMMARY=" + (", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "no workspace repos"))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in args
    owner = next((a[len("owner="):] for a in args if a.startswith("owner=")), "")
    args = [a for a in args if a != "--apply" and not a.startswith("owner=")]
    if len(args) != 2 or args[0] not in ("hooks", "remotes", "detach") or not Path(args[1]).is_dir():
        print("usage: slot_backup_setup.py <hooks|remotes|detach> <directory> [owner=<name>] [--apply]",
              file=sys.stderr)
        return 2
    print("MODE=" + ("apply" if apply else "dry-run"))
    if args[0] == "hooks":
        return cmd_hooks(Path(args[1]), apply)
    if args[0] == "detach":
        return cmd_detach(Path(args[1]), apply)
    return cmd_remotes(Path(args[1]), apply, owner)


if __name__ == "__main__":
    sys.exit(main())
