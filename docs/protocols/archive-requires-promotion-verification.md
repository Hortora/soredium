---
id: PP-20260801-a1b2c3
title: "SUPERSEDED: Slot archival promotion verification"
type: constraint
scope: slot-lifecycle
applies_to: [slot_manager.py, work-end]
severity: info
created: 2026-08-01
superseded: 2026-11-27
violation_hint: "This protocol is superseded — artifacts are written directly to project repos since workspace isolation (2026-11-26)"
---

## Status

**Superseded.** Since workspace isolation (2026-11-26), artifacts (blog entries,
specs, ADRs) are written directly to the project repo's `docs/` directory via
`resolve_artifact_dir.py`. There is no promotion step and no `.artifacts-promoted`
stamp. This protocol no longer applies to new slots.

## Original Rule (for reference)

`archive_slot()` checked for the `.artifacts-promoted` stamp file before
moving a slot to the attic. If the stamp was missing, it emitted
`WARN=artifacts_not_promoted`. Old slots in the attic may still have
(or be missing) this stamp — that is expected historical state.
