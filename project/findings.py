#!/usr/bin/env python3
"""Unified findings persistence — JSONL append-only with reader contract.

Writers blind-append under advisory flock. Readers group by dedup key,
resolve status by latest timestamp, severity by highest across group.
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TypedDict

SEVERITY_ORDER = {"critical": 3, "warning": 2, "note": 1}


class Finding(TypedDict, total=False):
    category: str
    dimension: str
    severity: str
    check: str
    location: str
    detail: str
    source: str
    branch: str
    status: str
    resolution: str
    timestamp: str


def _dedup_key(f: dict) -> tuple:
    loc = f.get("location")
    if loc:
        return (f.get("check", ""), loc, f.get("branch"))
    return (f.get("check", ""), f.get("detail", ""), f.get("branch"))


def read_findings(path: Path) -> list[dict]:
    """Read findings.jsonl and return deduplicated, resolved findings.

    Reader contract:
    1. Group by dedup key (check, location, branch) — fallback to (check, detail, branch)
    2. Status from latest timestamp entry
    3. Severity from highest across all entries in group
    4. Source from the highest-severity entry
    5. Resolution updates are appended lines, not in-place edits
    """
    if not path.exists():
        return []
    groups: dict[tuple, list[dict]] = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = _dedup_key(entry)
            groups.setdefault(key, []).append(entry)

    result = []
    for entries in groups.values():
        latest = max(entries, key=lambda e: e.get("timestamp", ""))
        highest_sev = max(
            entries,
            key=lambda e: SEVERITY_ORDER.get(e.get("severity", "warning"), 2),
        )
        merged = {**latest}
        merged["severity"] = highest_sev.get("severity") or "warning"
        merged["source"] = highest_sev.get("source", latest.get("source"))
        result.append(merged)
    return result


def append_finding(path: Path, finding: dict) -> None:
    """Append a single finding to the JSONL file under advisory flock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.write(json.dumps(finding) + "\n")
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def compact_findings(
    path: Path, archive_path: Path, max_age_days: int = 30
) -> int:
    """Archive resolved/dismissed findings older than max_age_days.

    Uses flock + atomic rename to maintain JSONL's concurrent-safety.
    Returns number of archived entries.
    """
    if not path.exists():
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    with open(path) as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            lines = fh.readlines()
            keep: list[str] = []
            archive: list[str] = []
            for raw in lines:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    keep.append(raw)
                    continue
                if entry.get("status") in ("resolved", "dismissed", "filed"):
                    ts = entry.get("timestamp", "")
                    if ts and ts < cutoff:
                        archive.append(raw)
                    else:
                        keep.append(raw)
                else:
                    keep.append(raw)
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(keep) + ("\n" if keep else ""))
            os.rename(str(tmp), str(path))
            if archive:
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                with open(archive_path, "a") as af:
                    af.write("\n".join(archive) + "\n")
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return len(archive)
