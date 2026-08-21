#!/usr/bin/env python3
"""Migrate .plan files to repo-qualified issue references.

For plans with issue-repo in ## State: parse + rewrite auto-upgrades.
For plans without: infer repo from .slot file or directory structure,
inject issue-repo into State, then parse + rewrite.

Usage:
    python3 scripts/migrate_plan_repos.py [--dry-run] [--path PATH]

Without --path, migrates all .plan files under known casehub/hortora trees.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))

REPO_MAP = {
    "engine": "casehubio/engine",
    "pages": "casehubio/casehub-pages",
    "parent": "casehubio/parent",
    "blocks": "casehubio/blocks",
    "blocks-ui": "casehubio/blocks-ui",
    "connectors": "casehubio/connectors",
    "examples": "casehubio/examples",
    "life": "casehubio/life",
    "clinical": "casehubio/clinical",
    "chat-app": "casehubio/chat-app",
    "platform": "casehubio/platform",
    "qhorus": "casehubio/qhorus",
    "work": "casehubio/work",
    "ledger": "casehubio/ledger",
    "quarkmind": "casehubio/quarkmind",
    "aml": "casehubio/aml",
    "soc": "casehubio/soc",
    "neocortex": "casehubio/neocortex",
    "scaffold": "casehubio/scaffold",
    "eidos": "casehubio/eidos",
    "openclaw": "casehubio/openclaw",
    "devtown": "casehubio/devtown",
    "drafthouse": "casehubio/drafthouse",
    "fsitrading": "casehubio/fsitrading",
    "desiredstate": "casehubio/casehub-desiredstate",
    "ras": "casehubio/casehub-ras",
    "ops": "casehubio/casehub-ops",
    "trellis": "Hortora/trellis",
    "soredium": "Hortora/soredium",
    "cc-praxis": "Hortora/soredium",
}


def infer_repo_from_slot(plan_path: Path) -> str:
    """Try to find the repo from the .slot file in parent directories."""
    for parent in [plan_path.parent, plan_path.parent.parent,
                   plan_path.parent.parent.parent]:
        slot_file = parent / ".slot"
        if slot_file.exists():
            text = slot_file.read_text()
            m = re.search(r'casehubio/(\S+)#', text)
            if m:
                repo_name = m.group(1)
                return f"casehubio/{repo_name}"
            m = re.search(r'Hortora/(\S+)#', text)
            if m:
                return f"Hortora/{m.group(1)}"
    return ""


def infer_repo_from_path(plan_path: Path) -> str:
    """Infer repo from directory structure."""
    parts = plan_path.parts
    for i, part in enumerate(parts):
        if part.startswith("work-casehub"):
            if i + 1 < len(parts):
                next_part = parts[i + 1]
                if next_part in REPO_MAP:
                    return REPO_MAP[next_part]
        if part.startswith("work-") and not part.startswith("work-casehub"):
            suffix = part[len("work-"):]
            if suffix in REPO_MAP:
                return REPO_MAP[suffix]
        if part.startswith("wsp-casehub-"):
            suffix = part[len("wsp-casehub-"):]
            if suffix in REPO_MAP:
                return REPO_MAP[suffix]
        if part.startswith("wsp-"):
            suffix = part[len("wsp-"):]
            if suffix in REPO_MAP:
                return REPO_MAP[suffix]
        if part == "work" and i + 1 < len(parts):
            next_part = parts[i + 1]
            if next_part in REPO_MAP:
                return REPO_MAP[next_part]
    for key in REPO_MAP:
        if f"/{key}/" in str(plan_path) or str(plan_path).endswith(f"/{key}/.plan"):
            return REPO_MAP[key]
    return ""


def infer_repo_from_claude_md(plan_path: Path) -> str:
    """Try CLAUDE.md GitHub repo field."""
    for parent in [plan_path.parent, plan_path.parent.parent,
                   plan_path.parent.parent.parent]:
        claude_md = parent / "CLAUDE.md"
        if claude_md.exists():
            text = claude_md.read_text().replace("**", "")
            m = re.search(r"GitHub repo:\s*(\S+)", text)
            if m:
                return m.group(1)
    return ""


def has_issue_repo(plan_path: Path) -> bool:
    return "issue-repo:" in plan_path.read_text()


def has_bare_numbers(plan_path: Path) -> bool:
    """Check if any queue items use bare #N (no repo prefix)."""
    in_queue = False
    for line in plan_path.read_text().splitlines():
        if line.strip() == "## Queue":
            in_queue = True
            continue
        if line.startswith("## "):
            in_queue = False
            continue
        if in_queue and re.match(r'\s*- \[[ x]\] #\d+', line):
            if not re.match(r'\s*- \[[ x]\] [A-Za-z0-9._-]+/[A-Za-z0-9._-]+#\d+', line):
                return True
    return False


def inject_issue_repo(plan_path: Path, repo: str) -> bool:
    """Add issue-repo to ## State section. Returns True if modified."""
    content = plan_path.read_text()
    if "issue-repo:" in content:
        return False

    lines = content.splitlines()
    new_lines = []
    injected = False

    for i, line in enumerate(lines):
        new_lines.append(line)
        if line.strip() == "## State" and not injected:
            # Find end of State section, inject before next ## or end
            pass
        if not injected and line.startswith("state:"):
            new_lines.append(f"issue-repo: {repo}")
            injected = True

    if not injected:
        # No state: field found, try after ## State line
        new_lines = []
        for line in lines:
            new_lines.append(line)
            if line.strip() == "## State" and not injected:
                new_lines.append(f"issue-repo: {repo}")
                injected = True

    if not injected:
        # No ## State section — add one before ## Queue
        new_lines = []
        for line in lines:
            if line.strip() == "## Queue" and not injected:
                new_lines.extend(["## State", f"issue-repo: {repo}", ""])
                injected = True
            new_lines.append(line)

    if injected:
        plan_path.write_text("\n".join(new_lines))
    return injected


def migrate_plan(plan_path: Path, dry_run: bool = False) -> str:
    """Migrate a single plan. Returns status string."""
    if not plan_path.exists():
        return "SKIP: not found"

    content = plan_path.read_text()
    if "## Queue" not in content:
        return "SKIP: no queue"
    if not re.search(r'- \[[ x]\] ', content):
        return "SKIP: empty queue"

    if not has_bare_numbers(plan_path):
        return "OK: already prefixed"

    repo = ""
    if has_issue_repo(plan_path):
        repo = "FROM_STATE"
    else:
        repo = infer_repo_from_slot(plan_path)
        if not repo:
            repo = infer_repo_from_path(plan_path)
        if not repo:
            repo = infer_repo_from_claude_md(plan_path)
        if not repo:
            return "FAIL: cannot determine repo"

        if dry_run:
            return f"WOULD: inject issue-repo={repo}, then rewrite"

        inject_issue_repo(plan_path, repo)

    # Parse and rewrite — backfill handles the rest
    try:
        from plan_manager import parse_plan, rewrite_plan
        tree = parse_plan(plan_path)
        if dry_run:
            return f"WOULD: rewrite with repo={repo}"
        rewrite_plan(plan_path, tree)
        return f"MIGRATED: repo={repo}"
    except ValueError as e:
        return f"FAIL: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def find_plans() -> list[Path]:
    roots = [
        Path.home() / "claude/casehub/slots",
        Path.home() / "claude/public/casehub",
        Path.home() / "claude/casehub/work",
        Path.home() / "claude/public/casehub-desiredstate",
        Path.home() / "claude/public/quarkmind",
        Path.home() / "claude/public/casehub-ops",
        Path.home() / "claude/public/casehub-ras",
        Path.home() / "claude/public/hortora",
        Path.home() / "claude/hortora/slots",
    ]
    plans = []
    for root in roots:
        if root.exists():
            for p in root.rglob(".plan"):
                if ".git" not in str(p):
                    plans.append(p)
    return sorted(plans)


def main():
    dry_run = "--dry-run" in sys.argv
    specific = None
    for i, arg in enumerate(sys.argv):
        if arg == "--path" and i + 1 < len(sys.argv):
            specific = Path(sys.argv[i + 1])

    if specific:
        plans = [specific]
    else:
        plans = find_plans()

    stats = {"OK": 0, "SKIP": 0, "MIGRATED": 0, "WOULD": 0, "FAIL": 0, "ERROR": 0}
    failures = []

    for plan in plans:
        result = migrate_plan(plan, dry_run=dry_run)
        status = result.split(":")[0]
        stats[status] = stats.get(status, 0) + 1
        if status in ("FAIL", "ERROR"):
            failures.append((plan, result))
        if not result.startswith("OK") and not result.startswith("SKIP"):
            print(f"  {result}  {plan}")

    print(f"\nTotal: {len(plans)} plans")
    for k, v in sorted(stats.items()):
        if v > 0:
            print(f"  {k}: {v}")

    if failures:
        print(f"\nFailures ({len(failures)}):")
        for path, msg in failures:
            print(f"  {path}: {msg}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
