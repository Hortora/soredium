#!/usr/bin/env python3
"""
Build a garden feedback table for session-end review.

Reads GE-IDs from the retrieval tracking DB (last N hours),
cross-references with garden entry frontmatter for staleness
and version signals, and compares against the project's current
stack versions.

Outputs a formatted table with flags. The LLM presents it and
collects the user's downgrades — no LLM judgment needed for the
mechanical parts.

Usage:
    python3 scripts/garden_feedback_table.py <project-path> [hours=4]
"""

import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


RETRIEVAL_DB = Path.home() / ".hortora" / "stats" / "retrieval-tracking.db"
GARDEN_PATH = Path(
    subprocess.run(
        ["bash", "-c", "echo ${HORTORA_GARDEN:-$HOME/.hortora/garden}"],
        capture_output=True, text=True,
    ).stdout.strip()
) if True else Path.home() / ".hortora" / "garden"

STALENESS_MONTHS = 6


def _parse_args(argv: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    positional = 0
    for arg in argv:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k] = v
        else:
            if positional == 0:
                result["project"] = arg
            positional += 1
    return result


def _get_recent_retrievals(hours: int) -> list[dict]:
    """Get unique GE-IDs retrieved in the last N hours."""
    if not RETRIEVAL_DB.exists():
        return []
    conn = sqlite3.connect(str(RETRIEVAL_DB))
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = conn.execute("""
        SELECT DISTINCT d.source_document_id, d.relevance_score, r.timestamp, r.query_text
        FROM retrieved_documents d
        JOIN retrieval_records r ON d.retrieval_id = r.retrieval_id
        WHERE r.timestamp > ?
        ORDER BY r.timestamp DESC
    """, (cutoff,)).fetchall()
    conn.close()

    seen: dict[str, dict] = {}
    for r in rows:
        doc_id = r["source_document_id"]
        if doc_id not in seen:
            ge_match = re.search(r"(GE-\d{8}-[0-9a-f]{6})", doc_id)
            if ge_match:
                seen[doc_id] = {
                    "doc_path": doc_id,
                    "ge_id": ge_match.group(1),
                    "score": r["relevance_score"],
                    "timestamp": r["timestamp"],
                    "query": r["query_text"],
                }
    return list(seen.values())


def _read_entry_frontmatter(doc_path: str) -> dict:
    """Read YAML frontmatter from a garden entry via git."""
    try:
        result = subprocess.run(
            ["git", "-C", str(GARDEN_PATH), "show", f"HEAD:{doc_path}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}

    content = result.stdout
    if not content.startswith("---"):
        return {}

    end = content.find("---", 3)
    if end < 0:
        return {}
    fm_block = content[3:end].strip()

    fm: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")

    title_match = re.search(r"^#\s+(.+)$", content[end + 3:], re.MULTILINE)
    if title_match:
        fm["_title"] = title_match.group(1).strip()

    return fm


def _parse_stack_versions(project_path: str) -> dict[str, str]:
    """Extract current stack versions from project files."""
    versions: dict[str, str] = {}
    project = Path(project_path)

    pom_candidates = [project / "pom.xml"] + sorted(project.glob("*/pom.xml"))
    for pom in pom_candidates:
        if not pom.exists():
            continue
        content = pom.read_text()
        if "quarkus" not in versions:
            quarkus = re.search(r"<quarkus.platform.version>([^<]+)</quarkus.platform.version>", content)
            if quarkus:
                versions["quarkus"] = quarkus.group(1)
        if "jdk" not in versions:
            java_match = re.search(r"<maven.compiler.release>(\d+)</maven.compiler.release>", content)
            if java_match:
                versions["jdk"] = java_match.group(1)

    pkg = project / "package.json"
    if pkg.exists():
        import json
        try:
            data = json.loads(pkg.read_text())
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for key in ("typescript", "react", "next", "vue", "angular"):
                if key in deps:
                    versions[key] = deps[key].lstrip("^~")
        except (json.JSONDecodeError, OSError):
            pass

    claude_md = project / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text()
        stack_match = re.search(r"\*\*Stack:\*\*\s*(.+)", content)
        if stack_match:
            for part in stack_match.group(1).split(","):
                part = part.strip()
                ver_match = re.match(r"(\w+)\s+([\d.]+)", part)
                if ver_match and ver_match.group(1).lower() not in versions:
                    versions[ver_match.group(1).lower()] = ver_match.group(2)

    return versions


def _check_version_match(verified_on: str, current_versions: dict[str, str]) -> str | None:
    """Compare verified_on against current versions. Returns flag text or None."""
    if not verified_on:
        return None
    for part in verified_on.split(","):
        part = part.strip()
        match = re.match(r"(\w+):\s*([\d.]+)", part)
        if not match:
            continue
        tech = match.group(1).lower()
        ver = match.group(2)
        if tech in current_versions and current_versions[tech] != ver:
            return f"verified on {tech} {ver}, project uses {current_versions[tech]}"
    return None


def _check_staleness(fm: dict) -> str | None:
    """Check if entry is stale based on last_reviewed or submitted date."""
    ref_date_str = fm.get("last_reviewed") or fm.get("submitted")
    if not ref_date_str:
        return "no submitted date"
    try:
        ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
    except ValueError:
        return None
    age_days = (datetime.now() - ref_date).days
    threshold = int(fm.get("staleness_threshold", "730"))
    if age_days > threshold:
        return f"stale: {age_days} days old (threshold {threshold})"
    if age_days > STALENESS_MONTHS * 30:
        reviewed = fm.get("last_reviewed")
        if not reviewed:
            return f"not reviewed in {age_days} days"
    return None


def build_table(project_path: str, hours: int = 4) -> dict:
    """Build the feedback table. Returns structured data for formatting."""
    retrievals = _get_recent_retrievals(hours)
    if not retrievals:
        return {"entries": [], "project_stack": {}, "hours": hours}

    current_versions = _parse_stack_versions(project_path)
    entries = []

    for r in retrievals:
        fm = _read_entry_frontmatter(r["doc_path"])
        if not fm:
            entries.append({
                "ge_id": r["ge_id"],
                "doc_path": r["doc_path"],
                "title": r["ge_id"],
                "flags": ["entry not found in garden"],
                "default_outcome": "RELEVANT",
            })
            continue

        title = fm.get("_title") or fm.get("title") or r["ge_id"]
        verified_on = fm.get("verified_on", "")
        entry_type = fm.get("type", "")
        flags = []

        version_flag = _check_version_match(verified_on, current_versions)
        if version_flag:
            flags.append(f"⚠️ {version_flag}")
        elif not verified_on and entry_type in ("gotcha", "undocumented"):
            flags.append("unverified for current stack")

        staleness_flag = _check_staleness(fm)
        if staleness_flag:
            flags.append(f"⚠️ {staleness_flag}")

        entries.append({
            "ge_id": r["ge_id"],
            "doc_path": r["doc_path"],
            "title": title,
            "type": entry_type,
            "verified_on": verified_on,
            "last_reviewed": fm.get("last_reviewed", ""),
            "submitted": fm.get("submitted", ""),
            "flags": flags,
            "default_outcome": "RELEVANT",
        })

    return {"entries": entries, "project_stack": current_versions, "hours": hours}


def format_table(data: dict) -> str:
    """Format the table for presentation."""
    entries = data["entries"]
    if not entries:
        return f"NO_ENTRIES=true\nDETAIL=No garden entries retrieved in the last {data['hours']} hours."

    lines = [f"ENTRY_COUNT={len(entries)}"]
    if data["project_stack"]:
        stack_str = ", ".join(f"{k}: {v}" for k, v in data["project_stack"].items())
        lines.append(f"PROJECT_STACK={stack_str}")

    flagged = sum(1 for e in entries if e["flags"])
    lines.append(f"FLAGGED_COUNT={flagged}")
    lines.append("")

    for i, e in enumerate(entries):
        flag_str = " | ".join(e["flags"]) if e["flags"] else ""
        prefix = "⚠️" if e["flags"] else " "
        lines.append(f"ENTRY={i + 1}")
        lines.append(f"  GE_ID={e['ge_id']}")
        lines.append(f"  TITLE={e['title']}")
        if e.get("type"):
            lines.append(f"  TYPE={e['type']}")
        lines.append(f"  DEFAULT=RELEVANT")
        if flag_str:
            lines.append(f"  FLAGS={flag_str}")

    return "\n".join(lines)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    project_path = args.get("project", ".")
    hours = int(args.get("hours", "4"))

    data = build_table(project_path, hours)
    print(format_table(data))


if __name__ == "__main__":
    main()
