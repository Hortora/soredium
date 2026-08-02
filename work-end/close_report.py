#!/usr/bin/env python3
"""
close_report.py — Mechanical close-out report for work-end and slot merge.

Collects step results into a JSON file and renders a structured summary.
Replaces LLM-assembled reports with deterministic output.

Subcommands:
  init <report-path>                          Create empty report file
  record <report-path> step=<name> [k=v ...]  Record a step result
  render <report-path>                        Output formatted report
"""

import json
import sys
from pathlib import Path


STEP_ORDER = [
    "rebase",
    "squash",
    "merge",
    "push-fork",
    "push-blessed",
    "artifacts",
    "journal-merge",
    "specs-posted",
    "stamp-project",
    "stamp-workspace",
    "scaffold-cleanup",
    "hygiene",
    "slot-archive",
    "archive",
]

STEP_LABELS = {
    "rebase": "Rebased",
    "squash": "Squashed",
    "merge": "Merged",
    "push-fork": "Pushed",
    "push-blessed": "Pushed to blessed",
    "artifacts": "Artifacts promoted",
    "journal-merge": "Journal merged",
    "specs-posted": "Specs posted",
    "stamp-project": "Stamped project branch",
    "stamp-workspace": "Stamped workspace branch",
    "scaffold-cleanup": "Scaffold cleaned",
    "hygiene": "Hygiene scan",
    "slot-archive": "Slot clones archived",
    "archive": "Slot archived",
}


def init(report_path: Path) -> None:
    report_path.write_text(json.dumps({"steps": {}}, indent=2))
    print("INIT=yes")


def record(report_path: Path, step: str, data: dict) -> None:
    report = json.loads(report_path.read_text())
    report["steps"][step] = data
    report_path.write_text(json.dumps(report, indent=2))
    print(f"RECORDED={step}")


def render(report_path: Path) -> None:
    report = json.loads(report_path.read_text())
    steps = report.get("steps", {})

    if not steps:
        print("(no steps recorded)")
        return

    lines = []
    for step_name in STEP_ORDER:
        if step_name not in steps:
            continue
        data = steps[step_name]
        result = data.get("result", "ok")
        icon = "✅" if result == "ok" else "❌"
        label = STEP_LABELS.get(step_name, step_name)
        detail = _format_detail(step_name, data)
        lines.append(f"{icon} {label}{detail}")

    for step_name in steps:
        if step_name not in STEP_ORDER:
            data = steps[step_name]
            result = data.get("result", "ok")
            icon = "✅" if result == "ok" else "❌"
            lines.append(f"{icon} {step_name} — {_kv_summary(data)}")

    for line in lines:
        print(line)


def _format_detail(step: str, data: dict) -> str:
    d = {k: v for k, v in data.items() if k != "result"}

    if step == "rebase":
        branch = d.get("branch", "")
        base = d.get("base", "")
        conflicts = d.get("conflicts", "no")
        suffix = " (resolved conflicts)" if conflicts == "yes" else ""
        return f" {branch} onto {base}{suffix}" if branch else ""

    if step == "squash":
        before = d.get("before", "?")
        after = d.get("after", "?")
        strategy = d.get("strategy", "")
        strat = f", strategy {strategy}" if strategy else ""
        return f" {before} → {after} commits{strat}"

    if step == "merge":
        method = d.get("method", "fast-forward")
        files = d.get("files", "")
        insertions = d.get("insertions", "")
        stats = f" ({files} files, {insertions} insertions)" if files else ""
        return f" to main via {method}{stats}"

    if step in ("push-fork", "push-blessed"):
        remote = d.get("remote", "")
        branch = d.get("branch", "")
        return f" to {remote}" + (f" ({branch})" if branch else "")

    if step == "artifacts":
        parts = []
        wp = d.get("workspace_promoted", "0")
        pp = d.get("project_promoted", "0")
        ic = d.get("issues_closed", "0")
        bp = d.get("blog_published", "0")
        pa = d.get("plans_archived", "0")
        if int(wp) + int(pp) > 0:
            parts.append(f"{wp} to workspace, {pp} to project")
        if int(ic) > 0:
            parts.append(f"{ic} issues closed")
        if int(bp) > 0:
            dest = d.get("blog_dest", "")
            parts.append(f"{bp} blog entries → {dest}" if dest else f"{bp} blog entries")
        if int(pa) > 0:
            parts.append(f"{pa} plans archived")
        return f": {'; '.join(parts)}" if parts else ""

    if step == "journal-merge":
        sections = d.get("sections", "0")
        target = d.get("target", "ARC42STORIES.MD")
        return f" → {target} ({sections} sections)"

    if step == "specs-posted":
        issue = d.get("issue", "")
        return f" to #{issue}" if issue else ""

    if step in ("stamp-project", "stamp-workspace"):
        sha = d.get("landed_sha", "")
        branch = d.get("branch", "")
        return f" ({branch})" + (f" — landed as {sha[:8]}" if sha else "")

    if step == "scaffold-cleanup":
        return ""

    if step == "hygiene":
        findings = d.get("findings", "0")
        return f" ({findings} findings)" if findings != "0" else " (clean)"

    if step == "slot-archive":
        count = d.get("count", "0")
        names = d.get("names", "")
        return f" {count} clones ({names})" if names else f" {count} clones"

    if step == "archive":
        slot = d.get("slot", "")
        dest = d.get("dest", "")
        return f" slot {slot} → {dest}" if slot else ""

    return ""


def _kv_summary(data: dict) -> str:
    parts = []
    for k, v in data.items():
        if k == "result":
            continue
        parts.append(f"{k}={v}")
    return ", ".join(parts) if parts else "done"


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    report_path = Path(sys.argv[2])

    if command == "init":
        init(report_path)
    elif command == "record":
        pairs = {}
        step = None
        for arg in sys.argv[3:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                if k == "step":
                    step = v
                else:
                    pairs[k] = v
        if not step:
            print("ERROR=missing_step", file=sys.stderr)
            sys.exit(1)
        if not report_path.exists():
            init(report_path)
        record(report_path, step, pairs)
    elif command == "render":
        if not report_path.exists():
            print("ERROR=no_report", file=sys.stderr)
            sys.exit(1)
        render(report_path)
    else:
        print(f"ERROR=unknown_command command={command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
