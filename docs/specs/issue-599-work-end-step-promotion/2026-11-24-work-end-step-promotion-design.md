# work end runs promotion and squash review as steps

**Issue:** Hortora/soredium#599
**Branch:** issue-599-work-end-step-promotion
**Date:** 2026-11-24

## Problem

Since `work end` was installed, the worklog shows 28 failed ceremonies against 14 successful ones. The `land` step in the close ceremony checks for unpromoted artifacts and unreviewed squashes *inside* `close.py`, returning one blocker at a time. Each retry costs a model turn, and before a resume fix each one re-asked `item_finished`, which could mark the next unstarted item as done.

Stop reasons at `land`: `squash_review_needed` 11, `promotion_needed` 9, `land_failed` 2.

## Design

### 1. New pipeline structure

**Current `_CLOSE_STEPS`:**
```
land → promote_backlog → publish → publish_blog
```

**New `_CLOSE_STEPS`:**
```
promote → squash_review → land → promote_backlog → publish → publish_blog
```

Both are mechanical steps. The pipeline stops on failure; the LLM reads the error output, runs the fix commands, and retries. Resume picks up at the failed step.

#### 1.1 `promote` step

A new `scope.py promote` command:

```python
def promote(workspace: Path) -> tuple[int, list[str]]:
    unpromoted, commands = ceremony.unpromoted_artifacts(workspace, covers)
    if unpromoted:
        return 2, ["ERROR=promotion_needed",
                   "UNPROMOTED=" + " ;; ".join(unpromoted),
                   "PROMOTE_COMMANDS=" + " ;; ".join(commands)]
    return 0, ["PROMOTED=nothing_needed"]
```

Calls the same `unpromoted_artifacts()` that `close()` currently uses. The function stays in `close.py`; the step just calls it via scope.

#### 1.2 `squash_review` step

A new `scope.py squash-review` command:

```python
def squash_review(workspace: Path) -> tuple[int, list[str]]:
    targets = resolve_targets(workspace)
    review_needed = []
    for target in targets:
        if target.is_workspace:
            continue
        reason = squash_marker.review_status(target.repo, target.branch, target.base_branch)
        if reason:
            review_needed.append(f"{target.repo.name}:{target.branch}: {reason}")
    if review_needed:
        return 2, ["ERROR=squash_review_needed",
                   "SQUASH_REVIEW=" + " ;; ".join(review_needed)]
    return 0, ["SQUASH_REVIEW=all_clear"]
```

Uses the same `squash_marker.review_status()` check that `close()` currently uses.

#### 1.3 Remove checks from close()

Remove the unpromoted-artifacts block (lines 1118-1124) and the squash-review block (lines 1126-1136) from `_close()`. By the time `land` runs, both have already passed. `close()` retains its `preflight()` call for rebase-time checks.

### 2. Preflight reports all blockers at once

Extend `sequence_preflight()` in `work.py` to include, for `end` only, an informational scan of everything that will block landing:

```python
# After SCOPE= line, before returning:
if command == "end":
    blockers = []
    unpromoted, _ = ceremony.unpromoted_artifacts(workspace, covers)
    if unpromoted:
        blockers.append(f"promotion: {len(unpromoted)} artifact(s)")
    review_needed = check_squash_review(workspace)
    if review_needed:
        blockers.append(f"squash: {len(review_needed)} branch(es)")
    # ... uncommitted, divergence checks ...
    if blockers:
        lines.append("PREFLIGHT_WARN=" + "; ".join(blockers))
```

These are `PREFLIGHT_WARN=` lines — informational, not blocking. The steps themselves block. This gives the LLM a heads-up before it starts the judgment steps (review, diary, item_finished), so it can tell the user upfront what needs fixing.

### 3. item_finished re-answer guard

Add a `skip_fn` to the `item_finished` StepDef:

```python
def _item_finished_already_answered(ctx) -> bool:
    return ctx.progress.get(ITEM_FINISHED_ANSWER, "") in ("yes", "no")
```

When this skip function returns True, the pipeline skips the step. The orchestrator engine prints a diagnostic `ITEM_FINISHED_REUSED=<answer>` line so the LLM knows the saved answer is being used.

This prevents the bug where a retry re-asks `item_finished`, gets `finished=yes`, and `mark_done` advances the queue to the next item — marking an unstarted item as done.

**Implementation detail:** The `item_finished` step is currently created with `skippable=False`. The `skip_fn` mechanism is different from `skippable` — `skippable` controls whether the LLM can choose to skip; `skip_fn` is an automatic gate the pipeline evaluates. The step stays non-skippable (the LLM can't skip it on first ask) but gains a `skip_fn` for automatic skip on resume.

Checking work.py's `run_loop` to verify: `skip_fn` is evaluated before the step runs and returns True to skip. `skippable` controls whether `outcome=skipped` is accepted from the LLM. These are independent.

### 4. Audit two worklog runs

Read-only investigation using `worktrace.py show`:

- `casehub/platform` 2026-11-20 06:43-06:51
- `casehub/pages` 2026-11-19 13:00-13:04

For each run, identify:
- Which items were marked done (`item_finished finished=yes` events)
- Whether each item was actually worked on (branch has commits beyond the scaffold)
- Whether the marking was a re-answer (item_finished answered multiple times in one run)

Report findings. Change nothing without owner approval.

### 5. exit_1 at land — error code with detail

The `land` function in `scope.py` returns exit code 1 with `ERROR=land_failed` for generic failures, but `DETAIL=` is sometimes empty because `close()` returned errors that were empty strings.

Fix: ensure every error path in `close()` produces a non-empty error string. In `scope.py land`, always include `DETAIL=` with the actual error text, and add an `ERROR_CODE=` field that distinguishes between:
- `land_rebase_failed` — rebase conflict during landing
- `land_no_targets` — no branches found to land
- `land_uncommitted` — repos have uncommitted changes
- `land_diverged` — base branch diverged from expected state

### Changes by file

| File | Change |
|------|--------|
| `project/work.py` | Add `promote` and `squash_review` to `_CLOSE_STEPS`; add `skip_fn` to `item_finished`; extend `sequence_preflight()` with `PREFLIGHT_WARN=` |
| `work-end/scope.py` | Add `promote` and `squash-review` commands; refine `land` error codes |
| `work-end/close.py` | Remove promotion and squash checks from `_close()`; ensure non-empty error strings |
| `docs/development/lifecycle-maintainer-guide.md` | Update step lists, error table, ceremony description |
| Tests | New tests for promote/squash_review steps, item_finished guard, preflight blockers |

### Order of implementation

1. item_finished guard (D3) — smallest, prevents the most damage
2. Promote step (D1) — extract from close, add to pipeline
3. Squash review step (D1) — same pattern as promote
4. Preflight extension (D2) — depends on promote/squash functions being available
5. exit_1 fix (deliverable 5) — small, independent
6. Audit (deliverable 4) — read-only, can be done anytime
7. Update lifecycle-maintainer-guide.md

## References

- `project/work.py:970-1067` — wrap/end pipeline structure
- `work-end/close.py:1044-1163` — close ceremony
- `work-end/scope.py:154-180` — land command
- `work-end/close.py:672-690` — unpromoted_artifacts()
- `project/progress.py` — Progress API for step tracking
- `docs/development/lifecycle-maintainer-guide.md:170-189` — ceremony documentation
- Hortora/soredium#599 — issue with worklog evidence
