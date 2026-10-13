# Robust Pipeline Architecture — Design Spec

**Issue:** #443
**Date:** 2026-10-12
**Status:** Draft

## Problem Statement

The work-end pipeline has a 63% fix-to-feature ratio. Of 100 issues filed between #343 and #442 (Sep 7 – Oct 12, 36 days), ~70 are fixes. Four fix chains exist where a fix was itself fixed, sometimes twice. The structural audit (#423, phases 1-7) addressed code duplication but did not eliminate the root causes — 11 bugs emerged in the 2 days after it landed.

### Seven Failure Patterns

| # | Pattern | Issue count | Representative |
|---|---------|-------------|----------------|
| 1 | File-as-Database: multi-writer state corruption | 23 | #441, #434, #410, #398 |
| 2 | Edge-Case Whack-a-Mole: N×M bugs from distributed classification | 17 | #422, #432, #437 |
| 3 | Negative Verification: missing ≈ success | 8 | #436, #375, #435 |
| 4 | Session Boundary Blindness: pipeline assumes one session | 9 | #439, #411, #414 |
| 5 | Multi-Repo Blindspot: single-repo model patched for multi-repo | 11 | #437, #438, #431 |
| 6 | LLM-as-Control-Plane Fragility: state-passing and looping | 7 | #434, #391, #393 |
| 7 | Postcondition Inversion: stamps checked instead of outcomes | 6 | #436, #386, #388 |

### Three Root Causes

These seven patterns reduce to three first-principles violations:

**A. Shared mutable state without a guardian.** `.plan` has 7 writers and 28+ readers. Six code paths bypass the canonical `plan_io.write_fields`. No locking, no schema enforcement, no transactional semantics. Git operations (rebase, merge, checkout) can corrupt the file between writes.

**B. Distributed classification without centralization.** Every step, skip predicate, and postcondition independently probes git to determine repo state. Each probe handles edge cases locally. When a new edge case surfaces (#422 zero-commit, #432 post-squash, #371 workspace-only), it gets fixed in one probe while N others remain vulnerable.

**C. Implicit contracts between components.** Postconditions check stamp file presence (`.artifacts-promoted`, `.landed`) rather than actual outcomes. Components communicate through string parsing and assumed conventions. No typed interfaces between the orchestrator engine and the LLM.

## Architecture Overview

Four phases of evolution, each independently shippable:

1. **Event-sourced lifecycle** — DB events as primary state, `.plan` as derived snapshot
2. **Classify-once context** — RepoContext with disposition enum, propagated to all consumers
3. **Outcome-based verification** — three-valued (PASS/FAIL/UNKNOWN), git state + events
4. **Typed LLM interface** — JudgmentRequest/Response formalizing the existing pattern

The approach is evolution, not replacement. The primitives exist (worklog DB events table, lifecycle.py state machine with CAS, RepoState classification). Two problem categories: (1) primitives that are sound but bypassed, and (2) primitives with quality bugs. Evolution addresses both: enforce the modules, fix the bugs in-place.

## Phase 1: Event-Sourced Lifecycle

### Current State

- `lifecycle.py` has a data-driven state machine with 12 states, 24 transitions, CAS writes, and evidence gates on closing transitions.
- The worklog DB `events` table captures lifecycle transitions — but as a write-only audit trail. Nothing reads events to derive state.
- `.plan` is the primary state store. 14 writes across 7 files target it. `plan_io.write_fields` is the canonical writer but multiple paths bypass it with raw `write_text()` or `replace()`.
- `.plan` participates in git operations (committed by `_commit_plan_to_git`), making it subject to rebase corruption.
- `.plan` contains two categories of data: **lifecycle state** (`state:`, `branch:`, `covers:`) and **work queue** (`## Queue`, `## Deferred`, design fields). The DB currently stores lifecycle events but NOT queue structure, ordering, or design-related fields.
- Progress tracking files (`.work-progress`, `.execute-progress`) have the same multi-writer, no-schema problems as `.plan` — addressed in a future phase (see Scope Limitations).

### Design

**Events become the primary source for lifecycle state.** The pipeline reads lifecycle state from DB queries, not `.plan` parsing. Queue and design-related `.plan` fields remain file-based in Phase 1, with `plan_manager.py` as their single owner — event-sourcing the queue is deferred.

#### Existing Event Infrastructure

The worklog DB `events` table already includes `repo_path TEXT` (schema V1, `worklog.py` line 72). `lifecycle.py`'s `_emit_to_worklog` already passes `repo_path` to `log_transition`. No schema extension needed — the column exists but is write-only.

#### State Derivation

```python
def get_lifecycle_state(work_item_id: int, repo_path: str | None = None) -> str:
    """Query most recent lifecycle event for this work item + repo.
    Returns to_state from the latest event, or 'idle' if no events."""
```

This replaces every `.plan` state: field read. One function, one source.

#### .plan as Hybrid Snapshot

`.plan` contains lifecycle state AND work queue data. After each lifecycle event, `plan_io.update_lifecycle_fields()` updates the lifecycle fields (`state:`, `branch:`, `evidence-era:`, etc.) from DB state while preserving the queue sections (`## Queue`, `## Deferred`, design fields) that are file-native:

```python
def update_lifecycle_fields(workspace: Path, work_item_id: int):
    """Update lifecycle fields in .plan from current DB state.
    Preserves queue sections and design fields unchanged.
    Called after every lifecycle event emission."""
```

`.plan` is committed to git for:
- Human readability (developers can inspect state)
- Clone bootstrap (fresh clones with no DB start from `.plan` snapshot)
- CI/hook consumption (non-Python tools that parse `.plan`)

Pipeline code reads lifecycle state from DB events (`get_lifecycle_state()`). Queue data is read from `.plan` via `plan_io` or `plan_manager.py`. If DB lifecycle state and `.plan` `state:` field disagree, DB events win.

**Post-rebase .plan regeneration:** Since `.plan` participates in git operations, rebase can corrupt its lifecycle fields. After any rebase or merge, the pipeline calls `update_lifecycle_fields()` to restore lifecycle state from DB. Queue sections may also be corrupted by rebase — this is detected by `plan_io.validate_queue()` and flagged as a corruption condition (existing `S13_MERGE_CONFLICT` check handles conflict markers).

#### Single-Writer Enforcement

All `.plan` lifecycle state mutations must route through `lifecycle.py` → `plan_io.update_lifecycle_fields()`. All queue mutations must route through `plan_manager.py` → `plan_io`. The bypass paths (verified against codebase):

| Bypass path | Current behavior | Migration |
|---|---|---|
| `scaffold.py` (3 writes) | Direct `write_text()` for initial `.plan` creation | Emit `scaffolded` event → lifecycle.py → update_lifecycle_fields() |
| `lifecycle.py` `_write_evidence_era` (1 write) | Reads `.plan`, inserts `evidence-era:` line, atomic replace. Has a bug: matches `state:` prefix without checking section context | Route through `plan_io.write_field(plan_path, 'evidence-era', 'true')` — immediate fix, eliminates bypass and bug |
| `lifecycle.py` `commit_transition` (1 write) | `plan_path.unlink(missing_ok=True)` — removes `.plan` during idle transition | Emit `plan_removed` event, remove via plan_io |
| `work_end_orchestrator.py` `_cleanup_close_artifacts` (1 write) | `plan.unlink()` — removes `.plan` during close | Route through plan_io removal |
| `work_end_orchestrator.py` `_promote_plan_next_inline` (1 write) | `copy2(plan_next, .plan)` — replaces `.plan` with next-branch plan | Route through plan_io |
| `work_end_orchestrator.py` `_elevate_plan_inline` (1 write) | `copy2(ws_plan, slot_plan)` — copies workspace plan to slot | Route through plan_io |
| `plan_manager.py` (2 writes) | Direct `write_text()` for queue manipulation | Route through plan_io (queue operations stay file-based) |
| `plan_migrate.py` (2 writes) | Direct `write_text()` for format migration | One-time migration — route through plan_io |
| `migrate_meta.py` (1 write) | Direct `write_text()` for .meta → .plan migration | Legacy — route through plan_io |
| `audit_work_end.py` (1 write) | Direct `write_text()` for test fixtures | Test-only — exempt from enforcement |

**Note:** `recover_plan.py` writes `.orphaned-plan`, not `.plan` — it is not a bypass path.

**Enforcement mechanism:** Static analysis test that greps for `.write_text()` / `.replace()` / `.unlink()` targeting `.plan` paths outside the canonical writers (`plan_io.py`, `lifecycle.py`). Runs at commit tier. Prevents regression permanently.

#### SQLite as Primary Store

SQLite with WAL mode (already configured in `worklog.py` line 169). Proven infrastructure — same DB, same connection management, same schema patterns. `busy_timeout` handles rare write contention between concurrent sessions.

**Reliability inversion (R1-08, critical):** The current event emission path is designed to be lossy — `_emit_to_worklog` wraps in try/except, `log_transition` is `@safe`. If events are primary, emission failures must propagate as errors and halt the lifecycle transition. Migration order matters: make emission fail-loud BEFORE any reader switches to querying events. Otherwise there's a window where `.plan` writes succeed, event emission fails silently, and readers see stale event state.

Specifically:
1. Remove `@safe` from `worklog.py` `log_transition` and `update_work_item_state`
2. Remove the blanket `try/except` in `lifecycle.py` `_emit_to_worklog`
3. Add `busy_timeout=5000` to the connection for write contention
4. Add explicit error handling: if DB write fails, the lifecycle transition fails — no silent degradation

**Recovery from DB corruption/loss:** Bootstrap from `.plan` snapshot + start a new event sequence. This is a defined disaster-recovery path, not an active dual-source model.

#### Migration Steps

| Step | What | Dependencies | Shippable? |
|---|---|---|---|
| 1a | Make event emission fail-loud: remove `@safe`, remove try/except, add busy_timeout | None | Yes — **must be first** |
| 1b | Build `get_lifecycle_state()` query function | None | Yes |
| 1c | Route each bypass writer through lifecycle.py / plan_io (14 paths, one at a time) | None | Yes per path |
| 1d | Build `plan_io.update_lifecycle_fields()` — merge DB lifecycle state into existing `.plan` | 1b | Yes |
| 1e | Replace `.plan` lifecycle state readers: `project/ctx.py` → `project/work.py` → `work_end_orchestrator.py` → postconditions | 1a, 1b | Yes per reader |
| 1f | Add post-rebase `.plan` regeneration via `update_lifecycle_fields()` | 1d | Yes |
| 1g | Static analysis test: grep for `.plan` writes outside canonical paths | 1c | Yes |

**First win:** After 1a, event emission is reliable — no more silent drops. After 1c, all state mutations go through canonical writers. These two eliminate the multi-writer class of bugs (12+ issues) even before the read side migrates.

## Phase 2: Classify-Once Context

### Current State

- `classify_repo()` in `project/repo_state.py` returns a frozen `RepoState` dataclass with `disposition: RepoDisposition`. The enum already has: `HAS_WORK`, `EMPTY_BRANCH`, `NO_BRANCH`, `ALREADY_LANDED`.
- `work.py` uses `classify_repos()` in `build_context()`.
- `work_end_orchestrator.py` ignores `RepoState` — builds its own `OrchestratorContext`. Skip predicates like `_skip_empty_branch` (line 316) check `disposition` but only for the repos that were classified; the orchestrator itself probes git independently.
- 12 postcondition functions in `step_postconditions.py` shell out to git independently.
- The `modes` field on `StepDef` (added in #427) declares which pipeline modes a step runs in, but is not yet connected to repo disposition.

### Design

#### RepoContext: RepoState + Verification Fields

`RepoContext` extends `RepoState` via composition — it wraps an existing `RepoState` and adds the fields needed for outcome verification and lifecycle tracking. `RepoState` is not renamed or deleted; `classify_repo()` continues to return `RepoState`. `RepoContext` adds the layer.

```python
@dataclass(frozen=True)
class RepoContext:
    # Existing RepoState (composition — all current fields preserved)
    state: RepoState              # includes path, name, repo_type, disposition,
                                  # branch, base_branch, commits_ahead, is_dirty,
                                  # has_remote, remote_branch_exists, has_upstream,
                                  # push_remote, canonical_path, is_slot_clone,
                                  # landing_sha

    # New fields for verification and lifecycle
    tree_sha: str                 # branch tip tree SHA at classification time
    main_tree_sha: str            # main tip tree SHA
    remote_synced: bool           # local main == origin main
    lifecycle_state: str          # from DB events (Phase 1), not .plan
```

#### Existing Disposition Enum

`RepoDisposition` already exists with the right values:

| Disposition | Meaning | Pipeline behavior |
|---|---|---|
| `HAS_WORK` | Feature branch, commits ahead of main | Full pipeline |
| `EMPTY_BRANCH` | Feature branch, zero commits ahead | Skip review/squash/land, trivial close |
| `NO_BRANCH` | No feature branch in this repo | Skip entirely |
| `ALREADY_LANDED` | Branch content is ancestor of main (post-landing) | Skip land, trivial verify |

**Note:** `ALREADY_LANDED` is distinct from "work done on main" (which is handled by `PipelineMode.MAIN` and `OrchestratorContext.on_main`). These are orthogonal: `ALREADY_LANDED` is a post-merge repo disposition, `MAIN` is a pipeline mode for branchless work. Both are preserved.

Every step checks `state.disposition` instead of shelling out to git. The 13 skip predicates reduce to `modes` declarations on `StepDef` evaluated against `disposition` at the engine level.

#### Per-Repo Orchestration

Single lifecycle per work item (D2). The orchestrator fans out within each lifecycle state for per-repo concerns:

- **PER_REPO_EXECUTE_STEPS** (rebase, land): iterate repos with `disposition=HAS_WORK`
- **PER_REPO_SWEEP_STEPS** (protocol, update_claude_md, doc_freshness): iterate only the active repo (the one the session actually changed)
- **Archive precondition**: check ALL repos in the slot before offering archive

The existing composite progress keys (`rebase:engine=done`) already support this. What changes: the fan-out uses `context.state.disposition` to filter, not per-step git probes.

#### Migration Steps

| Step | What | Dependencies | Shippable? |
|---|---|---|---|
| 2a | Build `RepoContext` wrapping `RepoState` + new verification fields | Phase 1b | Yes |
| 2b | Add `tree_sha`, `main_tree_sha`, `remote_synced` to `classify_repo()` output | None | Yes |
| 2c | Propagate `RepoContext` into `work_end_orchestrator.py`, replacing `OrchestratorContext` | 2a | Self-contained |
| 2d | Replace per-step git probes with `state.disposition` checks | 2c | Yes per step |
| 2e | Connect `modes` on `StepDef` to `disposition` evaluation | Existing RepoDisposition | Yes |
| 2f | Fix active-repo filtering in sweep fan-out (#437) | 2c | Yes |
| 2g | Add peer-repo precondition to archive step (#438) | 2c | Yes |

**First win:** After 2a + 2c, the biggest consumer uses `RepoContext`. Edge-case whack-a-mole stops because classification happens once, immutably.

## Phase 3: Outcome-Based Verification

### Current State

- Postconditions check stamp files (`.artifacts-promoted`, `.landed`, `.phase-a-complete`).
- Missing stamps → retry loop (#435, #386). Present stamps → trust without checking (#375).
- Empty data historically returned True (#436: `content_landed_postcondition` returned True when `landed_shas` was empty — fixed narrowly in #436 to return False, but the systemic pattern of stamp-checking remains across other postconditions).
- Two verification systems exist with overlapping checks and different return types (#429).

### Design

#### Three-Valued VerifyResult

```python
class VerifyResult(Enum):
    PASS = "pass"         # positive evidence of success
    FAIL = "fail"         # positive evidence of failure
    UNKNOWN = "unknown"   # insufficient evidence

@dataclass(frozen=True)
class Verification:
    check: str            # "content_landed", "branch_merged", "issues_closed"
    result: VerifyResult
    evidence: dict        # what was checked, what was found
    repo: str
```

UNKNOWN never collapses to PASS. Three-step resolution:

1. **Deterministic check** — verify git state directly
2. **Deterministic fallback/retry** — known recovery actions for specific UNKNOWN conditions
3. **LLM escalation** — last resort for genuinely ambiguous situations

#### Enumerated UNKNOWN Conditions

| Condition | Fallback | Escalate when |
|---|---|---|
| Partial landing (some repos landed) | Retry unfinished repos | Retry limit exceeded |
| Ambiguous branch state (detached HEAD, rebase-in-progress) | Reattach / abort and retry | Topology truly unknown |
| Missing evidence (expected git state doesn't match) | Wait-and-recheck with backoff (propagation delay) | N retries exhausted |

#### What Each Verification Checks

| Check | Positive evidence required | Returns UNKNOWN when |
|---|---|---|
| `content_landed` | main tip tree SHA matches branch content | main tip unchanged since classification |
| `branch_merged` | branch tip reachable from main via `merge-base --is-ancestor` | branch deleted before check |
| `issues_closed` | GitHub API confirms issue state=closed | API unavailable |
| `canonical_synced` | canonical repo main ≥ clone's landed SHA | canonical unreachable |
| `artifacts_promoted` | workspace diff empty for artifact paths | workspace unavailable |

#### Stamp File Elimination

No more `.artifacts-promoted`, `.landed`, `.phase-a-complete`. Verification reads:
1. Git state directly (tree SHAs, ancestry, diffs)
2. Event log (land event with SHA, promote event with paths)

The event log replaces stamps — it records WHEN something happened and WHAT the evidence was, not just THAT a file exists.

#### Migration Steps

| Step | What | Dependencies | Shippable? |
|---|---|---|---|
| 3a | Define `VerifyResult` and `Verification` types | None | Yes |
| 3b | Build `verify_outcome()` functions — git state + event checks | Phase 1b, 2a | Yes |
| 3c | Replace `content_landed_postcondition` (highest-failure) | 3b | Yes |
| 3d | Replace remaining postconditions one at a time | 3b | Yes per postcondition |
| 3e | Build UNKNOWN→fallback→escalation resolution path | 3a. Escalation uses existing ACTION= protocol during migration; switches to JudgmentRequest after Phase 4d | Yes |
| 3f | Remove stamp files after all consumers migrate | 3c, 3d | Yes per file |

**First win:** After 3c, the most common postcondition failure class (#436, #386, #388) is eliminated.

## Phase 4: Typed LLM Interface

### Current State

- `work_end_orchestrator.py` already implements Python-drives-LLM. The docstring says: "Python drives, LLM assists. The LLM cannot skip what it cannot see."
- `StepDef` has `step_type` (mechanical/judgment/lifecycle), `action_context_fn` providing structured context, `verify_fn` validating responses.
- But: `action_context_fn` returns ad-hoc dicts, `verify_fn` only validates counts not content, judgment steps lack explicit input/output contracts.
- The `COMPLETE_WITH=` hint (#391) was a step toward typed responses but remains stringly-typed.

### Design

This is formalization of the existing pattern, not a direction change.

#### JudgmentRequest / JudgmentResponse

```python
@dataclass(frozen=True)
class JudgmentRequest:
    step: str                    # "code_review", "brainstorm_offer", ...
    handler: str                 # path to handler .md file to load
    context: dict                # structured context (from action_context_fn)
    response_schema: dict        # JSON schema for expected response
    skippable: bool              # can the LLM skip this step?
    timeout_hint: str            # "quick" | "standard" | "extended"

@dataclass(frozen=True)
class JudgmentResponse:
    step: str                    # echoes request.step
    outcome: str                 # "completed" | "skipped" | "blocked"
    produced: int                # artifacts produced
    evidence: dict               # step-specific output
    block_reason: str | None     # if blocked, why
```

#### StepType Enum

`StepDef.step_type` is currently a plain string (`"mechanical"`, `"judgment"`, `"lifecycle"`), checked via string comparison. Since Phase 4 types the LLM interface, it should also type the step classification:

```python
class StepType(Enum):
    MECHANICAL = "mechanical"
    JUDGMENT = "judgment"
    LIFECYCLE = "lifecycle"
```

This catches typos at definition time and makes the `run_loop` dispatch exhaustive.

#### What Changes

- `StepDef.step_type` becomes `StepType` enum
- `action_context_fn` returns `JudgmentRequest` instead of ad-hoc dict
- `verify_fn` validates `JudgmentResponse` against the schema
- SKILL.md orchestrator loop parses `JudgmentRequest` and returns `JudgmentResponse`
- State is never passed by the LLM — the orchestrator reads from DB events (Phase 1)
- Invalid responses are rejected with specific error, not silently re-yielded

#### What Stays the Same

- Handler `.md` files still guide the LLM's judgment work
- The `run_loop` in `orchestrator_engine.py` still drives execution
- Mechanical steps remain pure Python
- The SKILL.md still contains the orchestrator call loop

#### Migration Steps

| Step | What | Dependencies | Shippable? |
|---|---|---|---|
| 4a | Define `JudgmentRequest` / `JudgmentResponse` dataclasses | None | Yes |
| 4b | Add `response_schema` field to `StepDef` | 4a | Yes |
| 4c | Update `run_loop` to emit structured requests | 4a | Yes |
| 4d | Update work-end SKILL.md to parse requests and return responses | 4c | Paired with 4c |
| 4e | Convert judgment steps one at a time (code_review first) | 4d | Yes per step |
| 4f | Remove old `ACTION=` / `step_done=` protocol | All steps converted | Cleanup |

**Coexistence:** Both protocols (old key=value and new typed) coexist during migration. `run_loop` detects which protocol the response uses and handles both.

## Phasing and Dependencies

```
Phase 1a-c (single writer + fail-loud)    ← highest leverage, do first
    │
    ├── Phase 1d-g (read migration, snapshot, static analysis)
    │       │
    │       └── Phase 3a-d (outcome verification)
    │                │
    │                └── Phase 3e (UNKNOWN escalation) ──→ uses Phase 4 typed interface
    │
    └── Phase 2 (classify-once context)
            │
            └── Phase 3a-d (outcome verification)

Phase 4a-d (typed LLM interface)  ← independent, parallel with 1-2
    │
    └── Phase 3e (UNKNOWN escalation uses JudgmentRequest)
```

Phase 1a-c is the critical path. Closing bypass writers and making event emission fail-loud eliminates the multi-writer class of bugs immediately. Phase 3e has a soft dependency on Phase 4 for escalation, but uses the existing `ACTION=` protocol as a bridge during migration. Phase 4 is independent of Phase 3a-d.

## What NOT to Do

- **Don't migrate everything at once.** Each step is a separate issue with its own tests.
- **Don't remove `.plan` files.** Lifecycle fields become DB-derived; queue sections stay file-native. `.plan` is still committed, still human-readable. The change is invisible to the developer experience.
- **Don't break the existing protocol during migration.** Old `ACTION=` / `step_done=` stays as fallback until all steps are converted.
- **Don't build complex slot coordination.** D2 (revised) keeps a single lifecycle per work item with per-repo fan-out at the orchestrator level — no new state machines.
- **Don't use `@safe` on primary write paths.** Errors must be raised, not silently dropped. `@safe` stays only on truly best-effort secondary operations.

## Scope Limitations

**Progress tracking files** (`.work-progress`, `.execute-progress`, `.land-ledger.jsonl`) suffer from the same multi-writer, no-schema problems as `.plan`. These are NOT addressed in this design — they remain file-based. Rationale: progress state is ephemeral (scoped to a single close sequence) and less critical than lifecycle state (which persists across sessions and branches). A future phase may event-source progress tracking, but the lifecycle migration must land first.

**Queue and design fields** in `.plan` (`## Queue`, `## Deferred`, design-repo, design-section-hashes, flyway-next-v) remain file-based with `plan_manager.py` as their single owner. Event-sourcing the queue would require significant DB schema extension. The lifecycle/queue split keeps the migration scope manageable.

**`.meta` files** are deprecated (14 files still reference for backward compat). Full removal of `.meta` read paths is cleanup work, not part of this architecture. It should happen but is independent of the four phases.

## Testing Strategy

Each phase has a testing approach:

**Phase 1:** Test `get_lifecycle_state()` with event sequences (unit tests with in-memory SQLite). Test `update_lifecycle_fields()` merges DB lifecycle state into existing `.plan` without corrupting queue sections. Test bypass closure — each former bypass path now routes through canonical writers. **Static analysis test** (commit-tier): grep for `.write_text()` / `.replace()` / `.unlink()` targeting `.plan` paths outside `plan_io.py` and `lifecycle.py` — fail if any found. This prevents regression permanently. Integration test: event → state derivation → `update_lifecycle_fields()` → `.plan` lifecycle fields match expected values.

**Phase 2:** Test `classify_repo()` produces correct `RepoDisposition` for each edge case (zero commits, no branch, already-landed, dirty). Test `RepoContext` immutability. Test skip predicate replacement — same steps skipped with `state.disposition` as with git probes. Test that no step shells out to git to determine repo type after classification.

**Phase 3:** Test each `verify_outcome()` for PASS, FAIL, UNKNOWN states. Test UNKNOWN resolution path — fallback before escalation. **Critical regression test:** no verification function returns PASS on empty/missing evidence (parameterized test with None, empty string, empty dict for every evidence field).

**Phase 4:** Test `JudgmentRequest` → `JudgmentResponse` round-trip. Test schema validation rejects malformed responses. Test coexistence — old protocol responses handled during migration. Test `StepType` enum covers all step_type values in existing StepDefs.

## Success Criteria

The redesign is complete when:

1. All `.plan` lifecycle writes route through `plan_io.update_lifecycle_fields()`, all queue writes through `plan_manager.py` → `plan_io` (zero direct file manipulation)
2. All lifecycle transitions route through `lifecycle.py` with event emission
3. All state reads use `get_lifecycle_state()` from DB, not `.plan` parsing
4. All steps use `RepoContext.disposition` for classification, not git probes
5. All postconditions use `VerifyResult` with three-valued logic
6. All judgment steps use `JudgmentRequest`/`JudgmentResponse`
7. Fix-to-feature ratio drops below 30% over a 30-day window
8. Zero fix chains (fix-of-a-fix) in any 30-day window

## References

- Issues #343-#442 (failure pattern analysis)
- #423 Pipeline structural audit (phases 1-7)
- #424 git_util.py extraction
- #425 slot_io.py extraction
- #426 RepoState classification
- #427 PipelineMode enum
- #428 Step dependencies
- #429 Verification unification
- #430 Typed Progress
- project/lifecycle.py (state machine, CAS writes, evidence gates)
- project/repo_state.py (classify_repo, RepoState)
- project/worklog.py (events table, WAL mode)
- work-end/work_end_orchestrator.py (orchestrator engine, StepDef)
- verification/step_postconditions.py (current postcondition logic)
- docs/protocols/git-util-single-source.md (single-source protocol)
- docs/protocols/evidence-before-claims.md (verification protocol)
- docs/protocols/skill-md-minimal-orchestrator-loop.md (orchestrator pattern)
