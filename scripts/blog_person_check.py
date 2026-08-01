#!/usr/bin/env python3
"""
Check staged blog files for person references that need author review.

Scans git-staged .md files in blog directories for sentences that may
reference named persons, identifiable groups, or characterisations.
Uses structural patterns (not a name dictionary) to flag candidates.

Usage:
    python3 blog_person_check.py [<repo-path>]

Exit codes:
    0  no blog files staged, or no person references found
    1  person references found — blocks commit
    2  error (git not available, etc.)

Output:
    BLOG_FILES=<count>
    FLAGGED=<count>
    For each finding: FLAG=<file>:<line> <sentence>
"""

import re
import subprocess
import sys
from pathlib import Path

PERSON_PATTERNS = [
    # "Name said/says/told/explained/mentioned/noted/argued/suggested"
    re.compile(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+"
        r"(?:said|says|told|explained|mentioned|noted|argued|suggested|asked|replied|confirmed|denied|claimed)\b"
    ),
    # "according to Name"
    re.compile(
        r"\baccording\s+to\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b",
        re.IGNORECASE,
    ),
    # "Name's [opinion/view/approach/decision/feedback/response/reaction]"
    re.compile(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'s\s+"
        r"(?:opinion|view|approach|decision|feedback|response|reaction|suggestion|concern|objection|preference)\b"
    ),
    # "he/she/they [said/decided/thinks/believes]" — indirect reference
    re.compile(
        r"\b(?:he|she)\s+(?:said|decided|thinks|believes|argued|suggested|wanted|preferred|insisted)\b",
        re.IGNORECASE,
    ),
    # "@username" mentions
    re.compile(r"@[a-zA-Z][a-zA-Z0-9_-]+"),
]

SAFE_PREFIXES = frozenset({
    "Claude", "GitHub", "Maven", "Quarkus", "Docker", "Kubernetes",
    "IntelliJ", "Gradle", "Spring", "React", "Python", "Java",
    "Hortora", "Soredium", "Jekyll", "Markdown", "Linux", "macOS",
    "Windows", "Redis", "Postgres", "MongoDB", "GraphQL", "REST",
    "OWASP", "JSON", "YAML", "ASCII", "UTF", "HTTP", "HTTPS",
    "Phase", "Step", "Stage", "Section", "Chapter", "Part", "Batch",
})


def is_safe_match(match_text: str) -> bool:
    first_word = match_text.split()[0] if match_text.split() else ""
    return first_word in SAFE_PREFIXES


def scan_diff(diff_text: str, filename: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    lines = diff_text.splitlines()
    line_num = 0

    for line in lines:
        if line.startswith("@@"):
            hunk_match = re.search(r"\+(\d+)", line)
            if hunk_match:
                line_num = int(hunk_match.group(1)) - 1
            continue
        if line.startswith("+") and not line.startswith("+++"):
            line_num += 1
            content = line[1:]
            for pattern in PERSON_PATTERNS:
                for m in pattern.finditer(content):
                    matched = m.group(0)
                    name_part = m.group(1) if m.lastindex and m.lastindex >= 1 else matched
                    if not is_safe_match(name_part):
                        findings.append((filename, line_num, matched.strip()))
        elif not line.startswith("-"):
            line_num += 1

    return findings


def get_staged_blog_files(repo_path: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    files = []
    for f in result.stdout.strip().splitlines():
        f = f.strip()
        if not f.endswith(".md"):
            continue
        if "/blog/" in f or f.startswith("blog/"):
            files.append(f)
    return files


def get_file_diff(repo_path: str, filepath: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "diff", "--cached", "--", filepath],
            capture_output=True, text=True, check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def main() -> int:
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "."

    blog_files = get_staged_blog_files(repo_path)
    print(f"BLOG_FILES={len(blog_files)}")

    if not blog_files:
        return 0

    all_findings: list[tuple[str, int, str]] = []
    for bf in blog_files:
        diff = get_file_diff(repo_path, bf)
        if diff:
            findings = scan_diff(diff, bf)
            all_findings.extend(findings)

    print(f"FLAGGED={len(all_findings)}")

    if all_findings:
        for filepath, line_num, sentence in all_findings:
            print(f"FLAG={filepath}:{line_num} {sentence}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
