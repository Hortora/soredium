---
id: PP-20260521-f84059
title: "validate_schema.py validates federation config only — GE frontmatter validation belongs in validate_pr.py"
type: rule
scope: repo
applies_to: "soredium scripts; issues and PRs touching GE schema or validation"
severity: guidance
violation_hint: "An issue or PR that adds GE frontmatter field validation (required fields, optional field formats, allowed values) to validate_schema.py instead of validate_pr.py"
created: 2026-05-21
---

`validate_schema.py` validates SCHEMA.md — the garden federation config (roles, upstream chains, GE-ID prefix format). It has no knowledge of GE frontmatter fields. All GE entry validation (required fields, optional field format checks, allowed values) belongs in `validate_pr.py`. Issues referencing `validate_schema.py` for GE schema changes should be re-scoped to `validate_pr.py` before implementation begins.
