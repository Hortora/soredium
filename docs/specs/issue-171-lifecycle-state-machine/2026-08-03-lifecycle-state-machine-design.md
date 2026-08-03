# Lifecycle State Machine — Design Spec

**Issue:** Hortora/soredium#171
**Date:** 2026-08-03
**Status:** Draft — pending design review

## Problem Statement

The work lifecycle system infers state from scattered filesystem signals: `.meta` existence, branch position, `.pause-stack`, `HAS_HANDOFF`, `.epic`/`.slot`. Every entry point independently re-derives state from these signals. Six of eleven entry points get it wrong — context setup is silently skipped, lifecycle events go untracked, and closing gates can be bypassed.

This inference-based approach is:
- **Fragile** — each new entry point must correctly combine 5+ signals
- **Untestable** — requires mocking multiple files and branch states in combination
- **Silent on failure** — skipped context setup produces no error
- **Bypassable** — manual `git merge` brings `.meta` to main with no close path (GE-20260521-b6a1a7)

## Design Goal

Replace inference with an explicit `state:` field in `.meta`. A single Python module (`lifecycle.py`) owns all state transitions. Entry points declare events; the state machine determines effects. No entry point decides what subset of work-start to run — the transition table decides.

---

## 1. States

Eleven states in a single flat namespace. No nested sub-machines.

| State | Meaning | `.meta` value | Resting? |
|-------|---------|---------------|----------|
| `idle` | On main, no work in progress | No `.meta` exists | Yes |
| `scaffolded` | Branch + `.meta` created, context setup pending | `state: scaffolded` | **No — transient** |
| `active` | Context loaded, working | `state: active` | Yes |
| `transitioning` | Between epic issues, context refresh pending | `state: transitioning` | **No — transient** |
| `paused` | On pause stack, WIP committed | `state: paused` | Yes |
| `closing:review` | Close initiated, code review pending | `state: closing:review` | Yes |
| `closing:verified` | Review passed, workspace and project artifact promotion pending | `state: closing:verified` | Yes |
| `closing:promoted` | Artifacts workspace-promoted and project-promoted, merge pending | `state: closing:promoted` | Yes |
| `closing:pushed` | Branch squashed and pushed, merge to main pending | `state: closing:pushed` | Yes |
| `closing:merged` | Merged to main, stamp pending | `state: closing:merged` | Yes |
| `closing:stamped` | Stamped, cleanup pending | `state: closing:stamped` | Yes |

### Transient States

`scaffolded` and `transitioning` are **not resting states**. They auto-resolve: the system detects the transient state and immediately runs the required side effects (context setup or context refresh) then transitions to `active`. A session that reads a transient state always resolves it — there is no user action required.

### State Invariants

Each state has invariants that must be true whenever the system is in that state:

| State | Invariants |
|-------|-----------|
| `idle` | No `.meta` exists. Project and workspace on main/base branch. |
| `scaffolded` | `.meta` exists with `state: scaffolded`. Branch created in project and workspace. `.meta` has branch, issue, date fields populated. |
| `active` | `.meta` exists with `state: active`. Project and workspace on the branch named in `.meta`. No transient context setup pending. |
| `transitioning` | `.meta` exists with `state: transitioning`. Epic file (`.epic` or `.slot`) exists. Previous issue checked off. Next issue marked active. |
| `paused` | `.meta` exists with `state: paused` **on the branch**. Entry present in `.pause-stack` on main. WIP commit is HEAD on both repos' branches. Project and workspace on main/base. |

**Paused state detection model:** The `paused` state is stored in `.meta` on the feature branch, which is not in the working tree when on main. Detection uses a two-step process: (1) the routing layer reads `.pause-stack` on main to identify paused branches, (2) after the user selects a branch and work-resume checks it out, `transition()` reads `state: paused` from the now-accessible `.meta`. The state machine never needs to read `paused` from main — the routing layer handles discovery, and `transition()` fires after checkout.
| `closing:review` | `.meta` exists. On the branch. No uncommitted changes in project. |
| `closing:verified` | Same as `closing:review` plus code review passed (recorded in `.meta`). |
| `closing:promoted` | Same as `closing:verified` plus `.artifacts-promoted` stamp exists OR `close_artifacts.py` returned success. |
| `closing:pushed` | Same as `closing:promoted` plus branch squashed to a single commit and pushed to fork/origin. |
| `closing:merged` | Project base branch has the branch content. Rebase/squash completed. |
| `closing:stamped` | Branch has closure stamp commit. Content verified on base branch. |

---

## 2. Events

Events are the inputs to the state machine. Each event corresponds to a user command or system trigger.

| Event | Source | Description |
|-------|--------|-------------|
| `work` | User command | Begin new work from main |
| `work_epic` | User command (`work epic #N`) | Set up single-repo epic |
| `slot_create` | User command (`work-slot create`) | Create a slot |
| `slot_epic` | User command (`work-slot epic #N`) | Create an epic slot |
| `auto_setup` | System (transient state detected) | Auto-resolve `scaffolded` → run context setup |
| `work_next` | User command (`work next`, `work-slot next`) | Advance to next epic issue |
| `auto_refresh` | System (transient state detected) | Auto-resolve `transitioning` → run context refresh |
| `work_pause` | User command (`work pause`) | Pause current branch |
| `work_resume` | User command (`work resume`) | Resume a paused branch |
| `work_end` | User command (`work end`) | Initiate close sequence |
| `review_pass` | System (code review completes) | Code review passed |
| `promote_pass` | System (`close_artifacts.py` succeeds) | Artifacts workspace-promoted and project-promoted |
| `push_pass` | System (squash + push branch succeeds) | Branch squashed and pushed to fork |
| `merge_pass` | System (rebase + push main succeeds) | Branch merged to main |
| `stamp_pass` | System (stamp written + verified) | Branch stamped as closed |
| `cleanup_pass` | System (cleanup completes) | Return to idle |
| `abort_close` | User command (abort during close) | Abort closing sequence |

---

## 3. Transition Table

### 3.1 Core Lifecycle

| # | From | Event | To | Side Effects | Gate |
|---|------|-------|----|-------------|------|
| T1 | `idle` | `work` | `scaffolded` | Create branch (project + workspace), write `.meta` with `state: scaffolded`, scaffold JOURNAL.md | Must be on main |
| T2 | `idle` | `work_epic` | `scaffolded` | Create branch, scaffold, write `.epic`, batch plan | Must be on main |
| T3 | `idle` | `slot_create` | `scaffolded` | Create slot clones, write `.meta` in slot with `state: scaffolded` | Must be on main, family root resolved |
| T4 | `idle` | `slot_epic` | `scaffolded` | Create epic slot, write `.meta` + `.slot` with `state: scaffolded` | Must be on main |
| T5 | `scaffolded` | `auto_setup` | `active` | Garden search, load specs, check protocols, verify IntelliJ | Automatic — fires on any read of `scaffolded` state |
| T6 | `active` | `work_next` | `transitioning` | `epic_manager.py advance`, update `.meta`, tick GitHub checkbox | Epic file must exist |
| T7 | `transitioning` | `auto_refresh` | `active` | Garden search (new issue keywords), load specs (new issue), check protocols | Automatic — fires on any read of `transitioning` state |
| T8 | `active` | `work_pause` | `paused` | WIP commit · **post-commit:** switch to main, push `.pause-stack` | `.meta` must exist |
| T9 | `paused` | `work_resume` | `active` | Pop stack, reset WIP, run context resume (§6.3) | Entry must be in `.pause-stack`; branch checked out before event fires |

### 3.2 Closing Sequence

| # | From | Event | To | Side Effects | Gate |
|---|------|-------|----|-------------|------|
| T10 | `active` | `work_end` | `closing:review` | Initiate close, run pre-close sweep | Must be on branch, no uncommitted changes |
| T11 | `closing:review` | `review_pass` | `closing:verified` | Record review result in `.meta` | Code review or final review must complete |
| T12 | `closing:verified` | `promote_pass` | `closing:promoted` | `close_artifacts.py` runs, `.artifacts-promoted` stamp written | Stamp must be written |
| T13 | `closing:promoted` | `push_pass` | `closing:pushed` | Squash commits, push branch to fork/origin | Push must succeed |
| T14 | `closing:pushed` | `merge_pass` | `closing:merged` | Rebase onto base branch, push main | Merge must succeed |
| T15 | `closing:merged` | `stamp_pass` | `closing:stamped` | Write closure stamp, verify content landed via `git cat-file` | `verify_stamp.py` must pass |
| T16 | `closing:stamped` | `cleanup_pass` | `idle` | Write EPIC-CLOSED.md · **post-commit:** return to main, write HANDOFF.md | On the branch |

### 3.3 Slot Phase A / Phase B Mapping

In slot mode, the closing sequence splits across two sessions:

| Phase | Transitions | Session |
|-------|------------|---------|
| Phase A | T10 → T11 → T12 → T13 (squash + push branch) | In the slot |
| Phase B | T14 (rebase onto main, push main) → T15 → T16 | From main repo via `work-slot merge` |

Phase A ends at `closing:pushed` — branch is squashed and pushed to fork, but not merged to main. Phase B starts from `closing:pushed` and completes the merge, stamp, and cleanup.

The `.phase-a-complete` marker file is **removed** — replaced by `state: closing:pushed` in `.meta`. Migration: if `.phase-a-complete` exists and `.meta` has no `state:` field, `read_state()` returns `closing:pushed`. New branches use the state field exclusively.

### 3.4 Session-Start Routing (skill-layer, not transition table)

Session start is NOT a state machine event. It is routing logic in the `project` skill and `work` router that reads the current state and dispatches to the appropriate handler. These are documented here for completeness but do NOT appear in the `TRANSITION_TABLE` dict in §15.2.

| Current State | Routing Action |
|---------------|---------------|
| `scaffolded` | Fire `auto_setup` event → resolves to T5 (`scaffolded → active`) |
| `transitioning` | Fire `auto_refresh` event → resolves to T7 (`transitioning → active`) |
| `active` | Show work lifecycle menu (resume/end/pause/wrap) — no state change |
| `paused` | Show pause stack (same as existing work router) — no state change |
| `closing:*` | Offer to continue close from current gate — no state change |

Transient states (`scaffolded`, `transitioning`) auto-resolve via their dedicated events. Resting states show the appropriate UI without firing any transition.

---

## 4. Invalid Transitions

Every `(state, event)` pair not in the transition table is invalid. The state machine raises `InvalidTransition` with a human-readable message.

### 4.1 Common Invalid Transitions and Error Messages

| From | Event | Why Invalid | Error Message |
|------|-------|-------------|---------------|
| `idle` | `work_next` | No branch exists | "Cannot advance — no active branch. Start work first." |
| `idle` | `work_pause` | Nothing to pause | "Cannot pause — no active branch." |
| `idle` | `work_end` | Nothing to close | "Cannot close — no active branch. You're on main." |
| `idle` | `work_resume` | Nothing to resume (no stack) | "Cannot resume — pause stack is empty." |
| `scaffolded` | `work_next` | Context setup hasn't run | "Branch not yet active — context setup must complete first." |
| `scaffolded` | `work_end` | Can't close before starting | "Cannot close — branch hasn't been activated yet." |
| `scaffolded` | `work_pause` | Can't pause before starting | "Cannot pause — branch hasn't been activated yet." |
| `active` | `work` | Already working | "Already on an active branch. Use `work end`, `work pause`, or `work next`." |
| `active` | `work_epic` | Already working | "Already on an active branch. Close or pause first." |
| `active` | `work_resume` | Not paused | "Branch is active, not paused. Nothing to resume." |
| `transitioning` | `work_end` | Context refresh pending | "Issue transition in progress — context refresh must complete first." |
| `transitioning` | `work_pause` | Context refresh pending | "Issue transition in progress — wait for context refresh." |
| `paused` | `work_end` | Can't close while paused | "Cannot close a paused branch. Resume it first, then close." |
| `paused` | `work_next` | Can't advance while paused | "Cannot advance — branch is paused. Resume first." |
| `paused` | `work_pause` | Already paused | "Branch is already paused." |
| `closing:review` | `work_pause` | Can't pause mid-close | "Cannot pause during close sequence. Abort or complete the close." |
| `closing:review` | `work_next` | Can't advance mid-close | "Cannot advance — close sequence in progress." |
| `closing:*` | `work` | Can't start new work mid-close | "Close sequence in progress. Complete or abort first." |
| `closing:*` | `work_epic` | Can't start epic mid-close | "Close sequence in progress. Complete or abort first." |
| `closing:verified` | `review_pass` | Already past review | "Review already passed — currently at workspace/project promotion stage." |
| `closing:promoted` | `promote_pass` | Already past promotion | "Workspace and project promotion already passed — currently at push stage." |
| `closing:pushed` | `push_pass` | Already past push | "Push already complete — currently at merge stage." |
| `closing:promoted` | `abort_close` | Past workspace and project promotion | "Cannot abort — artifacts already workspace-promoted and project-promoted. Continue forward." |
| `closing:pushed` | `abort_close` | Past workspace and project promotion | "Cannot abort — artifacts already workspace-promoted and project-promoted. Branch pushed — continue forward." |
| `closing:merged` | `abort_close` | Content on main | "Cannot abort — content already merged to main. Continue forward." |
| `closing:stamped` | `abort_close` | Branch stamped | "Cannot abort — branch already stamped. Only cleanup remains." |

### 4.2 Abort from Closing States

Only pre-artifact closing states can be aborted. Once artifacts are workspace-promoted and project-promoted (`closing:promoted` and beyond), the close path is forward-only — issues have been closed, specs promoted to workspace main and project, and blogs published. These operations are practically irreversible without manual intervention.

| From | Event | To | Side Effects |
|------|-------|----|-------------|
| `closing:review` | `abort_close` | `active` | Clear closing markers, restore working state |
| `closing:verified` | `abort_close` | `active` | Clear closing markers, restore working state |

This handles the case where code review finds issues that need fixing — abort the close, fix the code, then re-initiate `work_end`.

**Why `closing:promoted` and later are non-abortable:**
- `closing:promoted` — `close_artifacts.py` has already closed GitHub issues, workspace-promoted specs to workspace main and project-promoted specs to the project repo, and published blogs. Aborting would leave promoted artifacts on workspace main and project with no corresponding branch close.
- `closing:merged` — content has been rebased onto the base branch and pushed to the fork. Aborting would mean continuing work on a branch whose content is already on main, producing duplicate commits on the next close.
- `closing:stamped` — branch has a closure stamp commit. Only cleanup remains.

If the merge step (8j) fails at `closing:promoted`, the correct action is to fix the conflict and retry the merge, not abort. The state remains `closing:promoted` until `merge_pass` succeeds.

---

## 5. Entry Point → Event Mapping

Every way work can begin, mapped to the event it fires. This is the exhaustive list — if an entry point is not here, it doesn't exist.

### 5.1 User Commands

| Entry Point | Current State | Event | Notes |
|-------------|--------------|-------|-------|
| `work` from main (no stack) | `idle` | `work` | New branch path |
| `work` from main (with stack → "new") | `idle` | `work` | User chose "new" from stack picker |
| `work` from main (with stack → pick) | `paused` | `work_resume` | User chose a paused branch |
| `work` from feature branch | any | _(routing — §3.4)_ | Router detects state, shows menu |
| `work start` | `idle` | `work` | Synonym for `work` |
| `work end` | `active` | `work_end` | Initiate close |
| `work pause` | `active` | `work_pause` | Pause current branch |
| `work resume` | `paused` | `work_resume` | Resume from stack |
| `work epic #N` | `idle` | `work_epic` | Single-repo epic setup |
| `work next` | `active` | `work_next` | Advance epic issue |
| `work-slot create` | `idle` | `slot_create` | Create slot |
| `work-slot epic #N` | `idle` | `slot_epic` | Create epic slot |
| `work-slot next` | `active` | `work_next` | Same event as `work next` |
| `work-slot merge` | `closing:pushed` | `merge_pass` | Phase B merge |

### 5.2 System Events

| Trigger | Current State | Event | Notes |
|---------|--------------|-------|-------|
| Session hook (`project` skill) | `scaffolded` | `session_start` → `auto_setup` | Transient state auto-resolves |
| Session hook (`project` skill) | `transitioning` | `session_start` → `auto_refresh` | Transient state auto-resolves |
| Session hook (`project` skill) | `active` | `session_start` | Show lifecycle menu |
| Session hook (`project` skill) | `closing:*` | `session_start` | Offer to continue close |
| `close_artifacts.py` succeeds | `closing:verified` | `promote_pass` | Automatic after script |
| Code review passes | `closing:review` | `review_pass` | Automatic after review |
| Squash + push branch succeeds | `closing:promoted` | `push_pass` | Automatic after push |
| Rebase + push main succeeds | `closing:pushed` | `merge_pass` | Automatic after merge |
| Stamp + verify succeeds | `closing:merged` | `stamp_pass` | Automatic after stamp |
| Cleanup completes | `closing:stamped` | `cleanup_pass` | Automatic after cleanup |

### 5.3 External Events (Not Modelled — Detected and Recovered)

These are things that happen outside the state machine. They can leave `.meta` in an inconsistent state. The state machine detects and recovers rather than modelling them as transitions.

| External Event | Detection | Recovery |
|---------------|-----------|----------|
| Manual `git checkout main` while on branch | `.meta` branch field doesn't match current branch | Offer to switch back or discard |
| Manual `git merge --ff-only <branch>` to main | `.meta` exists on main (GE-20260521-b6a1a7) | Offer to complete close or remove `.meta` |
| Session crash mid-transition | Transient state persists beyond 1 hour | Re-run auto-resolve on next session |
| Session crash mid-close | `closing:*` state persists | Offer to continue from current gate |
| Manual `git push` bypassing work-end | Pre-push hook blocks if state < `closing:pushed` | Hook refuses the push |
| Workspace on stale branch (workspace dirty) | Workspace on non-main branch, project on main, no `.meta` | Switch workspace to main, then proceed with normal routing |
| Another session modifies `.meta` | State read doesn't match expected state | Hard stop — investigate |
| Branch deleted on remote | Branch exists locally but `git fetch --prune` removes tracking ref | Warn, offer to re-push or clean up |

---

## 6. Side Effects — Context Setup and Context Refresh

### 6.1 Context Setup (fires on `scaffolded → active`)

These are the work-start resume path steps that must run before any implementation work begins:

| # | Step | Source | Skippable? |
|---|------|--------|-----------|
| CS1 | Platform coherence (five questions) | work-start Step 2 | Skip if no PLATFORM.md |
| CS2 | Protocol check | work-start Step 3 | Skip if no protocols dir |
| CS3 | Garden search | work-start Step 3b | Skip if no garden or pure tooling task |
| CS4 | Load existing specs | work-start Step 3c | Never skip — always scan |
| CS5 | Epic overlay | work-start Step 3d | Skip if no epic file |
| CS6 | IntelliJ verification | work-start Step 11 | Skip only if user confirms docs-only |

### 6.2 Context Refresh (fires on `transitioning → active`)

A subset of context setup, focused on the new issue's domain:

| # | Step | What Changes |
|---|------|-------------|
| CR1 | Garden search | New keywords from new issue title/body |
| CR2 | Load specs | Specs matching new issue number |
| CR3 | Protocol check | Protocols relevant to new issue's domain |

Context refresh does NOT re-run platform coherence (same branch), IntelliJ verification (already connected), or epic overlay (already displayed by `work_next`).

### 6.3 Context Resume (fires on `paused → active`)

A full context setup minus epic overlay, which is handled separately by the resume flow's stack entry metadata:

| # | Step | Source | What Changes |
|---|------|--------|-------------|
| CX1 | Platform coherence | work-start Step 2 | Re-verify — session state may have drifted |
| CX2 | Protocol check | work-start Step 3 | Protocols may have changed while paused |
| CX3 | Garden search | work-start Step 3b | New entries may exist since pause |
| CX4 | Load specs | work-start Step 3c | Specs may have been updated |
| CX5 | IntelliJ verification | work-start Step 11 | New session needs IDE connection |

Context resume does NOT re-run epic overlay (CS5) — the resume flow reads epic context from the stack entry's metadata and displays it as Step 9b in work-resume.

T9's `context_resume` effect maps to this procedure.

**Issue identity source:** Context refresh reads the current issue number from the epic file (`.epic` or `.slot`), NOT from `.meta`'s `issue:` field. The epic file is updated by `advance_issue` (T6 effect) and is authoritative for issue identity during transitions. If `update_meta` (also a T6 effect) fails after `advance_issue` succeeds, the epic file still has the correct new issue and auto-resolve works correctly. If `advance_issue` itself fails, the epic file retains the old issue — auto-resolve refreshes context for the old issue, which is correct since the advance didn't happen.

---

## 7. Hygiene Invariants

`validate_state()` runs at every transition, BEFORE the state is written. If any invariant fails, the transition is rejected — state stays unchanged, error reported.

### 7.1 Universal Invariants (checked at every transition)

| Invariant | Check | Excludes |
|-----------|-------|----------|
| **No untracked files** | `git status --porcelain` filtered by exclude patterns | `.idea/`, `target/`, `build/`, `node_modules/`, `__pycache__/`, `*.iml`, `.worktrees/`, `slots/`. Skip when transitioning to `paused` (`wip_commit` effect handles untracked files) |
| **Branch alignment** | `.meta` branch field matches `git branch --show-current` in project AND workspace | Skip when transitioning to `idle` (`.meta` being removed) or `paused` (switching to main is the point) |
| **`.meta` integrity** | `.meta` has required fields: `branch`, `state`, `date` | Skip when transitioning from `idle` (`.meta` doesn't exist yet) |

### 7.2 Transition Pre-Conditions (checked by `validate_state()`)

These are conditions that must be true BEFORE the transition fires. `validate_state()` checks these alongside the universal invariants in §7.1. They describe pre-existing environmental state, not conditions established by effects.

| State Entering | Pre-Condition |
|---------------|--------------|
| `closing:review` | No uncommitted changes in project repo |
| `closing:review` | No uncommitted changes in workspace repo |

### 7.3 State Post-Conditions (design invariants — NOT checked by `validate_state()`)

These describe conditions that must be true AFTER the transition completes — they are established by effects and gate actions, not pre-existing. They guide implementors on what each state means and what each effect must accomplish, but `validate_state()` does not check them. Checking them at transition time would always fail because the effects that establish them have not yet executed.

| State | Post-Condition | Established By |
|-------|---------------|----------------|
| `closing:promoted` | `.artifacts-promoted` stamp exists | `write_promotion_stamp` effect |
| `closing:pushed` | Branch squashed to single commit and pushed to fork/origin | Push gate action (before `transition()`) |
| `closing:merged` | Branch content exists on base branch | Merge gate action (before `transition()`) |
| `closing:stamped` | `verify_stamp.py` passes — content confirmed on base branch via `git cat-file` (GE-20260801-836d85) | `write_stamp` effect |
| `paused` | WIP commit is HEAD on both repos | `wip_commit` effect |
| `active` (from `paused`) | WIP commit has been reset (working tree restored) | `reset_wip` effect |

### 7.4 Slot-Specific Invariants

| Invariant | When |
|-----------|------|
| `proj/` symlink resolves to a valid git repo | Any transition in slot context |
| `wksp/` symlink resolves to a valid git repo | Any transition in slot context |
| `.slot` file exists and is parseable | `work_next` in slot context |
| Epic active issue in `.slot` matches `.meta` active issue | `transitioning → active` in slot context |

### 7.5 Untracked File Exclude Patterns

The exclude list is configurable per project type via CLAUDE.md `## Project Type`:

| Project Type | Additional Excludes |
|-------------|-------------------|
| `java` | `target/`, `*.class`, `.mvn/`, `*.jar` |
| `skills` | `__pycache__/`, `*.pyc`, `.pytest_cache/` |
| `blog` | `_site/`, `.jekyll-cache/`, `.sass-cache/` |
| `generic` | (universal excludes only) |

---

## 8. Pre-Push Hook Enforcement

A git pre-push hook reads `state:` from `.meta` and blocks pushes that skip closing gates.

### 8.1 Hook Rules

| Condition | Push to main/base | Push to feature branch |
|-----------|-------------------|----------------------|
| No `.meta` exists | ALLOW | ALLOW |
| `state: active` | **BLOCK** — "Run work-end first" | ALLOW (WIP push) |
| `state: scaffolded` | **BLOCK** — "Branch not yet active" | ALLOW |
| `state: transitioning` | **BLOCK** — "Issue transition in progress" | ALLOW |
| `state: paused` | **BLOCK** — "Branch is paused" (defensive — see note) | ALLOW |
| `state: closing:review` | **BLOCK** — "Code review not complete" | ALLOW |
| `state: closing:verified` | **BLOCK** — "Artifacts not promoted (workspace and project)" | ALLOW |
| `state: closing:promoted` | **BLOCK** — "Push not complete" | ALLOW |
| `state: closing:pushed` | ALLOW — merge push | ALLOW |
| `state: closing:merged` | ALLOW — stamp push | ALLOW |
| `state: closing:stamped` | ALLOW — cleanup push | ALLOW |

**Note on `state: paused` row:** When properly paused, both repos are on main and `.meta` is on the branch — the hook reads no `.meta` and hits the "No `.meta` exists → ALLOW" row. The `state: paused` row is a defensive guard for the case where a user manually checks out a paused branch (bypassing work-resume), which would expose `.meta` with `state: paused`.

### 8.2 Hook Location

The hook reads `.meta` from the workspace's `design/` directory. In two-repo mode, this requires the hook to know the workspace path. Resolution:

1. Check `wksp/` symlink in the repo being pushed (follows to workspace)
2. If no symlink, check `$WORKSPACE` environment variable
3. Check `design/.meta` in the current repo (single-repo mode fallback)
4. If no `.meta` found anywhere, skip enforcement (repo not in lifecycle)

**Broken symlink detection:** If `wksp/` exists as a symlink but does not resolve to a valid directory, the hook BLOCKS the push with an error: "wksp/ symlink is broken — cannot verify lifecycle state. Fix the symlink or remove it to bypass." Similarly, if `$WORKSPACE` is set but the path doesn't exist, the hook blocks.

**Local `.meta` fallback (step 3):** When no workspace symlink or env var resolves (steps 1–2 fail without a broken symlink), the hook checks `design/.meta` in the current repo. This handles single-repo projects where `.meta` exists locally but no workspace configuration is present. Enforcement uses the local `.meta` state.

**Skip enforcement (step 4):** Only when no `.meta` is found anywhere — no workspace, no env var, no local file — does the hook skip. This means the repo was never configured for lifecycle management. When workspace was expected but unresolvable (steps 1–2 found symlink/env but path didn't resolve), the hook blocks rather than skipping — see broken symlink detection above.

### 8.3 Hook Implementation

```python
#!/usr/bin/env python3
"""Pre-push hook: enforce lifecycle state gates."""
import sys
from pathlib import Path

def find_meta():
    """Find .meta via wksp/ symlink or WORKSPACE env."""
    # ... resolution logic
    return meta_path or None

def main():
    meta = find_meta()
    if not meta or not meta.exists():
        sys.exit(0)  # No .meta = not in lifecycle, allow

    state = read_state(meta)
    push_target = sys.argv[1]  # remote name
    
    # Read stdin for ref updates (pre-push protocol)
    for line in sys.stdin:
        local_ref, local_sha, remote_ref, remote_sha = line.split()
        is_main_push = remote_ref.endswith('/main') or remote_ref.endswith(f'/{base_branch}')
        
        if is_main_push and state not in ('closing:pushed', 'closing:merged', 'closing:stamped'):
            print(f"BLOCKED: state is '{state}'. Run work-end to complete the close sequence.")
            sys.exit(1)
    
    sys.exit(0)

if __name__ == '__main__':
    main()
```

---

## 9. Stale State Recovery

When a session starts and finds a non-resting state, it must recover.

| Stale State | Detection | Recovery Action |
|-------------|-----------|----------------|
| `scaffolded` | Session start reads `.meta` | Auto-resolve: run context setup (T5/T16). No timeout needed — this is the normal path for slot sessions. |
| `transitioning` | Session start reads `.meta` | Auto-resolve: run context refresh (T7/T17). |
| `closing:review` | Session start reads `.meta` | "Close was interrupted at code review. Continue review? (y) / Abort close? (n)" |
| `closing:verified` | Session start reads `.meta` | "Close was interrupted at workspace/project artifact promotion. Continue? (y) / Abort? (n)" |
| `closing:promoted` | Session start reads `.meta` | "Close was interrupted at push. Artifacts already workspace-promoted and project-promoted — continue. (y)" |
| `closing:pushed` | Session start reads `.meta` | "Close was interrupted at merge. Branch pushed — continue. (y)" |
| `closing:merged` | Session start reads `.meta` | "Close was interrupted at stamping. Content on main — continue. (y)" |
| `closing:stamped` | Session start reads `.meta` | "Close was interrupted at cleanup. Branch stamped — continue. (y)" |

Aborting is only available from `closing:review` and `closing:verified` (pre-artifact states). From `closing:promoted` and later, the close path is forward-only — artifacts have been workspace-promoted and project-promoted, issues closed, and/or content merged. The only option is to continue from the current gate.

**`paused` is absent from this table** because paused branches are discovered via `.pause-stack` on main, not via stale `.meta` detection. The session-start routing (§3.4) checks `.pause-stack` and offers the stack picker — this is normal routing, not stale state recovery.

### 9.1 Orphaned `.meta` on Main

If `.meta` exists but the current branch is main (GE-20260521-b6a1a7, GE-20260517-9d8cdf):

1. Read `state:` from `.meta`
2. Read `branch:` from `.meta`
3. Check if the branch still exists locally: `git rev-parse --verify <branch>`

| Branch exists? | Action |
|---------------|--------|
| Yes | "`.meta` orphaned on main. Switch to `<branch>` to complete close? (y) / Remove `.meta`? (n)" |
| No | "`.meta` orphaned on main — branch `<branch>` no longer exists. Remove `.meta`? (y)" |

This replaces the current work-start State 3 detection with explicit state-aware recovery.

---

## 10. Migration

Existing `.meta` files do not have a `state:` field. Migration is backward-compatible:

### 10.1 Read Migration

```python
def read_state(meta_path: Path) -> Optional[str]:
    """Read state from .meta. Returns None if no .meta exists."""
    if not meta_path.exists():
        return None
    content = meta_path.read_text()
    for line in content.splitlines():
        if line.startswith('state:'):
            raw = line.split(':', 1)[1].strip()
            if raw in VALID_STATES:
                return raw
            raise CorruptedState(meta_path, raw)
    return 'active'  # Missing field → legacy migration default
```

Three cases:
- **No `.meta` file** → return `None`. The caller (`transition()`) maps `None → 'idle'` for transition table lookup.
- **`.meta` exists, no `state:` field** (legacy) → return `'active'`. An existing `.meta` without a `state:` field was created by the current system. If `.meta` exists and the branches are aligned, work was in progress — the system was in the `active` state implicitly.
- **`.meta` exists, `state:` has unrecognised value** → raise `CorruptedState`. A truncated or corrupt value (e.g. `closing:pro`) is never silently treated as `active`.

### 10.2 Write Migration

On the first `transition()` call for a legacy `.meta`, the `state:` field is appended. Subsequent calls update it in place.

```python
def write_state(meta_path: Path, state: str) -> None:
    """Write state to .meta. Appends if field missing, updates if present."""
    content = meta_path.read_text()
    lines = content.splitlines()
    
    state_line_idx = None
    for i, line in enumerate(lines):
        if line.startswith('state:'):
            state_line_idx = i
            break
    
    if state_line_idx is not None:
        lines[state_line_idx] = f'state: {state}'
    else:
        # Insert after 'branch:' line for consistent ordering
        for i, line in enumerate(lines):
            if line.startswith('branch:'):
                lines.insert(i + 1, f'state: {state}')
                break
        else:
            lines.append(f'state: {state}')
    
    # Atomic write: write to temp file then rename
    tmp_path = meta_path.parent / '.meta.tmp'
    tmp_path.write_text('\n'.join(lines) + '\n')
    tmp_path.replace(meta_path)  # Atomic on POSIX filesystems
```

This guarantees `.meta` is either fully old or fully new — never partially written. If the process is killed between `write_text()` and `replace()`, only the temp file is corrupted; `.meta` retains its previous content.

### 10.3 No Big-Bang Migration

There is no migration script that rewrites all existing `.meta` files. Migration happens lazily on first touch. This avoids:
- Modifying `.meta` on paused branches (would create a diff)
- Requiring a migration step before the feature can be used
- Breaking concurrent sessions that haven't updated their skills

### 10.4 Paused Branch Migration

Legacy paused branches have `.meta` without a `state:` field. When `work_resume` checks out a paused branch, `read_state()` returns `'active'` (migration default from §10.1). The transition `('active', 'work_resume')` is invalid — the state machine expects `('paused', 'work_resume')`.

The fix is a migration step in the `work_resume` flow, after checkout and before `transition()`. The write is routed through `lifecycle.py`'s `migrate_legacy_paused()` function to preserve the ownership constraint (§11.3: only `lifecycle.py` writes `state:`):

```python
# After checking out the paused branch:
from lifecycle import migrate_legacy_paused

if branch_was_on_pause_stack:
    migrate_legacy_paused(meta_path)  # writes state: paused if field is missing/defaulted
```

`migrate_legacy_paused()` is a `lifecycle.py` public API function (§15.1) that reads the current state, checks if it defaulted to `active` (legacy migration), and writes `state: paused` via the atomic `write_state()` path. This one-time write permanently fixes the `.meta` file. Subsequent `work_resume` calls see `state: paused` directly.

**Why not in `read_state()`:** `read_state()` should be a pure file reader. Adding pause-stack awareness would couple it to routing logic. The migration belongs in the flow that needs it (`work_resume`), not in the generic reader.

---

## 11. `.meta` Format

### 11.1 Current Format (before this change)

```yaml
branch: issue-171-lifecycle-state-machine
date: 2026-08-03
issue: 171
issue-repo: Hortora/soredium
covers: 171
project-sha: abc1234def5678
flyway-next-v: none
design-repo: workspace
design-section-hashes: abc123|def456|ghi789
```

### 11.2 New Format (after this change)

```yaml
branch: issue-171-lifecycle-state-machine
state: active
date: 2026-08-03
issue: 171
issue-repo: Hortora/soredium
covers: 171
project-sha: abc1234def5678
flyway-next-v: none
design-repo: workspace
design-section-hashes: abc123|def456|ghi789
```

One new field: `state`. No other changes to `.meta` format.

### 11.3 State Field Semantics

- Written by `lifecycle.py` only — no other script or skill writes `state:`
- Read by `lifecycle.py`, `ctx.py`, and the pre-push hook
- Values are the state names from Section 1 (lowercase, colon-separated for closing sub-states)
- Missing `state:` field defaults to `active` (legacy migration — §10.1). Present but unrecognised values raise `CorruptedState` (§14.7)

---

## 12. ctx.py Integration

`ctx.py` currently outputs `HAS_META=yes|no`. After this change:

### 12.1 New Output Fields

```
META_STATE=active          # The state: field from .meta (empty if no .meta)
META_IS_TRANSIENT=no       # yes if state is scaffolded or transitioning
```

**Branch alignment ownership change:** ctx.py currently clears the in-memory `meta` dict when `.meta`'s `branch:` field doesn't match the workspace or project branch (lines 109-113). After `lifecycle.py` adoption, this clearing behavior is removed from ctx.py. ctx.py reports the raw facts (`CURRENT_BRANCH`, `META_BRANCH`, `BRANCH_MISMATCH`); `lifecycle.py`'s `validate_state()` owns branch alignment validation as an invariant check (§7.1). Without this change, ctx.py would silently nullify `.meta` data that `lifecycle.py` needs to detect and report the mismatch.

### 12.2 Routing Changes

The `work` router currently calls `work_router.py` which infers state from branch position and file existence. After this change:

The existing `ROUTE` values (`start`, `resume_stack`, `resume_branch`, `workspace_dirty`) are replaced by state-based routing. The complete routing table:

| On main? | `META_STATE` | Stack? | Route |
|----------|-------------|--------|-------|
| yes | empty (idle) | no | → work-start (new branch) |
| yes | empty (idle) | yes | → stack picker (resume or new) |
| yes | any (orphaned `.meta`) | any | → orphan recovery (§9.1) |
| no | empty | any | → workspace_dirty recovery or unscaffolded branch (§5.3) |
| no | `scaffolded` | any | → fire `auto_setup` (T5) |
| no | `transitioning` | any | → fire `auto_refresh` (T7) |
| no | `active` | any | → feature branch lifecycle menu |
| no | `closing:*` | any | → continue close from current gate |

`work_router.py` reads `META_STATE` from ctx.py and applies this table

**Boundary between `lifecycle.py` and `work_router.py`:**

`lifecycle.py` owns the state machine — transitions, validation, state reads/writes. `work_router.py` becomes a context enricher that reads the state and adds non-state-machine context the `work` skill needs for routing:

| Concern | Owner |
|---------|-------|
| State transitions | `lifecycle.py` |
| Branch alignment validation | `lifecycle.py` (§7.1 invariants) |
| State classification (transient, closing, resting) | `lifecycle.py` |
| Stack depth (`.pause-stack`) | `work_router.py` |
| Slot/epic detection (`.slot`, `.epic`) | `work_router.py` |
| Handoff detection (`HANDOFF.md`) | `work_router.py` |
| Workspace dirty detection | `work_router.py` (recovery, not state machine) |

`work_router.py` is modified (not removed) because it retains independent routing logic that sits alongside the state machine.

### 12.3 Session Hook Integration

The `project` skill (session start hook) currently checks CLAUDE.md, workspace, and issue tracking. After this change, it also:

1. Reads `META_STATE` from ctx.py
2. If non-empty (`.meta` exists), routes to `work` router
3. The work router handles all state-based routing

This makes the work lifecycle implicit — every session on a feature branch with `.meta` enters the lifecycle automatically.

---

## 13. Transition Protocol

State transitions use a three-phase protocol. Phase 1 (`transition()`) validates the transition and returns the effects to execute. Phase 2 (effects + `commit_transition()`) executes pre-commit effects, then verifies the state hasn't been modified concurrently, atomically writes the new state, and emits the worklog event. Phase 3 executes post-commit effects — branch switches and cleanup that must run after state is committed.

Post-commit effects exist because some transitions switch branches (T8 `active → paused`, T16 `closing:stamped → idle`). After a branch switch, `.meta` on the original branch becomes inaccessible. State must be written BEFORE the switch so that `commit_transition()` can read and verify `.meta`. Post-commit effects run after state is committed and are tolerant of `.meta` inaccessibility.

```python
def transition(
    meta_path: Path,
    event: str,
    project: Optional[Path] = None,
    workspace: Optional[Path] = None,
) -> TransitionResult:
    """Phase 1: Validate transition and return result. Does NOT write state."""
    raw_state = read_state(meta_path)          # None if no .meta
    current_state = raw_state or 'idle'         # Map None → 'idle'
    
    key = (current_state, event)
    if key not in TRANSITION_TABLE:
        raise InvalidTransition(current_state, event, INVALID_MESSAGES.get(key, f"No transition from '{current_state}' on '{event}'"))
    
    new_state, effects = TRANSITION_TABLE[key]
    
    if project is not None and workspace is not None:
        validate_state(new_state, project, workspace)  # Hygiene check
    
    return TransitionResult(from_state=current_state, new_state=new_state, event=event, effects=effects)


def commit_transition(meta_path: Path, result: TransitionResult) -> None:
    """Phase 2: Verify state unchanged, write atomically, emit worklog.
    
    Three modes:
    - idle→*: verify .meta created by write_meta effect
    - *→idle: verify current state, emit worklog, skip write
      (post-commit return_to_main makes .meta inaccessible)
    - *→*: verify current state, write new state atomically
    """
    if result.from_state == 'idle':
        # idle→* transitions: .meta was created by the write_meta effect.
        current = read_state(meta_path)
        if current != result.new_state:
            raise StateError(f"Expected state '{result.new_state}' after scaffold, got '{current}'")
    else:
        # Re-read state to detect concurrent modification
        current = read_state(meta_path)
        if current != result.from_state:
            raise ConcurrentModification(expected=result.from_state, actual=current)
        if result.new_state != 'idle':
            write_state(meta_path, result.new_state)  # Atomic write (§10.2)
        # *→idle: skip write. .meta stays on the branch with from_state.
        # Post-commit return_to_main makes it inaccessible from main.
    
    worklog_emit(
        branch=read_field(meta_path, 'branch'),
        from_state=result.from_state,
        to_state=result.new_state,
        event=result.event,
        issue=read_field(meta_path, 'issue'),
        timestamp=datetime.utcnow().isoformat(),
    )
```

**Calling protocol:**

```python
# 1. Validate transition — no state written
result = transition(meta_path, event, project=project_path, workspace=workspace_path)

# 2. Execute pre-commit effects (caller owns execution)
for effect in result.effects:
    execute_effect(effect, context)

# 3. Commit — verify and write state atomically
commit_transition(meta_path, result)

# 4. Execute post-commit effects (branch switches, cleanup)
for effect in result.post_commit_effects:
    execute_effect(effect, context)
```

State never advances past completed work. If pre-commit effects fail, state stays at the old value and the next session retries from the correct position. Post-commit effects run after state is committed — if they fail, state reflects completed work but environmental cleanup may be incomplete (e.g. still on feature branch after state is `paused`). Recovery: next session detects the state and re-runs the missing cleanup.

For `idle → *` transitions, `.meta` does not exist yet. The `write_meta` effect creates `.meta` with the target state field. `commit_transition()` verifies that `.meta` was created correctly rather than writing state itself.

### 13.1 Effects Semantics

All effects in `TransitionResult.effects` are **instructions** — actions the caller must execute between `transition()` and `commit_transition()`. The calling skill owns effect execution. `transition()` is a pure validation function with no side effects.

**Unified calling protocol:**

1. For closing sequence events: perform the gate action (code review, artifact promotion, push, merge, stamp)
2. Call `transition(meta_path, event)` — validates, returns `TransitionResult` with effects
3. Execute all effects in `TransitionResult.effects` (pre-commit)
4. Call `commit_transition(meta_path, result)` — verifies state, writes atomically, emits worklog
5. Execute all effects in `TransitionResult.post_commit_effects` (branch switches, cleanup)

This is a single model for all transitions. The closing sequence adds a pre-transition gate action (step 1), but the transition protocol (steps 2–4) is identical for core lifecycle and closing sequence transitions.

**Gate-then-advance pattern (closing sequence):**

| Event | Gate action (before `transition()`) | Pre-commit Effects | Post-commit Effects |
|-------|--------------------------------------|-------------------|-------------------|
| `review_pass` | Code review completes | `['record_review']` | `[]` |
| `promote_pass` | `close_artifacts.py` succeeds | `['write_promotion_stamp']` | `[]` |
| `push_pass` | Squash + push branch succeeds | `[]` | `[]` |
| `merge_pass` | Rebase + push main succeeds | `['verify_content_landed']` | `[]` |
| `stamp_pass` | `verify_stamp.py` passes | `['write_stamp']` | `[]` |
| `cleanup_pass` | Cleanup operations complete | `['write_epic_closed']` | `['return_to_main', 'write_handoff']` |

Gate actions are NOT effects — they happen before `transition()` is called, driven by the work-end skill.

**Pre-transition action for `work_resume`:**

The `work_resume` event follows a similar pre-action pattern. Before firing `work_resume`, the caller checks out the paused branch — making `.meta` accessible so `transition()` can read `state: paused`. The checkout is NOT an effect; it is a pre-transition action. T9's effects (`pop_stack`, `reset_wip`, `context_resume`) execute between `transition()` and `commit_transition()`.

**Effect idempotency:** Every effect MUST be idempotent — guarded by an existence or state check so that re-execution is a no-op. If `commit_transition()` fails after effects execute (e.g. concurrent modification detected), the next session re-runs the same transition — effects must tolerate being executed twice.

**Idempotency guards per effect:**

| Effect | Guard | Re-execution Behavior |
|--------|-------|----------------------|
| `create_branch` | Branch exists? → skip | Prevents "branch already exists" error |
| `write_meta` | `.meta` exists? → skip | Prevents overwriting in-progress `.meta` |
| `write_epic` | `.epic` exists? → skip | Same |
| `write_slot_epic` | `.slot` + `.epic` exist? → skip | Prevents overwriting slot epic |
| `create_slot` | Slot directory exists? → skip | Same |
| `garden_search` | _(inherently idempotent)_ | Re-runs harmlessly |
| `load_specs` | _(inherently idempotent)_ | Re-runs harmlessly |
| `check_protocols` | _(inherently idempotent)_ | Re-runs harmlessly |
| `check_intellij` | _(inherently idempotent)_ | Re-runs harmlessly |
| `advance_issue` | Current issue matches next? → skip | Prevents double-advance |
| `update_meta` | _(overwrites — idempotent)_ | Same data written |
| `tick_github` | Checkbox already ticked? → skip | Prevents skipping an issue |
| `wip_commit` | Working tree clean? → skip | Prevents empty commit error |
| `push_stack` | Entry already in stack? → skip | Prevents duplicate entries |
| `switch_to_main` | Already on main? → no-op | Safe re-execution |
| `pop_stack` | Entry absent from stack? → skip | Prevents underflow |
| `reset_wip` | HEAD is not a WIP commit? → skip | Prevents resetting non-WIP work |
| `context_resume` | _(inherently idempotent)_ | Re-runs harmlessly |
| `write_epic_closed` | File exists? → skip | Prevents duplicate marker |
| `return_to_main` | Already on main? → no-op | Safe re-execution |
| `write_handoff` | _(overwrites — idempotent)_ | Same data written |
| `pre_close_sweep` | _(inherently idempotent)_ | Read-only search, re-runs harmlessly |
| `verify_content_landed` | _(inherently idempotent)_ | Read-only git cat-file check |
| `record_review` | _(overwrites — idempotent)_ | Same data written |
| `write_promotion_stamp` | _(overwrites — idempotent)_ | Same data written |
| `write_stamp` | Stamp commit exists? → skip | Prevents duplicate stamp |
| `clear_closing_markers` | _(inherently idempotent)_ | Re-runs harmlessly |

**Recovery from partial effect failure:** When the first effect succeeds but a subsequent effect fails, state stays at the old value (pre-commit effects never called `commit_transition()`). The next session re-runs `transition()` with the same event. The idempotency guards above ensure the already-completed effects skip cleanly, and execution continues from the failed effect.

### 13.2 Mapping to Worklog Events (#158)

| Worklog Event | State Transition |
|--------------|-----------------|
| `work-start` | `scaffolded → active` (T5) |
| `work-end` | `closing:stamped → idle` (T16) |
| `work-pause` | `active → paused` (T8) |
| `work-resume` | `paused → active` (T9) |
| `issue-activate` | `transitioning → active` (T7) — new issue context |
| `issue-complete` | `active → transitioning` (T6) — outgoing issue |

These six events are intentionally scoped to user-visible lifecycle boundaries. Internal transitions (T1–T4 branch creation, T10 close initiation, T11–T15 closing sub-gates) are not worklog events — they represent intermediate state machine steps within a single user-initiated action. The worklog tracks what the user did (started, ended, paused, resumed, advanced), not what the state machine did internally to get there.

### 13.3 Graceful Degradation

If the worklog DB is unavailable (not configured, permissions error), `worklog_emit()` warns once and continues. Worklog emission is observability — it never blocks a transition.

### 13.4 Loss Window and Authoritative History

Worklog emission happens in `commit_transition()` — after state is written. If the process crashes between the state write and the `worklog_emit()` call, the worklog event is permanently lost. Additionally, if the worklog DB is unavailable for an entire session, all events for that session are lost.

This is accepted by design. The worklog is **best-effort observability**, not an authoritative record. A write-ahead log pattern (pending → committed events) would add significant complexity (pending/committed markers, recovery replay, cleanup) for a single-developer CLI tool.

For authoritative state history, `git log` on `.meta` changes is the canonical source — every `commit_transition()` is followed by a git commit that records the state change. `git log --follow -- design/.meta` provides a complete, tamper-evident timeline of all lifecycle transitions.

---

## 14. Edge Cases

### 14.1 Two-Repo Naming Inversion (GE-20260714-2b8973)

In two-repo casehub projects, ctx.py's `WORKSPACE` and `PROJECT` names invert relative to CLAUDE.md's semantic roles. The state machine uses ctx.py's naming consistently — `.meta` is always at `$WORKSPACE/design/.meta` where `$WORKSPACE` is ctx.py's output, regardless of CLAUDE.md terminology.

### 14.2 Cherry-Pick Conflicts from Session Wrap (GE-20260605-1f6896)

The closing sub-states prevent this: artifacts are workspace-promoted and project-promoted during `closing:verified → closing:promoted` (Step 8a), which commits to workspace main and the project repo respectively. The merge (Step 8j / `closing:promoted → closing:merged`) only touches the project branch. No cherry-pick is used — the rebase operates on the project branch. Artifacts and code live in separate repos and never conflict.

In single-repo mode, the filter-repo preprocessing (Step 8j) strips scaffold paths before rebase, preventing scaffold-artifact conflicts.

### 14.3 Concurrent Sessions on Same Branch

Not modelled as a state machine concern. The state machine is single-writer — only one session should work a branch at a time. The two-phase protocol (§13) detects concurrent modification: `commit_transition()` re-reads the state before writing. If another session changed it between `transition()` and `commit_transition()`, a `ConcurrentModification` exception is raised with the expected and actual state values. This narrows the race window to sub-millisecond (between the re-read and the atomic `os.replace()` in `commit_transition()`).

### 14.4 Manual `git checkout` While in `closing:*`

If the user manually checks out a different branch while the close sequence is in progress:
- Branch alignment invariant fails on the next transition
- Transition is rejected with "Branch mismatch"
- User must re-checkout the closing branch to continue

### 14.5 `.meta` Deleted Manually

If `.meta` is deleted while in any state:
- `read_state()` returns `None` (no `.meta`)
- Next session sees `idle` state
- Any in-progress close is lost — branch is in limbo
- Hygiene: if the branch still exists, the next session's `work` command will detect State 6 (on non-main branch, no `.meta`) and offer to continue or return to main

### 14.6 Force Push That Rewrites History

If someone force-pushes to the branch, rewriting commits:
- The state machine doesn't track commit SHAs (except `project-sha` baseline)
- State is unaffected — it tracks lifecycle position, not code state
- The squash step in work-end will operate on whatever commits exist

### 14.7 `.meta` State Field Has Unknown Value

```python
def read_state(meta_path: Path) -> Optional[str]:
    if not meta_path.exists():
        return None
    content = meta_path.read_text()
    for line in content.splitlines():
        if line.startswith('state:'):
            raw = line.split(':', 1)[1].strip()
            if raw in VALID_STATES:
                return raw
            raise CorruptedState(meta_path, raw)
    return 'active'  # Missing field → legacy migration default
```

This distinguishes two cases:
- **Missing `state:` field** (legacy `.meta`) → return `'active'` (migration default)
- **Present but unrecognised value** (e.g. `state: closing:pro`) → raise `CorruptedState` with actionable message: "Unknown state 'closing:pro' in .meta — file may be corrupted. Run `read_state()` returned raw value; verify .meta manually."

A truncated or corrupt value is never silently treated as `active`. This is the internal validation within `read_state()` (§15.1) — it applies when `.meta` exists and has a `state:` field with an unrecognized value.

---

## 15. Module API

### 15.1 `lifecycle.py` — Public API

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

VALID_STATES = frozenset({
    'idle', 'scaffolded', 'active', 'transitioning', 'paused',
    'closing:review', 'closing:verified', 'closing:promoted',
    'closing:pushed', 'closing:merged', 'closing:stamped',
})

TRANSIENT_STATES = frozenset({'scaffolded', 'transitioning'})

CLOSING_STATES = frozenset({
    'closing:review', 'closing:verified', 'closing:promoted',
    'closing:pushed', 'closing:merged', 'closing:stamped',
})

RESTING_STATES = frozenset({
    'idle', 'active', 'paused',
    'closing:review', 'closing:verified', 'closing:promoted',
    'closing:pushed', 'closing:merged', 'closing:stamped',
})

@dataclass
class TransitionResult:
    from_state: str
    new_state: str
    event: str
    effects: list[str]           # Pre-commit: run between transition() and commit_transition()
    post_commit_effects: list[str]  # Post-commit: run after commit_transition() (branch switches, cleanup)

class InvalidTransition(Exception):
    def __init__(self, from_state: str, event: str, message: str):
        self.from_state = from_state
        self.event = event
        super().__init__(message)

class InvalidState(Exception):
    def __init__(self, state: str, violations: list[str]):
        self.state = state
        self.violations = violations
        super().__init__(f"State '{state}' invariant violations: {violations}")

class ConcurrentModification(Exception):
    def __init__(self, expected: str, actual: str):
        self.expected = expected
        self.actual = actual
        super().__init__(f"State changed by another session: expected '{expected}', found '{actual}'")

class CorruptedState(Exception):
    def __init__(self, meta_path: Path, raw_value: str):
        self.meta_path = meta_path
        self.raw_value = raw_value
        super().__init__(f"Unknown state '{raw_value}' in {meta_path} — file may be corrupted. Verify .meta manually.")

def read_state(meta_path: Path) -> Optional[str]:
    """Read lifecycle state from .meta. Returns None if no .meta exists.
    Raises CorruptedState if state: field has unrecognised value."""

def write_state(meta_path: Path, state: str) -> None:
    """Write lifecycle state to existing .meta atomically (§10.2). Raises if .meta doesn't exist."""

def transition(
    meta_path: Path,
    event: str,
    project: Optional[Path] = None,
    workspace: Optional[Path] = None,
) -> TransitionResult:
    """Phase 1: Validate transition and return result. Does NOT write state.
    
    Calling protocol:
    - read_state() returns None when .meta is absent. transition() maps None → 'idle'
      internally for transition table lookup.
    - transition() validates invariants but does NOT write state or emit worklog.
    - The caller executes effects, then calls commit_transition() to write state.
    """

def commit_transition(meta_path: Path, result: TransitionResult) -> None:
    """Phase 2: Verify state unchanged, write atomically, emit worklog.
    
    For idle→* transitions: verifies .meta was created by the write_meta effect.
    For all other transitions: re-reads state, compares to result.from_state,
    raises ConcurrentModification if changed, writes new state via atomic rename.
    """

def validate_state(
    state: str,
    project: Path,
    workspace: Path,
    exclude_patterns: Optional[list[str]] = None,
) -> list[str]:
    """Check hygiene invariants. Returns list of violations (empty = clean)."""

def is_transient(state: str) -> bool:
    """True if the state auto-resolves (scaffolded, transitioning)."""

def is_closing(state: str) -> bool:
    """True if in the closing sequence."""

def can_transition(from_state: str, event: str) -> bool:
    """Check if a transition is valid without executing it."""

def migrate_legacy_paused(meta_path: Path) -> bool:
    """Migrate legacy paused branch .meta: write state: paused if field missing/defaulted.
    Called by work_resume flow after checkout, before transition().
    Returns True if migration was performed, False if already migrated."""
```

### 15.2 Transition Table as Data

```python
# (from_state, event): (new_state, effects, post_commit_effects)
# effects run before commit_transition(); post_commit_effects run after.
TRANSITION_TABLE: dict[tuple[str, str], tuple[str, list[str], list[str]]] = {
    # Core lifecycle
    ('idle', 'work'):              ('scaffolded',        ['create_branch', 'write_meta'],                           []),
    ('idle', 'work_epic'):         ('scaffolded',        ['create_branch', 'write_meta', 'write_epic'],             []),
    ('idle', 'slot_create'):       ('scaffolded',        ['create_slot', 'write_meta'],                             []),
    ('idle', 'slot_epic'):         ('scaffolded',        ['create_slot', 'write_meta', 'write_slot_epic'],          []),
    ('scaffolded', 'auto_setup'):  ('active',            ['garden_search', 'load_specs', 'check_protocols', 'check_intellij'], []),
    ('active', 'work_next'):       ('transitioning',     ['advance_issue', 'update_meta', 'tick_github'],           []),
    ('transitioning', 'auto_refresh'): ('active',        ['garden_search', 'load_specs', 'check_protocols'],        []),
    ('active', 'work_pause'):      ('paused',            ['wip_commit'],                                            ['switch_to_main', 'push_stack']),
    ('paused', 'work_resume'):     ('active',            ['pop_stack', 'reset_wip', 'context_resume'],              []),
    
    # Closing sequence
    ('active', 'work_end'):        ('closing:review',    ['pre_close_sweep'],                                       []),
    ('closing:review', 'review_pass'):    ('closing:verified',  ['record_review'],                                  []),
    ('closing:verified', 'promote_pass'): ('closing:promoted',  ['write_promotion_stamp'],                          []),
    ('closing:promoted', 'push_pass'):    ('closing:pushed',    [],                                                 []),
    ('closing:pushed', 'merge_pass'):     ('closing:merged',    ['verify_content_landed'],                          []),
    ('closing:merged', 'stamp_pass'):     ('closing:stamped',   ['write_stamp'],                                    []),
    ('closing:stamped', 'cleanup_pass'):  ('idle',              ['write_epic_closed'],                               ['return_to_main', 'write_handoff']),
    
    # Abort (pre-artifact states only — post workspace/project promotion is forward-only)
    ('closing:review', 'abort_close'):    ('active', ['clear_closing_markers'],                                     []),
    ('closing:verified', 'abort_close'):  ('active', ['clear_closing_markers'],                                     []),
}
```

---

## 16. TDD Test Cases

### 16.1 Transition Table Tests

```python
import pytest
from lifecycle import (
    transition, commit_transition, read_state, write_state,
    InvalidTransition, InvalidState, ConcurrentModification, CorruptedState,
)

class TestValidTransitions:
    """Every row in the transition table produces the expected state and effects."""
    
    @pytest.mark.parametrize("from_state, event, expected_state, expected_effects", [
        ("idle",                "work",          "scaffolded",        ["create_branch", "write_meta"]),
        ("idle",                "work_epic",     "scaffolded",        ["create_branch", "write_meta", "write_epic"]),
        ("idle",                "slot_create",   "scaffolded",        ["create_slot", "write_meta"]),
        ("idle",                "slot_epic",     "scaffolded",        ["create_slot", "write_meta", "write_slot_epic"]),
        ("scaffolded",          "auto_setup",    "active",            ["garden_search", "load_specs", "check_protocols", "check_intellij"]),
        ("active",              "work_next",     "transitioning",     ["advance_issue", "update_meta", "tick_github"]),
        ("transitioning",       "auto_refresh",  "active",            ["garden_search", "load_specs", "check_protocols"]),
        ("active",              "work_pause",    "paused",            ["wip_commit"]),
        ("paused",              "work_resume",   "active",            ["pop_stack", "reset_wip", "context_resume"]),
        ("active",              "work_end",      "closing:review",    ["pre_close_sweep"]),
        ("closing:review",      "review_pass",   "closing:verified",  ["record_review"]),
        ("closing:verified",    "promote_pass",  "closing:promoted",  ["write_promotion_stamp"]),
        ("closing:promoted",    "push_pass",     "closing:pushed",    []),
        ("closing:pushed",      "merge_pass",    "closing:merged",    ["verify_content_landed"]),
        ("closing:merged",      "stamp_pass",    "closing:stamped",   ["write_stamp"]),
        ("closing:stamped",     "cleanup_pass",  "idle",              ["write_epic_closed"]),
    ])
    def test_valid_transition(self, from_state, event, expected_state, expected_effects, tmp_meta):
        write_state(tmp_meta, from_state)
        result = transition(tmp_meta, event)  # No project/workspace → validation skipped
        assert result.from_state == from_state
        assert result.new_state == expected_state
        assert result.effects == expected_effects
        assert read_state(tmp_meta) == from_state  # Phase 1 does NOT write state

    @pytest.mark.parametrize("closing_state", [
        "closing:review", "closing:verified",
    ])
    def test_abort_from_pre_artifact_closing_state(self, closing_state, tmp_meta):
        write_state(tmp_meta, closing_state)
        result = transition(tmp_meta, "abort_close")
        assert result.new_state == "active"
    
    @pytest.mark.parametrize("closing_state", [
        "closing:promoted", "closing:pushed", "closing:merged", "closing:stamped",
    ])
    def test_abort_blocked_from_post_artifact_closing_state(self, closing_state, tmp_meta):
        write_state(tmp_meta, closing_state)
        with pytest.raises(InvalidTransition):
            transition(tmp_meta, "abort_close")
```

### 16.2 Invalid Transition Tests

```python
class TestInvalidTransitions:
    """Every invalid (state, event) pair raises InvalidTransition."""
    
    @pytest.mark.parametrize("from_state, event", [
        ("idle",          "work_next"),
        ("idle",          "work_pause"),
        ("idle",          "work_end"),
        ("idle",          "work_resume"),
        ("scaffolded",    "work_next"),
        ("scaffolded",    "work_end"),
        ("scaffolded",    "work_pause"),
        ("active",        "work"),
        ("active",        "work_epic"),
        ("active",        "work_resume"),
        ("active",        "auto_setup"),
        ("transitioning", "work_end"),
        ("transitioning", "work_pause"),
        ("paused",        "work_end"),
        ("paused",        "work_next"),
        ("paused",        "work_pause"),
        ("closing:review",   "work_pause"),
        ("closing:review",   "work_next"),
        ("closing:review",   "work"),
        ("closing:review",   "work_epic"),
        ("closing:verified", "review_pass"),
        ("closing:promoted", "promote_pass"),
        ("closing:pushed",    "push_pass"),
    ])
    def test_invalid_transition_raises(self, from_state, event, tmp_meta):
        write_state(tmp_meta, from_state)
        with pytest.raises(InvalidTransition):
            transition(tmp_meta, event)
```

### 16.3 Migration Tests

```python
class TestMigration:
    """Legacy .meta files without state: field work correctly."""
    
    def test_missing_state_defaults_to_active(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\ndate: 2026-08-03\nissue: 42\n")
        assert read_state(meta) == "active"
    
    def test_unknown_state_raises_corrupted(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\nstate: bogus\ndate: 2026-08-03\n")
        with pytest.raises(CorruptedState):
            read_state(meta)
    
    def test_write_state_appends_to_legacy_meta(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\ndate: 2026-08-03\n")
        write_state(meta, "closing:review")
        content = meta.read_text()
        assert "state: closing:review" in content
        assert content.index("branch:") < content.index("state:")
    
    def test_write_state_updates_existing_field(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\nstate: active\ndate: 2026-08-03\n")
        write_state(meta, "closing:review")
        assert read_state(meta) == "closing:review"
        assert meta.read_text().count("state:") == 1
    
    def test_no_meta_returns_none(self, tmp_path):
        meta = tmp_path / ".meta"
        assert read_state(meta) is None
```

### 16.4 Hygiene Invariant Tests

```python
class TestHygieneInvariants:
    """Invariant violations block transitions."""
    
    def test_untracked_files_block_transition(self, tmp_project_with_untracked):
        meta, project, workspace = tmp_project_with_untracked
        write_state(meta, "active")
        with pytest.raises(InvalidState, match="Untracked files"):
            transition(meta, "work_end", project=project, workspace=workspace)
    
    def test_excluded_untracked_files_allowed(self, tmp_project_with_idea_dir):
        meta, project, workspace = tmp_project_with_idea_dir
        write_state(meta, "active")
        # .idea/ is in exclude list — should not block
        result = transition(meta, "work_end", project=project, workspace=workspace)
        assert result.new_state == "closing:review"
    
    def test_branch_mismatch_blocks_transition(self, tmp_project_wrong_branch):
        meta, project, workspace = tmp_project_wrong_branch
        write_state(meta, "active")
        with pytest.raises(InvalidState, match="Branch mismatch"):
            transition(meta, "work_end", project=project, workspace=workspace)
    
    def test_uncommitted_changes_block_close(self, tmp_project_with_dirty_tree):
        meta, project, workspace = tmp_project_with_dirty_tree
        write_state(meta, "active")
        with pytest.raises(InvalidState, match="Uncommitted changes"):
            transition(meta, "work_end", project=project, workspace=workspace)
    
    def test_no_paths_skips_validation(self, tmp_project_with_untracked):
        meta, project, workspace = tmp_project_with_untracked
        write_state(meta, "active")
        # Omitting project/workspace skips hygiene validation
        result = transition(meta, "work_end")
        assert result.new_state == "closing:review"
```

### 16.5 State Query Tests

```python
class TestStateQueries:
    """Helper functions for state classification."""
    
    @pytest.mark.parametrize("state, expected", [
        ("scaffolded", True),
        ("transitioning", True),
        ("active", False),
        ("paused", False),
        ("closing:review", False),
        ("idle", False),
    ])
    def test_is_transient(self, state, expected):
        assert is_transient(state) == expected
    
    @pytest.mark.parametrize("state, expected", [
        ("closing:review", True),
        ("closing:verified", True),
        ("closing:promoted", True),
        ("closing:pushed", True),
        ("closing:merged", True),
        ("closing:stamped", True),
        ("active", False),
        ("idle", False),
    ])
    def test_is_closing(self, state, expected):
        assert is_closing(state) == expected
    
    def test_can_transition_valid(self):
        assert can_transition("active", "work_end") is True
    
    def test_can_transition_invalid(self):
        assert can_transition("idle", "work_next") is False
```

### 16.6 Pre-Push Hook Tests

```python
class TestPrePushHook:
    """Hook blocks pushes to main when state gates are not satisfied."""
    
    @pytest.mark.parametrize("state, push_to_main, should_block", [
        ("active",              True,  True),
        ("scaffolded",          True,  True),
        ("closing:review",      True,  True),
        ("closing:verified",    True,  True),
        ("closing:promoted",    True,  True),
        ("closing:pushed",      True,  False),
        ("closing:merged",      True,  False),
        ("closing:stamped",     True,  False),
        ("active",              False, False),  # feature branch push
        ("closing:review",      False, False),  # feature branch push
        ("closing:pushed",      False, False),  # feature branch push
    ])
    def test_hook_enforcement(self, state, push_to_main, should_block, tmp_meta):
        write_state(tmp_meta, state)
        result = hook_check(tmp_meta, push_to_main=push_to_main)
        assert result.blocked == should_block
    
    def test_no_meta_allows_push(self, tmp_path):
        meta = tmp_path / ".meta"  # does not exist
        result = hook_check(meta, push_to_main=True)
        assert result.blocked is False
```

### 16.7 Stale State Recovery Tests

```python
class TestStaleStateRecovery:
    """Sessions that find non-resting states recover correctly."""
    
    def test_scaffolded_auto_resolves(self, tmp_meta):
        write_state(tmp_meta, "scaffolded")
        # Simulates session_start finding scaffolded state
        result = transition(tmp_meta, "auto_setup")
        assert result.new_state == "active"
    
    def test_transitioning_auto_resolves(self, tmp_meta):
        write_state(tmp_meta, "transitioning")
        result = transition(tmp_meta, "auto_refresh")
        assert result.new_state == "active"
    
    def test_orphaned_meta_on_main_detected(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\nstate: active\n")
        # Current branch is main, not issue-42-foo
        violations = validate_state("active", project=tmp_path, workspace=tmp_path)
        assert any("Branch mismatch" in v for v in violations)
```

### 16.8 Commit Transition Tests

```python
class TestCommitTransition:
    """Phase 2: commit_transition verifies state, writes atomically, emits worklog."""
    
    def test_commit_writes_new_state(self, tmp_meta):
        write_state(tmp_meta, "active")
        result = transition(tmp_meta, "work_end")
        commit_transition(tmp_meta, result)
        assert read_state(tmp_meta) == "closing:review"
    
    def test_commit_detects_concurrent_modification(self, tmp_meta):
        write_state(tmp_meta, "active")
        result = transition(tmp_meta, "work_end")
        # Simulate another session changing state between transition() and commit()
        write_state(tmp_meta, "paused")
        with pytest.raises(ConcurrentModification):
            commit_transition(tmp_meta, result)
    
    def test_commit_idle_to_scaffolded_verifies_meta_created(self, tmp_path):
        meta = tmp_path / ".meta"
        result = transition(meta, "work")
        # Simulate write_meta effect creating .meta with target state
        meta.write_text("branch: issue-1-test\nstate: scaffolded\ndate: 2026-08-03\n")
        commit_transition(meta, result)
        assert read_state(meta) == "scaffolded"
    
    def test_commit_idle_to_scaffolded_fails_if_meta_not_created(self, tmp_path):
        meta = tmp_path / ".meta"
        result = transition(meta, "work")
        # write_meta effect didn't run — .meta not created
        with pytest.raises(StateError):
            commit_transition(meta, result)
    
    def test_commit_to_idle_skips_write(self, tmp_meta):
        write_state(tmp_meta, "closing:stamped")
        result = transition(tmp_meta, "cleanup_pass")
        commit_transition(tmp_meta, result)
        # .meta still has from_state — write was skipped.
        # The return_to_main post-commit effect makes .meta inaccessible.
        assert read_state(tmp_meta) == "closing:stamped"
    
    def test_commit_to_idle_still_checks_concurrent_modification(self, tmp_meta):
        write_state(tmp_meta, "closing:stamped")
        result = transition(tmp_meta, "cleanup_pass")
        write_state(tmp_meta, "closing:merged")  # Another session rolled back
        with pytest.raises(ConcurrentModification):
            commit_transition(tmp_meta, result)
    
    def test_post_commit_effects_populated_for_branch_switching_transitions(self, tmp_meta):
        write_state(tmp_meta, "active")
        result = transition(tmp_meta, "work_pause")
        assert result.effects == ["wip_commit"]
        assert result.post_commit_effects == ["switch_to_main", "push_stack"]
    
    def test_post_commit_effects_empty_for_standard_transitions(self, tmp_meta):
        write_state(tmp_meta, "active")
        result = transition(tmp_meta, "work_end")
        assert result.post_commit_effects == []
```

---

## 17. File Inventory

| File | Purpose | New/Modified |
|------|---------|-------------|
| `lifecycle.py` | State machine core — transitions, validation, read/write | **New** |
| `test_lifecycle.py` | Tests for lifecycle.py | **New** |
| `ctx.py` | Add `META_STATE` and `META_IS_TRANSIENT` output fields | Modified |
| `work_router.py` | Read state from ctx.py instead of inferring | Modified |
| `scaffold.py` | Write `state: scaffolded` on creation | Modified |
| `work-start/SKILL.md` | Replace 6-state detection with state reads | Modified |
| `work-end/SKILL.md` | Replace preconditions with state transitions | Modified |
| `work-pause/SKILL.md` | Add `transition(active, work_pause)` call | Modified |
| `work-resume/SKILL.md` | Add `transition(paused, work_resume)` call | Modified |
| `work/SKILL.md` | Route based on state, not inference | Modified |
| `work-slot/SKILL.md` | Write `state: scaffolded` on slot creation | Modified |
| `project/SKILL.md` | Route to work lifecycle when `.meta` exists | Modified |
| `.git/hooks/pre-push` | Hook script reading state | **New** |

---

## 18. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `.meta` state field gets corrupted | Lifecycle stalls | Unknown values raise `CorruptedState` with actionable error (§14.7). Missing field defaults to `active` for legacy migration (§10.1) |
| Hook blocks legitimate pushes | Developer friction | Hook allows all feature-branch pushes; only blocks main pushes |
| Transient states never resolve (bug in auto-resolve) | Branch stuck in `scaffolded` forever | Next session re-attempts auto-resolve; hard timeout after 3 failed attempts |
| Single-repo mode has different `.meta` location | State reads fail | ctx.py already handles single-repo — `META_STATE` output adapts |
| Worklog DB unavailable | Events lost | Graceful degradation — warn, don't block (Section 13.3) |
| Concurrent sessions race on `.meta` | Corrupted state | `commit_transition()` re-reads before writing; raises `ConcurrentModification` if state changed (§14.3) |

---

## 19. Implementation Order

Matches the epic child issues (#172–#178):

1. **#172 — lifecycle.py** — transition table, read/write, validate_state. Pure Python, no skill changes. Tests: Sections 16.1–16.5.
2. **#173 — Wire into skills** — Replace work-start detection and work-end preconditions with state reads. ctx.py and work_router.py changes.
3. **#174 — Implicit work-start** — Epic setup chains via `scaffolded`. Session hook routes to work lifecycle. Slot messaging fix.
4. **#175 — Context refresh** — `work next` / `work-slot next` via `transitioning` state. Extract context refresh subroutine.
5. **#176 — Pre-push hook** — Hook script. Tests: Section 16.6.
6. **#177 — Hygiene invariants** — Untracked files, branch alignment, clean tree checks. Tests: Section 16.4.
7. **#178 — Worklog emission** — Wire `worklog_emit()` into `transition()`. Depends on #158.

Each step is independently deployable and testable. No step requires a later step to be useful.

---

## Appendix A: State Diagram

```
                    ┌──────────────────────────────────────────────┐
                    │                                              │
                    ▼                                              │
                 ┌──────┐  work / work_epic    ┌─────────────┐    │
                 │ idle │ ──────────────────── │ scaffolded  │    │
                 └──────┘  slot_create/epic    └──────┬──────┘    │
                    ▲                          auto   │           │
                    │                          setup  │           │
                    │                                 ▼           │
                    │                          ┌─────────────┐    │
                    │             ┌──────────  │   active    │ ◄──┤
                    │             │            └──────┬──────┘    │
                    │             │     work_end │    │ work_next │ abort
                    │             │             ▼    │           │ _close
                    │        work_pause  ┌──────────┐│  ┌───────────────┐
                    │             │      │ closing: │├──│ transitioning │
                    │             │      │ review   ││  └───────┬───────┘
                    │             ▼      └────┬─────┘│    auto  │
                    │       ┌────────┐        │      │  refresh │
                    │       │ paused │        ▼      │          │
                    │       └────┬───┘  ┌──────────┐ │          │
                    │            │      │ closing: ├─┘          │
                    │       work_resume │ verified │ abort_close │
                    │            │      └────┬─────┘            │
                    │            │           │                  │
                    │            └───────────┘                  │
                    │                        │                  │
                    │              promote   │                  │
                    │              _pass     ▼                  │
                    │                  ┌──────────┐             │
                    │                  │ closing: │             │
                    │                  │ promoted │  (forward   │
                    │                  └────┬─────┘   only)     │
                    │              push     │                   │
                    │              _pass    ▼                   │
                    │                  ┌──────────┐             │
                    │                  │ closing: │             │
                    │                  │ pushed   │             │
                    │                  └────┬─────┘             │
                    │              merge    │                   │
                    │              _pass    ▼                   │
                    │                  ┌──────────┐             │
                    │                  │ closing: │             │
                    │                  │ merged   │             │
                    │                  └────┬─────┘             │
                    │                       │                   │
                    │                       ▼                   │
                    │                  ┌──────────┐             │
                    │                  │ closing: │             │
                    │   cleanup_pass   │ stamped  │             │
                    └──────────────────┴──────────┘             │
```
