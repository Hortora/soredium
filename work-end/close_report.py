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
    "promote",
    "rebase",
    "squash",
    "land",
    "close-issues",
    "verify",
    "archive",
    "scaffold-cleanup",
]

STEP_LABELS = {
    "promote": "Artifacts promoted",
    "rebase": "Rebased",
    "squash": "Squashed",
    "land": "Landed",
    "close-issues": "Issues closed",
    "verify": "Verified",
    "archive": "Slot archived",
    "scaffold-cleanup": "Scaffold cleaned",
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

    if step == "promote":
        files = d.get("promoted_files", "")
        targets = d.get("target_repos", "")
        return f": {files} files → {targets}" if files else ": no artifacts"

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

    if step == "land":
        sha = d.get("landed_sha", "")
        repos = d.get("pushed_repos", "")
        return f" {repos} (SHA {sha[:7]})" if sha else ""

    if step == "close-issues":
        closed = d.get("closed", "0")
        return f" ({closed})"

    if step == "verify":
        verified = d.get("verified", "unknown")
        return f" ({verified})"

    if step == "archive":
        slot = d.get("slot", "")
        dest = d.get("dest", "")
        return f" slot {slot} → {dest}" if slot else ""

    if step == "scaffold-cleanup":
        return ""

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
