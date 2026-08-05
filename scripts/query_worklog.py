#!/usr/bin/env python3
"""Query worklog DB for recent activity — audit support tool."""
import sqlite3

conn = sqlite3.connect("/Users/mdproctor/.hortora/worklog.db")
conn.row_factory = sqlite3.Row

print("=== Recent slots (last 20) ===")
for r in conn.execute("SELECT slot_number, state, created_at, archived_at FROM slots ORDER BY slot_number DESC LIMIT 20").fetchall():
    sn = r["slot_number"]
    st = r["state"]
    ca = r["created_at"] or "?"
    aa = r["archived_at"] or "-"
    print(f"  Slot {sn:>3} | {st:>10} | created: {ca:>20} | archived: {aa}")

print()
print("=== Recent work_items (last 20) ===")
for r in conn.execute("""
    SELECT wi.id, wi.branch, wi.state, wi.slot_id, wi.work_path, wi.created_at, wi.ended_at,
           re.path as repo_path, re.github_repo
    FROM work_items wi
    LEFT JOIN repos re ON wi.repo_id = re.id
    ORDER BY wi.id DESC LIMIT 20
""").fetchall():
    issues = conn.execute("SELECT issue_number, issue_repo, is_primary FROM work_item_issues WHERE work_item_id=?", (r["id"],)).fetchall()
    issue_str = ", ".join(f'{i["issue_repo"]}#{i["issue_number"]}{"*" if i["is_primary"] else ""}' for i in issues)
    sid = r["slot_id"] or "-"
    rn = r["github_repo"] or (r["repo_path"] or "-").split("/")[-1]
    br = r["branch"] or "-"
    st = r["state"] or "?"
    ca = (r["created_at"] or "?")[:10]
    ea = (r["ended_at"] or "-")[:10] if r["ended_at"] else "-"
    print(f"  WI {r['id']:>3} | {st:>8} | slot:{sid!s:>3} | {rn:>12} | {br}")
    print(f"         created: {ca} | ended: {ea}")
    if issue_str:
        print(f"         issues: {issue_str}")

print()
print("=== Recent events (last 40) ===")
for r in conn.execute("SELECT timestamp, event_type, work_item_id, slot_id, repo_path, metadata FROM events ORDER BY id DESC LIMIT 40").fetchall():
    ts = r["timestamp"] or "?"
    et = r["event_type"] or "?"
    wi = r["work_item_id"] or "-"
    sl = r["slot_id"] or "-"
    rp = r["repo_path"] or "-"
    print(f"  {ts:>20} | {et:>20} | WI:{wi!s:>3} | slot:{sl!s:>3} | {rp}")
