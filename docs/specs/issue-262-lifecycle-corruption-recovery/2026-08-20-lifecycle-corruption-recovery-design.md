# Lifecycle Corruption Recovery — Design Spec

**Issues:** #262, #263
**Date:** 2026-08-20
**Branch:** issue-262-lifecycle-corruption-recovery

## Problem

The lifecycle state machine can reach inconsistent states: mid-ceremony crash,
stale `.plan` on main, branch deleted but `.plan` remains, queue drift vs GitHub.
Currently, `CorruptedState` exceptions halt the process and require manual
intervention. Invalid state values in `.plan` crash `ctx.py` (work_state.py:111
calls `_read_state()` without catching `CorruptedState`). The LLM has no
structured recovery path — it gets either a hard crash or a soft health warning.

Additionally, `work_health.py` has three functions that compare against literal
`"main"` instead of accepting a `base_branch` parameter (#263).

## Solution

### Architecture

New module `project/corruption.py` with a `diagnose()` function that checks
state-vs-environment coherence. Called by `ctx.py` after state detection.
Returns structured `Finding` objects — never mutates state (D2).

```
┌─────────┐     ┌──────────────┐     ┌───────────────┐
│ ctx.py   │────▶│ work_state.py │────▶│ lifecycle.py   │
│          │     │  detect()     │     │  read_state()  │
│          │     └──────────────┘     └───────────────┘
│          │
│          │────▶┌───────────────┐
│          │     │ corruption.py  │
│          │     │  diagnose()    │
│          │     └───────────────┘
│          │           │
│ CORRUPTION_COUNT=N   │ list[Finding]
│ CORRUPTION_0=...     │
└─────────┘            │
                       │
┌───────────────┐      │
│ work_health.py│──────┘  delegates detection
│  check_*()    │         for overlapping scenarios
└───────────────┘
```

Module boundaries:
- `lifecycle.py` — state machine (transitions, read/write, validation)
- `corruption.py` — state-vs-environment coherence (detection only, no mutation)
- `work_health.py` — advisory checks (delegates to corruption.py for overlapping detection)
- `ctx.py` — data gatherer (calls diagnose(), serialises findings)

### Integration with ctx.py

ctx.py changes:

1. `work_state.py` catches `CorruptedState` in `detect()` instead of crashing:
   ```python
   try:
       meta_state = _read_state(state_file) if state_file else ""
   except CorruptedState as e:
       meta_state = f"corrupted:{e.raw_value}"
   ```

2. ctx.py calls `diagnose()` after `ws_detect()`:
   ```python
   from corruption import diagnose
   findings = diagnose(
       plan_path=Path(state.plan_path) if state.plan_path else None,
       meta_state=state.meta_state,
       project=topo.project,
       workspace=topo.workspace,
       base_branch=base_branch,
       current_branch=current_branch,
       on_main=state.on_main,
       owner_repo=owner_repo,
   )
   ```

3. Serialise findings as indexed KEY=VALUE:
   ```
   CORRUPTION_COUNT=2
   CORRUPTION_0=S5_BRANCH_MISMATCH
   CORRUPTION_0_SEVERITY=error
   CORRUPTION_0_DETAIL=.plan says branch 'issue-42-foo', git says 'main'
   CORRUPTION_0_ACTIONS=switch_to_plan_branch,remove_plan
   CORRUPTION_1=S3_ACTIVE_ALL_CLOSED
   ...
   ```

4. The `work` router checks `CORRUPTION_COUNT > 0` before normal routing.
   If findings exist, enter triage flow instead of the normal lifecycle menu.

---

## Scenarios

### S1: .plan exists, state: missing

**Detection:** `.plan` has a `## State` section but no `state:` line.
`read_state()` already defaults to `'active'` (legacy migration).

**Severity:** warning

**Detail:** "state: field missing from .plan — defaulted to 'active' (legacy migration)"

**Actions:**
1. `accept_default` — acknowledge the default, continue normally
2. `write_scaffolded` — write `state: scaffolded` if branch was just created

**Notes:** This is the legacy migration path from #171. Most cases are
legitimate pre-migration `.plan` files. The finding is informational —
the user should know the default was applied.

### S2: .plan exists, state: invalid

**Detection:** `.plan` has `state:` with an unrecognised value.
`read_state()` raises `CorruptedState`. work_state.py catches it and
stores `meta_state = "corrupted:<raw_value>"`. corruption.py detects
the `corrupted:` prefix.

**Severity:** error

**Detail:** "Unknown state '<raw_value>' in .plan — file may be truncated or hand-edited"

**Actions:**
1. `write_active` — set state to 'active' (safe default for most cases)
2. `infer_from_environment` — check git state, GitHub issues, and closing
   artifacts to infer the correct state
3. `remove_plan` — delete .plan and start fresh

**Notes:** `infer_from_environment` runs a mini-triage: checks if branch
is ahead of base (→ active), if issues are closed (→ drained or closing:*),
if stamp commit exists (→ closing:stamped). This is a best-effort heuristic.

### S3: state: active but all issues closed

**Detection:** `state: active`, read `covers:` from .plan, check each
issue's GitHub state via `gh issue view --json state`.

**Severity:** warning

**Detail:** "state: active but all issues in covers (<list>) are CLOSED on GitHub"

**Actions:**
1. `transition_to_drained` — fire `work_end` → full close ceremony (recommended on branch)
2. `mark_complete_and_next` — if queue has remaining items, advance to next
3. `reopen_issues` — if closure was premature

**Gate:** Requires `owner_repo` to be set. If not, skip this check silently
(no GitHub access = can't verify issue state).

**Performance:** One `gh issue view` per issue in `covers:`. Typically 1-3
issues. Timeout 5s per call, total ≤15s. Falls back to skip on timeout.

### S4: state: closing:* but post-conditions not met

**Detection:** State is `closing:*`. For each closing sub-state, verify
the post-condition that should have been established by reaching that state:

| State | Post-condition check |
|-------|---------------------|
| `closing:review` | No check — review may not have started yet |
| `closing:verified` | No check — just means review passed |
| `closing:promoted` | `.artifacts-promoted` stamp or promotion evidence exists |
| `closing:pushed` | Branch exists on remote (`git ls-remote`) |
| `closing:merged` | Branch content on base branch (`git log base..branch` is empty) |
| `closing:stamped` | Last commit on branch starts with "chore: branch closed" |

If the post-condition for the current state is NOT met, the state was
written but the effect failed — mid-ceremony crash.

**Severity:** error

**Detail:** "state: closing:<sub> but <post-condition> not met — ceremony was interrupted"

**Actions:**
1. `continue_close` — resume from current gate (recommended)
2. `rollback_to_active` — abort close and return to active (only for
   pre-artifact states: closing:review, closing:verified)

**Notes:** For `closing:promoted` and later, rollback is not offered —
artifacts have been promoted, issues closed. Forward-only (matches
lifecycle spec §4.2).

### S5: .plan branch doesn't match current branch

**Detection:** `.plan`'s `branch:` field doesn't match `git branch --show-current`
in the workspace. Excludes the case where current branch is `base_branch`
and `.plan` branch is `base_branch` (valid for main-mode `.plan`).

**Severity:** error

**Detail:** ".plan says branch '<plan_branch>', git says '<current_branch>'"

**Actions:**
1. `switch_to_plan_branch` — `git checkout <plan_branch>` (recommended
   if branch exists)
2. `update_plan_branch` — update .plan to match current branch (if user
   intentionally switched)
3. `remove_plan` — delete .plan and start fresh

**Notes:** Before recommending `switch_to_plan_branch`, check that the
branch exists locally (`git branch --list`). If it doesn't exist, remove
that action from the list and recommend `remove_plan`.

### S6: state: active but branch doesn't exist

**Detection:** `state: active` (or any non-idle state), `.plan`'s `branch:`
field names a branch that doesn't exist locally (`git branch --list` returns
empty) AND doesn't exist on remote (`git ls-remote --heads origin <branch>`
returns empty).

**Severity:** error

**Detail:** "state: active but branch '<branch>' doesn't exist locally or on remote"

**Actions:**
1. `recreate_branch` — create the branch from base_branch (loses all
   prior work on the branch)
2. `remove_plan` — delete .plan and start fresh (recommended — the work
   is gone)

**Notes:** If the branch exists on remote but not locally, the situation
is recoverable: fetch and checkout. In that case, severity is warning and
the recommended action is `fetch_and_checkout`.

### S7: Stale .plan on main after work-end

**Detection:** On `base_branch`, `.plan` exists with `branch:` != `base_branch`,
and state is NOT `drained` (drained `.plan` on main is intentional per #261).

**Severity:** warning (if the branch still exists) / error (if branch deleted)

**Detail:** "stale .plan on main — references branch '<branch>' with state '<state>'"

**Actions:**
1. `switch_to_branch` — checkout the branch to complete the work
   (recommended if branch exists)
2. `remove_plan` — delete .plan (recommended if branch deleted or
   work is finished)

**Notes:** This overlaps with `check_stale_scaffold_on_main` in work_health.py.
After this change, work_health.py delegates detection to corruption.py.

### S8: Queue markers inconsistent with GitHub

**Detection:** `.plan` has `## Queue` with issue checkboxes. Compare
each issue's checked/unchecked state with GitHub:
- Unchecked in .plan but CLOSED on GitHub → inconsistent
- Checked in .plan but OPEN on GitHub → inconsistent

**Severity:** warning

**Detail:** "queue inconsistency: <N> issue(s) differ from GitHub — <list>"

**Actions:**
1. `sync_plan_with_github` — update .plan to match GitHub state (recommended)
2. `ignore` — leave as-is (user may have intentionally reopened/closed)

**Gate:** Same as S3 — requires `owner_repo`, skips on timeout.

**Notes:** This overlaps with `check_plan_state` in work_health.py.
Detection moves to corruption.py. work_health.py's auto-fix behavior
(`mark_completed()`) is retained for the entry/wrap scopes — corruption.py
only detects, work_health.py decides whether to auto-fix in its advisory
context.

---

## corruption.py API

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

@dataclass
class Finding:
    scenario: str        # S1_MISSING_STATE, S2_INVALID_STATE, etc.
    severity: str        # "error" | "warning"
    detail: str          # human-readable description
    actions: list[str]   # ordered, first is recommended

def diagnose(
    plan_path: Optional[Path],
    meta_state: str,
    project: Path,
    workspace: Path,
    base_branch: str = "main",
    current_branch: str = "",
    on_main: bool = False,
    owner_repo: str = "",
) -> list[Finding]:
    """Run all corruption checks. Returns findings (empty = healthy).
    
    Never raises — all exceptions are caught and converted to findings.
    Never mutates state — report only.
    """

# Individual check functions (exported for work_health.py delegation)
def check_missing_state(plan_path: Path) -> Optional[Finding]: ...
def check_invalid_state(meta_state: str, plan_path: Path) -> Optional[Finding]: ...
def check_active_all_closed(plan_path: Path, owner_repo: str) -> Optional[Finding]: ...
def check_closing_postconditions(meta_state: str, plan_path: Path,
                                  project: Path, workspace: Path,
                                  base_branch: str) -> Optional[Finding]: ...
def check_branch_mismatch(plan_path: Path, workspace: Path,
                           current_branch: str, base_branch: str) -> Optional[Finding]: ...
def check_branch_exists(plan_path: Path, project: Path) -> Optional[Finding]: ...
def check_stale_plan_on_main(plan_path: Path, meta_state: str,
                              base_branch: str, on_main: bool) -> Optional[Finding]: ...
def check_queue_consistency(plan_path: Path, owner_repo: str) -> Optional[Finding]: ...
```

Each `check_*` function is a pure detector: takes state + environment,
returns `Optional[Finding]`. `diagnose()` runs all of them and collects
non-None results.

### Execution order and short-circuiting

Checks run in order S1 → S8. Some checks short-circuit:
- If S2 fires (invalid state), skip S3/S4/S6 (they depend on valid state)
- If S5 fires (branch mismatch), skip S6 (branch existence is moot if mismatched)
- S3 and S8 are skipped if `owner_repo` is empty (no GitHub access)

### Git helper

```python
def _git(repo: Path, *args: str, timeout: int = 10) -> tuple[str, int]:
    """Run git command, return (stdout, returncode). Never raises."""
```

Matches `work_health.py`'s existing `_git` pattern. Extract to a shared
utility if a third module needs it.

---

## #263: base_branch threading through work_health.py

Three functions in `work_health.py` compare against literal `"main"`:

| Function | Line | Current | Fix |
|----------|------|---------|-----|
| `check_meta_consistency` | 93,95 | `current == "main"` | `current == base_branch` |
| `check_stale_scaffold_on_main` | 169 | `current != "main"` | `current != base_branch` |
| `check_dirty_main` | 199 | `current != "main"` | `current != base_branch` |

Changes:
1. Add `base_branch: str = "main"` parameter to each function
2. Add `base_branch` parameter to `run_checks()` and `main()`
3. Add `--base-branch` CLI argument
4. Thread from callers — `work/SKILL.md` passes `$BASE_BRANCH` from ctx.py

### work_health.py delegation to corruption.py

After corruption.py exists, refactor the overlapping checks:

```python
def check_meta_consistency(project, workspace, base_branch="main"):
    from corruption import check_branch_mismatch, check_stale_plan_on_main
    # ... use corruption.py detection, format as CHECK=... STATUS=...
```

The refactoring is additive — existing CHECK= output format is preserved.
No caller changes needed.

---

## work/SKILL.md routing changes

The `work` router checks `CORRUPTION_COUNT` before the normal `ROUTE` table:

```
Step 1b — Run the router
  python3 ~/.claude/skills/project/ctx.py

  If CORRUPTION_COUNT > 0:
    → Enter triage flow (present findings, ask user to confirm actions)
  Else:
    → Normal routing based on ROUTE value
```

Triage flow presentation:

```
⚠️ Lifecycle corruption detected (<N> finding(s)):

  1. [error] S5_BRANCH_MISMATCH — .plan says 'issue-42-foo', git says 'main'
     Actions:
       a. switch_to_plan_branch (Recommended)
       b. update_plan_branch
       c. remove_plan

  2. [warning] S8_QUEUE_INCONSISTENT — 2 issue(s) differ from GitHub
     Actions:
       a. sync_plan_with_github (Recommended)
       b. ignore

Pick actions (e.g. "1a 2a") or describe what you want:
```

After the user confirms, the LLM executes the selected actions (git
commands, plan_manager calls, lifecycle.py writes) and re-runs ctx.py
to verify the corruption is resolved.

---

## TDD test cases

### test_corruption.py

```python
import pytest
from pathlib import Path
from corruption import (
    diagnose, Finding,
    check_missing_state, check_invalid_state, check_active_all_closed,
    check_closing_postconditions, check_branch_mismatch,
    check_branch_exists, check_stale_plan_on_main, check_queue_consistency,
)


@pytest.fixture
def plan_file(tmp_path):
    """Create a minimal .plan file."""
    plan = tmp_path / ".plan"
    plan.write_text(
        "# Work Plan\n\n## State\n"
        "branch: issue-42-foo\nstate: active\ndate: 2026-08-20\n"
        "issue-repo: Hortora/soredium\ncovers: 42\n\n"
        "## Queue\n- [ ] #42 — Fix foo ← active\n"
    )
    return plan


class TestS1MissingState:
    def test_missing_state_field_returns_warning(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: issue-42-foo\ndate: 2026-08-20\n\n"
            "## Queue\n"
        )
        finding = check_missing_state(plan)
        assert finding is not None
        assert finding.scenario == "S1_MISSING_STATE"
        assert finding.severity == "warning"
        assert "accept_default" in finding.actions

    def test_present_state_field_returns_none(self, plan_file):
        assert check_missing_state(plan_file) is None

    def test_no_plan_returns_none(self, tmp_path):
        assert check_missing_state(tmp_path / ".plan") is None


class TestS2InvalidState:
    def test_corrupted_prefix_returns_error(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: issue-42-foo\nstate: closing:pro\n\n"
            "## Queue\n"
        )
        finding = check_invalid_state("corrupted:closing:pro", plan)
        assert finding is not None
        assert finding.scenario == "S2_INVALID_STATE"
        assert finding.severity == "error"

    def test_valid_state_returns_none(self, plan_file):
        assert check_invalid_state("active", plan_file) is None


class TestS3ActiveAllClosed:
    def test_skipped_without_owner_repo(self, plan_file):
        assert check_active_all_closed(plan_file, owner_repo="") is None

    # GitHub-dependent tests use monkeypatch on subprocess.run


class TestS4ClosingPostconditions:
    def test_closing_stamped_without_stamp_commit(self, tmp_path, monkeypatch):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: issue-42-foo\nstate: closing:stamped\n\n"
            "## Queue\n"
        )
        # Mock git log to return non-stamp last commit
        monkeypatch.setattr(
            "corruption.subprocess.run",
            lambda *a, **kw: type('R', (), {'stdout': 'feat: add feature\n', 'returncode': 0})()
        )
        finding = check_closing_postconditions(
            "closing:stamped", plan, tmp_path, tmp_path, "main"
        )
        assert finding is not None
        assert finding.scenario == "S4_CLOSING_POSTCONDITION"

    def test_non_closing_state_returns_none(self, plan_file):
        assert check_closing_postconditions(
            "active", plan_file, Path("/tmp"), Path("/tmp"), "main"
        ) is None


class TestS5BranchMismatch:
    def test_mismatch_returns_error(self, plan_file):
        finding = check_branch_mismatch(
            plan_file, plan_file.parent, current_branch="main", base_branch="main"
        )
        # plan says issue-42-foo, current is main
        assert finding is not None
        assert finding.scenario == "S5_BRANCH_MISMATCH"

    def test_matching_branches_returns_none(self, plan_file):
        finding = check_branch_mismatch(
            plan_file, plan_file.parent,
            current_branch="issue-42-foo", base_branch="main"
        )
        assert finding is None

    def test_main_plan_on_main_returns_none(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: main\nstate: active\n\n## Queue\n"
        )
        finding = check_branch_mismatch(
            plan, tmp_path, current_branch="main", base_branch="main"
        )
        assert finding is None


class TestS6BranchNotExist:
    def test_missing_branch_returns_error(self, plan_file, monkeypatch):
        monkeypatch.setattr(
            "corruption.subprocess.run",
            lambda *a, **kw: type('R', (), {'stdout': '', 'returncode': 0})()
        )
        finding = check_branch_exists(plan_file, plan_file.parent)
        assert finding is not None
        assert finding.scenario == "S6_BRANCH_NOT_EXIST"

    def test_no_plan_returns_none(self, tmp_path):
        assert check_branch_exists(tmp_path / ".plan", tmp_path) is None


class TestS7StalePlanOnMain:
    def test_stale_plan_on_main(self, plan_file):
        # plan says branch: issue-42-foo, but we're on main
        finding = check_stale_plan_on_main(
            plan_file, meta_state="active", base_branch="main", on_main=True
        )
        assert finding is not None
        assert finding.scenario == "S7_STALE_PLAN_ON_MAIN"

    def test_drained_plan_on_main_is_ok(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: main\nstate: drained\n\n## Queue\n"
        )
        finding = check_stale_plan_on_main(
            plan, meta_state="drained", base_branch="main", on_main=True
        )
        assert finding is None

    def test_not_on_main_returns_none(self, plan_file):
        finding = check_stale_plan_on_main(
            plan_file, meta_state="active", base_branch="main", on_main=False
        )
        assert finding is None


class TestS8QueueConsistency:
    def test_skipped_without_owner_repo(self, plan_file):
        assert check_queue_consistency(plan_file, owner_repo="") is None


class TestDiagnose:
    def test_healthy_state_returns_empty(self, plan_file):
        findings = diagnose(
            plan_path=plan_file,
            meta_state="active",
            project=plan_file.parent,
            workspace=plan_file.parent,
            base_branch="main",
            current_branch="issue-42-foo",
            on_main=False,
        )
        assert findings == []

    def test_no_plan_returns_empty(self, tmp_path):
        findings = diagnose(
            plan_path=None,
            meta_state="",
            project=tmp_path,
            workspace=tmp_path,
        )
        assert findings == []

    def test_multiple_findings_returned(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: issue-42-foo\ndate: 2026-08-20\n\n"
            "## Queue\n"
        )
        findings = diagnose(
            plan_path=plan,
            meta_state="active",
            project=tmp_path,
            workspace=tmp_path,
            current_branch="main",
            on_main=True,
            base_branch="main",
        )
        scenarios = {f.scenario for f in findings}
        # S1 (missing state) and S7 (stale plan on main) should both fire
        assert "S1_MISSING_STATE" in scenarios
        assert "S7_STALE_PLAN_ON_MAIN" in scenarios

    def test_invalid_state_short_circuits(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: issue-42-foo\nstate: bogus\n\n"
            "## Queue\n"
        )
        findings = diagnose(
            plan_path=plan,
            meta_state="corrupted:bogus",
            project=tmp_path,
            workspace=tmp_path,
            current_branch="issue-42-foo",
        )
        scenarios = {f.scenario for f in findings}
        assert "S2_INVALID_STATE" in scenarios
        # S3, S4, S6 should NOT fire (depend on valid state)
        assert "S3_ACTIVE_ALL_CLOSED" not in scenarios
        assert "S4_CLOSING_POSTCONDITION" not in scenarios
        assert "S6_BRANCH_NOT_EXIST" not in scenarios


class TestBaseBranchParameter:
    """#263 — verify base_branch is threaded, not hardcoded."""

    def test_non_main_base_branch(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: develop\nstate: drained\n\n## Queue\n"
        )
        # drained plan with branch: develop on develop should be ok
        finding = check_stale_plan_on_main(
            plan, meta_state="drained", base_branch="develop", on_main=True
        )
        assert finding is None
```

### test_work_health_base_branch.py

```python
class TestBaseBranchThreading:
    """#263 — hardcoded 'main' replaced with base_branch parameter."""

    def test_check_meta_consistency_uses_base_branch(self, ...):
        # On develop with plan saying develop — should be ok
        ...

    def test_check_stale_scaffold_uses_base_branch(self, ...):
        # On develop, stale scaffold detection uses develop
        ...

    def test_check_dirty_main_uses_base_branch(self, ...):
        # On develop, dirty check uses develop
        ...

    def test_run_checks_passes_base_branch(self, ...):
        # Verify base_branch flows through run_checks to individual checks
        ...
```

---

## Files changed

| File | Change | Description |
|------|--------|-------------|
| `project/corruption.py` | New | 8 corruption checks + diagnose() + Finding dataclass |
| `tests/test_corruption.py` | New | Tests for all 8 scenarios + diagnose() |
| `project/work_state.py` | Modify | Catch CorruptedState in detect(), store as `corrupted:<value>` |
| `project/ctx.py` | Modify | Call diagnose(), serialise findings as CORRUPTION_* KEY=VALUE |
| `project/work_health.py` | Modify | Thread base_branch (#263), delegate overlapping checks to corruption.py |
| `tests/test_work_health.py` | New/Modify | Tests for base_branch threading |
| `work/SKILL.md` | Modify | Add triage flow for CORRUPTION_COUNT > 0 |

## Implementation order

1. **corruption.py + tests** — pure detection, no integration yet
2. **work_state.py** — catch CorruptedState
3. **ctx.py** — call diagnose(), emit CORRUPTION_* lines
4. **work_health.py** — thread base_branch (#263), delegate to corruption.py
5. **work/SKILL.md** — triage routing

Each step is independently testable. Steps 1-4 are Python with pytest.
Step 5 is a skill update.

## References

- project/lifecycle.py — state machine, CorruptedState exception, VALID_STATES
- project/work_state.py:111 — latent crash on CorruptedState
- project/work_health.py:93,169,199 — hardcoded "main" (#263)
- project/ctx.py — KEY=VALUE output contract, integration point
- docs/specs/issue-171-lifecycle-state-machine — state machine design, §9 Stale State Recovery, §14.7 Unknown state values
- docs/specs/issue-261-unified-work-queue — drained state, base_branch audit (R1-11)
- GE-20260803-263c2c — explicit state machine replaces inference
- GE-20260803-293dd2 — three-phase transition protocol
- GE-20260817-649902 — .meta → .plan phantom tracked files
- docs/protocols/externalised-scripts-require-tests.md — tests required for new scripts
- docs/protocols/evidence-before-claims.md — verify before claiming
