# Pipeline Engine — Python-Driven Lifecycle

**Issue:** #384
**Branch:** issue-384-pipeline-lifecycle
**Date:** 2026-09-28
**Parent spec:** #382 Section E (unified mechanical pipeline)

## Problem

The work lifecycle (start, continue, pause, resume, next, find) is
orchestrated by the LLM reading SKILL.md files. This creates three failure
modes: LLM routing mistakes, no progress tracking for non-close commands,
and skills duplicating mechanical logic. See #384 for full problem
statement.

## Solution

Extend the `orchestrator_engine.run_loop` pattern (proven by
`work_end_orchestrator.py`) to cover the full lifecycle. A single
`project/work.py` entry point where each command maps to a step list.
Mechanical steps run without LLM involvement. Judgment steps yield to
the LLM via the existing `ACTION=` protocol.

## Architecture

### File changes overview

| Action | File | What |
|--------|------|------|
| **Move** | `work-end/orchestrator_engine.py` → `project/orchestrator_engine.py` | Shared engine |
| **Move** | `work-end/shared_steps.py` → `project/shared_steps.py` | StepDef, context base, shared step factories |
| **Move** | `work-end/close_progress.py` → `project/work_progress.py` | Progress tracking (renamed, generalized) |
| **Create** | `project/work.py` | Unified entry point — command parsing, step lists, dispatch |
| **Modify** | `work-end/work_end_orchestrator.py` | Update imports to `project/` |
| **Modify** | `work/SKILL.md` | Shrink to orchestrator loop + dispatch table |
| **Modify** | `work-start/SKILL.md` | Shrink to handler guide |
| **Modify** | `work-pause/SKILL.md` | Shrink to handler guide |
| **Modify** | `work-resume/SKILL.md` | Shrink to handler guide |
| **Create** | Tests for all new/moved modules |

### Single entry point — project/work.py

```python
def main():
    command = parse_command()  # start, continue, pause, resume, next, find
    ctx = build_context()     # reuses ctx.py output
    chain = evaluate_chain(command, ctx)  # reuses work_chain.py
    if chain.directive != "proceed":
        return handle_chain_directive(chain)
    pipeline = PIPELINES[command]
    result = run_loop(pipeline, ctx, ...)
    handle_result(result)
```

The LLM calls `work.py` in a loop until `ACTION=complete`. Each
invocation: read progress, run mechanical steps, yield at next judgment
point, exit. Identical to the work-end pattern.

**Commands handled by work.py:**
- `start` — new branch creation and context setup
- `continue` — resume existing branch
- `pause` — WIP commit + stack push
- `resume` — stack pop + WIP reset
- `next` — advance to next issue in queue
- `find` — discover and populate queue

**Commands NOT handled by work.py (stay in their orchestrators):**
- `end` — work_end_orchestrator.py (1644 lines, proven, stays in work-end/)
- `sync` — work_end_orchestrator.py with mode=sync (shares end pipeline)

The `work/SKILL.md` dispatch table routes `end`/`sync` to
`work_end_orchestrator.py` and all other commands to `work.py`. This is
the incremental migration per D4 — full unification into work.py is a
follow-up once work-end imports are stable under the new paths.

### Engine migration — project/orchestrator_engine.py

Move `orchestrator_engine.py` (322 lines) from `work-end/` to `project/`.
No logic changes — only the file location moves. Update imports in
`work_end_orchestrator.py` to use the new path.

### Progress unification — project/work_progress.py

Rename and generalize `close_progress.py`:

```python
def read_progress(workspace: Path) -> dict[str, str]:
    """Read .work-progress, falling back to .close-progress for compat."""
    wp = workspace / ".work-progress"
    if wp.exists():
        return _parse(wp)
    cp = workspace / ".close-progress"
    if cp.exists():
        return _parse(cp)
    return {}

def update_progress(workspace: Path, key: str, value: str) -> None:
    """Write to .work-progress (always)."""
    ...

def delete_progress(workspace: Path) -> None:
    """Remove .work-progress. Also removes .close-progress if present."""
    ...
```

`work_end_orchestrator.py` continues to call `read_close_progress` /
`update_close_progress` — these become thin wrappers around the new
functions for backward compat. New code uses `read_progress` /
`update_progress` directly.

### Context class

Extend `OrchestratorContextBase` from `shared_steps.py`:

```python
@dataclass
class WorkContext(OrchestratorContextBase):
    command: str = ""
    issue_n: str = ""
    issue_title: str = ""
    owner_repo: str = ""
    plan_path: Path | None = None
    meta_state: str = ""
    has_handoff: bool = False
    handoff_path: Path | None = None
    has_platform_doc: bool = False
    has_protocols_dir: bool = False
    flyway_next_v: str = "none"
    design_repo_key: str = ""
```

Built from `ctx.py` output — all KEY=VALUE pairs mapped to typed fields.

## Step Lists

### start pipeline

| # | Step | Type | Implementation | Skip condition |
|---|------|------|---------------|----------------|
| 1 | `clone_redirect` | mechanical | Check clone feature gate, offer redirect | clone feature OFF (default) |
| 2 | `sync_main` | mechanical | `branch_create.py sync-main` | — |
| 3 | `resolve_issue` | judgment | Yield ACTION=resolve_issue. LLM invokes issue-workflow Phase 2. | issue already resolved (passed as arg) |
| 4 | `stacked_pr_detect` | mechanical | Check issue body for dependency language, find open PR branches | no issue, no issue body |
| 5 | `activate_issues` | mechanical | `issue_setup.py activate-issues` | no GITHUB_PROJECT |
| 6 | `branch_name` | judgment | Yield ACTION=branch_name with suggested slug. LLM confirms/overrides. | — |
| 7 | `flyway_scan` | mechanical | `flyway_scan.py` | flyway_next_v == "none" |
| 8 | `create_branches` | mechanical | `branch_create.py create-branches` | — |
| 9 | `design_routing` | mechanical | `routing.py` + `section_hashes.py` | — |
| 10 | `scaffold` | mechanical | `scaffold.py` | — |
| 11 | `commit_scaffold` | mechanical | `branch_create.py commit-scaffold` | — |
| 12 | `lifecycle_start` | lifecycle | Fire `work_start` transition (idle → scaffolded) | — |
| 13 | `platform_coherence` | judgment | Yield ACTION=platform_coherence with platform doc path | no platform doc |
| 14 | `check_protocols` | judgment | Yield ACTION=check_protocols with protocol paths | no protocols dir |
| 15 | `garden_search` | mechanical | Search garden, return results | no garden configured |
| 16 | `load_specs` | mechanical | Find and list spec files for issue | — |
| 17 | `check_intellij` | mechanical | Check MCP availability | — |
| 18 | `brainstorm_offer` | judgment | Yield ACTION=brainstorm_offer | — |

**Postconditions:**
- `create_branches`: both repos on same branch name
- `scaffold`: .plan exists with state: scaffolded
- `commit_scaffold`: .plan committed to git

### continue pipeline

| # | Step | Type | Implementation | Skip condition |
|---|------|------|---------------|----------------|
| 1 | `auto_resolve_transient` | mechanical | Lifecycle transitions for scaffolded/transitioning → active | state already active |
| 2 | `lifecycle_continue` | lifecycle | Fire `work_continue` transition (self-transition, emits worklog) | — |
| 3 | `health_check` | mechanical | `work_health.py --scope entry` | — |
| 4 | `load_specs` | mechanical | Find and list spec files for active issue | — |
| 5 | `load_context` | judgment | Yield ACTION=load_context with .plan queue state, HANDOFF summary, issue context | — |

`continue` is intentionally short — the branch already exists. The
judgment step (load_context) is where the LLM reads the handoff,
orients itself, and decides what to work on.

### pause pipeline

| # | Step | Type | Implementation | Skip condition |
|---|------|------|---------------|----------------|
| 1 | `wip_commit_project` | mechanical | `pause_exec.py commit-wip <project>` | — |
| 2 | `wip_commit_workspace` | mechanical | `pause_exec.py commit-wip <workspace>` | — |
| 3 | `push_and_stack` | mechanical | `pause_exec.py push-and-stack` | — |

Entirely mechanical. No judgment steps needed.

**Postconditions:**
- `push_and_stack`: STACKED=yes (stack entry exists)

### resume pipeline

| # | Step | Type | Implementation | Skip condition |
|---|------|------|---------------|----------------|
| 1 | `stack_pick` | judgment | Yield ACTION=stack_pick with stack entries. LLM shows picker if multiple. | stack_depth == 1 (auto-select) |
| 2 | `pop_stack` | mechanical | `stack.py pop` | — |
| 3 | `checkout_branches` | mechanical | `resume_exec.py checkout-branches` | — |
| 4 | `rebase` | mechanical | `resume_exec.py rebase` | — |
| 5 | `reset_wip` | mechanical | `resume_exec.py reset-wip` | — |
| 6 | `context_resume` | judgment | Yield ACTION=load_context (same handler as continue) | — |

**Postconditions:**
- `checkout_branches`: both repos on same branch
- `reset_wip`: no WIP: commit as HEAD in either repo

### next pipeline

| # | Step | Type | Implementation | Skip condition |
|---|------|------|---------------|----------------|
| 1 | `lifecycle_next` | lifecycle | Fire `work_next` transition | — |
| 2 | `advance_issue` | mechanical | `plan_manager.py advance` | — |
| 3 | `tick_github` | mechanical | Check off completed issue on epic body | no epic |
| 4 | `context_refresh` | mechanical | Fire `auto_refresh` transition, load new specs | — |
| 5 | `deferred_check` | judgment | Yield ACTION=deferred_check if deferred items exist | no deferred items |

**Postconditions:**
- `advance_issue`: active marker moved to next issue
- `context_refresh`: state is `active`

### find pipeline

| # | Step | Type | Implementation | Skip condition |
|---|------|------|---------------|----------------|
| 1 | `refresh_cache` | mechanical | `enrichment.py refresh` | — |
| 2 | `query_recommendations` | mechanical | `enrichment.py what-next` | — |
| 3 | `present_candidates` | judgment | Yield ACTION=present_candidates with results | — |
| 4 | `populate_queue` | mechanical | `plan_manager.py append` | user selected no items |

## Conflict Resolution Tiers

From #382 D8. Applied during any rebase step across all pipelines.

**Tier 1 — Auto-resolve lifecycle files:**

```python
LIFECYCLE_AUTO_RESOLVE = {
    ".plan", "JOURNAL.md", ".close-progress", ".work-progress",
    ".close-log.jsonl", ".artifacts-promoted",
}
```

When rebase produces conflicts, check if all conflicted files are in
`LIFECYCLE_AUTO_RESOLVE`. If yes, take ours and continue. If not, escalate.

**Tier 2 — LLM semantic resolution:**
Yield `ACTION=resolve_conflict` with the remaining conflicted file list.
The LLM resolves imports, non-overlapping edits.

**Tier 3 — Human intervention:**
If LLM returns `UNRESOLVED=yes`, yield `ACTION=user_input` with the
unresolved file list.

Implementation: add `on_mechanical_error` callback to the rebase step
that classifies the error and routes through the tiers. The
`orchestrator_engine.run_loop` already supports `on_mechanical_error`.

## SKILL.md Changes

### work/SKILL.md

Shrinks to:
1. Parse the user's command
2. Call `python3 project/work.py <command> [args]`
3. Dispatch table mapping ACTIONs to handler files

```markdown
## Orchestrator Loop

Run the orchestrator:
\`\`\`bash
python3 project/work.py <command> workspace=<ws> project=<proj> ...
\`\`\`

Read ACTION= from output. Dispatch:

| ACTION | Handler |
|--------|---------|
| resolve_issue | handlers/resolve-issue.md |
| branch_name | handlers/branch-name.md |
| platform_coherence | handlers/platform-coherence.md |
| check_protocols | handlers/check-protocols.md |
| brainstorm_offer | handlers/brainstorm-offer.md |
| load_context | handlers/load-context.md |
| stack_pick | handlers/stack-pick.md |
| present_candidates | handlers/present-candidates.md |
| deferred_check | handlers/deferred-check.md |
| resolve_conflict | handlers/resolve-conflict.md |
| complete | Done. Report summary. |
| error | Diagnose and retry. |
```

### work-start/SKILL.md, work-pause/SKILL.md, work-resume/SKILL.md

These shrink to: "Invoke work skill which calls work.py." They no
longer contain step-by-step orchestration logic. The judgment handler
files move to `work/handlers/`.

## Testing Strategy

Per `externalised-scripts-require-tests` protocol:

| Module | Tests | Coverage |
|--------|-------|----------|
| `project/work_progress.py` | `tests/test_work_progress.py` | Read/write/delete, backward compat with .close-progress, command-scoped keys |
| `project/work.py` | `tests/test_work_pipeline.py` | Pipeline selection per command, step list composition, dry-run execution of each pipeline, context building from ctx.py output |
| Engine move | `tests/test_orchestrator_engine.py` (existing) | Verify imports work from new location |
| Conflict resolution | `tests/test_conflict_resolution.py` | Tier 1 auto-resolve, Tier 2 yield, Tier 3 escalation |

Existing tests for `pause_exec.py`, `resume_exec.py`, `branch_create.py`,
`scaffold.py` remain unchanged — these scripts are called, not modified.

## Migration Path

### Phase 1: Move shared infrastructure

1. Move `orchestrator_engine.py` → `project/`
2. Move `shared_steps.py` → `project/`
3. Rename + generalize `close_progress.py` → `project/work_progress.py`
4. Update `work_end_orchestrator.py` imports
5. Verify all existing tests pass

### Phase 2: Build work.py

1. Create `project/work.py` with command parsing and context building
2. Add step lists for each command (start, continue, pause, resume, next, find)
3. Mechanical steps delegate to existing scripts
4. Judgment steps yield ACTION= with context
5. Tests: dry-run each pipeline

### Phase 3: Shrink SKILL.md files

1. Create `work/handlers/` directory with handler markdown files
2. Shrink `work/SKILL.md` to orchestrator loop + dispatch table
3. Shrink `work-start/SKILL.md`, `work-pause/SKILL.md`, `work-resume/SKILL.md`
4. Move intent tracking (`.pausing`, `.resuming`) to `.work-progress`

### Phase 4: Conflict resolution tiers

1. Add `LIFECYCLE_AUTO_RESOLVE` set to `project/work.py`
2. Implement `on_mechanical_error` callback for rebase steps
3. Wire into `run_loop` via the existing extension point
4. Tests: conflict classification, auto-resolve, escalation

## What This Eliminates

| Failure mode | How eliminated |
|-------------|---------------|
| LLM skips work-start steps | Python step list runs all steps deterministically |
| LLM misinterprets SKILL.md branching | Python `PIPELINES[command]` handles all routing |
| Session dies mid-start, no recovery | `.work-progress` tracks position |
| LLM routing decisions for pause/resume | Mechanical operations run without LLM |
| Conflict blocks autonomous operation | Three-tier resolution auto-resolves lifecycle files |
| ~1200 lines of SKILL.md for LLM to interpret | Skills shrink to handler guides |
| Intent files (.pausing/.resuming) diverge from progress | Unified `.work-progress` |

## References

- #382 — unified mechanical pipeline (prerequisites A–D, Section E architecture)
- #382 decisions D7 (pipeline scope), D8 (conflict resolution tiers)
- #379 — idempotent pipeline (postconditions, check-execute-verify)
- `work-end/orchestrator_engine.py` — engine pattern (322 lines)
- `work-end/shared_steps.py` — StepDef, OrchestratorContextBase
- `work-end/work_end_orchestrator.py` — proven step list pattern (1644 lines)
- `work-end/close_progress.py` — progress tracking
- `work-start/branch_create.py`, `scaffold.py`, `flyway_scan.py` — existing externalized scripts
- `work-pause/pause_exec.py` — existing externalized pause operations
- `work-resume/resume_exec.py` — existing externalized resume operations
- `project/lifecycle.py` — state machine, TRANSITION_TABLE
- `project/ctx.py` — context resolution
- `project/work_chain.py` — bidirectional chaining engine
- `docs/protocols/skill-md-minimal-orchestrator-loop.md` — SKILL.md minimal protocol
- `docs/protocols/externalised-scripts-require-tests.md` — test requirement
