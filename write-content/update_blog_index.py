#!/usr/bin/env python3
"""Append a blog entry row to INDEX.md in the same directory.

Usage:
    update_blog_index.py <blog-file> [--summary "one-line summary"]

Creates INDEX.md if absent. Idempotent — skips if filename already present.
Falls back to frontmatter title: when --summary is omitted.
"""

import argparse
import re
import sys
from pathlib import Path


def parse_frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = line.split(":", 1)
        if len(kv) == 2:
            key = kv[0].strip()
            val = kv[1].strip().strip('"').strip("'")
            fields[key] = val
    return fields


INDEX_HEADER = """\
# Blog Index

| File | Date | Title |
|------|------|-------|
"""


def update_index(blog_file: Path, summary: str | None = None) -> None:
    if not blog_file.exists():
        print(f"Error: blog file does not exist: {blog_file}", file=sys.stderr)
        sys.exit(1)

    text = blog_file.read_text()
    fm = parse_frontmatter(text)
    if not fm:
        print(f"Error: no frontmatter found in {blog_file.name}", file=sys.stderr)
        sys.exit(1)

    date = fm.get("date")
    if not date:
        print(f"Error: no date in frontmatter of {blog_file.name}", file=sys.stderr)
        sys.exit(1)

    if summary is None:
        title = fm.get("title")
        if not title:
            print(
                f"Error: no title in frontmatter and no --summary provided for {blog_file.name}",
                file=sys.stderr,
            )
            sys.exit(1)
        summary = title

    filename = blog_file.name
    index_path = blog_file.parent / "INDEX.md"

    if index_path.exists():
        content = index_path.read_text()
        if filename in content:
            return
        if not content.endswith("\n"):
            content += "\n"
    else:
        content = INDEX_HEADER

    row = f"| [{filename}]({filename}) | {date} | {summary} |\n"
    index_path.write_text(content + row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Update blog INDEX.md")
    parser.add_argument("blog_file", type=Path, help="Path to the blog entry file")
    parser.add_argument("--summary", type=str, default=None, help="One-line summary")
    args = parser.parse_args()
    update_index(args.blog_file, args.summary)


if __name__ == "__main__":
    main()
