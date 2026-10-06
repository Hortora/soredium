#!/usr/bin/env python3
"""
mislinked_issues.py — Detect commits with bare #N references that likely
link to the wrong repo.

Scans git log for bare Refs/Closes #N, compares the issue title in the
current repo vs sibling repos, and flags when a sibling is a better match.

Usage:
    python3 scripts/mislinked_issues.py <repo-path>
    python3 scripts/mislinked_issues.py <repo-path> --siblings owner/sibling1,owner/sibling2
    python3 scripts/mislinked_issues.py <repo-path> --days 90
    python3 scripts/mislinked_issues.py <repo-path> --branch main
"""

import re
import subprocess
import sys
from pathlib import Path

BARE_REF = re.compile(r'(?:Refs|Closes|Fixes|Resolves)\s+#(\d+)', re.IGNORECASE)
PREFIXED_REF = re.compile(r'(?:Refs|Closes|Fixes|Resolves)\s+[\w-]+/[\w-]+#\d+', re.IGNORECASE)

_issue_cache: dict[str, dict[str, str]] = {}


def _git(repo: str, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, timeout=30,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def _gh_issue(repo: str, number: int) -> dict[str, str] | None:
    cache_key = f"{repo}#{number}"
    if cache_key in _issue_cache:
        return _issue_cache[cache_key]
    try:
        r = subprocess.run(
            ["gh", "issue", "view", str(number), "--repo", repo,
             "--json", "title,state"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            _issue_cache[cache_key] = None
            return None
        import json
        data = json.loads(r.stdout)
        _issue_cache[cache_key] = data
        return data
    except Exception:
        _issue_cache[cache_key] = None
        return None


def _word_overlap(text_a: str, text_b: str) -> float:
    """Word-level Jaccard similarity, ignoring common stop words."""
    stop = {"the", "a", "an", "in", "on", "to", "for", "of", "and", "or",
            "is", "it", "fix", "feat", "chore", "refactor", "docs", "test"}
    words_a = {w.lower() for w in re.findall(r'\w+', text_a)} - stop
    words_b = {w.lower() for w in re.findall(r'\w+', text_b)} - stop
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def _detect_owner_repo(repo_path: str) -> str:
    url = _git(repo_path, "remote", "get-url", "origin")
    if not url:
        return ""
    m = re.search(r'[:/]([\w-]+/[\w-]+?)(?:\.git)?$', url)
    return m.group(1) if m else ""


def scan_repo(repo_path: str, siblings: list[str], days: int = 0,
              branch: str = "", repo_override: str = "") -> list[dict]:
    owner_repo = repo_override or _detect_owner_repo(repo_path)
    if not owner_repo:
        print(f"ERROR: cannot detect owner/repo from {repo_path}", file=sys.stderr)
        return []

    log_args = ["log", "--format=%H|%s|%b", "--no-merges"]
    if days:
        log_args.append(f"--since={days} days ago")
    if branch:
        log_args.append(branch)

    raw = _git(repo_path, *log_args)
    if not raw:
        return []

    findings = []
    for line in raw.split("\n"):
        if "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 2:
            continue
        sha = parts[0][:12]
        subject = parts[1]
        body = parts[2] if len(parts) > 2 else ""
        full_msg = f"{subject} {body}"

        if PREFIXED_REF.search(full_msg):
            continue

        bare_matches = BARE_REF.findall(full_msg)
        if not bare_matches:
            continue

        for num_str in bare_matches:
            num = int(num_str)
            current_issue = _gh_issue(owner_repo, num)
            current_title = current_issue["title"] if current_issue else ""
            current_overlap = _word_overlap(subject, current_title) if current_title else 0.0

            best_sibling = None
            best_overlap = 0.0
            for sib in siblings:
                sib_issue = _gh_issue(sib, num)
                if not sib_issue:
                    continue
                sib_overlap = _word_overlap(subject, sib_issue["title"])
                if sib_overlap > best_overlap:
                    best_overlap = sib_overlap
                    best_sibling = (sib, sib_issue["title"], sib_overlap)

            verdict = "ok"
            if not current_issue:
                verdict = "DANGLING"
            elif best_sibling and best_sibling[2] > current_overlap + 0.1:
                verdict = "MISLINKED"
            elif current_overlap < 0.05:
                verdict = "SUSPECT"

            if verdict != "ok":
                finding = {
                    "sha": sha,
                    "subject": subject[:80],
                    "ref": f"#{num}",
                    "verdict": verdict,
                    "current_repo": owner_repo,
                    "current_title": current_title[:60] if current_title else "(not found)",
                    "current_overlap": f"{current_overlap:.0%}",
                }
                if best_sibling:
                    finding["better_match"] = f"{best_sibling[0]}#{num}"
                    finding["better_title"] = best_sibling[1][:60]
                    finding["better_overlap"] = f"{best_sibling[2]:.0%}"
                findings.append(finding)

    return findings


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    repo_path = sys.argv[1]
    siblings: list[str] = []
    days = 0
    branch = ""

    repo_override = ""
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg.startswith("--siblings="):
            siblings = arg.split("=", 1)[1].split(",")
        elif arg.startswith("--days="):
            days = int(arg.split("=", 1)[1])
        elif arg.startswith("--branch="):
            branch = arg.split("=", 1)[1]
        elif arg.startswith("--repo="):
            repo_override = arg.split("=", 1)[1]
        elif arg == "--siblings" and i + 1 < len(sys.argv):
            i += 1
            siblings = sys.argv[i].split(",")
        elif arg == "--days" and i + 1 < len(sys.argv):
            i += 1
            days = int(sys.argv[i])
        elif arg == "--branch" and i + 1 < len(sys.argv):
            i += 1
            branch = sys.argv[i]
        elif arg == "--repo" and i + 1 < len(sys.argv):
            i += 1
            repo_override = sys.argv[i]
        i += 1

    if not siblings:
        owner_repo = repo_override or _detect_owner_repo(repo_path)
        if owner_repo:
            org = owner_repo.split("/")[0]
            print(f"No --siblings specified. Checking {owner_repo} only.", file=sys.stderr)
            print(f"Tip: --siblings {org}/platform,{org}/engine for cross-repo detection", file=sys.stderr)

    findings = scan_repo(repo_path, siblings, days=days, branch=branch,
                         repo_override=repo_override)

    if not findings:
        print("No mislinked references found.")
        sys.exit(0)

    print(f"\n{'=' * 70}")
    print(f"MISLINKED ISSUE REFERENCES ({len(findings)} found)")
    print(f"{'=' * 70}")

    for f in findings:
        icon = {"MISLINKED": "❌", "DANGLING": "⚠️", "SUSPECT": "🔍"}[f["verdict"]]
        print(f"\n{icon} [{f['verdict']}] {f['sha']} {f['subject']}")
        print(f"   Ref: {f['ref']} → {f['current_repo']}: {f['current_title']} ({f['current_overlap']})")
        if "better_match" in f:
            print(f"   Better: {f['better_match']}: {f['better_title']} ({f['better_overlap']})")

    sys.exit(1)


if __name__ == "__main__":
    main()
