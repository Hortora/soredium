#!/usr/bin/env python3
"""
Validate artifact locations in a project or workspace repo.

Project repos: blog, adr, specs must be under docs/ (docs/blog/, docs/adr/, docs/specs/).
               docs/superpowers/ must not exist.
Workspace repos: blog, adr, specs, plans must be at root (blog/, adr/, specs/, plans/).
                 docs/superpowers/ must not exist.

Also checks CLAUDE.md for stale routing (blog → workspace in project repos)
and obsolete Blog directory fields.

Usage:
    python3 validate_artifact_locations.py <repo_path> --mode project|workspace [--fix]

Exit codes:
    0  clean
    1  issues found (CRITICAL)
    2  issues found (WARNING only)
"""

import argparse
import re
import sys
from pathlib import Path


class Issue:
    def __init__(self, severity: str, path: str, message: str, fix: str = ""):
        self.severity = severity
        self.path = path
        self.message = message
        self.fix = fix

    def __str__(self) -> str:
        result = f"[{self.severity}] {self.path}: {self.message}"
        if self.fix:
            result += f"\n  Fix: {self.fix}"
        return result


def find_md_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [f for f in directory.rglob("*.md") if f.name != "INDEX.md"]


def check_project(repo: Path) -> list[Issue]:
    issues: list[Issue] = []

    for artifact in ("blog", "adr", "specs"):
        root_dir = repo / artifact
        if root_dir.is_dir():
            files = find_md_files(root_dir)
            if files:
                docs_dir = repo / "docs" / artifact
                docs_files = {f.name for f in find_md_files(docs_dir)} if docs_dir.is_dir() else set()
                duplicates = [f for f in files if f.name in docs_files]
                unique = [f for f in files if f.name not in docs_files]

                if duplicates:
                    issues.append(Issue(
                        "CRITICAL", str(root_dir),
                        f"{len(duplicates)} duplicate files exist at root AND docs/{artifact}/",
                        f"git rm {artifact}/<files> (docs/ copies are canonical)",
                    ))
                if unique:
                    issues.append(Issue(
                        "CRITICAL", str(root_dir),
                        f"{len(unique)} files at root {artifact}/ not in docs/{artifact}/",
                        f"git mv {artifact}/<files> docs/{artifact}/",
                    ))

    sp_dir = repo / "docs" / "superpowers"
    if sp_dir.is_dir():
        sp_files = list(sp_dir.rglob("*"))
        content_files = [f for f in sp_files if f.is_file()]
        if content_files:
            issues.append(Issue(
                "CRITICAL", str(sp_dir),
                f"docs/superpowers/ exists with {len(content_files)} files",
                "Move specs to docs/specs/, plans to docs/plans/, delete superpowers/",
            ))
        else:
            issues.append(Issue(
                "WARNING", str(sp_dir),
                "Empty docs/superpowers/ directory exists",
                "rmdir docs/superpowers/",
            ))

    claude_md = repo / "CLAUDE.md"
    if claude_md.exists():
        text = claude_md.read_text()

        if re.search(r'\|\s*blog\s*\|\s*workspace\s*\|', text):
            issues.append(Issue(
                "CRITICAL", str(claude_md),
                "Routing table has blog → workspace (should be project)",
                "Change to: | blog | project | lands in docs/blog/ — promoted at work end |",
            ))

        if re.search(r'\*\*Blog directory:\*\*', text):
            issues.append(Issue(
                "WARNING", str(claude_md),
                "Obsolete **Blog directory:** field present",
                "Remove the line — blog routing is handled by the routing table",
            ))

        if "superpowers/specs/" in text or "superpowers/plans/" in text:
            issues.append(Issue(
                "WARNING", str(claude_md),
                "References to superpowers/ paths in CLAUDE.md",
                "Update to docs/specs/ and docs/plans/",
            ))

    return issues


def check_workspace(repo: Path) -> list[Issue]:
    issues: list[Issue] = []

    for artifact in ("blog", "adr", "specs", "plans"):
        docs_dir = repo / "docs" / artifact
        if docs_dir.is_dir():
            files = find_md_files(docs_dir)
            if files:
                issues.append(Issue(
                    "CRITICAL", str(docs_dir),
                    f"{len(files)} files at docs/{artifact}/ (should be at root {artifact}/)",
                    f"Move to {artifact}/",
                ))

    sp_dir = repo / "docs" / "superpowers"
    if sp_dir.is_dir():
        content_files = [f for f in sp_dir.rglob("*") if f.is_file()]
        if content_files:
            issues.append(Issue(
                "CRITICAL", str(sp_dir),
                f"docs/superpowers/ exists with {len(content_files)} files",
                "Move specs to specs/, plans to plans/, delete superpowers/",
            ))
        else:
            issues.append(Issue(
                "WARNING", str(sp_dir),
                "Empty docs/superpowers/ directory exists",
                "rmdir docs/superpowers/",
            ))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_path", type=Path)
    parser.add_argument("--mode", choices=["project", "workspace"], required=True)
    args = parser.parse_args()

    repo = args.repo_path.resolve()
    if not repo.is_dir():
        print(f"ERROR: {repo} is not a directory")
        return 1

    if args.mode == "project":
        issues = check_project(repo)
    else:
        issues = check_workspace(repo)

    if not issues:
        print(f"CLEAN: {repo.name}")
        return 0

    print(f"\n{repo.name}: {len(issues)} issue(s)")
    for issue in issues:
        print(f"  {issue}")

    has_critical = any(i.severity == "CRITICAL" for i in issues)
    return 1 if has_critical else 2


if __name__ == "__main__":
    sys.exit(main())
