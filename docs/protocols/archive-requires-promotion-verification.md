---
id: PP-20260801-a1b2c3
title: Slot archival must verify artifact promotion stamp
type: constraint
scope: slot-lifecycle
applies_to: [slot_manager.py, work-end]
severity: warning
created: 2026-08-01
violation_hint: "archive_slot called without .artifacts-promoted stamp — artifacts may be stranded"
---

## Rule

`archive_slot()` must check for the `.artifacts-promoted` stamp file before
moving a slot to the attic. If the stamp is missing, emit `WARN=artifacts_not_promoted`.

This applies even with `--force` — force bypasses landed/SHA checks but not
the promotion warning.

## Why

Slots archived without verified promotion leave artifacts stranded on branch
clones in the attic. The promotion stamp is the only mechanical proof that
`close_artifacts.py` successfully promoted specs, blogs, and ADRs to their
destinations.

## Enforcement

`slot_manager.py` `archive_slot()` checks for `.artifacts-promoted` in any
subdirectory's `design/` folder and at the slot root level.
