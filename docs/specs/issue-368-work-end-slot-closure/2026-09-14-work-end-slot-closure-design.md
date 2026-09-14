# Work-end slot closure — incomplete closure fix

**Issue:** Hortora/soredium#368
**Branch:** issue-368-work-end-slot-closure
**Date:** 2026-09-14

---

## Problem

`work-end` leaves multi-repo slots in a half-closed state when a mechanical
step fails structurally. Observed on slot 181 closing casehubio/parent#469
(8-repo dual-framework extraction on main with a `.plan` queue).

The `.close-progress` file showed: review pass complete, all per-repo sweeps
done across 25 repos, `promote_mechanical_attempt=4` — promote tried 4 times
and never completed. No `.landed` marker, no stamps, no pushes. Everything
downstream of promote never ran.

### Failure chain

1. Promote step fails (archive-plans worktree issue on main, push to wrong
   remote) — these root causes were fixed in commit 7e6da3e
2. Orchestrator retries promote 3 more times (deterministic failure)
3. After 4 attempts, orchestrator yields `user_input CONTEXT=step_failed`
4. LLM tries `step_done=promote` → blocked ("Cannot mark mechanical step
   as done")
5. LLM tries `skip_step=promote` → blocked (`last_yielded` is
   `write_content`, not `promote`)
6. Dead end — no way to advance past the failed step
7. Landing, stamping, pushing, archiving never run

### Two independent root causes remain

**Root Cause 1:** The orchestrator treats mechanical step failures identically
to judgment step failures. The original spec (issue-271, section D10) explicitly
designed different policies: judgment steps escalate to the user; mechanical
steps auto-skip and let `verify_slot_close.py` catch gaps downstream. The
implementation deviated.

**Root Cause 2:** `verify_slot_close.py` checks all repos in the slot
(25 repos in slot 181), not just the repos that had work (9 repos in
`Covers:`). This produces dozens of false failures that obscure real problems.

---

## Fix 1: Auto-skip mechanical steps after MAX retries (D1)

Implement the original spec's D10 policy in `orchestrator_engine.py`.

### Changes to `orchestrator_engine.py`

**`run_loop()`** — after a mechanical step exhausts retries, mark it as
`skipped_error` and continue the loop instead of returning a dead-end
`user_input` result:

```python
# In the mechanical step error handling block (lines 234-244):
if result and "ERROR" in result:
    if on_mechanical_error:
        override = on_mechanical_error(step, ctx, result)
        if override is not None:
            ctx.steps_executed.append(f"{step.name}:ERROR:classified")
            return override
    attempt += 1
    update_close_progress(ctx.workspace, attempt_key, str(attempt))
    if attempt >= MAX_MECHANICAL_RETRIES:
        # D10: auto-skip mechanical failures, verify catches gaps
        update_close_progress(ctx.workspace, step.name, "skipped_error")
        ctx.steps_executed.append(f"{step.name}:SKIPPED_ERROR")
        continue  # loop continues to next step
    ctx.steps_executed.append(f"{step.name}:ERROR:{attempt}")
    return _make_error_result(step.name, attempt, result)
```

**`MAX_MECHANICAL_RETRIES`** — new constant, value `3`. Separate from
`MAX_JUDGMENT_RETRIES` (also 3 but semantically different — judgment
retries escalate, mechanical retries auto-skip).

**`done()` check** — recognize `skipped_error` as a terminal state:

```python
def done(self, step: str) -> bool:
    return self.progress.get(step) in ("done", "skipped", "skipped_error")
```

### Changes to `work_end_orchestrator.py`

**`_close_per_repo_mechanical()`** — apply the same auto-skip logic for
per-repo mechanical steps. When a per-repo step exhausts retries for a
specific repo, mark that repo's step as `skipped_error` and continue to
the next repo:

```python
# In the retryable failure handling (around line 1282):
if retryable_failure:
    step_key, attempt, result = retryable_failure
    if attempt >= MAX_MECHANICAL_RETRIES:
        update_close_progress(ctx.workspace, step_key, "skipped_error")
        ctx.steps_executed.append(f"{step_key}:SKIPPED_ERROR")
        # Don't return — fall through to check if all repos are done
    else:
        from orchestrator_engine import _make_error_result
        return _make_error_result(step_key, attempt, result)
```

**`per_repo_done()` check** — recognize `skipped_error`:

```python
def per_repo_done(self, step: str) -> bool:
    if not self.in_slot or not self.slot_repos:
        return self.done(step)
    return all(
        self.progress.get(f"{step}:{repo}") in ("done", "skipped", "skipped_error")
        for repo in self.slot_repos
    )
```

**`_build_close_step_outcomes()`** — track `skipped_error` distinctly from
`skipped` in session boundary events:

```python
elif status == "skipped_error":
    outcomes[step_name] = {"ran": True, "skipped_error": True}
```

### Why this unblocks landing (Gap 4)

When promote auto-skips, `report_promote` runs (records 0 promoted files),
`promote_pass` lifecycle transition fires with evidence
`{"promoted_files": 0, "target_repos": [...]}`. The lifecycle accepts empty
evidence (validates present keys have valid values but does not require
non-empty content). The loop advances to `closing:promoted` → `land` runs
normally. Landing doesn't depend on artifact promotion.

### Impact on `progress_summary.py`

The close report should surface `skipped_error` steps. Add a new section
to the summary output:

```
Skipped (mechanical failure):
  promote — exit_1: worktree_failed (4 attempts)
```

### Impact on verify

`verify_slot_close.py`'s `check_artifacts_promoted` already returns
`status: warn` when no `.artifacts-promoted` stamp is found. Auto-skipped
promote flows through to verify, which catches the gap and reports it as
a warning — not a fatal block.

---

## Fix 2: Scope verify to covered repos (D2)

### New function: `_parse_covers_repos()`

Extract repo names from the `Covers:` line in `.slot`:

```python
def _parse_covers_repos(slot_dir: str) -> set[str]:
    """Extract repo names from the Covers: line in .slot."""
    slot_file = Path(slot_dir) / ".slot"
    if not slot_file.exists():
        return set()
    for line in slot_file.read_text().splitlines():
        if line.startswith("Covers:"):
            parts = line.split(":", 1)[1].strip()
            return {
                entry.split(":")[0].strip()
                for entry in parts.split(",")
                if ":" in entry
            }
    return set()
```

### Changes to `verify_slot_close.py`

**`_resolve_original_repos()`** — accept optional `covers_repos` filter:

```python
def _resolve_original_repos(
    slot_dir: str,
    covers_repos: set[str] | None = None,
) -> dict[str, str]:
    result = {}
    slot_path = Path(slot_dir)
    for sub in sorted(slot_path.iterdir()):
        if not sub.is_dir() or not (sub / ".git").exists():
            continue
        if sub.name in (".m2", "attic"):
            continue
        if covers_repos and sub.name not in covers_repos:
            continue  # skip repos not in Covers:
        local_url = git(str(sub), "remote", "get-url", "local")
        if local_url.returncode == 0 and local_url.stdout.strip():
            orig_path = local_url.stdout.strip()
            if Path(orig_path).is_dir():
                result[sub.name] = orig_path
    return result
```

**`check_landed_completeness()`** — accept optional `covers_repos` to
scope the completeness check:

```python
def check_landed_completeness(
    slot_dir: str,
    covers_repos: set[str] | None = None,
) -> dict:
    expected_repos = covers_repos if covers_repos else _parse_slot_repos(slot_dir)
    if not expected_repos:
        return {"status": "pass", "detail": "no repos to check"}
    landed_repos = _parse_landed_repos(slot_dir)
    missing = expected_repos - landed_repos
    if missing:
        return {"status": "fail",
                "detail": f"repos not in .landed: {', '.join(sorted(missing))}"}
    extra = landed_repos - expected_repos
    if extra:
        return {"status": "warn",
                "detail": f"extra repos in .landed: {', '.join(sorted(extra))}"}
    return {"status": "pass",
            "detail": f"{len(landed_repos)}/{len(expected_repos)} repos landed"}
```

**`main()`** — parse covers repos and pass through:

```python
covers_repos = _parse_covers_repos(slot_dir) if slot_dir else None

# Pass to _resolve_original_repos
original_repos = _resolve_original_repos(slot_dir, covers_repos=covers_repos)

# Pass to verify()
verify(..., covers_repos=covers_repos)
```

**`verify()`** — accept and pass `covers_repos`:

```python
def verify(
    ...,
    covers_repos: set[str] | None = None,
) -> bool:
    ...
    if slot_dir:
        checks.append(("landed_completeness",
                        check_landed_completeness(slot_dir, covers_repos=covers_repos)))
```

### Fallback behavior

When `Covers:` is not present in `.slot` (older slots, single-issue
slots), `_parse_covers_repos` returns an empty set. All functions fall
back to their existing behavior (check all repos). No regression for
existing slots.

---

## Testing strategy

### Test file: `tests/test_work_end_orchestrator.py` (extend existing)

| Test | Assert |
|------|--------|
| `test_mechanical_step_auto_skips_after_max_retries` | After 3 failures, step is marked `skipped_error`, loop continues to next step |
| `test_mechanical_auto_skip_allows_landing` | Promote fails → auto-skips → `promote_pass` fires → `land` runs normally |
| `test_judgment_step_still_escalates_to_user` | Judgment steps still yield `user_input CONTEXT=step_failed` after 3 failures (no behavior change) |
| `test_skipped_error_recognized_by_done` | `ctx.done("promote")` returns True when progress has `promote=skipped_error` |
| `test_per_repo_mechanical_auto_skip` | Per-repo step in slot mode auto-skips individual repos after MAX retries |
| `test_per_repo_done_with_skipped_error` | `ctx.per_repo_done("land")` returns True when some repos are `done` and others are `skipped_error` |
| `test_promote_pass_fires_with_zero_promoted` | Lifecycle evidence `{"promoted_files": 0, ...}` is accepted after skipped promote |

### Test file: `tests/test_verify_slot_close.py` (extend existing)

| Test | Assert |
|------|--------|
| `test_parse_covers_repos` | Parses `Covers: platform:276,engine:1049` → `{"platform", "engine"}` |
| `test_parse_covers_repos_missing` | No `Covers:` line → empty set |
| `test_resolve_original_repos_scoped` | With `covers_repos={"engine"}`, only `engine` is resolved, `aml` is skipped |
| `test_landed_completeness_scoped` | With 9 covers repos and 9 landed, passes even though slot has 25 repos |
| `test_landed_completeness_fallback` | No `Covers:` → falls back to `_parse_slot_repos` (existing behavior) |
| `test_verify_scoped_no_false_failures` | Full verify run with `covers_repos` produces no false failures for non-covered repos |

---

## Files changed

### Modified files

| File | Change |
|------|--------|
| `work-end/orchestrator_engine.py` | Auto-skip mechanical steps after MAX_MECHANICAL_RETRIES; add MAX_MECHANICAL_RETRIES constant |
| `work-end/work_end_orchestrator.py` | Auto-skip in `_close_per_repo_mechanical`; recognize `skipped_error` in `done()`, `per_repo_done()`; track in step outcomes |
| `work-end/verify_slot_close.py` | Add `_parse_covers_repos()`; scope `_resolve_original_repos()` and `check_landed_completeness()` to covers repos |
| `work-end/progress_summary.py` | Surface `skipped_error` steps in close report |
| `tests/test_work_end_orchestrator.py` | Auto-skip tests, lifecycle evidence tests |
| `tests/test_verify_slot_close.py` | Scoping tests, fallback tests |

### Unchanged files

All other work-end scripts remain unchanged. The fixes are in the
orchestrator layer (sequencing and verification), not the execution
layer (individual scripts).

---

## Scope

### In scope

- Auto-skip mechanical steps after MAX retries (orchestrator_engine.py)
- Per-repo auto-skip in slot mode (work_end_orchestrator.py)
- `skipped_error` state recognition across done checks
- Close report surfacing of skipped steps
- Verify scoping to covered repos (verify_slot_close.py)
- Tests for all changes

### Not in scope

- Promote script fixes (already fixed in 7e6da3e)
- Push remote resolution (already fixed in 7e6da3e)
- Changes to the lifecycle state machine
- Changes to individual execution scripts (land_flow, land_branch, etc.)
- Haiku validation changes

---

## References

- Hortora/soredium#368 — issue description with reproduction steps
- issue-271 spec section D10 — original mechanical step policy (auto-skip)
- issue-224 spec — slot landing design (verification extensions)
- `orchestrator_engine.py:234-244` — current error handling (dead end)
- `work_end_orchestrator.py:1245-1312` — per-repo mechanical fan-out
- `verify_slot_close.py:381-394` — `_resolve_original_repos` (unscoped)
- `verify_slot_close.py:286-298` — `check_landed_completeness` (unscoped)
- Slot 181 `.close-progress` — concrete failure evidence
- Slot 181 `.slot` — 25 repos vs 9 covered repos
- `docs/protocols/evidence-before-claims.md` — verification discipline
- `docs/protocols/externalised-scripts-require-tests.md` — test requirements
