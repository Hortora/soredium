# Idempotent Work-End Pipeline — Design Spec

**Issue:** #379
**Branch:** issue-379-idempotent-work-end
**Date:** 2026-09-25

## Problem

When any step in the work-end ceremony fails mid-execution, the system is left in
an inconsistent state. Recovery is ad-hoc. The root causes are:

1. Steps claim success before side effects complete (optimistic reporting)
2. Steps are not idempotent — re-running after failure creates duplicates or misses
   incomplete work
3. State is spread across .slot files, worklog DB, disk markers, and git branches —
   they can disagree
4. Workarounds for one failure create cascading inconsistencies

## Solution

Every mechanical step follows the **check-execute-verify** pattern:

```python
def step(context):
    if postcondition_met(context):        # CHECK: already done?
        return ALREADY_DONE               #   skip
    execute(context)                      # EXECUTE: do the work
    if not postcondition_met(context):    # VERIFY: did it work?
        raise StepFailed(...)             #   fail explicitly
    record_completion(context)            # only now: mark done
```

The orchestrator engine (`run_loop`) enforces this mechanically for every step.
No step can bypass the pattern because the engine owns the loop.

## Architecture

### StepDef extension

Add `postcondition_fn` to `StepDef`:

```python
@dataclass
class StepDef:
    name: str
    phase: str
    step_type: str
    script_fn: Callable | None = None
    skip_fn: Callable | None = None
    action_context_fn: Callable | None = None
    verify_fn: Callable | None = None       # existing: LLM-side verify
    postcondition_fn: Callable | None = None # NEW: mechanical postcondition
    from_state: str | None = None
    to_state: str | None = None
    event: str | None = None
```

`postcondition_fn` signature: `(ctx) -> bool`. Returns True if the step's
postcondition is met (work already done or just completed successfully).

`verify_fn` (existing) is for LLM-side validation (e.g., "did you produce findings?").
`postcondition_fn` (new) is for mechanical validation (e.g., "is the SHA on main?").
They serve different purposes and both remain.

### Engine changes (orchestrator_engine.py)

`run_loop` changes for mechanical steps:

```python
# Current flow:
#   if done(step): skip
#   execute
#   mark done

# New flow:
#   if done(step): skip
#   if postcondition_fn and postcondition_fn(ctx):   # CHECK
#       mark done, skip
#   execute                                           # EXECUTE
#   if postcondition_fn and not postcondition_fn(ctx): # VERIFY
#       return error (postcondition not met)
#   mark done
```

Steps without a `postcondition_fn` follow the current flow unchanged. This allows
incremental adoption — postconditions are added step by step, not all at once.

### Postcondition library (verification/step_postconditions.py)

New file in the existing `verification/` library. Each function checks one step's
postcondition against ground truth (filesystem, git, markers).

```python
def rebase_postcondition(ctx) -> bool:
    """Branch is ahead of base, merge-base == base tip."""
    result = git(ctx.project, "merge-base", "--is-ancestor",
                 ctx.base_branch, ctx.branch)
    return result.returncode == 0

def push_postcondition(ctx) -> bool:
    """SHA reachable from origin/main."""
    sha = ctx.landed_shas.get(ctx.project.name, "")
    if not sha:
        return False
    result = git(ctx.project, "merge-base", "--is-ancestor",
                 sha, f"origin/{ctx.base_branch}")
    return result.returncode == 0

def stamp_postcondition(ctx) -> bool:
    """Branch tip starts with 'chore: branch closed' and SHA is on base."""
    tip = git(ctx.project, "log", "-1", "--format=%s", ctx.branch)
    if tip.returncode != 0:
        return False
    if not tip.stdout.strip().startswith("chore: branch closed"):
        return False
    sha_match = re.search(r"landed as ([0-9a-f]+)", tip.stdout.strip())
    if not sha_match:
        return True  # old format stamp, still valid
    sha = sha_match.group(1)
    check = git(ctx.project, "merge-base", "--is-ancestor", sha, ctx.base_branch)
    return check.returncode == 0

def promote_postcondition(ctx) -> bool:
    """Artifact stamp exists."""
    stamp = ctx.workspace / ".artifacts-promoted"
    return stamp.exists()

def archive_move_postcondition(ctx) -> bool:
    """Slot dir in attic, not in slots."""
    if not ctx.slot_path or not ctx.family_root:
        return False
    attic = ctx.family_root / "attic" / ctx.slot_num
    return attic.is_dir() and not ctx.slot_path.is_dir()

def landed_marker_postcondition(ctx) -> bool:
    """.landed exists with populated landed_shas for all slot repos."""
    if not ctx.slot_path:
        return False
    landed = ctx.slot_path / ".landed"
    if not landed.exists():
        return False
    content = landed.read_text()
    if "landed_shas=" not in content:
        return False
    for line in content.splitlines():
        if line.startswith("landed_shas="):
            shas = line.split("=", 1)[1]
            pairs = [p for p in shas.split(",") if ":" in p]
            return len(pairs) > 0 and all(
                p.split(":", 1)[1].strip() for p in pairs
            )
    return False

def checkout_main_postcondition(ctx) -> bool:
    """Both repos on main."""
    for repo in [ctx.project, ctx.workspace]:
        result = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if result.returncode != 0 or result.stdout.strip() != "main":
            return False
    return True

def issues_closed_postcondition(ctx) -> bool:
    """All covered issues are closed on GitHub."""
    if not ctx.covers or not ctx.issue_repo:
        return True
    from plan_io import parse_covers
    for issue_num in parse_covers(ctx.covers):
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--repo", ctx.issue_repo,
             "--json", "state", "--jq", ".state"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or result.stdout.strip() != "CLOSED":
            return False
    return True
```

### Per-repo postconditions (slot mode)

In slot mode, postconditions run per-repo. The engine's per-repo fan-out
(`_close_per_repo_mechanical`) calls the postcondition for each repo:

```python
# Before executing repo:
ctx.current_repo_project = repo_path
if step.postcondition_fn and step.postcondition_fn(ctx):
    mark_done(step_key)
    continue  # already done for this repo

# After executing repo:
if step.postcondition_fn and not step.postcondition_fn(ctx):
    failures[repo] = {"ERROR": "POSTCONDITION_FAILED", ...}
```

## Phase 1: Journal-Based Progress Tracking

Extend `.execute-progress` to cover all phases, not just landing.

### Current state

- `.close-progress` tracks orchestrator steps (review done, promote done, etc.)
- `.execute-progress` tracks per-repo landing state (rebased, merged, pushed, stamped)
- Both files are in the workspace root

### Changes

`.execute-progress` gains entries for all mechanical phases:

```
# Phase: promotion
default=promoted

# Phase: rebase
soredium:issue-379=rebased

# Phase: landing
soredium:issue-379=pushed
soredium:issue-379:sha=abc123
cc-praxis:issue-379=stamped

# Phase: archive
archive_moved=yes
archive_db_updated=yes
```

The orchestrator reads `.execute-progress` on startup to determine where to
resume. `.close-progress` continues to own orchestrator-level step tracking
(which step in the STEPS sequence is current). `.execute-progress` owns
within-step progress (which repo has been rebased, which pushed, etc.).

No consolidation of the two files — they track different things at different
granularities.

## Phase 2: Postcondition Checks

Each mechanical step in the STEPS list gets a `postcondition_fn`. The mapping:

| Step | Postcondition | Check |
|------|--------------|-------|
| promote | Stamp file exists | `.artifacts-promoted` present |
| rebase | Branch ahead of base | `merge-base --is-ancestor base branch` |
| land | SHA on main | `merge-base --is-ancestor sha origin/main` |
| stamp | Tip is stamp commit with valid SHA | `log -1 --format=%s` + SHA ancestry |
| write_marker | .phase-a-complete exists | `Path.exists()` |
| write_landed | .landed exists with populated SHAs | Parse and validate |
| close_issues | All issues CLOSED | `gh issue view --json state` |
| verify | All checks pass | Delegates to verify_slot_close.py |
| archive_slot | Slot in attic, not in slots | `Path.exists()` on both |
| checkout_main | Both repos on main | `rev-parse --abbrev-ref HEAD` |
| cleanup_stack | Pause stack entry removed | Stack file parse |
| cleanup | Scaffold files removed | File existence check |
| upstream_push | SHA on upstream remote | `ls-remote` |

Judgment steps (review, forage, squash, etc.) keep their existing `verify_fn`
and do NOT get `postcondition_fn`. Judgment steps are LLM-driven — their
"postcondition" is the LLM marking them done via `step_done=`.

Lifecycle steps (review_pass, promote_pass, etc.) do NOT get postconditions.
They are state transitions, not operations with side effects.

## Phase 3: Honest Reporting

Move all success output to after postcondition verification:

### Pattern

Current (optimistic):
```python
print(f"ARCHIVED={slot_num}")    # printed before shutil.move
shutil.move(src, dst)            # might fail
```

New (honest):
```python
shutil.move(src, dst)
if not dst.exists():
    raise StepFailed("move did not complete")
print(f"ARCHIVED={slot_num}")    # only after verification
```

### Specific changes

1. **archive_slot** (`slot_manager.py`): Move `ARCHIVED=` print and DB transition
   to after `shutil.move()` returns AND `Path(attic/N).exists()` confirms.

2. **write_landed** (`work_end_orchestrator.py`): `.landed` is written as a journal
   step. Verify all SHAs are confirmed reachable from origin/main before writing.
   Current code writes `.landed` with `landed_shas=` that may be empty (#373).

3. **promote** (`close_artifacts.py`): `.artifacts-promoted` stamp is already
   written last. Verify stamp content matches what was actually promoted.

4. **land** (`land_flow.py`): Already has `_verify_content_landed` postcondition
   check. Move progress writes to after verification passes.

5. **close_issues** (`artifact_promote.py`): Add `gh issue view` verification
   loop after close attempts. Only report `CLOSED=N` after confirming state.

## Phase 4: Convergence Testing

### Test file

`tests/test_convergence.py` — pytest tests using `tmp_path` and mocked
subprocess calls.

### Failure scenarios to test

Each test simulates a failure at a specific point, then verifies re-running
the pipeline converges to the correct end state.

| Scenario | Failure point | Expected re-run behavior |
|----------|--------------|--------------------------|
| Push fails after rebase | land step, push subprocess | Rebase skipped (postcondition met), push retried |
| Stamp fails after push | stamp subprocess | Push skipped (SHA on main), stamp retried |
| Archive fails after landed | shutil.move | .landed exists, archive retried |
| Promote partial | One artifact fails | Completed artifacts skipped, failed retried |
| Issue close network error | gh subprocess | Retry close, verify state |
| Kill after merge, before push | Between steps | Merge skipped (postcondition: branch merged), push runs |
| Kill after push, before stamp | Between steps | Push skipped (SHA on remote), stamp runs |
| Full pipeline re-run (no failure) | None | All postconditions met, all steps skipped, ACTION=complete |

### Test structure

```python
class TestConvergence:
    """Verify re-running work-end after failures converges."""

    def _make_ctx(self, tmp_path, **overrides):
        """Build an OrchestratorContext with tmp_path workspace."""
        ...

    def test_idempotent_full_rerun(self, tmp_path):
        """Pipeline run twice with no failures produces same result."""
        ...

    def test_resume_after_push_failure(self, tmp_path):
        """Rebase not re-run when push fails and is retried."""
        ...

    def test_resume_after_archive_failure(self, tmp_path):
        """Archive retried, .landed not re-written."""
        ...
```

### Postcondition unit tests

Separate test file `tests/test_step_postconditions.py` — unit tests for each
postcondition function. These test the check logic itself, not the pipeline.

```python
def test_stamp_postcondition_valid(tmp_path):
    """Stamp with valid SHA on base returns True."""
    ...

def test_stamp_postcondition_stale_sha(tmp_path):
    """Stamp with SHA not on base returns False."""
    ...

def test_promote_postcondition_no_stamp(tmp_path):
    """No .artifacts-promoted returns False."""
    ...
```

## What This Eliminates

From the issue's documented failure modes, all become impossible or self-healing:

- "Slot archive started but never completed" — re-run converges
- "Ready-to-land slot with unpushed original main" — push postcondition checks
- ".landed with empty SHAs" — postcondition requires populated SHAs
- "Archive appears to succeed but move didn't happen" — postcondition verifies both paths
- "DB says active, disk says landed" — markers only written after verification
- "Partial slot landing, some repos skipped" — per-repo progress + re-run completes the rest
- "Manual workaround cascade" — re-run picks up wherever the workaround left off

## What Does NOT Change

- The 6-phase ceremony structure (review, promote, rebase, squash, land, close)
- The STEPS list ordering
- The lifecycle state machine
- Judgment step handling (LLM-driven, verify_fn)
- The SKILL.md orchestration flow
- `.close-progress` / `.execute-progress` file split (they track different granularities)

## File Changes Summary

| File | Change |
|------|--------|
| `verification/step_postconditions.py` | NEW: all postcondition functions |
| `work-end/orchestrator_engine.py` | Extend `run_loop` for check-execute-verify |
| `work-end/shared_steps.py` | Add `postcondition_fn` to StepDef |
| `work-end/work_end_orchestrator.py` | Wire postcondition_fn to each mechanical StepDef |
| `work-end/land_flow.py` | Move progress writes after verification |
| `work-end/close_artifacts.py` | Verify stamp content after promotion |
| `work-end/work_end_execute.py` | Verify operations before reporting success |
| `work-slot/slot_manager.py` | Move archive success after shutil.move verification |
| `tests/test_convergence.py` | NEW: convergence tests |
| `tests/test_step_postconditions.py` | NEW: postcondition unit tests |

## References

- #379 — issue with detailed failure analysis and implementation proposal
- #373 — stale .landed on re-activated slots (symptom of optimistic marker writing)
- #301 — SHA divergence from sync-main rebase
- `docs/protocols/evidence-before-claims.md` — "run the command, read the output, THEN claim"
- `docs/protocols/externalised-scripts-require-tests.md` — all new scripts need pytest tests
- `docs/protocols/archive-requires-promotion-verification.md` — archive checks .artifacts-promoted
- `work-end/orchestrator_engine.py` — current run_loop implementation
- `work-end/work_end_orchestrator.py` — STEPS list with ~40 step definitions
- `work-end/land_flow.py` — current land_batch with partial idempotency
- `verification/postconditions.py` — existing lifecycle gate checks
- `work-end/verify_slot_close.py` — existing post-close audit
