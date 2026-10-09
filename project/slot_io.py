"""slot_io.py — canonical .slot and .landed file I/O.

Single source of truth for slot structure parsing. All pipeline code
imports from here.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LandedInfo:
    shas: dict[str, str]
    has_ledger: bool
    issues: set[int]
    branch: str
    failed: str


@dataclass(frozen=True)
class SlotInfo:
    repos: list[str]
    primary: str
    branch: str
    title: str
    description: str
    issue: str
    issue_repo: str
    covers: str
    is_epic: bool
    isolation_type: str
    isx_instance: str
    isx_template: str
    state: str
    context: str
    slot_number: int | None


def parse_slot(slot_dir: Path) -> SlotInfo | None:
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return None

    content = slot_file.read_text()
    repos: list[str] = []
    primary = ""
    branch = ""
    title = ""
    description_lines: list[str] = []
    issue = ""
    issue_repo = ""
    covers = ""
    is_epic = False
    isolation_type = ""
    isx_instance = ""
    isx_template = ""
    state = "active"
    context_lines: list[str] = []
    slot_number: int | None = None

    section = ""
    for line in content.splitlines():
        if line.startswith("# Slot"):
            m = re.match(r"# Slot (\d+)", line)
            if m:
                slot_number = int(m.group(1))
            if "—" in line:
                branch = line.split("—", 1)[1].strip()
        if line.startswith("slug:"):
            branch = line.split(":", 1)[1].strip()
        if line.startswith("title:"):
            title = line.split(":", 1)[1].strip()
        if line.startswith("Covers:"):
            covers = line.split(":", 1)[1].strip()

        if line.startswith("## "):
            section = line.strip()
            continue

        if section == "## Issue":
            stripped = line.strip()
            if stripped.startswith("Type:"):
                is_epic = stripped.split(":", 1)[1].strip() == "epic"
            elif "#" in stripped and not stripped.startswith("Covers:"):
                parts = stripped.split("#")
                if len(parts) == 2:
                    issue_repo = parts[0]
                    issue = parts[1]
        elif section == "## Description":
            description_lines.append(line.strip())
        elif section == "## What to do":
            context_lines.append(line.strip())
        elif section == "## Repos":
            stripped = line.strip()
            if stripped.startswith("- "):
                is_primary = "(primary)" in stripped
                name = stripped[2:].split("(")[0].strip()
                if name:
                    if is_primary:
                        primary = name
                    repos.append(name)
        elif section == "## Isolation":
            stripped = line.strip()
            if stripped.startswith("type:"):
                isolation_type = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("instance:"):
                isx_instance = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("template:"):
                isx_template = stripped.split(":", 1)[1].strip()
        elif section in ("## State", "## Status"):
            stripped = line.strip()
            if stripped.startswith("state:") or stripped.startswith("status:"):
                state = stripped.split(":", 1)[1].strip()

    if primary and primary in repos:
        repos.remove(primary)
        repos.insert(0, primary)
    elif repos and not primary:
        primary = repos[0]

    return SlotInfo(
        repos=repos,
        primary=primary,
        branch=branch,
        title=title,
        description=" ".join(l for l in description_lines if l).strip(),
        issue=issue,
        issue_repo=issue_repo,
        covers=covers,
        is_epic=is_epic,
        isolation_type=isolation_type,
        isx_instance=isx_instance,
        isx_template=isx_template,
        state=state,
        context=" ".join(l for l in context_lines if l).strip(),
        slot_number=slot_number,
    )


def parse_landed(slot_dir: Path) -> LandedInfo | None:
    landed_file = slot_dir / ".landed"
    if not landed_file.exists():
        return None

    shas: dict[str, str] = {}
    has_ledger = False
    issues: set[int] = set()
    branch = ""
    failed = ""

    for line in landed_file.read_text().splitlines():
        if line.startswith("landed_shas="):
            shas_str = line.split("=", 1)[1]
            for entry in shas_str.split(","):
                if ":" in entry:
                    repo, sha = entry.split(":", 1)
                    shas[repo] = sha
        elif line.startswith("issue="):
            has_ledger = True
            parts = {p.split("=", 1)[0]: p.split("=", 1)[1]
                     for p in line.split() if "=" in p}
            if "issue" in parts:
                try:
                    issues.add(int(parts["issue"]))
                except ValueError:
                    pass
            if "repo" in parts and "sha" in parts:
                shas[parts["repo"]] = parts["sha"]
        elif line.startswith("branch="):
            branch = line.split("=", 1)[1]
        elif line.startswith("failed="):
            failed = line.split("=", 1)[1]

    return LandedInfo(
        shas=shas,
        has_ledger=has_ledger,
        issues=issues,
        branch=branch,
        failed=failed,
    )


def discover_repos(slot_dir: Path) -> list[str]:
    repos = []
    for entry in sorted(slot_dir.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        if entry.name in (".m2", "attic"):
            continue
        if (entry / ".workspace").exists():
            continue
        repos.append(entry.name)
    return repos


def write_slot(slot_dir: Path, *, slot_number: int, repos: list[str],
               branch: str, issue: str, issue_repo: str, covers: str,
               context: str, title: str = "", description: str = "",
               isolation_type: str = "", isx_instance: str = "",
               isx_template: str = "") -> None:
    content = f"# Slot {slot_number}\n"
    content += f"slug: {branch}\n"
    if title:
        content += f"title: {title}\n"
    content += f"\n## Issue\n{issue_repo}#{issue}\nCovers: {covers}\n"
    if description:
        content += f"\n## Description\n{description}\n"
    content += f"\n## What to do\n{context}\n"
    content += "\n## Repos\n"
    for i, repo in enumerate(repos):
        primary = " (primary)" if i == 0 else ""
        content += f"- {repo}{primary}\n"
    if isolation_type:
        content += (f"\n## Isolation\ntype: {isolation_type}\n"
                    f"instance: {isx_instance}\ntemplate: {isx_template}\n")
    content += f"\n## State\nstate: active\n"
    content += f"\n## Created\n{datetime.date.today().isoformat()}, branch: {branch}\n"
    (slot_dir / ".slot").write_text(content)


def set_slot_state(slot_dir: Path, state: str) -> bool:
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return False
    lines = slot_file.read_text().splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.strip().startswith("state:") or line.strip().startswith("status:"):
            lines[i] = f"state: {state}"
            updated = True
            break
    if not updated:
        for i, line in enumerate(lines):
            if line.startswith("## Created"):
                lines.insert(i, f"\n## State\nstate: {state}\n")
                updated = True
                break
    if not updated:
        lines.append(f"\n## State\nstate: {state}")
    slot_file.write_text("\n".join(lines) + "\n")
    return True


def write_landed(slot_dir: Path, *, shas: dict[str, str],
                 issues: str, branch: str,
                 failed: str = "") -> None:
    shas_str = ",".join(f"{k}:{v}" for k, v in shas.items() if v)
    content = f"landed_shas={shas_str}\nissues={issues}\nbranch={branch}\n"
    if failed:
        content += f"failed={failed}\n"
    (slot_dir / ".landed").write_text(content)
