# Unified Work Lifecycle — Design Spec

**Issue:** Hortora/soredium#180
**Date:** 2026-08-04
**Status:** Draft — pending design review

## Problem Statement

The work lifecycle has grown organically into fragmented routes: `work`, `work epic`,
`work-slot create`, `work-slot epic`. Each has its own input parsing, file format, and
iteration logic. This creates three problems:

1. **Trellis cannot determine the current active issue.** worklog.db records
   start/pause/resume/end but not issue-level transitions. `.meta` keeps the primary
   issue static; the current child issue lives only in `.epic`'s `← active` marker,
   which is branch-scoped and not queryable cross-session.

2. **No unified issue queue.** Multiple issues on one branch are in `covers:` and
   closed together — there is no iteration. Epic children iterate, but only within
   one epic. There is no concept of "work through #5, then epic #50's children,
   then #32."

3. **Epic handling is a separate route.** `work epic #N` is distinct from `work #N`.
   No auto-detection. Four entry events in the lifecycle state machine (`work`,
   `work_epic`, `slot_create`, `slot_epic`) for what is conceptually one operation
   with varying input.

## Design Goal

Replace the fragmented routes with a unified model:

- One input format: 1..n issue numbers OR free text (not mixed)
- Epics auto-detected from GitHub and recursively expanded (unlimited depth)
- One file format (`.plan`) for the issue queue, identical for branch and slot work
- `work-next` iterates a flat leaf-issue list derived from the `.plan` tree
- worklog.db records every issue transition for trellis observability
- Dynamic slot repo management driven by specs, not upfront

### Secondary Goal — Reduce Command Fragmentation

The current system has too many distinct commands that Claude can confuse, skip, or
misroute. Real-world failures include:

- `work-end` inside a slot doing Phase B manually instead of routing through
  `work-slot merge`, leaving the slot without a `.landed` marker and in an
  inconsistent archival state
- `work epic #N` being a separate route from `work #N`, requiring Claude to
  know which to invoke
- `work-slot create` vs `work-slot epic` being separate subcommands

The unified model reduces the command surface:
- `work-start` replaces `work-start` + `work epic` (auto-detection)
- `work-slot` replaces `work-slot create` + `work-slot epic` (auto-detection)
- `work-end` is one command regardless of context — branch or slot, it runs
  the full close sequence. There is no Phase A / Phase B split. There is no
  separate `work-slot merge`. There is no path where Claude can "decide" to
  merge directly or skip steps.
- `work-next` is one command regardless of context — same behavior in branch
  and slot mode

## Scope Principle — Additive, Not Replacement

**This spec adds the `.plan` file, unified queue, auto-epic detection, worklog events,
and dynamic slot repos. It does NOT replace or simplify any existing work-start,
work-end, or slot infrastructure.**

The following are explicitly **unchanged and must be preserved**:

### Unchanged work-start Infrastructure

All existing work-start steps remain. The spec changes only the issue resolution
and queue-building steps (Steps 1 and 4). Everything else is preserved:

| Step | What it does | Changed? |
|------|-------------|----------|
| Step 0 | Project initialisation (`project` skill) | No |
| Step 2 | Platform coherence (5 questions against PLATFORM.md) | No |
| Step 3 | Protocol checks (docs/protocols/) | No |
| Step 3b | Garden search (gardenSearch MCP + provenance recording) | No |
| Step 3c | Load existing specs (MANDATORY — workspace + project scan) | No |
| Step 3d | Epic overlay (display current batch/issue context) | **Yes — reads `.plan` instead of `.epic`** |
| Step 4 | Issue resolution (issue-workflow Phase 2 delegation) | **Yes — see section 10** |
| Step 4b | Stacked PR base detection (project branch + GitHub deps) | No |
| Step 4c | Activate issues on project board | No |
| Step 4d | Sync main and fork before branch creation | No |
| Step 5 | Branch name derivation | No |
| Step 6 | Flyway V scan | No |
| Step 7 | Atomic branch creation (project + workspace, with rollback) | No |
| Step 8 | Design routing cascade + SHA baseline + section hashes | No |
| Step 9 | Scaffold (.meta + JOURNAL.md via scaffold.py) | **Yes — adds `.plan`** |
| Step 10 | Commit and push scaffold | **Yes — stages `.plan` alongside `.meta`** |
| Step 11 | IntelliJ MCP pre-checks (retry, hard-stop) | No |
| Step 12 | Offer brainstorming | No |
| Resume path | Detection table, Branch Switch Helper, context reload | **Yes — reads `.plan` for queue state** |

### Unchanged work-end Infrastructure

The full closing sequence is preserved. The spec adds `.plan`-aware invariant
checks but does not remove or replace any existing step:

| Step | What it does | Changed? |
|------|-------------|----------|
| Pre-condition 0 | Branch divergence check (workspace vs project alignment) | No |
| Pre-condition 0b | Epic confirmation gate (`epic_manager.py check`) | **Yes — reads `.plan`** |
| Pre-condition 1 | Pause stack interaction (cleanup closing branch from stack) | No |
| Pre-condition 2 | No-.meta graceful degradation | No |
| Step 1 | Branch reconnaissance (`branch_recon.py`) | No |
| Step 2 | Flyway V re-scan | No |
| Step 3 | Design routing cascade (three-layer resolution) | No |
| Step 3b | Pre-close sweep (forage, protocol, update-claude-md, doc-sync, ADR, diary) | No |
| Step 3b-slot | Per-repo sweep in slot mode | No |
| Step 3c | Code review — HARD GATE | No |
| Step 4 | Inventory artifacts | No |
| Step 5 | Journal validation (anchored/unanchored, section drift) | No |
| Step 6 | Spec selection + posting to GitHub issue | No |
| Step 7 | Present close plan | No |
| Step 8a | Artifact promotion (`close_artifacts.py` with routing) | No |
| Step 8a-verify | Promotion verification (`verify_promotion.py`) | No |
| Step 8d | Journal merge (three-way with SHA baseline) | No |
| Step 8h | Close report rendering | No |
| Step 8i | Hygiene scan (unpublished blogs, unstamped branches, flyway) | No |
| Step 8j | Squash analysis (strategy detection, clustering, approval UX) | No |
| Step 8k | Final build verification | No |
| Step 9 | EPIC-CLOSED.md creation | No |
| Step 10 | Return to base branches | No |
| Step 11 | ARC42 stale scan | No |
| Step 12 | HANDOFF.md writing, session rename | No |
| Slot close | Review, promote, squash, push, merge to original, stamp, archive — all in one `work-end` | **Yes — Phase A/B collapsed into single sequence** |

### Unchanged Slot Infrastructure

All slot creation, merge, and archive infrastructure is preserved:

- `git clone --shared` with independent branch namespace
- Per-slot `.m2` directory (shared across repos in the slot)
- `.mvn/maven.config` pointing to slot `.m2` + `.gitignore` entry
- `resolve_workspace_source()` — workspace detection via `wksp` symlink
- Workspace clone, `wksp`/`proj` symlink repointing, `_unignore_subdir()`
- `replicate_claude_md()` — symlink-aware CLAUDE.md replication
- `_exclude_symlinks()` — `.git/info/exclude` for `wksp`/`proj`
- `sync_main()` — upstream/fork remote detection and rebase
- Scaffold pre-creation via `scaffold.py` during `create_slot()`
- `.merge-progress` resume file for crash recovery during `work-end` merge step
- Workspace stamp commits (separate from project stamp)
- `verify_landed_shas()` — `git merge-base --is-ancestor` per repo
- `.artifacts-promoted` stamp as push gate
- `check_cross_deps()` — Maven dependency graph ordering
- Epic checkbox catch-up on merge and archive (`tick_epic_checkboxes()`,
  `_fix_stale_checkboxes()`)
- `relocate_claude_projects()` / `remove_claude_projects()` on archive/delete
- `ensure_clone_layout()` — legacy worktree-to-clone migration
- Worklog events: `slot-create` (unchanged); `slot-phase-a`, `slot-merge`,
  `slot-archive` replaced by unified `work-end` event (section 6.4)
- Duplicate epic slot guard (scan active slots, refuse if same epic tracked)

### Unchanged Pause/Resume Infrastructure

- `work-pause`: WIP commit on both repos, push stack entry, switch to base
- `work-resume`: Pick from stack, checkout, rebase onto current base, reset WIP, pop
- Stack depth warnings (>3 paused branches)
- Slot redirect (paused branch in a slot → display slot path, stop)
- Single-repo mode support (stack at `$PROJECT/.pause-stack`)
- Lifecycle transitions: `active → paused`, `paused → active`

### Unchanged Cross-Cutting Infrastructure

- Two-repo model (project + workspace with matching branches) — all path
  resolution via `proj`/`wksp` symlinks, never CWD
- Single-repo mode (`SINGLE_REPO=yes` from ctx.py) — workspace equals project
- `work` router (`work_router.py`) — state detection, route dispatch, options menu
- Handover skill — end-of-session context preservation
- Pre-push hook (`pre_push_hook.py`) — blocks pushes to main outside closing states
- Issue-workflow Phase 2 — issue search, creation, cross-cutting detection
- Artifact promotion routing — three-layer cascade (workspace/project/cross-repo),
  `workspace_artifacts.py` scanning (5 categories), docs prefix for project routing,
  plan archival to `plans/attic/`, blog publishing via `blog_dest.py`

---

## 1. Invocation Modes

Two mutually exclusive input modes for both `work-start` and `work-slot`.

### 1.1 Issue Mode

```
work-start #42 #50 #32
work-slot #42 #50 #32
```

- Each number resolved via GitHub API (`gh issue view`), cross-repo refs
  (`engine#42`) handled by existing work-start Step 4 cross-repo detection
- Epics auto-detected: if an issue has a `## Scope` section with `- [ ] #N`
  checkboxes, it is an epic. Detection is recursive — children are checked too.
- Queue built in the order given
- Branch name derived from first (primary) issue: `issue-42-<slug>`
- For `work-slot`: user specifies which repos to include (unchanged from today)
- Issue-workflow Phase 2 validates each issue (existing issues checked, labels
  applied, epic placement assessed)

### 1.2 Free Text Mode

```
work-start "improve the scoring engine"
work-slot "improve the scoring engine"
```

- Branch name derived from text: `improve-scoring-engine`
- `.plan` created with empty queue
- Issues created during the brainstorming/design phase via issue-workflow Phase 2,
  added to `.plan` as created
- `.meta` `issue:` field starts empty; set when first issue is created
- For `work-slot`: slot created with current repo only. Additional repos added later
  when specs name them (always prompted, never automatic)

### 1.3 No Mixing

Issue numbers and free text are not mixed in a single invocation. Either all arguments
are issue numbers, or the argument is a description string.

---

## 2. The `.plan` File

### 2.1 Purpose

Replaces `.epic` as the universal issue queue. Represents an ordered tree of work items
where each item is either a leaf issue or an epic (container of children). The file is
identical in format and semantics for branch work and slot work.

### 2.2 Location

| Context | Path |
|---------|------|
| Branch work | `<WORKSPACE>/design/.plan` |
| Slot work | `slots/<N>/<primary-workspace>/design/.plan` |
| Single-repo mode | `<PROJECT>/design/.plan` (WORKSPACE == PROJECT) |

### 2.3 Format

```markdown
# Work Plan — issue-42-batch-work

## Queue
- [x] #42 — Fix login validation
- [ ] #50 — Weighted profiles (epic)
  - [x] #108 — Add weight field
  - [ ] #109 — Update scoring ← active
  - [ ] #110 — Migration script
- [ ] #32 — Update API docs

## Session State
Current: #109 — Update scoring
Queue position: 2/3 (top-level), 2/3 (within epic #50)
Started: 2026-08-04
Last wrap: work-next completed #108
```

### 2.4 Nested Epics

Epics can contain epics at unlimited depth. Each nested epic is indented further.

```markdown
## Queue
- [ ] #42 — Fix login ← active
- [ ] #50 — Weighted profiles (epic)
  - [ ] #51 — Add weight field
  - [ ] #52 — Scoring subsystem (epic)
    - [ ] #60 — Score calculator
    - [ ] #61 — Score migration
  - [ ] #53 — API endpoints
- [ ] #32 — Update API docs
```

### 2.5 Batch Planning Within Epics

For epics with 5+ children, LLM-driven batch planning groups related children using
four criteria: domain affinity, shared API surface, scale fit, dependency ordering.
User approves the batch plan before it's written. Batches appear as sub-headings
within the epic's indented block:

```markdown
- [ ] #50 — Weighted profiles (epic)
  ### Batch 1 — Data model ← current
  - [ ] #108 — Add weight field ← active
  - [ ] #109 — Migration script
  ### Batch 2 — Scoring logic
  - [ ] #110 — Update scoring algorithm
  - [ ] #111 — Recalculate existing scores
```

Batch boundaries are safe exit points — `work-end` prompts when a batch completes.

For nested epics: if a nested epic has 5+ children, it gets its own batch headings
at its indentation level. Batch planning is per-epic, not global.

After batch planning, the approved batch plan is written back to the GitHub epic
`## Scope` section (with diff preview and user confirmation, same as today's
`work-slot epic` Step 5).

### 2.6 Scale and Complexity Estimation

During epic detection, each child issue's labels are read. Missing `scale:` and
`complexity:` labels are estimated and applied (same as today's `work-slot epic`
Step 3). This feeds batch planning's scale-fit criterion.

### 2.7 Free Text Mode (Empty Queue)

```markdown
# Work Plan — improve-scoring-engine

## Queue
(empty — issues created during design)

## Session State
Started: 2026-08-04
```

Issues are appended to `## Queue` as they are created during brainstorming.

### 2.8 Single Issue (Trivial Queue)

```markdown
# Work Plan — issue-42-fix-login

## Queue
- [ ] #42 — Fix login validation ← active

## Session State
Current: #42 — Fix login validation
Started: 2026-08-04
```

Every `work-start` produces a `.plan`. Single-issue branches get a trivial one.
This ensures trellis always has the same file to scan.

---

## 3. `.meta` Evolution

`.meta` remains the branch identity card — minimal, stable, readable by ctx.py.

### 3.1 Unchanged Fields

| Field | Purpose |
|-------|---------|
| `branch:` | Branch name |
| `state:` | Lifecycle state (managed by lifecycle.py) |
| `project-sha:` | Baseline SHA at branch creation |
| `date:` | Creation date |
| `issue-repo:` | GitHub org/repo for the primary issue |
| `flyway-next-v:` | Flyway version tracking |
| `design-repo:` | Where design artifacts live |
| `design-section-hashes:` | ARC42 section hash tracking |

All unchanged fields are populated by their existing work-start steps (Step 6 for
flyway, Step 8 for design routing + hashes). These steps are not modified.

### 3.2 Changed Fields

| Field | Change |
|-------|--------|
| `issue:` | Can start **empty** in free text mode. Set when the first issue is created. Once set, never changes. |
| `covers:` | Grows incrementally. Each `work-next` completion appends the finished issue (with deduplication). At `work-end`, all issues in `covers:` get closed. |

### 3.3 New Field

| Field | Purpose |
|-------|---------|
| `plan: yes` | Signals a `.plan` file exists. Lets ctx.py detect it without filesystem scanning. Absent on legacy branches. |

### 3.4 What `.meta` Does NOT Track

- The current active issue — lives in `.plan` (`← active` marker)
- The full queue — lives in `.plan`
- Epic structure — lives in `.plan`

---

## 4. Unified `work-next`

One command. Same behavior in branch and slot mode. Reads `.plan`, advances the queue.

### 4.1 Flattened Iteration

The `.plan` tree is displayed for human readability and trellis visualization, but
`work-next` operates on a **flattened pre-order traversal of leaf issues only**.

Epic parent items are containers — they are never "active." They get marked `[x]`
automatically when all their children complete.

```
# Tree in .plan:
- [ ] #42 — Fix login
- [ ] #50 — Weighted profiles (epic)
  - [ ] #108 — Add weight field
  - [ ] #52 — Scoring subsystem (epic)
    - [ ] #60 — Score calculator
    - [ ] #61 — Score migration
  - [ ] #53 — API endpoints
- [ ] #32 — Update API docs

# Flattened leaf list for work-next:
#42 → #108 → #60 → #61 → #53 → #32
```

### 4.2 Algorithm

1. Find the `← active` item in `.plan`
2. Mark it `[x]`, append its issue number to `covers:` in `.meta` (with deduplication)
3. Record `issue-complete` in worklog.db
4. Find the next leaf:
   - If the completed item has a next sibling → that's next
   - If no next sibling and parent is an epic → check if all children done;
     if so, mark parent `[x]`. Recurse up until we find a next sibling or
     exhaust the queue.
   - When landing on an epic (not a leaf) → descend to its first child
     (recursively, for nested epics)
5. Mark the new item `← active`
6. Record `issue-activate` in worklog.db
7. Update `.plan` `## Session State` (current issue, queue position)
8. Rewrite `.plan` file in-place (handle indentation-based nesting for parent
   `[x]` marking — this requires a tree parser, not the current flat line-matching)
9. Return result dict: `{completed, next_issue, batch_complete, epic_complete, safe_exit}`

**Caller responsibilities** (not part of `advance_issue` effect):
- Tick the completed issue's checkbox on the GitHub epic body (if child of an epic) —
  this is the `tick_github` effect, separate from `advance_issue`
- Fire lifecycle transition: `active → transitioning` → execute effects → `commit_transition()`
- Auto-resolve: `transitioning → active` (context refresh: garden search, load specs,
  check protocols for the new issue)

This separation (advance logic returns data, caller handles GitHub + lifecycle) matches
the current architecture where `advance()` returns a result dict and the skill fires
transitions.

### 4.3 Edge Cases

| Case | Behavior |
|------|----------|
| Queue exhausted | Report "all issues complete." Return `epic_complete=True`. `work-end` is the natural next step. |
| Batch boundary | Report "Batch N complete — safe exit point." Return `safe_exit=True, batch_complete=True`. |
| Nested epic completes | Mark nested epic `[x]`, advance to parent epic's next child. |
| Single issue queue | `work-next` reports "no next issue" — queue has one item. |
| Free text, 0-1 issues | `work-next` is not applicable until 2+ issues exist in `.plan`. |

---

## 5. Lifecycle State Machine Changes

### 5.1 Events Removed

| Event | Reason | Cleanup Required |
|-------|--------|-----------------|
| `work_epic` | Subsumed by `work`. Epic detection is automatic. | Remove from `TRANSITION_TABLE`, `INVALID_MESSAGES` (line 117: `('active', 'work_epic')`), effects list |
| `slot_epic` | Subsumed by `slot_create`. Same reason. | Remove from `TRANSITION_TABLE` |

### 5.2 Transition Table Changes

| # | Before | After |
|---|--------|-------|
| T1 | `(idle, work) → scaffolded` effects: `[create_branch, write_meta]` | effects: `[create_branch, write_meta, build_plan]` |
| T2 | `(idle, work_epic) → scaffolded` effects: `[create_branch, write_meta, write_epic]` | **Removed** |
| T3 | `(idle, slot_create) → scaffolded` effects: `[create_slot, write_meta]` | effects: `[create_slot, write_meta, build_plan]` |
| T4 | `(idle, slot_epic) → scaffolded` effects: `[create_slot, write_meta, write_slot_epic]` | **Removed** |
| T6 | `(active, work_next) → transitioning` effects: `[advance_issue, update_meta, tick_github]` | Same, but `advance_issue` reads `.plan` instead of `.epic` |
| Tcleanup | `(closing:stamped, cleanup_pass) → idle` effects: `[write_epic_closed]` | effects: `[write_plan_closed]` — removes `design/.plan` during scaffold cleanup alongside `.meta` and `JOURNAL.md` |

`build_plan` always runs, even for single issues (produces a trivial `.plan`). It is
not conditional.

### 5.3 New Effect

| Effect | Description |
|--------|-------------|
| `build_plan` | Resolve issues from GitHub (via issue-workflow Phase 2 for validation), auto-detect epics (recursive with cycle detection), estimate scale/complexity labels, batch-plan epics with 5+ children (with user approval), write `.plan` file. In free text mode, writes an empty `.plan`. |

### 5.4 No New States

The 11 existing states cover the full lifecycle. `.plan` is an artifact managed by
effects, not a state machine concern.

### 5.5 Backward Compatibility

If a branch has `.epic` but no `.plan`, the `advance_issue` effect falls back to
reading `.epic`. Existing in-progress epics finish naturally under the old format.

---

## 6. Worklog.db Additions

### 6.1 New Event Types

Two new event types in the `events` table. No schema migration needed — `event_type`
is a free text column.

| Event Type | When | Metadata |
|------------|------|----------|
| `issue-activate` | `work-start` (first issue), `work-next` (advance) | `{issue_number, issue_repo}` |
| `issue-complete` | `work-next` (completed issue) | `{issue_number, issue_repo}` |

### 6.2 New Functions

```python
@safe
def record_issue_activate(conn, branch, repo_path,
                          issue_number, issue_repo):
    wid = _find_work_item(conn, branch, repo_path)
    if wid is None:
        return
    _log_event(conn, "issue-activate", work_item_id=wid,
               repo_path=repo_path,
               metadata={"issue_number": issue_number,
                          "issue_repo": issue_repo})
    conn.commit()

@safe
def record_issue_complete(conn, branch, repo_path,
                          issue_number, issue_repo):
    wid = _find_work_item(conn, branch, repo_path)
    if wid is None:
        return
    _log_event(conn, "issue-complete", work_item_id=wid,
               repo_path=repo_path,
               metadata={"issue_number": issue_number,
                          "issue_repo": issue_repo})
    conn.commit()
```

These follow the existing `@safe` pattern — errors are logged as `WARN=worklog_error`
and swallowed. This means trellis may show stale data if worklog writes fail. This is
the same tradeoff as all existing worklog functions and is acceptable: worklog is
observability, not a gate.

### 6.3 `work_item_issues` Table Update

The `work_item_issues` table records issues at work-start time. With incremental
`covers:` growth, new issues completed via `work-next` must also be added:

```python
# Inside record_issue_complete, after _log_event:
conn.execute(
    "INSERT OR IGNORE INTO work_item_issues "
    "(work_item_id, issue_number, issue_repo, is_primary) "
    "VALUES (?, ?, ?, 0)",
    (wid, issue_number, issue_repo),
)
```

This keeps `work_item_issues` in sync with `.meta` `covers:` for trellis queries.

### 6.4 Simplified Slot Worklog Events

Collapsing Phase A/B into a single `work-end` simplifies slot tracking:

| Before (3 events) | After (1 event) | Notes |
|-------------------|-----------------|-------|
| `slot-phase-a` | — | No longer a separate step |
| `slot-merge` | — | Merged into work-end |
| `slot-archive` | `work-end` | Single event with metadata: `{landed_shas, archived_to, promoted, published}` |

The slot lifecycle in worklog.db becomes: `slot-create → work-end` (with
`issue-activate` / `issue-complete` events in between for queue iteration).

Existing events `slot-phase-a` and `slot-merge` can be kept for backward
compatibility (old slots in the db) but are no longer written by new code.

### 6.5 Trellis Query Pattern

```sql
-- "What issue is being worked right now on this branch?"
SELECT e.metadata FROM events e
JOIN work_items wi ON e.work_item_id = wi.id
WHERE wi.state = 'active'
  AND e.event_type = 'issue-activate'
ORDER BY e.id DESC LIMIT 1
```

Combined with `active_work()`, trellis gets: which branches/slots are active, which
repo, and which specific issue is currently being worked.

---

## 7. Dynamic Slot Repo Management

### 7.1 Add Repo

`work-slot add-repo <name>`:

1. Validate repo exists in family root
2. `sync_main()` on the original repo (handles upstream/fork remote detection)
3. `git clone --shared --branch main` into `slots/<N>/<name>`
4. Create the feature branch in the clone
5. Set up Maven `.m2` isolation: point `.mvn/maven.config` at the slot's shared
   `.m2` directory, add `.mvn/` to the clone's `.gitignore`
6. Resolve workspace via `resolve_workspace_source()`, wire `wksp`/`proj` symlinks,
   `_exclude_symlinks()` for `.git/info/exclude`, `replicate_claude_md()`
7. Update `.slot` file repos list
8. Report: "Added <name> to slot <N>"

### 7.2 Remove Repo

`work-slot remove-repo <name>`:

1. Guard: no uncommitted changes, no unpushed commits on feature branch
2. Guard: cannot remove the primary repo
3. `relocate_claude_projects()` for the removed clone
4. Remove clone directory from slot
5. Update `.slot` file repos list
6. Report: "Removed <name> from slot <N>"

### 7.3 Spec-Driven Flow

Repos are added when specs name them, not at issue creation time:

1. Brainstorming/design produces a spec
2. Spec names repos involved (e.g., "changes needed in engine and trellis")
3. Prompt: "This spec references engine and trellis. engine is already in the slot.
   Add trellis? (y/n)"
4. On yes → `work-slot add-repo trellis` internally

Always prompted, never automatic. Some spec references are "do later," not "do now."

### 7.4 `.slot` File

`.slot` remains as the slot identity/config file. Unchanged format, updated repos list
when repos are added or removed. `.plan` sits alongside it as the issue queue — two
files with distinct concerns.

---

## 8. `work-end` Safety Gates

The closing sequence uses lifecycle state transitions where each gate must pass before
advancing. Invariant checks at each gate block the transition if something's missing.

**These gates are in ADDITION to all existing work-end steps** (branch recon, flyway
re-scan, pre-close sweep, code review, journal validation, squash analysis, etc.).
They add `.plan`-aware checks to the existing infrastructure.

### 8.1 Pre-Close Invariants (before `active → closing:review`)

- No uncommitted changes in project or workspace repos
- No untracked files that look like work product (not IDE/session artifacts) —
  existing `validate_state()` check, preserved as-is
- Branch alignment: workspace and project on matching branches — existing
  `validate_state()` check
- `.plan` status acknowledged — uncompleted items flagged, user confirms safe-exit
  or all-done. Uses `safe_exit` flag from `.plan` advance logic (batch boundary
  = safe exit, mid-batch = requires `confirm-partial`)
- All files saved in IDE (if IntelliJ MCP available)

### 8.2 Post-Review Invariants (before `closing:verified → closing:promoted`)

- Artifact scan: all promotable files identified (specs, plans, ADRs in 5 categories
  via `workspace_artifacts.py`)
- Blog scan: diary entries or blog posts detected and flagged for publishing
- Nothing silently skipped — each promotable item explicitly accepted or declined

### 8.3 Post-Promote Invariants (before `closing:promoted → closing:pushed`)

- Promotion verification via `verify_promotion.py`: workspace-routed artifacts
  checked via `git cat-file -e main:<artifact>`, project-routed via filesystem
  existence (with `docs/` prefix for specs/ADRs)
- `.artifacts-promoted` stamp exists (existing push gate)
- Blog publication confirmed (or explicitly declined)
- No orphaned design artifacts left in workspace branch

### 8.4 Slot-Specific Invariants (during slot `work-end`)

`work-end` in a slot runs the full close sequence — there is no Phase A/B split
and no separate `work-slot merge` command. The slot-specific invariants are
checked at the appropriate points within the single sequence:

- All repos in `.slot` have clean working trees (before review)
- `check_cross_deps()` Maven ordering respected during merge (before push)
- All repos have their feature branch pushed to the clone's origin (before merge)
- Fast-forward merge to original repo succeeds for each project repo (during merge)
- `verify_content_landed` passes for every repo (`git merge-base --is-ancestor`)
  after merge
- No repo clone has unpushed commits that would be lost on archive (before archive)
- Epic checkbox catch-up (`_fix_stale_checkboxes()`) runs before archive
- Archive does NOT delete until all verifications pass

The `.merge-progress` resume file is preserved as a crash-recovery mechanism —
if `work-end` fails mid-merge (e.g., network error during push), the resume
file tracks which repos have been pushed so retry skips completed repos.

### 8.5 Enforcement

Safety gates are enforced at three layers:

1. **`validate_state()` in lifecycle.py** — called during `transition()`. Currently
   checks untracked files, branch mismatch, uncommitted changes. Extended to check
   `.plan` completion status when `plan: yes` is in `.meta`.
2. **Pre-push hook (`pre_push_hook.py`)** — blocks pushes to main outside closing
   states (`closing:pushed`, `closing:merged`, `closing:stamped`). Unchanged.
3. **Skill-layer checks** — the remaining invariants (IDE files saved, artifact scan,
   blog scan) remain in the skill layer, enforced by the work-end SKILL.md steps.

---

## 9. `work-end` Queue Handling

### 9.1 Complete Queue

All items in `.plan` are `[x]`. `covers:` in `.meta` has all issue numbers. `work-end`
closes everything in `covers:`.

### 9.2 Incomplete Queue

Uncompleted items remain in `.plan`. They are NOT in `covers:` and don't get closed.

At close time:
- Batch boundary: "Batch N complete — safe exit point. Close now? (y/confirm-partial)"
- Mid-batch: "N items remaining in current batch. Type `confirm-partial` to close anyway."
- Uncompleted items reported in the work-end summary and handover

### 9.3 Issue Closure

`covers:` is the authoritative list. Only issues in `covers:` get closed at `work-end`.
This is unchanged from today — `covers:` just grows incrementally via `work-next`
rather than being set all-at-once at branch creation.

### 9.4 Scaffold Cleanup

During `cleanup_pass` (the final lifecycle transition `closing:stamped → idle`), the
`write_plan_closed` effect removes `design/.plan` alongside `design/.meta` and
`design/JOURNAL.md`. In single-repo mode, `filter-repo` preprocessing strips these
paths before squash (same as today for `.meta` and `.epic`).

---

## 10. Unified `work-start` Flow (Changes Only)

The full work-start flow is preserved. This section describes only what changes.

### 10.1 Issue Mode — Changes to Step 4

After existing cross-repo detection (unchanged), issue resolution proceeds as:

1. Parse all `#N` refs from invocation argument
2. For each issue, validate via issue-workflow Phase 2 (existing delegation —
   searches for existing issues, applies labels, checks epic placement)
3. Auto-detect epics: for each resolved issue, call `detect_epic()` (section 14)
4. For epics: fetch children recursively. Estimate scale/complexity labels per child.
5. For epics with 5+ children: LLM-driven batch planning (present to user for approval)
6. Build `.plan` with full queue (tree structure)
7. Set first issue as primary. `COVERS` starts as just the primary issue (not all
   issues — they accumulate via `work-next`)

### 10.2 Free Text Mode — Changes to Step 1 and Step 4

- Step 1: accept free text as work description (existing behavior)
- Step 4: skip issue-workflow Phase 2. `.meta` `issue:` and `issue-repo:` start empty.
- Step 9: scaffold writes `.meta` with empty `issue:` and `plan: yes`
- `.plan` created with empty queue
- During brainstorming (Step 12), issues are created via issue-workflow Phase 2 and
  appended to `.plan`. First issue created becomes the primary — `.meta` `issue:` and
  `issue-repo:` are set. If the first issue is in a different repo than the project,
  `issue-repo:` reflects that (cross-repo tracking).

### 10.3 Changes to Step 9 (Scaffold)

`scaffold.py` invocation adds `plan=yes` parameter. Scaffold stages `.plan` alongside
`.meta` and `JOURNAL.md` in the commit-scaffold step (Step 10).

### 10.4 Changes to Step 3d (Epic Overlay — Resume Path)

On resume, the epic overlay reads `.plan` instead of `.epic`:
- If `plan: yes` in `.meta`: read `.plan` for queue state, display progress
- If `.epic` exists but no `.plan`: fall back to current `.epic` overlay (backward compat)
- Display: current issue, queue position, completed/total count, batch info

### 10.5 Slot Variants

`work-slot` follows the same changes. Additional:
- Issue mode: user specifies repos (unchanged)
- Free text mode: slot with current repo only
- `work-start` implicit (scaffold.py called internally, state → `scaffolded`)
- Duplicate epic guard: scan active slots, refuse if same epic tracked (unchanged)

---

## 11. Unified `work-slot` Flow (Revised)

### 11.1 Merged Subcommands

`work-slot create` and `work-slot epic` merge into a single `work-slot` invocation.
Epic detection is automatic — no separate command needed.

| Before | After |
|--------|-------|
| `work-slot create` + `work-slot epic #N` | `work-slot #42 #50 #32` (auto-detects epics) |
| `work-slot create` (single issue) | `work-slot #42` |
| — | `work-slot "improve scoring"` (free text, current repo) |

### 11.2 Remaining Subcommands

| Subcommand | Change |
|------------|--------|
| `work-slot list` | Unchanged |
| `work-slot next` | Delegates to unified `work-next` logic (reads `.plan`) |
| `work-slot status` | Reads `.plan` for queue progress; includes divergence detection (cross-check `.plan` against GitHub epic body for added/closed issues since batch planning) |
| `work-slot remove <N>` | Unchanged (manual archive/cleanup) |
| `work-slot add-repo <name>` | **New** (section 7.1) |
| `work-slot remove-repo <name>` | **New** (section 7.2) |

### 11.3 Removed Subcommands

| Subcommand | Reason |
|------------|--------|
| `work-slot merge` | Subsumed by `work-end`. Running `work-end` in a slot does the full sequence including merge to original, stamp, and archive. There is no separate merge step. |
| `work-slot epic` | Subsumed by `work-slot` with auto-epic detection. |

---

## 12. ctx.py and work_router.py Updates

### 12.1 New ctx.py Output Variables

When `plan: yes` exists in `.meta`, ctx.py reads `.plan` and outputs:

| Variable | Source | Purpose |
|----------|--------|---------|
| `HAS_PLAN` | `.meta` `plan: yes` | Whether a `.plan` file exists |
| `PLAN_PATH` | Resolved path to `.plan` | For callers that read the file |
| `PLAN_ACTIVE_ISSUE` | `← active` marker in `.plan` | Current issue being worked |
| `PLAN_POSITION` | Queue progress (e.g., "3/7") | For display |
| `PLAN_BATCH` | Current batch info (if applicable) | For display |

### 12.2 Backward Compatibility with `IS_EPIC`

The existing `IS_EPIC`, `EPIC_PATH`, `EPIC_BATCH`, `EPIC_ACTIVE_ISSUE` variables
continue to be output when `.epic` files exist (no `.plan`). When `.plan` exists,
these variables are populated from `.plan` data for backward compatibility:

- `IS_EPIC` = `yes` if `.plan` contains any epic items
- `EPIC_PATH` = `PLAN_PATH`
- `EPIC_BATCH` = `PLAN_BATCH`
- `EPIC_ACTIVE_ISSUE` = `PLAN_ACTIVE_ISSUE`

This ensures handover, work-end, and work_router.py continue to work without
immediate updates. They can migrate to the `PLAN_*` variables incrementally.

### 12.3 work_router.py Changes

`work_router.py` currently has parallel epic detection logic via `epic_manager.detect()`.
Updated to also detect `.plan` via the `HAS_PLAN` / `PLAN_*` variables from ctx.py
(eliminating the duplicate detection). The options menu on resume shows queue progress
from `.plan` when present.

---

## 13. Pause/Resume Interaction with `.plan`

### 13.1 `.plan` Persists on the Branch

`.plan` is a committed file on the branch. When work-pause commits WIP and switches
to main, the `.plan` file (with its `← active` marker) stays on the branch. When
work-resume checks out the branch, `.plan` is restored automatically by git.

### 13.2 Pause Stack Entries

The pause stack entry gains a new optional field:

| Field | Source | Purpose |
|-------|--------|---------|
| `plan_active_issue` | `.plan` `← active` marker | Display during work-resume stack picker |
| `plan_position` | Queue progress | Display during work-resume stack picker |

These replace the existing `epic_batch` and `epic_active_issue` fields when `.plan`
is present. When `.epic` is present instead, the existing fields are used.

### 13.3 work-resume Display

When resuming a `.plan`-based branch, display queue context:

```
Resuming: issue-42-batch-work
  Queue: #42 ✓, #50 (2/3), #32 pending
  Active: #109 — Update scoring
```

---

## 14. Handover Interaction with `.plan`

### 14.1 Current Behavior

Handover reads `IS_EPIC` from ctx.py. If `yes`, reads `## Session State` and
`## Batch Plan` from `EPIC_PATH` and renders an Epic Progress section.

### 14.2 Updated Behavior

When `HAS_PLAN=yes` (from ctx.py), handover reads `.plan` instead:

- Parses `## Queue` for progress (completed/active/pending counts)
- Parses `## Session State` for current issue and position
- Renders a Queue Progress section:

```markdown
## Queue Progress
- Completed: #42, #108
- Active: #109 — Update scoring (epic #50, 2/3)
- Pending: #110, #53, #32
```

The `IS_EPIC` backward-compatibility bridge (section 12.2) ensures handover
works for `.plan` branches even before the handover skill is updated to read
`HAS_PLAN` directly.

---

## 15. Session Handling When Slots Are Archived

### 15.1 Problem

When `work-slot merge` or `work-slot remove` archives a slot, any Claude session
whose CWD is inside that slot (e.g., `slots/38/engine/`) finds itself in a
deleted or moved directory. Git operations fail, file edits fail, the session
is stranded.

### 15.2 Detection

After archive/remove, if the current session is inside the archived slot:
- `pwd` returns a path containing `slots/<N>/` that no longer exists, OR
- `pwd` returns a path containing `slots/attic/<N>/` (moved, not deleted)

### 15.3 Recovery Flow

1. Detect CWD is inside an archived/removed slot
2. Display: "Slot <N> has been archived. Switching to family root."
3. Change CWD to the family root (parent of `slots/`)
4. If the session was work-started in the slot, the lifecycle state is now
   `idle` (the branch was merged/stamped). Report this.
5. If trellis is running, notify it that the slot's work items are `ended`

### 15.4 Prevention

`archive_slot()` already calls `_escape_slot_cwd()` (slot_manager.py) which
detects if CWD is inside the slot and changes to the family root before
archiving. This is preserved. The above flow handles the case where a
DIFFERENT session (not the one running archive) is inside the slot.

---

## 16. Trellis Integration

### 15.1 Primary Source: worklog.db

Cross-session, cross-workspace. Trellis reads:
- `active_work()` — which branches/slots are active, which repo
- Latest `issue-activate` event per work item — the current active issue
- `issue-complete` events — completed issue history

**New code required:** trellis sidecar has no worklog.db reader today. This requires:
- SQLite JDBC dependency in `pom.xml`
- New `WorklogReader` class that opens `~/.hortora/worklog.db` read-only
- REST endpoint exposing active work and current issues

### 15.2 Secondary Source: `.plan` File

Filesystem scan for richer UI:
- Full queue tree with progress markers
- Epic expansion and nesting
- Batch boundaries
- Upcoming work items

`WorkspaceScanner` gains a new `scanPlanFile()` method — a new parser, not an
update to `scanEpicFile()`. The `.plan` format (`## Queue` with indentation-based
nesting, `← active` markers) is structurally different from `.epic` (`Current batch:`,
flat checkbox lines).

### 15.3 Trellis Data Model

New records added to `WorkspaceModel`:

```java
record WorkPlan(
    Path planFile,
    List<QueueItem> queue,
    QueueItem activeItem,
    int completedCount,
    int totalCount
) {}

sealed interface QueueItem {
    int issueNumber();
    String title();
    boolean completed();

    record LeafIssue(int issueNumber, String title,
                     boolean completed, boolean active) implements QueueItem {}

    record EpicIssue(int issueNumber, String title,
                     boolean completed, List<QueueItem> children) implements QueueItem {}
}
```

`WorkspaceModel` gains `List<WorkPlan> plans` alongside the existing `List<EpicInfo> epics`.
`SlotInfo.isEpic` derives from `.plan` existence when present, falling back to
`Type: epic` in `.slot` for backward compat.

`LifecycleManager.epicSetup()` and `epicNext()` updated to call the new `.plan`
manager instead of `epic_manager.py` when `.plan` is present.

---

## 17. Backward Compatibility

### 16.1 In-Progress Epics

Branches with `.epic` but no `.plan` continue to work. The `advance_issue` effect
falls back to reading `.epic`. No forced migration.

### 16.2 `.meta` Without `plan:` Field

Legacy branches without `plan: yes` are assumed to have no `.plan` file. ctx.py
outputs `HAS_PLAN=no` and uses the existing `IS_EPIC` codepath.

### 16.3 `work epic #N` Syntax

Remains as an alias. Routes to the unified flow — auto-detection confirms what the
user already told us. The full branch-creation-plus-batch-planning flow runs through
the unified `build_plan` effect.

### 16.4 Migration Path

No active migration needed. New branches get `.plan` automatically. Old branches
finish under the old format. When all old branches close, `.epic` support can be
removed in a cleanup pass.

---

## 18. Epic Auto-Detection

### 17.1 Algorithm

```
detect_epic(issue_number, issue_repo):
    body = gh issue view <N> --repo <repo> --json body
    if body contains "## Scope" section:
        children = parse all "- [ ] #N" and "- [x] #N" from Scope section
        filter out closed children (already done)
        if children is non-empty:
            return Epic(issue_number, children)
    return LeafIssue(issue_number)
```

### 17.2 Recursive Detection

After detecting an epic's children, each child is also checked:

```
build_queue(issue_numbers, visited=set()):
    queue = []
    for N in issue_numbers:
        if N in visited:
            warn("Cycle detected: #{N} already in queue. Skipping.")
            continue
        visited.add(N)
        result = detect_epic(N)
        if result is Epic:
            result.children = build_queue(result.children, visited)
        queue.append(result)
    return queue
```

### 17.3 Duplicate Epic Guard

Before building the queue, scan active slots and branches for epics already being
tracked. Refuse if the same epic is already in progress (same as today's
`work-slot epic` Step 0).

---

## 19. New Infrastructure: `.plan` Parser

### 18.1 Why This Is New Code

The current `epic_manager._parse_batches()` produces a flat list of issues within
batches. It uses line-by-line regex matching on a flat file. The `.plan` format
requires:

- **Tree parser**: indentation-based nesting to build `QueueItem` tree
- **Tree rewriter**: mark parent epics `[x]` when all children complete, handling
  arbitrary nesting depth
- **Batch detection within indentation context**: `### Batch N` headers scoped to
  their parent epic's indentation level

This is the largest new-code component. It cannot be built by extending
`_parse_batches()` — it requires a new parser.

### 18.2 Parser Design

```python
def parse_plan(plan_path: Path) -> PlanTree:
    """Parse .plan file into a tree of QueueItems."""

def flatten_leaves(tree: PlanTree) -> list[LeafItem]:
    """Pre-order traversal returning only leaf issues."""

def advance(plan_path: Path, meta_path: Path) -> AdvanceResult:
    """Mark current active complete, find next leaf, rewrite .plan."""

def rewrite_plan(plan_path: Path, tree: PlanTree):
    """Write tree back to .plan format preserving indentation."""
```

### 18.3 Backward Compatibility

```python
def advance_issue(plan_path: Path | None, epic_path: Path | None,
                  meta_path: Path) -> AdvanceResult:
    """Dispatch to .plan or .epic advance based on what exists."""
    if plan_path and plan_path.exists():
        return plan_manager.advance(plan_path, meta_path)
    elif epic_path and epic_path.exists():
        return epic_manager.advance(epic_path, meta_path)
    else:
        raise NoQueueFile("No .plan or .epic found")
```

---

## 20. Implementation Phases

### Phase 1 — `.plan` parser and worklog additions

- `.plan` file format: tree parser, writer, flatten, advance logic
- worklog.py: `record_issue_activate`, `record_issue_complete`, `work_item_issues` update
- Unit tests for all of the above (tree parsing, nesting, batch boundaries, cycle detection)
- No skill changes yet — pure infrastructure

### Phase 2 — ctx.py and work_router.py

- ctx.py: `HAS_PLAN`, `PLAN_PATH`, `PLAN_ACTIVE_ISSUE`, `PLAN_POSITION`, `PLAN_BATCH`
- Backward compat bridge: populate `IS_EPIC` etc. from `.plan` data
- work_router.py: `.plan` detection, eliminate duplicate epic detection
- Unit tests

### Phase 3 — Unified `work-start`

- Issue mode: multi-issue queue building with auto-epic detection
- Free text mode: empty queue, deferred issue creation
- `build_plan` effect integrated into scaffold flow
- `.meta` `plan: yes` field, scaffold stages `.plan`
- Preserve all existing steps (platform coherence, protocols, garden, specs,
  stacked PRs, fork sync, flyway, design routing, IntelliJ)

### Phase 4 — Unified `work-next`

- Read `.plan` instead of `.epic`
- Flattened leaf iteration with tree rewrite
- Backward compatibility with `.epic`
- worklog event recording
- `safe_exit` and `batch_complete` flags

### Phase 5 — Unified `work-slot`

- Merge `work-slot create` and `work-slot epic`
- `work-slot add-repo` and `work-slot remove-repo`
- `.plan` alongside `.slot`
- Preserve all slot infrastructure (section "Unchanged Slot Infrastructure")

### Phase 6 — Pause/resume and handover

- Pause stack entry: `plan_active_issue`, `plan_position` fields
- work-resume: display queue context from `.plan`
- Handover: Queue Progress section from `.plan`

### Phase 7 — `work-end` updates

- `.plan`-aware invariant checks in `validate_state()`
- `write_plan_closed` cleanup effect
- Scaffold cleanup includes `.plan`
- Preserve all existing work-end steps

### Phase 8 — Trellis integration

- `WorkspaceScanner.scanPlanFile()` — new parser
- `WorklogReader` — new SQLite reader with REST endpoint
- `WorkPlan` / `QueueItem` data model
- `LifecycleManager` updates for `.plan` manager
- `SlotInfo.isEpic` derivation from `.plan`

---

## 21. Test Plan

### 20.1 Unit Tests

- `.plan` tree parser: single issue, multi-issue, nested epics, batch plans, empty queue
- `.plan` tree writer: same variants (round-trip: parse → write → parse = identical)
- `flatten_leaves()`: verify pre-order traversal for nested structures
- Advance logic: linear, epic boundary, nested epic boundary, batch boundary,
  queue exhausted, cycle detection, parent `[x]` marking on child completion
- worklog.py: `record_issue_activate`, `record_issue_complete`, `work_item_issues`
  update, query patterns
- `.meta` covers accumulation with deduplication
- ctx.py: `HAS_PLAN` / `PLAN_*` output with and without `.plan`
- Pause stack: `plan_active_issue`, `plan_position` serialization

### 20.2 Integration Tests

- `work-start #42` → trivial `.plan` created, all existing steps still run
- `work-start #42 #50 #32` → multi-issue `.plan` with auto-epic detection
- `work-start "improve scoring"` → empty `.plan`, branch from text
- `work-next` through a mixed queue (leaf, epic, nested epic)
- `work-end` with complete vs incomplete queue
- `work-pause` / `work-resume` with `.plan` context preservation
- Slot: `work-slot #42 #50` → `.plan` + `.slot` created
- Slot: `add-repo`, `remove-repo`
- Backward compat: `.epic` without `.plan` still iterates

### 20.3 End-to-End

- Full lifecycle: `work-start #A #B(epic) #C` → `work-next` through all → `work-end`
- Trellis: worklog.db query returns correct active issue after each transition
- Free text: `work-start "fix things"` → brainstorm → create issues → `work-next` → `work-end`
- Slot with dynamic repos: `work-slot "improve scoring"` → add repos via spec → `work-next` → `work-end`
