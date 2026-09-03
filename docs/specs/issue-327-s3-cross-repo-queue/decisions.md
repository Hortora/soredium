# Decisions — #327 S3_ACTIVE_ALL_CLOSED cross-repo queue fix

## D1: Unification scope

**Choice:** Extract `plan_reader.py` as a shared module in `project/` — unify queue parsing, plan field reading, and covers parsing across all consumers
**Alternatives:**
- Minimal fix (B) — fix only the two #327 bugs + shared queue parser. Leaves 19 covers copies and 13 field-reader copies in place.
- Full plan_manager consolidation (C) — move ALL plan parsing into plan_manager.py. Too large a scope, risks destabilising the most-used module.
**Rationale:** 4/5 commits to corruption.py are false-positive fixes caused by duplicated parsing logic. Mechanical replacement across ~15 files, each already has tests. Fixes the class of bug, not just the instance.
**Trade-offs:** Larger diff than a minimal fix (~15 files touched vs 2-3). Each change is mechanical but the review surface is wider.
**Sources:** project/corruption.py (13 field-reader copies), work-slot/plan_manager.py:103-105 (canonical _ITEM_RE), 19 covers.split(",") call sites across the codebase
**Exploration:** quick
**Status:** captured

## D2: Module location

**Choice:** `project/plan_reader.py` — new read-only module in `project/` with its own simplified `QueueItem` (ref, title, completed, active) and its own copy of the canonical `_ITEM_RE` regex
**Alternatives:**
- Extract shared types to `project/plan_types.py`, import from both plan_manager and plan_reader. Single source of truth for regex, but introduces new import dependency from `work-slot/` to `project/`.
**Rationale:** `project/` is already on every consumer's import path. plan_manager's full `QueueItem` has 8 fields for write/edit operations — readers only need 4. No circular dependency risk. Regex is stable (changed once in history).
**Trade-offs:** Regex is copied, not shared. If the regex changes in plan_manager, plan_reader must be updated manually. Mitigated by the regex being stable and tests covering both.
**Sources:** work-slot/plan_manager.py:103-105, project/corruption.py, project/lifecycle.py, project/work_health.py
**Exploration:** quick
**Status:** captured

## D2b: Module name

**Choice:** `plan_io.py` — covers create, read, update, delete (full CRUD lifecycle)
**Alternatives:**
- `plan_reader.py` — read-only. But user identified writes and deletes also need unifying, so read-only scope is insufficient.
**Rationale:** The `.plan` lifecycle is create/read/update/delete. All four operations share the section parser. One module, one parser, four operations.
**Trade-offs:** None significant — natural extension of D2.
**Sources:** project/lifecycle.py `_write_lifecycle_state()` and `_write_branch()`, work-start/scaffold.py inline plan building
**Exploration:** quick
**Status:** captured

## D3: Traceability design

**Choice:** Structured parse result with unparsed-line tracking, and enriched corruption findings that include parsed context
**Alternatives:**
- Silent parsing (current) — silently drops unmatched lines, findings don't show what was parsed. Makes false positives invisible until they fire in production.
**Rationale:** The recurring false-positive pattern exists because parsers silently drop what they can't match. Surfacing unparsed lines as a signal (not an error) and including parsed queue state in findings makes the system self-diagnosing.
**Trade-offs:** Slightly more verbose finding detail strings. Worth it — the reader immediately sees why a finding is or isn't corruption.
**Sources:** project/corruption.py:263-268 (current S3 finding detail lacks queue context)
**Exploration:** quick
**Status:** captured
