"""Shared test helpers for slot_manager decomposition tests."""

import subprocess
from pathlib import Path


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True, check=True)
    return path


def init_repo_with_workspace(path: Path) -> Path:
    """Create a git repo with a companion workspace repo and wksp symlink."""
    repo = init_repo(path)
    ws_path = path.parent / f"wsp-{path.parent.name}-{path.name}"
    ws = init_repo(ws_path)
    (repo / "wksp").symlink_to(ws)
    return repo


def init_repo_with_remote(path: Path) -> Path:
    bare = path.parent / f".{path.name}-bare.git"
    bare.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(bare), str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], capture_output=True)
    (path / "README.md").write_text(f"# {path.name}\n")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "initial"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "push", "-u", "origin", "main"], capture_output=True, check=True)
    return path


def land_slot(family: Path, slot: Path, branch: str) -> dict[str, str]:
    """Put a slot in the landed state the way a finished close leaves it.

    Each repo's branch is fast-forwarded onto its canonical main, and the slot's
    .landed marker records the SHAs. Returns {repo: sha}.
    """
    import datetime
    shas: dict[str, str] = {}
    for clone in sorted(d for d in slot.iterdir() if (d / ".git").exists()):
        canonical = family / clone.name
        if not canonical.is_dir():
            continue
        tip = subprocess.run(["git", "-C", str(clone), "rev-parse", "--verify", "-q", branch],
                             capture_output=True, text=True).stdout.strip()
        if not tip:
            continue
        subprocess.run(["git", "-C", str(canonical), "fetch", "-q", str(clone), branch],
                       capture_output=True, check=True)
        current = subprocess.run(["git", "-C", str(canonical), "branch", "--show-current"],
                                 capture_output=True, text=True).stdout.strip()
        if current == "main":
            subprocess.run(["git", "-C", str(canonical), "merge", "-q", "--ff-only", tip],
                           capture_output=True, check=True)
        else:
            subprocess.run(["git", "-C", str(canonical), "branch", "-f", "main", tip],
                           capture_output=True, check=True)
        shas[clone.name] = tip
    (slot / ".landed").write_text("\n".join([
        f"branch={branch}",
        f"repos={','.join(shas)}",
        f"landed_shas={','.join(f'{n}:{s}' for n, s in shas.items())}",
        f"timestamp={datetime.datetime.now(datetime.timezone.utc).isoformat()}",
    ]) + "\n")
    return shas
