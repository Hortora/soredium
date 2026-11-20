---
id: PP-20261120-48d0d5
title: "A read never writes: reading the queue, detecting state and resolving context change no file"
type: rule
scope: repo
applies_to: "project/queue_io.py read_queue, project/work_state.py, project/ctx.py, project/topology.py, any show/status/detect/list command"
severity: critical
refs:
  - tests/test_queue_io.py
  - tests/test_ctx_reads_only.py
violation_hint: "A function named read, detect, resolve, show, status or list that renames, moves, deletes or rewrites a file, or calls a migrate function"
created: 2026-11-20
---

Code that only looks must leave every file byte-for-byte as it found it. Layout migrations (an older `.plan` to `.queue`, files out of `design/`, `.meta` into `.plan`) run only from code that is about to write, or from an explicit command, and each one prints what it did (`MIGRATED_PLAN=`). A legacy layout seen during a read is reported (`LEGACY_LAYOUT=`), not converted. Three migrations once hid in the read path and converted a slot that was only being inspected. Pin any new read with a test that snapshots every file under the directory before and after and compares the bytes.
