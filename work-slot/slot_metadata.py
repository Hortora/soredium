"""slot_metadata.py — promotion stamps, landed marker verification, checkbox fixes.

Parsing and writing moved to project/slot_io.py (Phase 2, #425).
"""

import sys
from pathlib import Path

from slot_core import run_cmd

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
from landed_check import content_on_base


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
        canonical = family_root / repo_name
        if not canonical.is_dir():
            clone_in_slot = slot_dir / repo_name
            if clone_in_slot.is_dir():
                rc, url, _ = run_cmd([
                    "git", "-C", str(clone_in_slot), "remote", "get-url", "local",
                ])
                if rc == 0 and url.strip():
                    resolved = Path(url.strip())
                    if resolved.is_dir():
                        canonical = resolved
            if not canonical.is_dir():
                failures.append(f"{repo_name}: canonical repo not found at {canonical}")
                continue
        result = content_on_base(canonical, sha, "main")
        if not result.landed:
            failures.append(f"{repo_name}: {result.describe()}")
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
