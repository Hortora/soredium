"""
enrichment.py — Issue enrichment and GitHub cache for what-next recommendations.

Extends the worklog DB (v2) with strategic classification, trajectory notes,
and cached GitHub issue state. Used by work-end (capture) and work-start (query).
"""

import argparse
import datetime
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import worklog

VALID_STRATEGIC_ROLES = {"quick-win", "load-bearing", "parallelizable", "dependency-unlocker", "consolidation"}
VALID_READINESS = {"ready", "needs-design", "needs-spike", "needs-decision"}
VALID_DECAY = {"stable", "compounding", "perishable"}
VALID_BLAST_RADIUS = {"isolated", "local", "cross-cutting", "foundational"}

_ENUM_FIELDS = {
    "strategic_role": VALID_STRATEGIC_ROLES,
    "readiness": VALID_READINESS,
    "decay": VALID_DECAY,
    "blast_radius": VALID_BLAST_RADIUS,
}

_ENRICHMENT_COLUMNS = [
    "strategic_role", "readiness", "decay", "blast_radius", "cohesion",
]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _validate_enums(**fields) -> None:
    for field_name, valid_set in _ENUM_FIELDS.items():
        value = fields.get(field_name)
        if value is not None and value not in valid_set:
            raise ValueError(
                f"{field_name} must be one of {sorted(valid_set)}, got {value!r}"
            )


# --- Enrichment CRUD ---

def upsert_enrichment(conn: sqlite3.Connection, issue_number: int,
                      issue_repo: str, **fields) -> None:
    _validate_enums(**fields)
    existing = conn.execute(
        "SELECT * FROM issue_enrichment WHERE issue_number=? AND issue_repo=?",
        (issue_number, issue_repo),
    ).fetchone()
    merged = {}
    if existing:
        for col in _ENRICHMENT_COLUMNS:
            merged[col] = existing[col]
    for col in _ENRICHMENT_COLUMNS:
        if col in fields and fields[col] is not None:
            merged[col] = fields[col]
    conn.execute(
        "INSERT OR REPLACE INTO issue_enrichment "
        "(issue_number, issue_repo, strategic_role, readiness, decay, "
        "blast_radius, cohesion, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (issue_number, issue_repo,
         merged.get("strategic_role"), merged.get("readiness"),
         merged.get("decay"), merged.get("blast_radius"),
         merged.get("cohesion"), _now()),
    )
    conn.commit()


def get_enrichment(conn: sqlite3.Connection, issue_number: int,
                   issue_repo: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM issue_enrichment WHERE issue_number=? AND issue_repo=?",
        (issue_number, issue_repo),
    ).fetchone()
    return dict(row) if row else None


def list_enrichments(conn: sqlite3.Connection,
                     issue_repo: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM issue_enrichment WHERE issue_repo=? ORDER BY issue_number",
        (issue_repo,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- Trajectory Notes ---

def append_trajectory(conn: sqlite3.Connection, issue_number: int,
                      issue_repo: str, note: str,
                      source_branch: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO trajectory_notes "
        "(issue_number, issue_repo, note, source_branch, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (issue_number, issue_repo, note, source_branch, _now()),
    )
    conn.commit()
    return cur.lastrowid


def get_trajectory(conn: sqlite3.Connection, issue_number: int,
                   issue_repo: str, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM trajectory_notes "
        "WHERE issue_number=? AND issue_repo=? "
        "ORDER BY id DESC LIMIT ?",
        (issue_number, issue_repo, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# --- Cache CRUD ---

def upsert_cached_issue(conn: sqlite3.Connection, issue_number: int,
                        issue_repo: str, title: str, state: str,
                        labels: list[str], body: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO github_issue_cache "
        "(issue_number, issue_repo, title, state, labels, body, cached_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (issue_number, issue_repo, title, state,
         json.dumps(labels), body, _now()),
    )
    conn.commit()


def get_cached_issue(conn: sqlite3.Connection, issue_number: int,
                     issue_repo: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM github_issue_cache WHERE issue_number=? AND issue_repo=?",
        (issue_number, issue_repo),
    ).fetchone()
    return dict(row) if row else None


def is_cache_fresh(conn: sqlite3.Connection, issue_repo: str,
                   ttl_seconds: int = 300) -> bool:
    row = conn.execute(
        "SELECT MIN(cached_at) as oldest FROM github_issue_cache WHERE issue_repo=?",
        (issue_repo,),
    ).fetchone()
    if row is None or row["oldest"] is None:
        return False
    oldest = datetime.datetime.fromisoformat(row["oldest"])
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=ttl_seconds)
    return oldest >= cutoff


# --- Cache Refresh ---

def refresh_cache(conn: sqlite3.Connection, issue_repo: str,
                  ttl_seconds: int = 300) -> int:
    if is_cache_fresh(conn, issue_repo, ttl_seconds):
        return 0
    try:
        result = subprocess.run(
            ["gh", "issue", "list", "--state", "open",
             "--json", "number,title,state,labels,body",
             "--limit", "500", "--repo", issue_repo],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"WARN=cache_refresh_failed repo={issue_repo} stderr={result.stderr.strip()}", file=sys.stderr)
            return 0
        issues = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"WARN=cache_refresh_error repo={issue_repo} detail={e}", file=sys.stderr)
        return 0
    if not issues:
        print(f"WARN=cache_refresh_empty repo={issue_repo}", file=sys.stderr)
        return 0
    fetched_numbers = {i["number"] for i in issues}
    with conn:
        for issue in issues:
            label_names = [l["name"] for l in issue.get("labels", [])]
            conn.execute(
                "INSERT OR REPLACE INTO github_issue_cache "
                "(issue_number, issue_repo, title, state, labels, body, cached_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (issue["number"], issue_repo, issue["title"],
                 issue["state"], json.dumps(label_names),
                 issue.get("body", ""), _now()),
            )
        conn.execute(
            "DELETE FROM github_issue_cache "
            "WHERE issue_repo=? AND issue_number NOT IN ({})".format(
                ",".join("?" * len(fetched_numbers))
            ),
            (issue_repo, *sorted(fetched_numbers)),
        )
    return len(issues)


# --- Query Layer ---

VALID_MODES = {"general", "quick-wins", "critical-path", "parallelizable", "compounding", "cohesion"}

_SCALE_ORDER = {"XS": 5, "S": 4, "M": 3, "L": 2, "XL": 1}
_DECAY_WEIGHT = {"compounding": 3, "perishable": 2, "stable": 1}
_ROLE_WEIGHT = {"dependency-unlocker": 4, "load-bearing": 3, "quick-win": 2, "consolidation": 1, "parallelizable": 1}
_READINESS_WEIGHT = {"ready": 3, "needs-spike": 2, "needs-design": 1, "needs-decision": 0}


def _parse_scale(labels_json: str | None) -> int:
    if not labels_json:
        return 0
    try:
        labels = json.loads(labels_json)
    except (json.JSONDecodeError, TypeError):
        return 0
    for label in labels:
        if ":" in label:
            prefix, value = label.split(":", 1)
            if prefix.lower() == "scale":
                return _SCALE_ORDER.get(value.upper(), 0)
    return 0


def _score_general(enrichment_row: dict | None, labels_json: str | None) -> int:
    if enrichment_row is None:
        return 0
    score = 0
    score += _ROLE_WEIGHT.get(enrichment_row.get("strategic_role", ""), 0)
    score += _READINESS_WEIGHT.get(enrichment_row.get("readiness", ""), 0)
    score += _DECAY_WEIGHT.get(enrichment_row.get("decay", ""), 0)
    score += _parse_scale(labels_json)
    return score


def what_next(conn: sqlite3.Connection, issue_repo: str,
              mode: str = "general", cohesion_tag: str | None = None,
              limit: int = 5) -> list[dict]:
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}")

    rows = conn.execute(
        "SELECT c.issue_number, c.issue_repo, c.title, c.labels, "
        "e.strategic_role, e.readiness, e.decay, e.blast_radius, e.cohesion, e.updated_at "
        "FROM github_issue_cache c "
        "LEFT JOIN issue_enrichment e "
        "ON c.issue_number = e.issue_number AND c.issue_repo = e.issue_repo "
        "WHERE c.issue_repo=? AND c.state='OPEN'",
        (issue_repo,),
    ).fetchall()

    results = []
    for row in rows:
        row = dict(row)
        enriched = row.get("strategic_role") is not None
        enr = row if enriched else None

        if mode == "quick-wins" and enriched and row.get("strategic_role") != "quick-win":
            continue
        if mode == "quick-wins" and enriched and row.get("readiness") != "ready":
            continue
        if mode == "critical-path" and enriched and row.get("strategic_role") != "load-bearing":
            continue
        if mode == "parallelizable" and enriched:
            if row.get("blast_radius") != "isolated" or row.get("readiness") != "ready":
                continue
        if mode == "compounding" and enriched and row.get("decay") != "compounding":
            continue
        if mode == "cohesion" and enriched and row.get("cohesion") != cohesion_tag:
            continue

        score = _score_general(enr, row.get("labels")) if enriched else 0

        traj = conn.execute(
            "SELECT note, created_at FROM trajectory_notes "
            "WHERE issue_number=? AND issue_repo=? ORDER BY id DESC LIMIT 1",
            (row["issue_number"], row["issue_repo"]),
        ).fetchone()

        results.append({
            "issue_number": row["issue_number"],
            "issue_repo": row["issue_repo"],
            "title": row["title"],
            "score": score,
            "enriched": enriched,
            "strategic_role": row.get("strategic_role"),
            "readiness": row.get("readiness"),
            "decay": row.get("decay"),
            "blast_radius": row.get("blast_radius"),
            "cohesion": row.get("cohesion"),
            "recent_trajectory": dict(traj) if traj else None,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="Issue enrichment and GitHub cache")
    sub = parser.add_subparsers(dest="command", required=True)

    p_upsert = sub.add_parser("upsert")
    p_upsert.add_argument("--issue", type=int, required=True)
    p_upsert.add_argument("--repo", required=True)
    p_upsert.add_argument("--role")
    p_upsert.add_argument("--readiness")
    p_upsert.add_argument("--decay")
    p_upsert.add_argument("--blast-radius")
    p_upsert.add_argument("--cohesion")

    p_traj = sub.add_parser("trajectory")
    p_traj.add_argument("--issue", type=int, required=True)
    p_traj.add_argument("--repo", required=True)
    p_traj.add_argument("--text", required=True)
    p_traj.add_argument("--branch")

    p_get = sub.add_parser("get")
    p_get.add_argument("--issue", type=int, required=True)
    p_get.add_argument("--repo", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--repo", required=True)

    p_refresh = sub.add_parser("refresh")
    p_refresh.add_argument("--repo", required=True)
    p_refresh.add_argument("--ttl", type=int, default=300)

    p_next = sub.add_parser("what-next")
    p_next.add_argument("--repo", required=True)
    p_next.add_argument("--mode", default="general")
    p_next.add_argument("--cohesion-tag")
    p_next.add_argument("--limit", type=int, default=5)

    args = parser.parse_args()
    db_path = os.environ.get("WORKLOG_DB")
    conn = worklog.connect(db_path)

    try:
        if args.command == "upsert":
            fields = {}
            if args.role:
                fields["strategic_role"] = args.role
            if args.readiness:
                fields["readiness"] = args.readiness
            if args.decay:
                fields["decay"] = args.decay
            if args.blast_radius:
                fields["blast_radius"] = args.blast_radius
            if args.cohesion:
                fields["cohesion"] = args.cohesion
            upsert_enrichment(conn, args.issue, args.repo, **fields)
            print(json.dumps({"ok": True}))

        elif args.command == "trajectory":
            rid = append_trajectory(conn, args.issue, args.repo, args.text,
                                    source_branch=args.branch)
            print(json.dumps({"ok": True, "id": rid}))

        elif args.command == "get":
            result = get_enrichment(conn, args.issue, args.repo)
            if result is None:
                print(json.dumps(None))
            else:
                print(json.dumps(result))

        elif args.command == "list":
            result = list_enrichments(conn, args.repo)
            print(json.dumps(result))

        elif args.command == "refresh":
            count = refresh_cache(conn, args.repo, ttl_seconds=args.ttl)
            print(json.dumps({"ok": True, "count": count}))

        elif args.command == "what-next":
            result = what_next(conn, args.repo, mode=args.mode,
                               cohesion_tag=args.cohesion_tag, limit=args.limit)
            print(json.dumps(result))

    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
