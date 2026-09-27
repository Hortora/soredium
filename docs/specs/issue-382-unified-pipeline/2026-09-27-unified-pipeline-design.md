# Unified Mechanical Pipeline — Design Spec

**Issue:** #382
**Branch:** issue-382-unified-pipeline
**Date:** 2026-09-27

## Problem

The work lifecycle is orchestrated by the LLM reading SKILL.md files and making
routing decisions. This creates three categories of failure that block autonomous
operation:

1. **State corruption from unvalidated writes.** `commit_transition()` validates
   state, but `plan_manager.py set-state`, `elevate_plan_inline`, and direct
   `write_field` calls bypass validation. Invalid states like `closing:landed`
   get written and persist.

2. **State loss from uncommitted changes.** `commit_transition()` writes state
   to disk but doesn't commit to git. Any git operation (checkout, rebase, merge,
   strip) discards the uncommitted change. The working tree reverts to the last
   committed `.plan`, causing state/meta_state mismatch → progress wipe → infinite loop.

3. **Manual recovery for deterministic situations.** The system diagnoses
   "all issues CLOSED, merge landed, cleanup didn't complete" but then asks the
   user what to do instead of recovering automatically.

## Solution Overview

Five subsystems, each independently valuable, collectively sufficient for
autonomous operation:

| Subsystem | What it fixes |
|-----------|--------------|
| A. State hardening | Corruption from unvalidated writes + state loss from uncommitted changes |
| B. Sync operation | No way to land work without closing the branch |
| C. Continuation pattern | Context loss when preparing next-session artifacts |
| D. Auto-recovery | Manual intervention for deterministic situations |
| E. Pipeline engine | LLM-as-orchestrator → LLM-as-service |

---

## A. State Hardening

### A1. Commit state changes to git

Every `commit_transition()` call also commits `.plan` to the workspace branch:

```python
def commit_transition(plan_path, result, ...):
    # ... existing validation, evidence gating ...
    write_state(plan_path, result.new_state)

    # NEW: commit to git
    workspace = plan_path.parent
    rel = plan_path.relative_to(workspace)
    subprocess.run(
        ["git", "-C", str(workspace), "add", str(rel)],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-m",
         f"chore: lifecycle {result.from_state} → {result.new_state}"],
        capture_output=True,
    )

    # ... existing worklog emission ...
```

**Why this works:** The state change is now part of the branch's commit history.
Rebase replays commits (including state commits). Merge preserves them. Checkout
can't lose them. `git log .plan` shows every transition for auditing.

**Assumption:** The git index is clean when `commit_transition` runs. In practice,
lifecycle transitions happen during the orchestrator's mechanical loop, which
doesn't leave staged files. If stray files are staged, they'll be included in the
commit — acceptable trade-off vs. complexity of a temporary index.

### A2. Remove .plan from LIFECYCLE_FILES strip list

Currently `.plan` is in `land_flow.LIFECYCLE_FILES` and gets stripped from the
workspace branch before merge. This destroys state for post-land lifecycle
transitions.

**Change:** Remove `.plan` from `LIFECYCLE_FILES`. The `.plan` file:
- Stays on the feature branch permanently (auditable lifecycle history)
- Reaches main temporarily during merge
- Gets removed from main by the cleanup step

**Cleanup step change:** Add `.plan` to the cleanup removal list in
`branch_cleanup.py` `cleanup-scaffold` command:

```python
scaffold_files = [
    "JOURNAL.md", ".execute-progress", ".land-ledger.jsonl",
    ".artifacts-promoted", ".plan",  # <-- add
]
```

### A3. One gate for state writes

Close all bypass paths:

| Bypass | Fix |
|--------|-----|
| `plan_manager.py set-state` | Remove the command. State is pipeline-managed. |
| `elevate_plan_inline` (line 517) | Add `(closing:stamped, elevate)` → `active` to TRANSITION_TABLE. Call `commit_transition` instead of string replacement. |
| `lifecycle.py` line 625 (migrate) | Route through `commit_transition` with a `migrate_pause` event. |
| `write_field` (plan_io.py) | Add validation: if field is `state`, reject values not in VALID_STATES. |

**write_field safety net:**

```python
def write_field(plan_path: Path, field_name: str, value: str) -> None:
    if field_name == "state":
        from lifecycle import VALID_STATES
        if value not in VALID_STATES:
            raise ValueError(f"Invalid state '{value}'. Valid: {sorted(VALID_STATES)}")
    write_fields(plan_path, {field_name: value})
```

### A4. New transition table entries

```python
TRANSITION_TABLE.update({
    # Sync (land without closing)
    ('active', 'work_sync'):              ('closing:review',    ['pre_close_sweep'],              []),
    ('closing:stamped', 'sync_pass'):     ('active',            ['promote_plan_next', 'clear_closing_markers'], []),

    # Elevate (slot plan promotion)
    ('closing:stamped', 'elevate'):       ('active',            ['elevate_plan_to_slot'],          []),

    # Migrate
    ('idle', 'migrate_pause'):            ('paused',            [],                                []),
})
```

---

## B. Sync Operation

### B1. `work sync` command

New lifecycle command: land completed work without closing the branch.

```
python3 work.py sync
```

**Pipeline:** Shares all steps with `work end` up to and including the landing
phase. Diverges at the terminal phase:

```
Shared:  review → promote → rebase → squash → land → close-issues → verify
Sync:    → sync_pass (closing:stamped → active) → promote-plan-next
End:     → stamp_pass → cleanup_pass → stamp-branch → archive → checkout-main
```

### B2. Sync lifecycle transitions

```
active ──work_sync──→ closing:review ──(same close sequence)──→ closing:stamped
closing:stamped ──sync_pass──→ active
```

After `sync_pass`:
- State resets to `active`
- `.plan-next` promoted to `.plan` (if exists)
- `HANDOFF-next` promoted to `HANDOFF.md` (if exists)
- `.close-progress` deleted
- Branch stays open, slot stays active

### B3. Sync vs End — orchestrator routing

The orchestrator needs to know whether this is a sync or end. Pass `mode=sync`
or `mode=end` to the orchestrator:

```python
# In STEPS, terminal steps have skip predicates based on mode
StepDef("sync_pass", "closing:stamped", "lifecycle",
        skip_fn=_skip_not_sync_mode,
        from_state="closing:stamped", to_state="active", event="sync_pass"),
StepDef("stamp_pass", "closing:merged", "lifecycle",
        skip_fn=_or_skip(_skip_cycle_mode, _skip_sync_mode),
        from_state="closing:merged", to_state="closing:stamped", event="stamp_pass"),
```

---

## C. Continuation Pattern (.plan-next / HANDOFF-next)

### C1. Build before ceremony

Before running sync or end, the pipeline builds continuation artifacts:

1. **`.plan-next`** — next issue queue. Built by:
   - `plan_manager.py build-next` — reads the current `.plan`, identifies
     uncompleted issues, builds a fresh queue
   - Or: the LLM drafts it during brainstorming/planning (judgment step)

2. **`HANDOFF-next`** — continuation context. Built by:
   - Copying `HANDOFF.md` and revising it for the new queue (LLM judgment)
   - Or: writing from scratch if the work direction changed

These files are committed to the branch before the ceremony starts. They
survive ceremony failures because they're committed, not working-tree-only.

### C2. Promote as a pipeline step

After sync_pass (or cleanup_pass in end mode), the pipeline promotes:

```python
def _promote_plan_next(ctx):
    plan_next = ctx.workspace / ".plan-next"
    plan = ctx.workspace / ".plan"
    if plan_next.exists():
        shutil.copy2(plan_next, plan)
        plan_next.unlink()
        # Write active state to the promoted .plan
        write_state(plan, "active")
        # Commit
        _git(ctx.workspace, "add", ".plan")
        _git(ctx.workspace, "rm", "--ignore-unmatch", ".plan-next")
        _git(ctx.workspace, "commit", "-m",
             "chore: promote .plan-next to .plan")
    # Same for HANDOFF-next → HANDOFF.md
    handoff_next = ctx.workspace / "HANDOFF-next.md"
    handoff = ctx.workspace / "HANDOFF.md"
    if handoff_next.exists():
        shutil.copy2(handoff_next, handoff)
        handoff_next.unlink()
        _git(ctx.workspace, "add", "HANDOFF.md")
        _git(ctx.workspace, "rm", "--ignore-unmatch", "HANDOFF-next.md")
        _git(ctx.workspace, "commit", "-m",
             "chore: promote HANDOFF-next to HANDOFF.md")
```

**Postcondition:** `.plan` exists with `state: active` AND `.plan-next` does not
exist. If postcondition not met, retry.

### C3. End mode — cleanup after promotion

In end mode (not sync), the cleanup step runs AFTER promotion:
1. Promote `.plan-next` → `.plan` (if exists)
2. Remove scaffold files from main
3. Stamp branch as closed
4. Archive slot (if applicable)

If no `.plan-next` exists, `.plan` is removed during cleanup (current behavior).

---

## D. Auto-Recovery

### D1. Deterministic recovery rules

When `ctx.py` detects corruption (`CORRUPTION_COUNT > 0`), the triage flow
currently presents options and waits for user input. For deterministic cases,
auto-recover instead:

| Condition | Diagnosis | Auto-recovery |
|-----------|-----------|---------------|
| `.plan` in `closing:*` state + all covered issues CLOSED on GitHub | Interrupted work-end, merge landed | `remove_plan` |
| `.plan` state not in VALID_STATES | Invalid state written by bypass path | `remove_plan` if all issues CLOSED, else `write_active` |
| `.plan` branch ≠ current branch + current branch is main | Stale `.plan` from previous branch | `remove_plan` |
| `.plan` state is `active` + branch doesn't exist | Orphaned `.plan` | `remove_plan` |

**Conservative rule:** Auto-recover only when ALL signals agree. If any signal
is ambiguous (e.g., some issues CLOSED, some OPEN), present options to the user.

### D2. Implementation in ctx.py

`ctx.py` already computes `CORRUPTION_COUNT` and individual findings. Add
auto-recovery to each finding:

```python
@dataclass
class CorruptionFinding:
    severity: str
    scenario: str
    detail: str
    actions: list[Action]
    auto_recoverable: bool = False
    auto_action: str = ""
```

When `auto_recoverable=True` and `auto_action` is set, the triage flow executes
the action without prompting:

```python
if all(f.auto_recoverable for f in findings):
    for f in findings:
        execute_action(f.auto_action)
    print("AUTO_RECOVERED=yes")
else:
    # Present options to user (current behavior)
```

---

## E. Pipeline Engine (Future Phase)

### E1. Scope

Extend the `orchestrator_engine.run_loop` pattern to cover the full lifecycle.
This is Phase 2+ work — the state hardening (A), sync (B), continuation (C),
and auto-recovery (D) can land first without restructuring the engine.

### E2. Architecture sketch

```python
# work.py — single entry point
def main():
    command = parse_command()  # start, continue, sync, end, pause, resume, next, find
    ctx = build_context()
    pipeline = select_pipeline(command, ctx)
    result = run_loop(pipeline.steps, ctx, ...)
    handle_result(result)
```

Each command maps to a step list:

```python
PIPELINES = {
    "start": [
        StepDef("resolve_issue", "setup", "mechanical", ...),
        StepDef("create_branch", "setup", "mechanical", ...),
        StepDef("scaffold", "setup", "mechanical", ...),
        StepDef("platform_coherence", "setup", "judgment", ...),
        StepDef("garden_search", "setup", "mechanical", ...),
        StepDef("brainstorm_offer", "setup", "judgment", ...),
    ],
    "sync": CLOSE_STEPS + [
        StepDef("sync_pass", ...),
        StepDef("promote_plan_next", ...),
    ],
    "end": CLOSE_STEPS + [
        StepDef("stamp_pass", ...),
        StepDef("cleanup_pass", ...),
        StepDef("stamp_branch", ...),
        StepDef("archive", ...),
    ],
}
```

All steps follow check-execute-verify (#379). Mechanical steps run without
LLM involvement. Judgment steps yield to the LLM via the same `ACTION=` protocol.

### E3. Conflict resolution tiers

When rebase encounters conflicts, the pipeline attempts resolution in order:

**Tier 1 — Auto-resolve lifecycle files:**
```python
LIFECYCLE_AUTO_RESOLVE = {".plan", "JOURNAL.md", ".close-progress", ...}

def auto_resolve_conflicts(repo_path):
    conflicted = git_conflicted_files(repo_path)
    lifecycle = [f for f in conflicted if f in LIFECYCLE_AUTO_RESOLVE]
    content = [f for f in conflicted if f not in LIFECYCLE_AUTO_RESOLVE]

    for f in lifecycle:
        git(repo_path, "checkout", "--ours", f)  # take our version
        git(repo_path, "add", f)

    return content  # remaining conflicts for higher tiers
```

**Tier 2 — LLM semantic resolution:**
The pipeline yields remaining conflicts to the LLM with context:
```python
return {
    "ACTION": "resolve_conflict",
    "FILES": ",".join(remaining),
    "CONTEXT": "rebase_conflict",
}
```

**Tier 3 — Human intervention:**
If the LLM can't resolve (returns `UNRESOLVED=yes`), yield to the user:
```python
return {
    "ACTION": "user_input",
    "CONTEXT": "conflict_requires_human",
    "FILES": ",".join(unresolved),
}
```

### E4. Skills as judgment callables

Skills that survive as judgment callables (invoked by the pipeline when
genuine LLM reasoning is needed):

| Skill | Pipeline integration |
|-------|---------------------|
| `code-review` | Pipeline yields `ACTION=code_review`, LLM runs review, returns findings count |
| `branch-audit` | Pipeline yields per dimension, LLM runs audit |
| `write-content` | Pipeline yields `ACTION=write_content`, LLM writes diary entry |
| `forage` / `protocol` | Pipeline yields for SWEEP, LLM scans session |
| `brainstorming` | Pipeline yields `ACTION=brainstorm_offer`, LLM runs design exploration |
| `git-squash` | Pipeline yields `ACTION=squash`, LLM classifies commits |

Skills that become pipeline steps (no LLM needed):

| Current skill | Pipeline step |
|--------------|--------------|
| `work-start` branch creation | `create_branch` mechanical step |
| `work-start` scaffold | `scaffold` mechanical step |
| `work-end` promotion | `promote` mechanical step (already is) |
| `work-end` landing | `land` mechanical step (already is) |
| `work-pause` | `pause` mechanical step |
| `work-resume` | `resume` mechanical step |

---

## Implementation Phases

### Phase 1: State hardening (A1–A4)

**Files changed:**
- `project/lifecycle.py` — commit .plan to git in `commit_transition`
- `project/plan_io.py` — add VALID_STATES validation to `write_field`
- `work-end/land_flow.py` — remove `.plan` from `LIFECYCLE_FILES`
- `work-end/branch_cleanup.py` — add `.plan` to cleanup removal list
- `work-end/work_end_orchestrator.py` — replace `elevate_plan_inline` with `commit_transition` call
- `work-slot/plan_manager.py` — remove `set-state` command
- `project/lifecycle.py` — add `elevate` and `migrate_pause` to TRANSITION_TABLE

**Tests:**
- Test that `commit_transition` creates a git commit
- Test that `write_field` rejects invalid states
- Test that `.plan` survives rebase (committed state)
- Test that `.plan` is cleaned from main by cleanup step

### Phase 2: Sync operation (B1–B3)

**Files changed:**
- `project/lifecycle.py` — add `work_sync` and `sync_pass` transitions
- `work-end/work_end_orchestrator.py` — add `mode` parameter, sync skip predicates
- `project/work_chain.py` — add `sync` command evaluation
- `work/SKILL.md` — add `work sync` routing

**Tests:**
- Test sync lands work but doesn't stamp/archive
- Test sync resets state to active
- Test sync promotes `.plan-next`

### Phase 3: Continuation pattern (C1–C3)

**Files changed:**
- `work-slot/plan_manager.py` — add `build-next` command
- `work-end/work_end_orchestrator.py` — add `promote_plan_next` step
- Continuation artifact promotion function

**Tests:**
- Test `.plan-next` promoted to `.plan` after sync
- Test `HANDOFF-next` promoted to `HANDOFF.md`
- Test promotion postcondition
- Test ceremony failure leaves `-next` files intact

### Phase 4: Auto-recovery (D1–D2)

**Files changed:**
- `project/ctx.py` — add `auto_recoverable` flag to corruption findings
- `work/SKILL.md` — auto-execute when all findings are auto-recoverable

**Tests:**
- Test auto-recovery for "all issues CLOSED + closing state"
- Test auto-recovery for "invalid state + all issues CLOSED"
- Test NO auto-recovery for ambiguous cases

### Phase 5: Pipeline engine (E1–E4)

**Files changed:**
- New `work.py` entry point
- Extend `orchestrator_engine.py` for full lifecycle pipelines
- New step lists for start, continue, pause, resume
- Conflict resolution tiers

This phase is the largest and can be broken into sub-phases.

---

## What This Eliminates

| Failure mode | How it's eliminated |
|-------------|-------------------|
| Invalid state (`closing:landed`) | A3: one gate validates all writes |
| State loss (uncommitted .plan changes) | A1: commit_transition commits to git |
| .plan stripped before post-land transitions | A2: .plan not in strip list |
| Orchestrator infinite loop (state/meta_state mismatch) | A1: committed state survives branch ops |
| .plan-next not promoted | C2: promotion is a pipeline step with postcondition |
| Manual recovery for deterministic situations | D1: auto-recover when all signals agree |
| Must plan next batch before landing | B1: sync lands without closing, plan next after |
| LLM routing mistakes | E2: Python pipeline owns routing |
| Conflict blocks autonomous operation | E3: three-tier resolution |

---

## References

- #379 — idempotent pipeline (postconditions, check-execute-verify)
- #382 — this issue (unified mechanical pipeline)
- `project/lifecycle.py` — state machine, VALID_STATES, TRANSITION_TABLE
- `project/plan_io.py` — write_field (no validation)
- `project/work_chain.py` — bidirectional chaining (already deterministic)
- `work-end/orchestrator_engine.py` — run_loop pattern
- `work-end/work_end_orchestrator.py` — STEPS list, elevate_plan_inline bypass
- `work-end/land_flow.py` — LIFECYCLE_FILES strip list
- `work-end/branch_cleanup.py` — cleanup-scaffold command
- `work-slot/plan_manager.py` — set-state bypass command
- `docs/protocols/evidence-before-claims.md`
- Incident: `.plan-next` promotion failure (2026-09-27)
- Incident: `closing:landed` invalid state from bypass write
- Incident: orchestrator infinite loop from uncommitted state changes
