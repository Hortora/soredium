# 0013 — Unified .plan file replaces .meta and .epic

Date: 2026-08-14
Status: Accepted

## Context and Problem Statement

Branch state was tracked across three files: `.meta` (identity/lifecycle), `.plan` (work queue), and `.epic` (legacy queue fallback). This caused fragmented "what's next" routing — the active issue was tracked in three places (`← active` in `.plan`, `Current: #N` in `.plan` Session State, `issue: N` in `.meta`), leading to premature work-end suggestions in slots and two sources of truth for current issue.

## Decision Drivers

* One source of truth for branch state — consumers should read one file, not three
* `.meta` and `.plan` are always created together, deleted together, live in the same directory
* `.epic` is a legacy fallback that `.plan` already fully subsumes (nested epics with `(epic)` marker)
* Migration must be transparent — existing branches upgrade on first read

## Considered Options

* **Option A** — Keep two files, drop `issue:` from `.meta`
* **Option B** — Merge `.meta` into `.plan` as a `## State` section
* **Option C** — Merge `.plan` into `.meta` as structured YAML

## Decision Outcome

Chosen option: **Option B**, because `.plan`'s markdown format is human-readable and already used by the plan parser; `.meta`'s key-value format fits naturally as a markdown section.

### Positive Consequences

* One file, one parser, zero sync issues
* `ctx.py` outputs single `ACTIVE_ISSUE` instead of `PLAN_ACTIVE_ISSUE` + `EPIC_ACTIVE_ISSUE`
* 1,339 lines of dead code removed (epic_manager.py + tests)
* Migration-on-read handles all legacy scenarios transparently

### Negative Consequences / Tradeoffs

* `lifecycle.py` reads/writes must be section-scoped (avoid matching `state:` in queue items)
* `rewrite_plan()` must use atomic writes since it now holds lifecycle state too
* All skill markdown referencing `.meta` or `PLAN_ACTIVE_ISSUE` needed updating (11 skills)

## Pros and Cons of the Options

### Option A — Keep two files, drop issue: from .meta

* ✅ Smaller change — fewer files touched
* ✅ Clear separation of concerns
* ❌ Two files still means two parsers, two paths to resolve
* ❌ Backward compatibility issue with pre-change branches still needs migration

### Option B — Merge .meta into .plan

* ✅ One file — no sync, no divergence possible
* ✅ Human-readable (markdown with key-value `## State` section)
* ✅ Migration-on-read is simpler (one target format)
* ❌ Section-scoped parsing needed to avoid false matches

### Option C — Merge .plan into .meta as YAML

* ✅ Machine-parseable
* ❌ Not human-readable (queue items as YAML lists)
* ❌ Git diffs unfriendly
* ❌ Breaks all existing `.plan` parsers

## Links

* [#238](https://github.com/Hortora/soredium/issues/238) — Unify queue tracking
* [ADR-0001](0001-documentation-completeness-must-be-universal.md) — Universal documentation completeness (same "one source of truth" principle)
