#!/usr/bin/env python3
"""Clone manager — create and manage family clone directories.

Commands:
  create   — create a local clone of a canonical repo
  status   — check if a clone exists for a repo
  enabled  — check if clone feature is enabled system-wide

The clone feature is OFF by default. Enable with:
  claude config set clone_enabled true
Or add "clone_enabled": true to ~/.claude/settings.json.

Usage:
  python3 clone_manager.py create family_root=<path> repo=<name>
  python3 clone_manager.py status family_root=<path> repo=<name>
  python3 clone_manager.py enabled
"""

import json
import subprocess
import sys
from pathlib import Path


def _settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def is_enabled() -> bool:
    """Check if clone feature is enabled in settings."""
    settings_file = _settings_path()
    if not settings_file.exists():
        return False
    try:
        settings = json.loads(settings_file.read_text())
        return settings.get("clone_enabled", False) is True
    except (json.JSONDecodeError, OSError):
        return False


def clone_exists(family_root: Path, repo: str) -> Path | None:
    """Return clone path if it exists, None otherwise."""
    clone_path = family_root / "clone" / repo
    if clone_path.is_dir() and (clone_path / ".git").exists():
        return clone_path
    return None


def is_declined(family_root: Path, repo: str) -> bool:
    """Check if clone was declined for this repo."""
    config_file = family_root / "clone" / ".clone-config"
    if not config_file.exists():
        return False
    for line in config_file.read_text().splitlines():
        if line.strip() == f"decline:{repo}":
            return True
    return False


def record_decline(family_root: Path, repo: str) -> None:
    """Record that the user declined clone for this repo."""
    clone_dir = family_root / "clone"
    clone_dir.mkdir(exist_ok=True)
    config_file = clone_dir / ".clone-config"
    existing = config_file.read_text() if config_file.exists() else ""
    marker = f"decline:{repo}"
    if marker not in existing:
        config_file.write_text(existing.rstrip() + f"\n{marker}\n")


def create_clone(family_root: Path, repo: str) -> dict[str, str]:
    """Create a local clone of canonical_repo into clone/<repo>.

    Returns dict with CREATED, CLONE_PATH, or ERROR keys.
    """
    canonical = family_root / repo
    if not canonical.is_dir() or not (canonical / ".git").exists():
        return {"ERROR": "canonical_not_found",
                "ERROR_DETAIL": f"No git repo at {canonical}"}

    clone_dir = family_root / "clone"
    clone_dir.mkdir(exist_ok=True)

    target = clone_dir / repo
    if target.is_dir() and (target / ".git").exists():
        return {"CREATED": "already_exists",
                "CLONE_PATH": str(target)}

    result = subprocess.run(
        ["git", "clone", "--local", str(canonical), str(target)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return {"ERROR": "clone_failed",
                "ERROR_DETAIL": result.stderr.strip()[:200]}

    return {"CREATED": "yes", "CLONE_PATH": str(target)}


def cmd_create(opts: dict[str, str]) -> int:
    family_root = Path(opts.get("family_root", ""))
    repo = opts.get("repo", "")
    if not family_root or not repo:
        print("ERROR=missing_args")
        print("ERROR_DETAIL=family_root and repo are required")
        return 1
    result = create_clone(family_root, repo)
    for k, v in result.items():
        print(f"{k}={v}")
    return 1 if "ERROR" in result else 0


def cmd_status(opts: dict[str, str]) -> int:
    family_root = Path(opts.get("family_root", ""))
    repo = opts.get("repo", "")
    if not family_root or not repo:
        print("ERROR=missing_args")
        return 1
    existing = clone_exists(family_root, repo)
    if existing:
        print(f"EXISTS=yes")
        print(f"CLONE_PATH={existing}")
    else:
        print("EXISTS=no")
    declined = is_declined(family_root, repo)
    print(f"DECLINED={'yes' if declined else 'no'}")
    return 0


def cmd_decline(opts: dict[str, str]) -> int:
    family_root = Path(opts.get("family_root", ""))
    repo = opts.get("repo", "")
    if not family_root or not repo:
        print("ERROR=missing_args")
        return 1
    record_decline(family_root, repo)
    print(f"DECLINED=yes")
    print(f"REPO={repo}")
    return 0


def cmd_enabled() -> int:
    enabled = is_enabled()
    print(f"ENABLED={'yes' if enabled else 'no'}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: clone_manager.py <create|status|enabled> key=value ...",
              file=sys.stderr)
        return 1

    command = sys.argv[1]
    opts: dict[str, str] = {}
    for arg in sys.argv[2:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            opts[k] = v

    if command == "enabled":
        return cmd_enabled()
    elif command == "create":
        return cmd_create(opts)
    elif command == "status":
        return cmd_status(opts)
    elif command == "decline":
        return cmd_decline(opts)
    else:
        print(f"ERROR=unknown_command")
        return 1


if __name__ == "__main__":
    sys.exit(main())
