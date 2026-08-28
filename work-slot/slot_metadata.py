"""slot_metadata.py — .slot file parsing/writing, promotion stamps, landed markers."""

import datetime
from pathlib import Path

from slot_core import run_cmd, get_slot_repos


def _read_promotion_stamp(slot_dir: Path) -> tuple[list[str], list[str], str]:
    """Read artifact promotion data from .artifacts-promoted stamps in the slot.
    Returns (promoted_files, published_blogs, publish_dest)."""
    promoted: list[str] = []
    published: list[str] = []
    pub_dest = ""

    for sub in slot_dir.iterdir():
        if not sub.is_dir():
            continue
        stamp = sub / ".artifacts-promoted"
        if not stamp.exists():
            stamp = sub / "design" / ".artifacts-promoted"
        if not stamp.exists():
            continue
        stamp_data: dict[str, str] = {}
        for line in stamp.read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                stamp_data[k.strip()] = v.strip()

        ws_count = int(stamp_data.get("workspace_promoted", "0"))
        proj_count = int(stamp_data.get("project_promoted", "0"))
        blog_count = int(stamp_data.get("blog_published", "0"))
        plans_count = int(stamp_data.get("plans_archived", "0"))

        if ws_count > 0:
            promoted.append(f"workspace:{ws_count}")
        if proj_count > 0:
            promoted.append(f"project:{proj_count}")
        if plans_count > 0:
            promoted.append(f"plans:{plans_count}")
        if blog_count > 0:
            published.append(f"blog:{blog_count}")

    return promoted, published, pub_dest


def write_slot_md(slot_dir: Path, slot_number: int, repos: list[str],
                  branch: str, issue: str, issue_repo: str,
                  covers: str, context: str,
                  isolation_type: str = "", isx_instance: str = "",
                  isx_template: str = "") -> None:
    content = f"""# Slot {slot_number} — {branch}

## Issue
{issue_repo}#{issue}
Covers: {covers}

## What to do
{context}

## Repos
"""
    for i, repo in enumerate(repos):
        primary = " (primary)" if i == 0 else ""
        content += f"- {repo}{primary}\n"
    if isolation_type:
        content += f"\n## Isolation\ntype: {isolation_type}\ninstance: {isx_instance}\ntemplate: {isx_template}\n"
    content += f"\n## Created\n{datetime.date.today().isoformat()}, branch: {branch}\n"
    (slot_dir / ".slot").write_text(content)


def parse_slot_md(slot_dir: Path) -> dict:
    slot_md = slot_dir / ".slot"
    if not slot_md.exists():
        return {}
    content = slot_md.read_text()
    result: dict = {"repos": [], "context": "", "issue": "", "issue_repo": "", "covers": "", "is_epic": False, "isolation_type": "", "isx_instance": "", "isx_template": ""}

    in_issue = False
    in_what = False
    in_repos = False
    in_isolation = False
    context_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("# Slot") and "—" in line:
            result["branch"] = line.split("—", 1)[1].strip()
        if line.startswith("Covers:"):
            result["covers"] = line.split(":", 1)[1].strip()
        if line.startswith("## Issue"):
            in_issue, in_what, in_repos, in_isolation = True, False, False, False
            continue
        if line.startswith("## What to do"):
            in_issue, in_what, in_repos, in_isolation = False, True, False, False
            continue
        if line.startswith("## Repos"):
            in_issue, in_what, in_repos, in_isolation = False, False, True, False
            continue
        if line.startswith("## Isolation"):
            in_issue, in_what, in_repos, in_isolation = False, False, False, True
            continue
        if line.startswith("## "):
            in_issue, in_what, in_repos, in_isolation = False, False, False, False
            continue
        if in_issue and line.strip().startswith("Type:"):
            result["is_epic"] = line.strip().split(":", 1)[1].strip() == "epic"
        if in_issue and "#" in line and not line.startswith("Covers:"):
            parts = line.strip().split("#")
            if len(parts) == 2:
                result["issue_repo"] = parts[0]
                result["issue"] = parts[1]
        if in_what:
            context_lines.append(line.strip())
        if in_repos and line.strip().startswith("- "):
            repo_name = line.strip().lstrip("- ").split(" ")[0].strip()
            if repo_name:
                result["repos"].append(repo_name)
        if in_isolation:
            stripped = line.strip()
            if stripped.startswith("type:"):
                result["isolation_type"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("instance:"):
                result["isx_instance"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("template:"):
                result["isx_template"] = stripped.split(":", 1)[1].strip()

    result["context"] = " ".join(l for l in context_lines if l).strip()
    return result


def is_slot_landed(slot_dir: Path) -> bool:
    return (slot_dir / ".landed").exists()


def verify_landed_shas(slot_dir: Path, family_root: Path) -> tuple[bool, list[str]]:
    landed_file = slot_dir / ".landed"
    if not landed_file.exists():
        return False, ["no .landed marker"]
    shas_line = ""
    for line in landed_file.read_text().splitlines():
        if line.startswith("landed_shas="):
            shas_line = line.split("=", 1)[1]
    if not shas_line:
        return False, ["no landed_shas in .landed marker"]
    failures = []
    for entry in shas_line.split(","):
        if ":" not in entry:
            continue
        repo_name, sha = entry.split(":", 1)
        if sha == "unknown":
            failures.append(f"{repo_name}: SHA is 'unknown'")
            continue
        original = family_root / repo_name
        if not original.is_dir():
            failures.append(f"{repo_name}: original repo not found at {original}")
            continue
        run_cmd(["git", "-C", str(original), "fetch", "origin", "main"])
        rc, _, _ = run_cmd([
            "git", "-C", str(original), "merge-base", "--is-ancestor", sha, "origin/main",
        ])
        if rc != 0:
            failures.append(f"{repo_name}: SHA {sha[:12]} not reachable from main")
    return len(failures) == 0, failures


def _fix_stale_checkboxes(slot_path: Path, issues_to_tick: list[int]) -> int:
    """Tick unchecked boxes for completed issues. Returns count fixed."""
    content = slot_path.read_text()
    fixed = 0
    lines = content.splitlines()
    result = []
    for line in lines:
        for n in issues_to_tick:
            if f"- [ ] #{n} " in line or line.rstrip().endswith(f"- [ ] #{n}"):
                line = line.replace("- [ ]", "- [x]", 1)
                fixed += 1
                break
        result.append(line)
    if fixed:
        slot_path.write_text("\n".join(result))
    return fixed
