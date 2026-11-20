---
id: PP-20261120-565ac8
title: "The script that performs a lifecycle action records it in the worklog, and recording never fails the action"
type: rule
scope: repo
applies_to: "Any script that starts, steps, wraps, ends, lands, stamps, closes, publishes, promotes, pauses, resumes or archives"
severity: important
refs:
  - project/worktrace.py
  - tests/test_worktrace.py
violation_hint: "A new land/publish/promote/close/archive path with no worktrace.record call; a record call whose failure can raise into the caller; a detail passed by a name that is also a parameter of record"
created: 2026-11-20
---

Every lifecycle action is recorded through `project/worktrace.py` by the code that performs it, at the moment it happens, with issue references in full `owner/repo#N` form. A failed or refused action is recorded too (`publish-failed`, `work-<command>-stopped` with its reason). Recording is never allowed to change the outcome: `record` swallows every error into one `WARN=worklog_not_recorded` line, and its fixed parameters are positional-only so a detail name cannot collide with them. A trace that records only what began is worse than none, because it looks complete.
