---
id: PP-20261120-7ce4e2
title: "One queue per area of work, never synced; queue_io.queue_dir is the only place that decides where it is"
type: rule
scope: repo
applies_to: "Every script that reads, writes, commits or names a queue file: project/, work-end/, work-start/, work-slot/, handover/"
severity: critical
refs:
  - project/queue_io.py
  - project/queue_home.py
  - tests/test_queue_home.py
violation_hint: "A path built by hand as <workspace>/.queue or .plan; a push, pull, merge or reset of a queue between a clone and canonical; reading or committing the .queue a workspace clone inherited in a slot that carries .queue-root"
created: 2026-11-20
---

A queue belongs to one area of work: a numbered slot, a permanent clone, or a canonical workspace. Nothing copies, pushes, pulls, merges or resets it between areas. `queue_io.queue_dir(workspace)` is the single rule for its location and every reader and writer goes through `read_queue` / `write_queue` or asks `queue_dir`; no script builds the path itself. In an area marked `.queue-root` the `.queue` and `.plan` that workspace clones inherited from their repos are not that area's work: they are never read as a fallback, judged, committed, rewritten or removed. Existing slots are switched one at a time with `project/queue_home.py adopt`, by the person who owns the slot.
