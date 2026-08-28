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
