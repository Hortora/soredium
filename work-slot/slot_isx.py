"""slot_isx.py — ISX instance lifecycle management."""

import shutil
from pathlib import Path

from slot_core import run_cmd, get_slot_repos
from slot_metadata import parse_slot_md


def _check_isx_available() -> bool:
    return shutil.which("isx") is not None


def _truncate_instance_name(name: str, max_len: int = 63) -> str:
    if len(name) <= max_len:
        return name
    return name[:max_len].rstrip("-")


def _teardown_isx(slot_dir: Path) -> None:
    info = parse_slot_md(slot_dir)
    if info.get("isolation_type") != "isx":
        return
    instance = info.get("isx_instance", "")
    if not instance:
        return
    rc, _, stderr = run_cmd(["isx", "destroy", instance])
    if rc != 0:
        print(f"WARN=isx_destroy_failed instance={instance} err={stderr.strip()}")


def _wire_isx_remotes(slot_dir: Path, repos: list[str], instance: str) -> None:
    for repo_name in repos:
        clone_path = slot_dir / repo_name
        if not clone_path.is_dir():
            continue
        remote_url = f"isx://{instance}/home/agentuser/{repo_name}"
        run_cmd(["git", "-C", str(clone_path), "remote", "add", "isx", remote_url])


def sync_isx(slot_dir: Path) -> int:
    info = parse_slot_md(slot_dir)
    if info.get("isolation_type") != "isx":
        print("ERROR=not_isx_slot")
        print("ERROR_DETAIL=This slot has no ISX isolation.")
        return 1

    branch = info.get("branch", "")
    repos = get_slot_repos(slot_dir)

    for repo_name in repos:
        clone_path = slot_dir / repo_name
        if not clone_path.is_dir():
            continue
        rc, _, _ = run_cmd(["git", "-C", str(clone_path), "remote", "get-url", "isx"])
        if rc != 0:
            print(f"WARN=no_isx_remote repo={repo_name}")
            continue
        rc, _, stderr = run_cmd(["git", "-C", str(clone_path), "fetch", "isx", branch])
        if rc != 0:
            print(f"WARN=fetch_failed repo={repo_name} err={stderr.strip()}")
            continue
        rc, _, stderr = run_cmd(["git", "-C", str(clone_path), "merge", "--ff-only", f"isx/{branch}"])
        if rc != 0:
            print(f"ERROR=merge_failed repo={repo_name} err={stderr.strip()}")
            print("ERROR_DETAIL=Histories have diverged. Resolve manually or reset.")
            return 1
        print(f"SYNCED={repo_name}")

    return 0
