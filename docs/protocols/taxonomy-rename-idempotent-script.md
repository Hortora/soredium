---
id: PP-20260522-77da80
title: "Taxonomy value renames require a permanent idempotent cleanup script in scripts/"
type: rule
scope: repo
applies_to: "any change to taxonomy values used in blog/note frontmatter across multiple repos"
severity: important
refs:
  - scripts/revert_diary_subtype.py
violation_hint: "Using a throwaway /tmp/ script, or no script at all, when changing a taxonomy value that appears in frontmatter files across multiple repos and active sessions"
created: 2026-05-22
---

When a taxonomy value changes (e.g. `subtype: diary` → `subtype: log`), active Claude sessions that loaded the old skills before the change continue generating the stale value until they reload. A permanent, idempotent Python script must be written to `scripts/` — not `/tmp/` — and re-run periodically until all sessions converge. The script must: walk `~/claude/` recursively; use CRLF-normalisation and frontmatter-safe regex (not `str.split('---')`); apply only within the frontmatter block; write only if changed; support a `--dry-run` default and `--apply` flag. Convergence is confirmed when the dry-run reports zero files to change.
