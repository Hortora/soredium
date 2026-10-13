# Classify-Once RepoContext — Design Spec

**Issue:** #449
**Date:** 2026-10-13
**Status:** Draft
**Parent:** #443 (Robust Pipeline Architecture), Phase 2

## Problem Statement

The work-end pipeline classifies repo state distributedly. 12 postcondition functions and 13 skip predicates shell out to git independently. When a new edge case surfaces (zero-commit, post-squash, workspace-only), it gets fixed in one probe while N others remain vulnerable — the N×M edge-case whack-a-mole pattern responsible for 17 issues in the post-refactor analysis.

Additionally, the orchestrator's `_close_per_repo_mechanical` has a fallback path (lines 1770-1800) that shells out to git when `ctx.repos` is empty, duplicating classification logic that `classify_repo()` already handles.

## Scope

This issue implements Phase 2 of the robust pipeline architecture (#443):

- **2a:** Build `RepoContext` wrapping `RepoState` + verification fields
- **2b:** Add `tree_sha`, `main_tree_sha`, `remote_synced` to classification
- **2c:** Propagate `RepoContext` into `work_end_orchestrator.py`
- **2d:** Replace skip-predicate git probes with `state.disposition` checks
- **2e:** Connect `dispositions` on `StepDef` to disposition evaluation in engine
- **2f:** Fix active-repo filtering in sweep fan-out (#437)
- **2g:** Add peer-repo precondition to archive step (#438)

**Also includes:** `get_lifecycle_state()` (Phase 1b) as a prerequisite for RepoContext's `lifecycle_state` field.

**Out of scope:** Postcondition refactoring (Phase 3), typed LLM interface (Phase 4), DB-derived state reads replacing .plan parsing (Phase 1e).

## Architecture

### get_lifecycle_state() — Phase 1b prerequisite

Added to `~/.claude/lib/worklog.py` alongside existing query functions:

```python
def get_lifecycle_state(conn: sqlite3.Connection,
                        work_item_id: int) -> str | None:
    """Most recent lifecycle state from events for this work item.
    Returns to_state from the latest event, or None if no events."""
    row = conn.execute(
        "SELECT json_extract(metadata, '$.to_state') AS to_state "
        "FROM events WHERE work_item_id=? "
        "AND json_extract(metadata, '$.to_state') IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (work_item_id,),
    ).fetchone()
    return row["to_state"] if row else None
```

Not decorated with `@safe` — callers handle failures explicitly. Uses `$.to_state` to match the key stored by `lifecycle.py`'s `_emit_to_worklog`.

### RepoContext dataclass

Lives in `project/repo_state.py` alongside `RepoState`:

```python
@dataclass(frozen=True)
class RepoContext:
    state: RepoState

    # Verification fields (computed at classification time)
    tree_sha: str          # branch tip tree SHA (empty if no branch)
    main_tree_sha: str     # base_branch tip tree SHA
    remote_synced: bool    # local base_branch == origin/base_branch

    # Lifecycle (from DB events, Phase 1b)
    lifecycle_state: str | None  # from get_lifecycle_state(), None on DB failure
```

`frozen=True` — RepoContext is a classification-time snapshot (D8). Fields reflect pipeline-entry state. Any mid-pipeline check that needs current state must query directly (D9).

### Two-phase construction (D2)

`classify_repo()` stays unchanged — returns `RepoState`. A new `build_repo_context()` wraps it:

```python
def build_repo_context(
    state: RepoState,
    base_branch: str,
    conn: sqlite3.Connection | None = None,
    work_item_id: int | None = None,
) -> RepoContext:
    tree_sha = ""
    if state.branch:
        result = git(state.path, "rev-parse", f"{state.branch}^{{tree}}")
        if result.returncode == 0:
            tree_sha = result.stdout.strip()

    main_result = git(state.path, "rev-parse", f"{base_branch}^{{tree}}")
    main_tree_sha = main_result.stdout.strip() if main_result.returncode == 0 else ""

    # Compare local refs — no network call
    local_main = git(state.path, "rev-parse", base_branch)
    origin_main = git(state.path, "rev-parse", f"origin/{base_branch}")
    remote_synced = (
        local_main.returncode == 0
        and origin_main.returncode == 0
        and local_main.stdout.strip() == origin_main.stdout.strip()
    )

    lifecycle_state = None
    if conn is not None and work_item_id is not None:
        try:
            lifecycle_state = worklog.get_lifecycle_state(conn, work_item_id)
        except Exception:
            pass  # informational — not a control-flow gate (D4)

    return RepoContext(
        state=state,
        tree_sha=tree_sha,
        main_tree_sha=main_tree_sha,
        remote_synced=remote_synced,
        lifecycle_state=lifecycle_state,
    )
```

A convenience function builds contexts for all repos:

```python
def build_repo_contexts(
    repos: list[RepoState],
    base_branch: str,
    conn: sqlite3.Connection | None = None,
    work_item_id: int | None = None,
) -> list[RepoContext]:
    return [build_repo_context(r, base_branch, conn, work_item_id)
            for r in repos]
```

### OrchestratorContext integration (D3)

`OrchestratorContext.repos` changes from `list` (untyped) to `list[RepoContext]`. All existing access paths update mechanically:

| Before | After |
|--------|-------|
| `r.disposition` | `r.state.disposition` |
| `r.path` | `r.state.path` |
| `r.name` | `r.state.name` |
| `r.repo_type` | `r.state.repo_type` |
| `r.has_upstream` | `r.state.has_upstream` |
| `r.is_slot_clone` | `r.state.is_slot_clone` |
| `r.landing_sha` | `r.state.landing_sha` |

The orchestrator entry point changes from:

```python
from repo_state import classify_repos as _classify_repos
repos = _classify_repos(project=project, workspace=workspace, ...)
```

to:

```python
from repo_state import classify_repos as _classify_repos, build_repo_contexts
raw_repos = _classify_repos(project=project, workspace=workspace, ...)
repos = build_repo_contexts(raw_repos, base_branch, conn, work_item_id)
```

`OrchestratorContextBase.repos` in `shared_steps.py` also changes to `list[RepoContext]` for type consistency.

### Empty repos handling (D6)

For slot pipelines, if `parse_slot` returns None (corrupted/missing .slot file), `classify_repos` falls back to directory enumeration — listing subdirectories with `.git` that do NOT have a `.workspace` marker file:

```python
# In classify_repos, after parse_slot returns None:
if slot_path is not None:
    from slot_io import parse_slot
    info = parse_slot(slot_path)
    if info is None:
        # Fallback: enumerate git repos excluding workspaces
        repos = []
        for entry in sorted(slot_path.iterdir()):
            if not entry.is_dir() or not (entry / ".git").exists():
                continue
            if (entry / ".workspace").exists():
                continue  # workspace dirs are not source repos
            state = classify_repo(entry, branch, base_branch, RepoType.CLONE)
            if state is not None:
                repos.append(state)
        return repos
    # ... normal path
```

After robust classification, if repos is still empty for a non-main pipeline, the orchestrator raises an error:

```python
if not repos and pipeline_mode != PipelineMode.MAIN:
    raise ValueError(
        f"classify_repos returned empty for {pipeline_mode.value} pipeline "
        f"at {slot_path or project}"
    )
```

### Disposition filtering on StepDef (D7)

Two new fields on `StepDef`:

```python
ALL_DISPOSITIONS = frozenset(RepoDisposition)
ALL_REPO_TYPES = frozenset(RepoType)

@dataclass
class StepDef:
    name: str
    phase: str
    step_type: str
    # ... existing fields ...
    modes: frozenset[PipelineMode] = field(default_factory=lambda: ALL_MODES)
    dispositions: frozenset[RepoDisposition] = field(
        default_factory=lambda: ALL_DISPOSITIONS)
    disposition_repo_types: frozenset[RepoType] = field(
        default_factory=lambda: ALL_REPO_TYPES)
```

Semantics: "run this step if at least one repo with a type in `disposition_repo_types` has a disposition in `dispositions`." Default values match ALL — no behavioral change for existing StepDefs.

### Engine evaluation order (D10)

The engine evaluates in cheapest-first order:

1. **modes** — set membership: `pipeline_mode in step.modes`
2. **dispositions** — aggregate check: `any(r.state.disposition in step.dispositions for r in repos if r.state.repo_type in step.disposition_repo_types)`
3. **skip_fn** — arbitrary code (may include git operations)

If modes or dispositions exclude a step, skip_fn is never reached. skip_fn cannot relax a disposition filter — dispositions are structural constraints, not soft preferences.

### Skip predicate replacement (D5)

| Current skip predicate | Replacement |
|------------------------|-------------|
| `_skip_empty_branch` | `dispositions={HAS_WORK}`, `disposition_repo_types={RepoType.PROJECT}` on review/audit StepDefs |
| `_skip_multi_repo_partial_close` (disposition part) | Disposition check in per-repo fan-out loop — already uses `r.disposition` |
| `_close_per_repo_mechanical` fallback (lines 1770-1800) | Removed entirely — `ctx.repos` is guaranteed non-empty (D6) |

The per-repo fan-out in `_close_per_repo_mechanical` already uses disposition checks for the `ctx.repos` path (lines 1754-1767). The fallback path (lines 1770-1800) that shells out to git is removed.

### Active-repo filtering in sweep fan-out (#437, step 2f)

`_close_per_repo_judgment` already filters by `RepoDisposition.HAS_WORK` (line 1867-1868). The fix ensures this filtering uses `ctx.repos` consistently — no fallback to `ctx.slot_repos` without disposition data.

### Peer-repo precondition for archive (#438, step 2g)

`_skip_multi_repo_partial_close` checks whether ALL repos in the slot have landed before offering archive. The fix:

1. Uses `ctx.repos` (now `list[RepoContext]`) exclusively — no fallback git probes
2. Checks `r.state.disposition` for each repo: all must be `NO_BRANCH`, `EMPTY_BRANCH`, or `ALREADY_LANDED`
3. Also checks workspace directories for active `.plan` files (existing logic, lines 286-289)

## Migration Plan

### Step ordering (dependency-driven):

```
1b: get_lifecycle_state() in worklog.py     ← no dependencies
2a: RepoContext dataclass                    ← no dependencies
2b: tree_sha, main_tree_sha, remote_synced   ← 2a
    build_repo_context() + build_repo_contexts()
2c: Propagate into orchestrator              ← 2a, 2b
    - OrchestratorContext.repos type change
    - Mechanical access-path updates (r.x → r.state.x)
    - classify_repos → build_repo_contexts at entry
    - Empty repos hard error
2e: StepDef.dispositions field               ← 2a (needs RepoDisposition import)
    - Add fields to StepDef
    - Engine evaluation in run_loop
2d: Replace skip predicates                  ← 2c, 2e
    - _skip_empty_branch → disposition declarations
    - Remove fallback git-probe path
2f: Sweep fan-out filtering                  ← 2c
2g: Archive peer-repo precondition           ← 2c
```

### Each step is independently shippable and testable.

## Testing Strategy

**Phase 1b (get_lifecycle_state):**
- Unit test with in-memory SQLite: insert events, verify correct state returned
- Test with no events → returns None
- Test with multiple events → returns most recent to_state
- Test JSON path: verify `$.to_state` matches what `_emit_to_worklog` stores

**RepoContext (2a, 2b):**
- Test `build_repo_context()` with various RepoState inputs
- Test frozen=True — immutability
- Test lifecycle_state degradation — DB failure → None, no exception
- Test remote_synced — local refs comparison, no network calls

**Orchestrator integration (2c):**
- Test mechanical access-path updates compile
- Test empty repos raises ValueError for non-main pipelines
- Test classify_repos directory-enumeration fallback excludes `.workspace` dirs

**Disposition filtering (2e):**
- Test default dispositions/repo_types → ALL (no behavioral change)
- Test engine evaluation order: modes → dispositions → skip_fn
- Test disposition filter excludes step when no matching repos exist
- Test disposition_repo_types filters correctly (PROJECT only for review steps)

**Skip predicate replacement (2d):**
- Test review/audit steps skip when all project repos are EMPTY_BRANCH
- Test review/audit steps run when any project repo has HAS_WORK
- Test fallback path is gone — no git probes in _close_per_repo_mechanical for empty repos path

**Fan-out fixes (2f, 2g):**
- Test sweep fan-out only runs for HAS_WORK repos
- Test archive skipped when any repo has HAS_WORK disposition

## What NOT to Do

- **Don't refactor postconditions.** They shell out to git independently — that's Phase 3's problem. Phase 2 only touches skip predicates and the fallback path.
- **Don't make RepoContext mutable.** Frozen at classification time. Mid-pipeline checks that need current state query the DB directly.
- **Don't re-classify after rebase.** Skip predicates run before rebase, so the snapshot is valid. Phase 3 re-derives what it needs for post-rebase verification.
- **Don't add `@safe` to get_lifecycle_state.** Callers handle failures explicitly. `build_repo_context` degrades to `lifecycle_state=None` on failure.

## Success Criteria

Phase 2 is complete when:

1. `RepoContext` exists with all four new fields (tree_sha, main_tree_sha, remote_synced, lifecycle_state)
2. `get_lifecycle_state()` exists in worklog.py and returns correct state from events table
3. `OrchestratorContext.repos` is `list[RepoContext]` — all access paths updated
4. All skip predicates that probed git now use `state.disposition` or StepDef.dispositions
5. `StepDef` has `dispositions` and `disposition_repo_types` fields evaluated by the engine
6. The fallback git-probe path in `_close_per_repo_mechanical` is removed
7. Empty repos for non-main pipelines raises a hard error
8. classify_repos has directory-enumeration fallback for corrupted .slot files
9. Sweep fan-out correctly filters by HAS_WORK disposition (#437)
10. Archive step checks all repos via disposition before offering (#438)
11. All changes have unit tests

## References

- Parent spec: `specs/issue-443-robust-pipeline-architecture/2026-10-12-robust-pipeline-architecture-design.md` § Phase 2
- Parent decisions: `specs/issue-443-robust-pipeline-architecture/decisions.md` (D1-D6)
- `project/repo_state.py` — RepoState, classify_repo, classify_repos
- `work-end/work_end_orchestrator.py` — OrchestratorContext, skip predicates, per-repo fan-out
- `project/shared_steps.py` — StepDef, PipelineMode, OrchestratorContextBase
- `verification/step_postconditions.py` — 12 postcondition functions (Phase 3 scope)
- `~/.claude/lib/worklog.py` — events table, existing query functions
- `project/lifecycle.py` — _emit_to_worklog (stores `to_state` in event metadata)
- `work-end/orchestrator_engine.py` — run_loop (modes evaluation)
- Issues: #437 (sweep fan-out filtering), #438 (archive peer-repo precondition)
- `docs/protocols/evidence-before-claims.md`
- `docs/protocols/externalised-scripts-require-tests.md`
