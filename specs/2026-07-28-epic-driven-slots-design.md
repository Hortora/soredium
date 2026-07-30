# Epic-Driven Slots — Design Spec

**Date:** 2026-07-28
**Epic:** TBD (will be created during implementation)
**Status:** Approved design, awaiting implementation plan

## Overview

Enhance `work-slot` to accept an epic and drive through its child issues
in a single slot, with intelligent batch planning that groups related
issues together and orders them by dependencies. The slot stays alive
across sessions, tracking progress through the batch plan. GitHub is the
source of truth for progress (closed/open children on the epic issue).

## Motivation

Today work-slot creates one slot per issue. Epics with 10+ child issues
require manual orchestration — the user must decide which issue to work
next, create slots individually, and track progress mentally. This
creates friction and loses context across sessions.

The batch planning also solves a second problem: issues that should land
together (related domain changes, coupled API surfaces) get grouped into
branches that merge as a unit, while unrelated issues are separated.

## Architecture

### Separation of Concerns

Epic sequencing (batch planning, issue advancement, progress tracking)
is a distinct concern from slot infrastructure (worktree creation, `.m2`
isolation, symlink management). The implementation separates these:

- **`epic_manager.py`** — owns batch plan parsing, epic body update
  logic, progress queries, and issue advancement. Exposes subcommands:
  - `plan <slot-dir>` — parse SLOT.md, return batch plan as JSON
  - `advance <slot-dir>` — atomically advance to next issue: update
    SLOT.md checkboxes/markers, append completed issue to `COVERS` in
    `.meta`, optionally check GitHub epic checkbox. Returns new state.
  - `status <slot-dir>` — return progress summary and divergence data
  Mechanical operations live in the script; the skill handles judgment
  (user confirmation, batch announcements, safe-exit prompts).
- **`slot_manager.py`** — owns slot lifecycle (create, merge, archive).
  Extended to call `epic_manager.py` when creating epic slots.
- **SLOT.md** — stores both slot metadata (repos, branch) and epic state
  (batch plan, progress) in a backward-compatible format.

This separation enables future single-repo epic support (Hortora/soredium#TBD)
where `epic_manager.py` stores state in `.meta` extensions rather than
SLOT.md, without requiring the slot infrastructure.

### Scope

This spec targets **multi-repo family projects** where `work-slot` is the
established workflow. Single-repo projects without a family root are
out of scope for this iteration — tracked as Hortora/soredium#TBD.

## Design

### Epic Slot Creation

New command: `work-slot epic <owner/repo>#<N>` (or `work-slot epic #N`
when repo is inferrable from context).

**Steps:**

0. **Guard: check for existing epic slot.** Scan active slots via
   `list_slots()` and check each SLOT.md for `Type: epic` with the
   same epic issue number. If found, refuse:
   > "Slot N already tracks epic #M (branch: `<branch>`).
   > Run `work-slot merge` to land it first, or `work-slot status`
   > to see its progress."
   This prevents divergent work from two slots tracking the same epic.

1. Fetch the epic issue body and all child issues from GitHub (parse
   Scope checklist `- [ ] #N` entries and/or cross-references)
2. For each child issue, read labels (scale, complexity). If labels are
   missing, estimate from title + body using the Scale and Complexity
   Triage table, propose labels, apply on user approval.
3. Analyze children for batch grouping:
   - Same domain/subsystem → group together
   - Shared API surface (changes that should land together) → group
   - Scale fit (combine small issues, keep large ones solo or paired)
   - Dependency mentions ("depends on #N") → later batch
4. Propose a batch plan table:

   ```
   ┌────────┬──────────────┬─────────┬──────────────────────────────┐
   │ Batch  │    Issues    │  Scale  │         Why together         │
   ├────────┼──────────────┼─────────┼──────────────────────────────┤
   │ 1      │ #108, #109   │ S+S     │ Vocabulary — no API change   │
   │ 2      │ #111, #112   │ M+M     │ Weighted profiles — the API  │
   │ 3      │ #116         │ M       │ Depends on #111              │
   └────────┴──────────────┴─────────┴──────────────────────────────┘
   ```

5. User approves or adjusts the batch plan.
6. Write the approved batch plan to the epic's Scope section on GitHub.

   **Safeguards:**
   - Locate the `## Scope` section by heading match (case-insensitive,
     `##` or `###`). If not found, warn and skip the body update — the
     batch plan is still stored in SLOT.md.
   - Show a diff preview of the proposed body change before writing.
   - Preserve all content outside the Scope section unchanged.
   - The user explicitly confirms the body update after reviewing the
     preview. If declined, only SLOT.md records the plan.

7. Create a single slot with branch named using the existing
   `issue-NNN-<slug>` convention (e.g. `issue-50-weighted-profiles`).
   The branch is derived from the epic's issue number, following the
   same naming rules as `work-start` Step 5.
8. Write SLOT.md with full batch plan and state tracking (see SLOT.md
   Structure below).
9. Record in worklog: `record_slot_create()` with epic metadata.

   The batch plan is committed to the slot workspace for durability.
   This is a one-shot LLM decision — re-running the command on the
   same inputs may produce a different grouping. The approved and
   committed plan is authoritative.

### Batch Plan on GitHub Epic

The epic's Scope section gets rewritten with batch groupings:

```markdown
## Scope

### Batch 1 — Vocabulary and docs (S+S+S+S)
- [ ] #108 — Rename disposition to temperament
- [ ] #109 — Update terminology docs
- [ ] #110 — Align error messages
- [ ] #114 — Add glossary entry

### Batch 2 — Weighted profiles API (M+M)
- [ ] #111 — Add weight parameter
- [ ] #112 — Dominant-auxiliary scoring

### Batch 3 — Signal store extension (S)
- [ ] #115 — Qualifier SPI widening
```

Issues get checked off (`- [x]`) as `work-slot next` advances. This is
progress signaling on GitHub, not issue closure — issues remain open
until `work-end` closes them via `COVERS`.

### SLOT.md Structure

Epic SLOT.md extends the standard format with additional sections while
maintaining backward compatibility with `parse_slot_md()`:

```markdown
# Slot 38 — issue-50-weighted-profiles

## Issue
owner/repo#50
Covers: 108,109,110,114
Type: epic
Safe exit: after any completed batch

## What to do
Epic #50 — Weighted Profiles. Working through batched child issues.
Current: Batch 2 — Weighted profiles API (M+M)

## Batch Plan

### Batch 1 — Vocabulary and docs (S+S+S+S)
- [x] #108 — Rename disposition to temperament
- [x] #109 — Update terminology docs
- [x] #110 — Align error messages
- [x] #114 — Add glossary entry

### Batch 2 — Weighted profiles API (M+M) ← current
- [ ] #111 — Add weight parameter ← active
- [ ] #112 — Dominant-auxiliary scoring

### Batch 3 — Signal store extension (S)
- [ ] #115 — Qualifier SPI widening

### Batch 4 — DispositionHealth SPI (M)
- [ ] #116 — Health SPI (depends on #111, #115)

### Batch 5 — Eval judges (M+M)
- [ ] #113 — Primary judge
- [ ] #117 — Fallback judge

## Session State
Current batch: 2
Current issue: #111 — Add weight parameter
Last wrap: 2026-07-28, session covered batch 1 in full

## Repos
- engine (primary)

## Created
2026-07-28, branch: issue-50-weighted-profiles
```

**Backward compatibility with `parse_slot_md()`:**

The `## Issue`, `## What to do`, and `## Repos` sections are preserved
with their existing headings. `parse_slot_md()` correctly extracts:
- `issue_repo` and `issue` from `## Issue` (the epic number)
- `covers` from the `Covers:` line (completed issues so far)
- `context` from `## What to do`
- `repos` from `## Repos`

**The issue line MUST use `owner/repo#N` format without a title suffix.**
The parser at `slot_manager.py` line 301 splits on `#` and expects
exactly two parts. A line like `owner/repo#50 — Epic Title` would
produce `issue = "50 — Epic Title"`, breaking `gh issue view` and
`scan_ready()` downstream. The epic title is available from the
`## What to do` section and via GitHub API — it does not need to be
on the issue line.

The `## Batch Plan` and `## Session State` sections are new —
`parse_slot_md()` skips them via the `if line.startswith("## "):`
guard (lines 299-300 in `slot_manager.py`), which resets all section
flags for unknown headings.

The `Type: epic` and `Safe exit:` lines within `## Issue` are correctly
skipped by the parser (no `#` character, not starting with `Covers:`).
`parse_slot_md()` is extended to detect the `Type: epic` line and
return an `is_epic` flag. Functions that iterate slots (`list_slots()`,
`scan_ready()`) gain an optional `epic_only` filter.

The `← current` and `← active` markers are what the LLM reads on
session resume. Checkboxes mirror the epic on GitHub. Session State
gets updated on every wrap.

### In-Slot Workflow

**Starting work:**

`work-start` detects the existing scaffold (state 2, resume path).
Detection of epic context happens AFTER the standard detection flow:

1. State 2 fires: `.meta` exists, branches aligned → resume path
2. Resume path runs Steps 0, 2, 3, 3b, 11
3. **Epic overlay:** After standard resume, check for SLOT.md in the
   slot directory (one level up from the repo worktree:
   `$PROJECT/../SLOT.md`). If SLOT.md exists and contains `Type: epic`
   in the `## Issue` section:
   a. Read `## Session State` for current batch/issue
   b. Read `## Batch Plan` for batch structure
   c. Display epic progress:
      ```
      Epic #50 — Batch 2 of 5. Issues: #111, #112.
      Start with #111 — Add weight parameter.
      ```
   d. Set active issue for commit linkage (`Refs #111`)

This detection works because slot creation pre-creates the scaffold
(`.meta` and `JOURNAL.md`) via `scaffold.py`. The resume path fires
naturally; the epic overlay reads SLOT.md for additional context.

work-start does NOT modify SLOT.md. It only reads the epic context to
provide a richer resume experience.

**Advancing through issues:**

User says "next" → invokes `work-slot next`.

`work-slot next` calls `epic_manager.py advance`:

```bash
python3 ~/.claude/skills/work-slot/epic_manager.py advance <slot-dir>
```

The script atomically:
1. Checks off the issue in SLOT.md (checkbox + advance `← active` marker)
2. Appends the completed issue to `COVERS` in `.meta`
3. Checks the GitHub epic checkbox (`- [x] #N` — progress signaling,
   not issue closure). Non-fatal on failure.
4. Returns JSON: `{"completed": N, "next_issue": N, "batch_complete": bool, "epic_complete": bool, "safe_exit": bool}`

The skill then handles judgment:
- If `batch_complete`: announce batch complete, note safe exit point
- If `epic_complete`: run `epic_manager.py status <slot-dir>` to check
  for divergence. If no divergence (all epic children accounted for in
  the batch plan), add the epic issue number itself to `COVERS` in
  `.meta` so that `work-end` closes it alongside the children. If
  divergence is detected (children added after batching that are still
  open), warn and leave the epic open — the user addresses the
  remaining children first. Then announce epic complete and prompt for
  work-end.
- Otherwise: print what's next for immediate LLM context

**Epic issue closure:** The epic issue (#N) is added to `COVERS` only
when `epic_complete` is true AND no divergence is detected. This
ensures:
- Safe exit mid-epic never closes the epic prematurely (it's not in
  COVERS until the last issue in the last batch completes)
- Re-entry across multiple slots is safe (each slot's COVERS contains
  only its own completed children; only the final slot adds the epic)
- If children were added to the epic after batching, the epic stays
  open until the user handles them

**Issue closure is deferred to `work-end`.** Issues are NOT closed on
GitHub during `work-slot next`. The `COVERS` field in `.meta`
accumulates all completed issues across all batches. When `work-end`
runs, it reads `COVERS` and closes all listed issues — matching the
platform's principle that issues close at branch close time, after
code is verified and merged to main.

**`COVERS` accumulation:** `COVERS` in `.meta` starts empty at epic
slot creation (the epic issue number is stored in `issue:`, not in
`covers:`). Each call to `work-slot next` (via `epic_manager.py advance`)
appends exactly one issue — the just-completed issue — to `COVERS`.
Entire batches are NEVER pre-loaded into `COVERS`.

Example progression:
- Slot created: `covers:` (empty)
- After #108 done: `covers: 108`
- After #109 done: `covers: 108,109`
- After all Batch 1: `covers: 108,109,110,114`
- After #111 done (Batch 2): `covers: 108,109,110,114,111`
- Safe exit + work-end: closes #108, #109, #110, #114, #111

This keeps `COVERS` as a faithful record of completed work. At any
point, `work-end` can safely close every issue in `COVERS` — they have
all been worked on. The `Covers:` line in SLOT.md mirrors `.meta` for
`parse_slot_md()` compatibility.

**Error recovery for `work-slot next`:**

Each operation in `work-slot next` is idempotent:
- GitHub checkbox update: checking an already-checked box is a no-op
- SLOT.md update: re-running produces the same state
- `.meta` COVERS update: duplicate issue numbers are deduplicated

If any step fails (network error, permission issue), the LLM reports
the failure and the user can retry `work-slot next` safely.

**Session wraps:**

Normal handover flow, enhanced with epic context:
- SLOT.md Session State section updated with current position
- Handover skill auto-includes epic progress summary (see Integration
  with handover below)
- New session reads SLOT.md for full context:

  ```
  Epic #50 — Weighted Profiles (Batch 2 of 5)
    Done:    #108 ✓  #109 ✓  #110 ✓  #114 ✓  (Batch 1 complete)
    Current: #111 — Add weight parameter (in progress)
    Next:    #112 — Dominant-auxiliary scoring

    Last session: implemented WeightedProfile record and repository layer.
    Handover notes: tests passing, need to wire into evaluation pipeline.
  ```

### Safe Exit

After any completed batch (no partial issues), the user can exit:

1. Run `work-end` — executes Phase A (review, verify, squash, push
   branch). Phase A is the same as existing slot mode.
2. Run `work-slot merge` from the main repo — executes Phase B
   (rebase, push main, stamp branches, archive slot). **Phase B must
   complete before re-entry.** Code that stays on a pushed branch
   without merging to main is unreachable from the next slot's branch
   point.
3. To continue the epic later: `work-slot epic #N` again — fetches
   the epic from GitHub, sees which children are closed, re-batches
   remaining open issues into a new slot.

   **Branch naming for re-entry:** The new slot gets a new branch
   using the `issue-NNN-<slug>` convention with a batch suffix:
   `issue-50-weighted-profiles-b3` (where `b3` indicates starting
   from batch 3). The slot number is always freshly allocated by
   `allocate_slot_number()`.

### work-slot status

Shows epic progress for the current or specified slot.

**Usage:** `work-slot status` (in a slot) or
`work-slot status <family-root> slot=<N>` (from main repo).

**Output:**

```
Epic #50 — Weighted Profiles
Branch: issue-50-weighted-profiles (Slot 38)

  Batch 1 — Vocabulary and docs (S+S+S+S) ✅
    #108 ✓  #109 ✓  #110 ✓  #114 ✓

  Batch 2 — Weighted profiles API (M+M) ← current
    #111 — Add weight parameter ← active
    #112 — Dominant-auxiliary scoring

  Batch 3 — Signal store extension (S)
    #115 — Qualifier SPI widening

  Progress: 4/10 issues (40%), 1/5 batches complete
  Safe exit: yes (Batch 1 complete)
```

**Data sources:**
- SLOT.md for batch plan and local progress markers
- GitHub epic body for current checkbox state (cross-check)
- `.meta` for COVERS

**Divergence detection:** If SLOT.md and GitHub disagree (an issue
closed on GitHub that SLOT.md shows as open, or a new issue added to
the epic after batching), report the divergence:

```
⚠️ Divergence detected:
  - #118 added to epic on GitHub — not in batch plan
  - #109 closed on GitHub but not checked in SLOT.md
  Action: re-run `work-slot epic #N` after this slot completes to
  pick up changes.
```

### Integration with work-start

Epic slot detection extends the existing work-start resume path
(state 2). It does not add a new detection state — it overlays
additional context after the standard resume completes.

1. State 2 fires: `.meta` exists, branches aligned → resume path
2. Resume path runs Steps 0, 2, 3, 3b, 11
3. After standard resume steps, check for slot context:
   - Guard: `$PROJECT` path must contain `/worktrees/` (same check
     as work-end Slot Mode Detection). Skip if not in a slot.
   - Path: `$PROJECT/../SLOT.md` (one directory up from repo worktree)
   - If exists and contains `Type: epic` in the `## Issue` section:
     a. Read `## Session State` for current batch/issue
     b. Read `## Batch Plan` for batch structure
     c. Display epic progress summary (batch N of M, active issue)
     d. Set active issue for commit linkage (`Refs #NNN`)
   - If SLOT.md does not exist or is not an epic: no change to
     existing behaviour.

### Integration with handover

Handover detects epic slot context via the same SLOT.md path:

1. Resolve `$PROJECT` via ctx.py (already done in handover's Path
   Resolution)
2. Guard: `$PROJECT` path must contain `/worktrees/`. Skip if not
   in a slot.
3. Check `$PROJECT/../SLOT.md` exists
4. If exists and contains `Type: epic`:
   - Read current batch, active issue, and progress from SLOT.md
   - Include an "Epic Progress" section in HANDOFF.md:
     ```
     ## Epic Progress
     Epic #50 — Batch 2 of 5
     Done: #108, #109, #110, #114 (Batch 1)
     Active: #111 — Add weight parameter
     Next: #112 → then Batch 3 (#115)
     ```
   - Placement: after "## Last Session", before "## What's Left"
5. When not in an epic slot (no SLOT.md or no `Type: epic`), this
   section is omitted entirely.

### Worklog Integration

Epic slot operations record lifecycle events via the worklog, matching
the pattern established by existing slot operations in `slot_manager.py`
(which already calls `record_slot_create()`, `record_slot_merge()`,
`record_slot_archive()`):

| Operation | Worklog call | Extra metadata |
|-----------|-------------|----------------|
| Create epic slot | `record_slot_create()` | `epic_number`, `batch_count`, `total_issues` |
| `work-slot next` | `record_event()` | `type: epic_advance`, `from_issue`, `to_issue` |
| Safe exit (Phase A) | `record_slot_phase_a()` | `completed_batches`, `remaining_batches` |
| Merge (Phase B) | `record_slot_merge()` | (unchanged) |
| Archive | `record_slot_archive()` | (unchanged) |

The worklog provides observability for epic progress across sessions.
Without it, the only way to audit epic state is to read SLOT.md or
check GitHub — the eidos#100 incident proved this is insufficient.

## Command Surface

### New Commands

| Command | What it does |
|---------|-------------|
| `work-slot epic <owner/repo>#<N>` | Create an epic slot with batch planning |
| `work-slot next` | Check off current issue, advance to next |
| `work-slot status` | Show epic progress with divergence detection |

### Modified Commands/Skills

| Existing | Change |
|----------|--------|
| `work-slot create` | Unchanged — single-issue slots still work |
| `work-start` | Detect epic slot via SLOT.md `Type: epic`, show batch context on resume |
| `work-end` | After Phase A, offer stamp/close/archive if in a slot. Closes all issues in COVERS at branch close. |
| `handover` | In epic slot, auto-include epic progress summary via SLOT.md detection |

## What This Does NOT Do

- Does not create multiple slots (one slot per epic, not per issue)
- Does not auto-implement issues (human drives the work, LLM assists)
- Does not change single-issue slot workflow (backward compatible)
- Does not auto-merge between batches (safe exit is user-initiated)
- Does not close issues during batch advancement (deferred to work-end)
- Does not support single-repo non-family projects (future — Hortora/soredium#TBD)

## Dependencies

- GitHub CLI (`gh`) for issue fetching and epic body updates
- Existing `slot_manager.py` infrastructure for slot creation/lifecycle
- Existing `handover` skill for session wraps
- `worklog.py` for lifecycle event recording

## Future

### Single-Repo Epic Support

The `epic_manager.py` module is designed to be storage-agnostic — it
operates on a batch plan data structure, not on SLOT.md directly. A
future `work-epic` command can reuse the same batch planning and
advancement logic, storing state in `.meta` extensions or a dedicated
file in the workspace `design/` directory. Tracked as
Hortora/soredium#TBD.

### Epic Evolution

When issues are added to or removed from an epic on GitHub after
batching, `work-slot status` detects the divergence and reports it.
Full reconciliation (re-batching mid-slot) is future work — the
current design treats the approved batch plan as immutable within a
slot. New issues are picked up when re-running `work-slot epic #N`
for remaining batches after safe exit.
