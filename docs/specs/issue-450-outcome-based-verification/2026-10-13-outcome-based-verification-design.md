# Outcome-Based Verification — Design Spec

**Issue:** #450
**Date:** 2026-10-13
**Status:** Draft
**Parent:** #443 (Robust Pipeline Architecture), Phase 3

## Problem Statement

The work-end pipeline uses two overlapping verification systems with
different return types:

1. `step_postconditions.py` — 14 functions returning `bool` (12 active,
   2 dead code: `stamp_postcondition`, `archive_move_postcondition`),
   used by the orchestrator engine's check-execute-verify pattern
2. `close_checks.py` / `close_verify.py` — functions returning
   `list[Finding]`, used for close-time verification reports

Both check overlapping things (e.g., `content_landed_postcondition` vs
`check_landed_completeness`, `stamp_postcondition` vs `check_branch_stamp`).
Edge-case fixes applied to one layer don't propagate to the other —
exactly the pattern that caused #436 (empty `landed_shas` returned True),
#375 (negative check: absent stamp ≈ success), and #435 (stamp never
written but postcondition passed).

Additionally, both systems use binary outcomes (bool or ERROR/WARN
severity) that cannot distinguish "verified — it passed" from
"insufficient evidence to determine." Missing evidence currently
collapses to either True (dangerous) or False (retry loop), with no
path for the engine to try deterministic recovery before retrying
or escalating.

## Design Overview

Replace both verification systems with a single layer built on
three-valued outcomes: PASS (positive evidence of success), FAIL
(positive evidence of failure), UNKNOWN (insufficient evidence).
The engine handles UNKNOWN via deterministic retry and, as a last
resort, LLM escalation.

### Architecture

```
verification/
  outcomes.py          # VerifyResult, Verification, verify_*() functions
  __init__.py          # Finding (unchanged — presentation type)
  close_verify.py      # composes verify_*() → to_finding() → report
  close_checks.py      # partially deprecated: overlapping checks migrate
                       #   to outcomes.py; non-overlapping checks remain:
                       #   check_no_open_findings, check_no_stale_scaffold,
                       #   check_slot_archive_status, check_landed_completeness,
                       #   resolve_canonical_repos (utility)
  step_postconditions.py  # fully deprecated, all consumers migrate to outcomes.py
  postconditions.py    # unchanged (Finding-based lifecycle gate checks)
  slot_checks.py       # unchanged (slot isolation checks)
  repo_checks.py       # unchanged (stuck-state checks)
  cross_checks.py      # unchanged
```

**Deprecation scope:** `step_postconditions.py` is fully deprecated —
every function moves to `outcomes.py`. `close_checks.py` is partially
deprecated — only functions that overlap with `step_postconditions.py`
move. Non-overlapping close-time checks (`check_no_open_findings`,
`check_no_stale_scaffold`, `check_slot_archive_status`,
`check_landed_completeness`) remain in `close_checks.py` because they
serve the close-verify report and have no orchestrator-engine
counterpart. `resolve_canonical_repos` is a utility function, not a
check — it stays.

## Types

### VerifyResult

```python
class VerifyResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
```

### Verification

```python
@dataclass(frozen=True)
class Verification:
    check: str            # "content_landed", "branch_merged", etc.
    result: VerifyResult
    evidence: dict        # what was checked, what was found
    repo: str             # repo name (for per-repo fan-out)
```

**Evidence dict convention:** Keys describe what was checked, values
describe what was found. Examples:

```python
# PASS
Verification("content_landed", VerifyResult.PASS,
    {"method": "tree_sha_match", "branch_tree": "abc123", "main_tree": "abc123"},
    repo="soredium")

# FAIL
Verification("content_landed", VerifyResult.FAIL,
    {"method": "diff_check", "diff_files": ["src/main.py", "tests/test_x.py"]},
    repo="soredium")

# UNKNOWN
Verification("content_landed", VerifyResult.UNKNOWN,
    {"reason": "main_tip_unchanged", "main_sha_at_classify": "def456",
     "main_sha_now": "def456"},
    repo="soredium")
```

### Composition helper

```python
def compose_verifications(check: str, *verifications: Verification) -> Verification:
    """Compose multiple verifications into one, preserving all evidence.

    Returns the worst result (FAIL > UNKNOWN > PASS) with a composite
    evidence dict containing all constituent results. No information is
    lost — the engine sees the worst result, and the evidence dict
    contains the full picture for diagnostics and escalation.
    """
    worst = VerifyResult.PASS
    composite_evidence: dict = {}
    for v in verifications:
        composite_evidence[v.check] = {
            "result": v.result.value,
            "evidence": v.evidence,
            "repo": v.repo,
        }
        if v.result == VerifyResult.FAIL:
            worst = VerifyResult.FAIL
        elif v.result == VerifyResult.UNKNOWN and worst != VerifyResult.FAIL:
            worst = VerifyResult.UNKNOWN
    repo = verifications[0].repo if verifications else ""
    return Verification(check, worst, composite_evidence, repo)
```

Used when a step needs to compose multiple checks into a single
`Verification` (D3 — one Verification per step). All constituent
results are preserved in the evidence dict, so the engine and LLM
escalation can see which specific check failed or returned UNKNOWN.
`close_verify.py` calls individual functions directly for its
multi-check report.

## Verify Functions

All live in `verification/outcomes.py`. Each returns `Verification`.
Pure functions — observe and report, never retry (D2).

**Signature convention:** Verify functions that need repo context
take explicit parameters (repo path, branch, base_branch, landed_sha)
rather than a context object. This makes them testable without
constructing full context objects and explicit about their inputs.

**Context type note:** `work_end_orchestrator.py`'s `OrchestratorContext`
does NOT inherit from `OrchestratorContextBase` — it is an independent
dataclass with additional fields (`landed_shas`, `meta_state`,
`pipeline_mode`, `current_repo_project`, etc.). The `outcome_fn`
lambda binds specific fields from whichever context type the
orchestrator uses, so verify functions are context-type-agnostic.

**Binding at step definition time:** When wiring a verify function
to a `StepDef.outcome_fn`, use a lambda or partial to bind the
repo-specific parameters from the orchestrator context:

```python
StepDef("land", "close", "mechanical",
    outcome_fn=lambda ctx: compose_verifications("land",
        verify_push(ctx.current_repo_project, ctx.base_branch),
        verify_content_landed(ctx.current_repo_project,
            ctx.landed_shas.get(ctx.current_repo_project.name, ""),
            ctx.base_branch)),
    ...)
```

This preserves the engine's `(ctx) -> Verification` contract while
verify functions remain pure and context-free.

### verify_content_landed

Replaces `content_landed_postcondition` and parts of
`check_landed_completeness`.

```python
def verify_content_landed(ctx, repo: RepoContext) -> Verification:
    """Verify branch content is on main after landing."""
```

**PASS evidence:**
- `merge-base --is-ancestor landed_sha base_branch` succeeds, OR
- branch tree SHA matches main tree SHA (squash merge), OR
- `git diff base_branch..landed_sha -- <source_exts>` is empty

**FAIL evidence:**
- `git diff` shows files with content differences

**UNKNOWN conditions:**
- No `landed_sha` available (not yet recorded) — falls back to stamp
  file `.landed` as secondary evidence (this spec's D4: dual-read stamp migration)
- Main tip unchanged since classification (`main_tree_sha` matches
  current) — evidence may be propagating from a remote push

### verify_branch_merged

Replaces `check_branch_merged` and aspects of `stamp_postcondition`.

```python
def verify_branch_merged(ctx, repo: RepoContext) -> Verification:
    """Verify branch commits are reachable from main."""
```

**PASS evidence:**
- No non-ceremony commits ahead of base, AND tree SHAs match (or
  pre-stamp tree matches), OR
- `merge-base --is-ancestor branch~1 base` succeeds, OR
- Landing SHA from stamp is ancestor of base

**FAIL evidence:**
- Non-ceremony, non-lifecycle commits exist ahead of base with
  content differences

**UNKNOWN conditions:**
- Branch deleted before check (ref not found)

### verify_branch_stamped

Replaces `stamp_postcondition` and `check_branch_stamp`.

```python
def verify_branch_stamped(ctx, repo: RepoContext) -> Verification:
    """Verify branch has a 'chore: branch closed' stamp commit."""
```

**PASS evidence:**
- Tip commit (within last 5) starts with `"chore: branch closed"`,
  AND if it contains `"landed as <SHA>"`, that SHA is on base branch

**FAIL evidence:**
- No stamp commit found in recent history

**UNKNOWN conditions:**
- Stamp exists but SHA not resolvable (object may not have been
  fetched)

### verify_push

Replaces `push_postcondition` and `check_main_pushed`.

```python
def verify_push(ctx, repo: RepoContext) -> Verification:
    """Verify main is pushed to origin."""
```

**PASS evidence:**
- `git log origin/main..main --oneline` is empty (zero unpushed)

**FAIL evidence:**
- N commits ahead of origin

**UNKNOWN conditions:**
- Remote unreachable (network error)

### verify_issues_closed

Replaces `issues_closed_postcondition` and `check_issues_closed`.

```python
def verify_issues_closed(ctx) -> Verification:
    """Verify covered issues are closed on GitHub."""
```

**PASS evidence:**
- All closable issues report `state=CLOSED` via `gh issue view`

**FAIL evidence:**
- One or more issues report state != CLOSED

**UNKNOWN conditions:**
- `gh` command fails (API unavailable, rate limited)

### verify_artifacts_promoted

Replaces `promote_postcondition` and `check_artifacts_promoted`.

```python
def verify_artifacts_promoted(ctx, repo: RepoContext) -> Verification:
    """Verify workspace artifacts have been promoted."""
```

**PASS evidence:**
- `.artifacts-promoted` stamp exists (this spec's D4 — stamp read
  as secondary evidence during migration), OR
- Promotion stamp commit found in git log, OR
- Branch has no diff against base (nothing to promote)

**FAIL evidence:**
- No stamp, no promotion commit, and branch has meaningful diff

**UNKNOWN conditions:**
- Workspace unavailable

### verify_rebase

Replaces `rebase_postcondition`.

```python
def verify_rebase(ctx, repo: RepoContext) -> Verification:
    """Verify base branch is ancestor of feature branch."""
```

**PASS evidence:**
- `merge-base --is-ancestor base_branch branch` succeeds

**FAIL evidence:**
- Ancestry check fails

**UNKNOWN conditions:**
- Branch ref not found

### verify_checkout_main

Replaces `checkout_main_postcondition`.

```python
def verify_checkout_main(ctx) -> Verification:
    """Verify both repos are on main."""
```

**PASS evidence:**
- Both project and workspace HEAD are `main`

**FAIL evidence:**
- One or both repos on a different branch

### verify_canonical_sync

Replaces `check_canonical_sync`.

```python
def verify_canonical_sync(ctx, slot_dir, repo_name, canonical_path) -> Verification:
    """Verify canonical repo has the landed content."""
```

**PASS evidence:**
- Landed SHA is ancestor of canonical main, OR
- Tree SHA match on canonical main, OR
- Diff between landed SHA and canonical main is empty

**FAIL evidence:**
- All fallbacks exhausted (ancestry, tree-SHA match, diff) and
  content differences confirmed

**UNKNOWN conditions:**
- SHA not resolvable in canonical repo (object may not have been
  fetched yet — propagation delay, not definitive failure)
- Canonical repo unreachable (network error)

### verify_landed_marker

Replaces `landed_marker_postcondition` and `check_landed_marker`.

```python
def verify_landed_marker(ctx, slot_dir) -> Verification:
    """Verify .landed marker exists with valid SHA data."""
```

During stamp migration (this spec's D4): reads `.landed` file as primary (stamp file
still written). After migration: replaced by event log query.

### verify_slot_phase_complete

Replaces `write_marker_postcondition` and `check_slot_marker`.

```python
def verify_slot_phase_complete(ctx, slot_dir, marker) -> Verification:
    """Verify a slot phase marker exists."""
```

During stamp migration (this spec's D4): reads marker file. After migration: replaced
by event log query.

## Engine Integration

### StepDef changes

`postcondition_fn` on `StepDef` is replaced by `outcome_fn`, which
returns `Verification` instead of `bool`.

The existing `verify_fn` field on `StepDef` is actively used by 8
judgment steps in `work_end_orchestrator.py` for LLM response
validation (e.g., `_verify_produced_required`, `_verify_squash`,
`_verify_forcing_function`). It has a different signature
`(workspace, produced, **kw) -> str | None` and serves a different
purpose — it validates judgment responses, not mechanical outcomes.
**`verify_fn` is unchanged.**

```python
@dataclass
class StepDef:
    name: str
    phase: str
    step_type: str
    script_fn: Callable | None = None
    skip_fn: Callable | None = None
    action_context_fn: Callable | None = None
    verify_fn: Callable | None = None        # unchanged — judgment response validation
    outcome_fn: Callable | None = None       # NEW — replaces postcondition_fn; returns Verification
    # postcondition_fn removed
    from_state: str | None = None
    to_state: str | None = None
    event: str | None = None
    modes: frozenset[PipelineMode] = ALL_MODES
    dispositions: frozenset[RepoDisposition] = ALL_DISPOSITIONS
    disposition_repo_types: frozenset[RepoType] = ALL_REPO_TYPES
    requires: tuple[str, ...] = ()
    staleness_relevant: bool = True
```

### run_loop() three-way dispatch

The orchestrator engine's mechanical step handling changes from
binary (bool) to three-way (VerifyResult).

**Re-execute vs re-verify:** Some steps are idempotent (rebase,
push) — re-execution can resolve an UNKNOWN. Others are
non-idempotent (land) — re-execution is dangerous and only
re-verification makes sense. A new `idempotent` flag on `StepDef`
(default `True`) controls the retry strategy:

```python
@dataclass
class StepDef:
    # ... existing fields ...
    idempotent: bool = True  # False for steps like "land" where re-execution is dangerous
```

```python
# Pre-execution check
if step.outcome_fn:
    v = step.outcome_fn(ctx)
    if v.result == VerifyResult.PASS:
        _mark_done(ctx, step.name)
        ctx.steps_executed.append(f"{step.name}:verify_skip")
        continue
    if v.result == VerifyResult.FAIL:
        # Proceed to execution — the step needs to run
        pass
    if v.result == VerifyResult.UNKNOWN:
        attempt += 1
        if attempt >= MAX_MECHANICAL_RETRIES:
            return _yield_unknown_escalation(step.name, v)
        if not step.idempotent:
            # Non-idempotent: yield for re-verification only, no re-execution
            return _make_unknown_retry_result(step.name, attempt, v)
        # Idempotent: continue to execution — may resolve the UNKNOWN
        pass

# ... execute step ...

# Post-execution verify
if step.outcome_fn:
    v = step.outcome_fn(ctx)
    if v.result == VerifyResult.PASS:
        _mark_done(ctx, step.name)
        continue
    if v.result == VerifyResult.FAIL:
        return _make_verify_fail_result(step.name, attempt, v)
    if v.result == VerifyResult.UNKNOWN:
        attempt += 1
        if attempt >= MAX_MECHANICAL_RETRIES:
            return _yield_unknown_escalation(step.name, v)
        return _make_unknown_retry_result(step.name, attempt, v)
```

For non-idempotent steps returning UNKNOWN post-execution, the engine
returns `_make_unknown_retry_result` which causes the orchestrator to
re-invoke `run_loop()`. On re-entry, the pre-execution check re-runs
`outcome_fn` — if evidence has propagated (e.g., push reached remote),
it returns PASS and the step is marked done without re-execution.

### Per-repo fan-out

For `PER_REPO_EXECUTE_STEPS` (rebase, land), the orchestrator
iterates repos and calls `outcome_fn` per-repo. The existing
`per_repo_mechanical` callback in `run_loop()` already handles
this fan-out — it sets `ctx.current_repo_project` temporarily
and tracks per-repo progress with composite keys
(`land:soredium=done`).

With `outcome_fn`, the per-repo path works as follows:

1. `per_repo_mechanical` iterates repos with matching disposition
2. For each repo, it sets `ctx.current_repo_project` and calls
   `step.outcome_fn(ctx)` — the lambda bound at step definition
   reads `ctx.current_repo_project` to resolve the repo
3. Per-repo results are tracked individually:
   - PASS → `_mark_done(ctx, f"{step.name}:{repo_name}")`
   - FAIL → return error for this specific repo
   - UNKNOWN → retry this repo only (other repos' results are
     preserved in composite progress keys)

Partial completion is natural: repo A may be PASS while repo B
is UNKNOWN. The composite progress (`land:repoA=done`) ensures
only unfinished repos retry on the next loop iteration.

The `Verification.repo` field identifies which repo the result
belongs to, enabling per-repo diagnostics in escalation and
close-verify reporting.

### UNKNOWN escalation

When UNKNOWN persists after `MAX_MECHANICAL_RETRIES`:

```python
def _yield_unknown_escalation(step_name, verification):
    return {
        "ACTION": "user_input",
        "CONTEXT": "unknown_verification",
        "STEP": step_name,
        "CHECK": verification.check,
        "RESULT": "unknown",
        "EVIDENCE": json.dumps(verification.evidence),
        "REASON": f"Verification '{verification.check}' returned UNKNOWN "
                  f"after {MAX_MECHANICAL_RETRIES} retries",
    }
```

The LLM receives structured UNKNOWN context (check name, evidence
dict) and can make a judgment call — inspect the evidence, try a
manual resolution, or ask the user.

## close_verify.py Adaptation

### Verification → Finding adapter

```python
def verification_to_findings(v: Verification) -> list[Finding]:
    if v.result == VerifyResult.PASS:
        return []
    severity = "ERROR" if v.result == VerifyResult.FAIL else "WARN"
    evidence_summary = "; ".join(f"{k}={v}" for k, v in v.evidence.items())
    return [Finding(severity, v.check, evidence_summary)]
```

`close_verify.py`'s `_run_branch_checks()` and `_run_slot_checks()`
switch from calling `close_checks.py` functions to calling
`outcomes.py` `verify_*()` functions, converting via
`verification_to_findings()`. The output format (VERIFIED=,
FAILURE_N=, BLOCKING_FAIL=) stays unchanged.

## Migration Plan

Follows the parent spec's 3a→3f ordering. Each step is independently
shippable.

### Step 3a: Define types

- Add `VerifyResult` enum and `Verification` dataclass to
  `verification/outcomes.py`
- Add `worst_of()` composition helper
- Add `verification_to_findings()` adapter
- Tests: unit tests for types, worst_of, adapter

### Step 3b: Build verify functions

- Implement all `verify_*()` functions in `verification/outcomes.py`
- Each function checks git state first, falls back to stamp files
  as secondary evidence (this spec's D4: dual-read stamp migration)
- Tests: unit tests per function covering PASS, FAIL, UNKNOWN paths
- **First win target:** `verify_content_landed` — replaces the
  highest-failure postcondition (#436, #386, #388)

### Step 3c: Replace content_landed_postcondition

- Wire `verify_content_landed` into the step that uses
  `content_landed_postcondition`
- Add `outcome_fn` to `StepDef`, remove `postcondition_fn`
- Update `run_loop()` for three-way dispatch
- Update `close_verify.py` to use `verify_content_landed` via adapter
- Remove `content_landed_postcondition` from `step_postconditions.py`
- Tests: integration test that UNKNOWN triggers retry then escalation

### Step 3d: Replace remaining postconditions

One at a time, in order of failure frequency:
1. `push_postcondition` → `verify_push`
2. `stamp_postcondition` → `verify_branch_stamped`
3. `rebase_postcondition` → `verify_rebase`
4. `promote_postcondition` → `verify_artifacts_promoted`
5. `issues_closed_postcondition` → `verify_issues_closed`
6. `checkout_main_postcondition` → `verify_checkout_main`
7. `landed_marker_postcondition` → `verify_landed_marker`
8. `write_marker_postcondition` → `verify_slot_phase_complete`
9. `archive_move_postcondition` → (simple directory check, inline)
10. `cleanup_scaffold_postcondition` → (list check, inline)
11. `promote_plan_next_postcondition` → (file existence, inline)
12. `fork_next_postcondition` → (branch check, inline)
13. `checkout_fork_postcondition` → (branch check, inline)

Corresponding `close_checks.py` functions are replaced at the same
time — no check exists in two places.

### Step 3e: UNKNOWN resolution path

- Build `_yield_unknown_escalation()` in `orchestrator_engine.py`
- Build `_make_unknown_retry_result()` for retry with evidence
- Add UNKNOWN handler to SKILL.md orchestrator loop
- Tests: engine-level tests for UNKNOWN retry and escalation

### Step 3f: Remove stamp files

After all consumers migrate. Full consumer enumeration:

**`.artifacts-promoted` consumers:**
- `close_artifacts.py:88-89` — writes the stamp (primary writer)
- `land_branch.py:102-107` — reads stamp
- `work_end_execute.py:201` — reads stamp
- `corruption.py:180-181` — checks for stamp
- `branch_cleanup.py:100` — lists as scaffold file
- `land_flow.py:102` — lists as cleanup file
- `conflict_resolution.py:11` — lists as lifecycle file
- `step_postconditions.py` — reads in `promote_postcondition`
- `close_checks.py` — reads in `check_artifacts_promoted`

**`.landed` consumers:**
- `slot_io.py:145,273` — reads and writes `.landed`
- `work_end_orchestrator.py:422-423` — writes `.landed` content
- `ctx.py:59` — checks existence for slot detection
- `step_postconditions.py` — reads in `landed_marker_postcondition`
- `close_checks.py` — reads in `check_landed_marker`,
  `check_canonical_sync`, `check_landed_completeness`

**`.phase-a-complete` consumers:**
- `work_end_execute.py:384` — writes the marker
- `step_postconditions.py` — reads in `write_marker_postcondition`
- `close_checks.py` — reads in `check_slot_marker`

**Removal steps:**
1. Stop writing `.artifacts-promoted` in `close_artifacts.py`
2. Stop writing `.phase-a-complete` in `work_end_execute.py`
3. Stop writing `.landed` in `slot_io.py` and
   `work_end_orchestrator.py` (migrate to event log)
4. Remove stamp-file fallback reads from `verify_*()` functions
5. Remove `verify_stamp.py` (standalone stamp verifier)
6. Clean up `LIFECYCLE_FILES` set in `close_checks.py`
7. Update non-verification consumers (`corruption.py`,
   `branch_cleanup.py`, `land_flow.py`, `conflict_resolution.py`,
   `ctx.py`) to use event log or remove references
8. Tests: verify all tests pass without stamp files

## Scope Boundaries

**In scope:**
- `VerifyResult`/`Verification` types
- `verify_*()` functions replacing both `step_postconditions.py` and
  `close_checks.py`
- Engine three-way dispatch for UNKNOWN
- `close_verify.py` adapter
- Stamp file elimination

**Out of scope:**
- Event-sourced lifecycle (Phase 1 — partially landed, continues
  independently)
- Typed LLM interface (Phase 4, #451 — uses `Verification` as input
  but is a separate concern)
- `postconditions.py` lifecycle gate checks (Finding-based, different
  purpose — these are pre-work-start checks, not step postconditions)
- `slot_checks.py`, `repo_checks.py`, `cross_checks.py` — slot
  isolation and stuck-state checks, unrelated to outcome verification

## Testing Strategy

- **Unit tests:** Each `verify_*()` function tested with mocked git
  state for all three outcomes (PASS, FAIL, UNKNOWN)
- **Composition tests:** `worst_of()` and `verification_to_findings()`
- **Engine tests:** `run_loop()` with verify functions returning each
  result type, retry counting, escalation threshold
- **Integration tests:** Full close sequence with verify functions
  replacing postconditions, verify output format unchanged
- **Protocol:** `externalised-scripts-require-tests` — every new .py
  file ships with tests in the same commit

## References

- Parent spec: `specs/issue-443-robust-pipeline-architecture/2026-10-12-robust-pipeline-architecture-design.md` § Phase 3
- Parent decisions: D5 (verification model), D2 (single lifecycle), D3 (events primary)
- `verification/step_postconditions.py` — 14 bool postconditions (12 active, 2 dead code) being replaced
- `verification/close_checks.py` — Finding-based checks being replaced
- `verification/close_verify.py` — composed reporter being adapted
- `project/orchestrator_engine.py:265-329` — current binary postcondition dispatch
- `project/shared_steps.py:34-49` — StepDef with postcondition_fn
- `project/repo_state.py:192-236` — RepoContext with tree_sha, main_tree_sha
- Issues: #436, #375, #435, #386, #388
