# Work-End v2: Atomic Close Ceremony

**Date:** 2026-11-04
**Issue:** Hortora/soredium#499
**Status:** Draft
**Supersedes:** Current work-end orchestrator (work_end_orchestrator.py, 2,250 LOC)

## Problem Statement

Work-end has accumulated 80 issues in 70 days (>1/day). The system cannot be
stabilised by patching — structural problems guarantee new bugs appear as fast
as old ones close.

**Root causes:**

1. **Dual-purpose `.plan`** — simultaneously an issue queue and lifecycle state
   container. 7 independent deletion paths, only 3 guard the queue. Every
   plan-wipe bug (#358, #364, #442, #466, #485, #496, #498) is this coupling.

2. **Combinatorial pipeline** — 53 steps × 5 modes × 5 repo dispositions.
   Each fix touches one execution path and can break others silently.

3. **Scattered state** — `.close-progress`, `.plan state:`, git HEAD, and LLM
   context can all disagree. No consistency protocol, no transaction boundary.

4. **Bolt-on multi-repo** — mutable `OrchestratorContext` overridden per repo
   iteration. Every step must use `getattr(ctx, "current_repo_project", None)
   or ctx.project` — miss one and it's a bug (14 multi-repo issues).

5. **Recovery creates failure** — reconciliation resets progress, phase-skip
   fills gaps, lifecycle transitions fail on concurrent modification. Each
   recovery mechanism creates new failure modes (13 loop/stall bugs).

## Design Decisions

Six decisions captured in `decisions.md`:

| # | Decision | Key consequence |
|---|----------|----------------|
| D1 | Strip to essential close ceremony | 53 steps → 7 steps |
| D2 | Separate queue from ceremony state | .plan split into .queue + ephemeral .close-state |
| D3 | One ceremony, different inputs | 5 modes → resolve phase produces CloseTarget list |
| D4 | Fully mechanical execution | No LLM loop, no progress file, no reconciliation |
| D5 | Eliminate most corruption triage | 620 lines → ~50 lines of git-level pre-flight |
| D6 | Replace state machine with status field | 776 lines, 12 states → 4 status values |

## Architecture

### Three-Phase Model

```
PRE-CLOSE (LLM-driven, independent, writes to git)
    │
    │  git committed state only
    ▼
CLOSE CEREMONY (single Python invocation, mechanical)
    │
    │  queue updated, repos on main
    ▼
POST-CLOSE (reads committed state, failures non-fatal)
```

Each phase communicates with the next only through committed git state. No
shared mutable files, no progress tracking, no reconciliation.

**Failure isolation guarantee:** Pre-close failures do not corrupt ceremony
state. Ceremony failures do not destroy the queue. Post-close failures do
not invalidate the landed code.

### Pre-Close Phase

The LLM runs judgment work through normal skill invocations — not through
an orchestrator pipeline. Each item writes to git independently:

1. **Code review** — `code-review` / `branch-audit` skill
2. **Squash plan** — decide on squash commit message and strategy (the actual
   squash happens in the ceremony's `land` step via `squash_merge`)
3. **Content creation** — `write-content` skill for blog/diary
4. **Artifact promotion** — copy specs, ADRs from workspace to project repo
5. **Uncommitted changes** — commit or stash outstanding work

These are standard skill invocations using existing infrastructure. They
are not orchestrator steps. They do not share mutable state with each other
or with the close ceremony.

The work-end SKILL.md presents a pre-close checklist. The user (or the LLM
following the checklist) completes items and confirms readiness. **Pre-close
is advisory, not enforced** — the user can skip it and run the ceremony
directly. The ceremony reads only committed git state; anything not committed
before ceremony start is not included. The risk of skipping pre-close is
landing without review or blog, not data corruption.

**What disappears:**
- `forcing_function` step — pre-close items don't block the ceremony
- `loose_ends_sweep` — the pre-close checklist replaces it
- `verify_recover` — nothing to recover from
- Handler `.md` files — judgment stays in the LLM via skills, not dispatched handlers

### Close Ceremony

Single Python entry point: `python3 work-end/close.py <workspace>`

No arguments for mode, repo, evidence, or state. Reads everything from git
and `.queue`.

#### Step 1: Resolve

Determine what to close. Read `.queue` for the active item and branch name.
Discover repos and classify which have the branch with commits.

```python
@dataclass(frozen=True)
class CloseTarget:
    repo: Path              # the repo to land
    branch: str             # the feature branch name
    base_branch: str        # target branch (usually "main", configurable per repo)
    transport: str          # "direct" or "two-hop" (slot clones use canonical as relay)
    canonical: Path | None  # canonical repo path (two-hop only)
    push_target: str        # remote to push to ("origin", "upstream", or local remote name)
    mirror_target: str      # fork-model: remote to mirror to after push ("origin" for forks, "" otherwise)
    is_workspace: bool      # workspace repos have design artifacts, not source code

def resolve(workspace: Path) -> list[CloseTarget]:
    queue = read_queue(workspace)
    branches = discover_active_branches(workspace, queue)
    targets = []
    for branch in branches:
        for repo, base, transport, canonical, push, mirror in discover_repo_topology(workspace):
            if branch_exists(repo, branch) and has_commits(repo, branch, base):
                is_ws = (repo == workspace)
                targets.append(CloseTarget(
                    repo=repo, branch=branch, base_branch=base,
                    transport=transport, canonical=canonical,
                    push_target=push, mirror_target=mirror,
                    is_workspace=is_ws))
    return targets
```

**Branch discovery:** `discover_active_branches()` reads `queue.branch` for
the active item's branch. In a slot context, it also scans all slot repos for
additional feature branches (repos on different branches for different issues).
This handles cumulative slot close (#493) — all active branches are collected
and closed in one ceremony. Replaces `scan-branches` from `work_end_execute.py`.

**Repo topology discovery:** `discover_repo_topology()` determines which repos
participate and how they push:

1. **Slot detection:** Reads `.slot` files for slot topology. Each slot clone
   gets `transport="two-hop"` with `canonical` pointing to the canonical repo.
   Canonical resolution follows git remotes (`local` → `origin`, checking for
   local directory paths). Push target for slot clones is the local remote
   pointing at the canonical.

2. **Branch mode fallback:** For non-slot branches, discovers `project` +
   `workspace` repos. Also scans `family_root` for sibling repos that have
   the branch with commits ahead — handles multi-repo projects.

3. **Fork model detection:** For each repo, `push_target` is "upstream" if an
   `upstream` remote exists (fork model), otherwise "origin". `mirror_target`
   is "origin" for fork-model repos (push to upstream, mirror to fork), empty
   otherwise.

4. **Base branch:** Read from repo configuration (default "main").

Replaces `classify_repos()` in `repo_state.py`, `build_slot_batch()` and
`build_branch_batch()` in `land_flow.py`, and `_detect_push_target()` /
`_detect_mirror_target()`.

A slot with 3 repos produces 3 targets. A single-repo branch produces 1 (or 2
with workspace). The ceremony doesn't know or care about the difference —
`transport` tells `land()` how to push, `push_target` tells it where.

#### Step 2: Pre-flight Checks

Verify preconditions before mutating anything:

```python
def preflight(targets: list[CloseTarget]) -> dict:
    errors = []
    rescued = {}
    for t in targets:
        if is_dirty(t.repo):
            errors.append(f"{t.repo.name}: uncommitted changes")
        if not branch_exists(t.repo, t.base_branch):
            errors.append(f"{t.repo.name}: no {t.base_branch} branch")
        if not remote_reachable(t.repo, t.push_target):
            errors.append(f"{t.repo.name}: remote {t.push_target} not reachable")
        # Rescue local-only commits on base branch
        local_only = commits_ahead_of_remote(t.repo, t.base_branch, t.push_target)
        if local_only > 0:
            rescue_name = f"rescue-{t.repo.name}"
            create_branch(t.repo, rescue_name, t.base_branch)
            reset_to_remote(t.repo, t.base_branch, t.push_target)
            rescued[t.repo.name] = rescue_name
    return {"errors": errors, "rescued": rescued}
```

**Local-only commit rescue:** If the base branch has commits not on the
remote (from an interrupted prior ceremony that merged but didn't push),
`preflight()` rescues them to a named branch before resetting to match
remote. Without this, `pull()` during `land()` could destroy local-only
work. Preserves the safety logic from `_preflight_direct()` in the current
`land_flow.py`.

Replaces: most of `corruption.py` (620 lines, 17+ scenarios). Pre-flight
checks refuse to run rather than trying to recover after the fact.

#### Step 3: Land (per target)

Squash-merge branch to base for each target:

```python
LIFECYCLE_FILES = [
    "JOURNAL.md", ".close-state", ".execute-progress",
    ".land-ledger.jsonl", ".artifacts-promoted", ".squash-plan",
    ".close-progress", ".close-report.json",
    ".close-log.jsonl", ".wrap-log.jsonl", ".work-progress",
]

def land(target: CloseTarget) -> str:
    # Idempotency: if branch content already on base, skip.
    # Two checks: (a) branch HEAD is ancestor of base (ff-merge case),
    # (b) no source-file diff between branch and base (squash case).
    if branch_already_landed(target.repo, target.branch, target.base_branch):
        return find_landed_sha(target.repo, target.branch, target.base_branch)

    # TWO_HOP workspace repos are stamp-only — no merge, no push.
    # Slot workspace clones have no direct remote; content is design artifacts.
    if target.is_workspace and target.transport == "two-hop":
        return ""

    # Read squash plan BEFORE stripping (it's consumed by squash_merge)
    squash_msg = read_squash_plan(target.repo) if not target.is_workspace else None

    checkout(target.repo, target.base_branch)
    pull(target.repo, target.push_target, target.base_branch)

    if target.is_workspace:
        # Workspace repos: strip lifecycle files, then non-ff merge (ADR-0016).
        # Strip is pre-merge for workspace because lifecycle files must not
        # reach base branch (ADR-0016: lifecycle on workspace main → corruption).
        # No rebase for workspace — non-linear history is acceptable for
        # methodology artifacts.
        strip_lifecycle_files(target.repo, target.branch, LIFECYCLE_FILES)
        sha = merge_no_ff(target.repo, target.branch)
    else:
        # Project repos: rebase onto base, then squash-merge.
        # Rebase brings the branch onto the base branch tip so that
        # ff-merge is possible after squashing. Without rebase, the
        # branch diverges from base whenever other work has landed,
        # and git merge --ff-only fails.
        rebase_onto_base(target.repo, target.branch, target.base_branch,
                         target.push_target)
        sha = squash_merge(target.repo, target.branch,
                           target.base_branch, squash_msg)

    # Post-merge: strip lifecycle files from base branch if any leaked through
    strip_lifecycle_files_from_tree(target.repo, target.base_branch, LIFECYCLE_FILES)

    # Content verification: check that source files from the branch appear
    # on base after merge. Catches silent content loss from merge conflicts.
    verify_content_landed(target.repo, target.branch, target.base_branch)

    # Push
    if target.transport == "two-hop":
        push_two_hop(target.repo, target.canonical)
    else:
        push(target.repo, target.push_target, target.base_branch)
        # Fork model: mirror to fork remote after pushing to upstream
        if target.mirror_target:
            push(target.repo, target.mirror_target, target.base_branch,
                 force_with_lease=True)
    return sha
```

**`rebase_onto_base()` semantics:** Checkout the feature branch, fetch the
remote base branch, and rebase onto it. This brings the branch onto the base
branch tip so that the subsequent ff-merge can succeed. Includes:
- **Skip check:** If the remote base is already an ancestor of HEAD, the
  branch is already on top — skip rebase (avoids re-rebasing after a prior
  squash step, per #486).
- **3 retry attempts:** Rebase can fail due to conflicts. On each failure,
  `git rebase --abort` and retry. After 3 failures, record the conflict
  (repo, branch, commit count, error) and stop the ceremony.
- **Workspace skip:** Workspace repos are never rebased (ADR-0016) — they
  use non-ff merge instead.

**`squash_merge()` semantics:** After rebase, the branch is on top of the
base branch tip. Soft-reset to the base branch tip (which is now the
merge-base, since rebase made it so) and recommit all changes as a single
commit using the squash plan message. Then checkout the base branch and
`git merge --ff-only` the feature branch. This produces a clean
single-commit on the base branch while keeping the branch tip as an ancestor
of the base (so `branch_already_landed()` can use `merge-base --is-ancestor`
for idempotency). If no squash plan exists, the commit messages are
concatenated.

**`branch_already_landed()` idempotency:** Two detection methods: (a) branch
HEAD is an ancestor of the base branch (ff-merge or squash-then-ff case), and
(b) no source-file diff between branch and base (content-identical check for
cases where ancestry was lost). Both methods are needed for robustness.

**Workspace handling (ADR-0016):** DIRECT workspace repos get non-ff merge
(workspace history may diverge from base). TWO_HOP workspace repos (slot
clones) are stamp-only — they have no direct remote and their content is
design artifacts, not source code. For TWO_HOP workspace repos, `land()`
returns an empty SHA; `stamp()` uses the project repo's SHA instead.

**Lifecycle file stripping:** Two-stage approach. Stage 1: for workspace repos,
strip from the branch before merge (prevents lifecycle files from reaching
base branch per ADR-0016). Stage 2: for all repos, strip from the base branch
tree after merge (defensive cleanup catches any files that leaked through
squash or non-ff merge). If merge fails, the branch retains its lifecycle
files for retry (lesson from #466).

**Content verification:** After merge, checks that source files (by extension)
from the branch appear on the base branch. If content is missing, the ceremony
stops. This is the replacement for `_verify_content_landed()` and
`verify_stamp.py` — same safety check, integrated into the ceremony flow.

**Fork model:** Repos with an `upstream` remote (canonical repo) and `origin`
(fork) push to upstream first, then mirror to origin. `push_target` and
`mirror_target` on `CloseTarget` encode this. Replaces `upstream_push.py`.

**Two-hop transport:** Slot clones push to a canonical repo via the local
remote, which then pushes to origin. `push_two_hop()` handles this relay.

#### Step 4: Stamp (per target)

Mark each branch as closed with an empty commit containing the landed SHA:

```python
def stamp(target: CloseTarget, landed_sha: str):
    # Idempotency: if already stamped, skip
    if is_stamp_commit(target.repo, target.branch):
        return

    # TWO_HOP workspace: use project repo's SHA if no independent SHA
    effective_sha = landed_sha or find_project_sha(landed_shas)

    checkout(target.repo, target.branch)
    commit_empty(target.repo,
        f"chore: branch closed — landed as {effective_sha} on {target.base_branch}")

    # Push stamp to appropriate remote
    stamp_remote = target.push_target
    if target.mirror_target:
        stamp_remote = target.mirror_target  # stamps go to fork, not upstream
    push(target.repo, stamp_remote, target.branch, force_with_lease=True)

    # Record branch closure in worklog database
    record_worklog_end(target.branch, target.repo, effective_sha)
```

**Idempotency:** If the branch tip is already a stamp commit (matches
prefix `"chore: branch closed"`), skip.

**Worklog recording:** Records branch closure in the worklog database for
observability (used by `work_progress.py` and the TUI). Non-fatal if worklog
is unavailable.

#### Step 5: Elevate Queue (slots only)

For slot workspaces, elevate `.queue` to the slot root before checking out
the base branch. The `.queue` lives on the feature branch; after checkout,
it would be replaced by whatever is on the base branch. Must run while
still on the feature branch.

```python
def elevate_queue(workspace: Path, slot_root: Path | None):
    if not slot_root:
        return  # non-slot: .queue lands on base via workspace merge
    ws_queue = workspace / ".queue"
    slot_queue = slot_root / ".queue"
    if not ws_queue.exists():
        return
    # CRITICAL (#496): Never overwrite a slot-level queue that already
    # exists. The slot queue is the epic queue (all issues in the slot).
    # The workspace queue is a single-issue subset.
    if slot_queue.exists():
        return
    copy(ws_queue, slot_queue)
```

#### Step 6: Checkout Base Branch

Switch all repos to their base branch:

```python
def checkout_all(targets: list[CloseTarget]):
    for target in targets:
        checkout(target.repo, target.base_branch)
```

#### Step 7: Advance Queue and Persist

Mark the active item done, activate the next, commit and push:

```python
def advance(workspace: Path, expected_issue: str) -> QueueItem | None:
    queue = read_queue(workspace)
    active = queue.active_item()

    # Idempotency guard: refuse to advance if the active item doesn't match
    # what we're closing. Prevents crash-then-re-run from skipping a queue
    # item — if advance() already ran, the active item will have changed,
    # and this check prevents advancing again.
    if active is None or active.ref != expected_issue:
        return queue.active_item()  # already advanced or wrong item

    queue.complete_active()
    if queue.has_next():
        queue.activate_next()
        queue.set_status("active")
    else:
        queue.set_status("drained")
    write_queue(workspace, queue)
    return queue.active_item()

def commit_and_push_queue(workspace: Path, closing_issue: str):
    """Commit the queue advancement to git and push."""
    if not (workspace / ".queue").exists():
        return  # slot stamp-only workspace — .queue not on base branch
    git_add(workspace, ".queue")
    git_commit(workspace, f"chore: advance queue — completed {closing_issue}")
    push(workspace)
```

**`expected_issue`** comes from `.close-state` (written at ceremony start with
the issue being closed). On re-run after crash, if `advance()` already
completed, the active item will be the *next* issue (not the one being closed),
so the guard prevents double-advancing.

**Dual-path ordering:** The ceremony handles slot and non-slot workspaces
differently because `.queue` accessibility varies by transport mode:

- **Non-slot (DIRECT workspace):** `land()` merged the workspace to the base
  branch, so `.queue` exists on base. The ceremony checks out the base branch
  first, then advances `.queue` there, then commits and pushes. The queue
  change is persisted in git.

- **Slot (TWO_HOP workspace):** The workspace was stamp-only — never merged
  to base. `.queue` does NOT exist on the base branch. The ceremony advances
  `.queue` while still on the feature branch (where it exists), then elevates
  the ADVANCED queue to the slot root, then checks out the base branch. The
  slot root is outside git and persists on disk across sessions. No
  `commit_and_push` is needed — the next work-start reads from the slot root.

**Crash safety (slot path):** `advance()` writes `.queue` to disk on the
feature branch (uncommitted). If the session crashes before `elevate_queue()`,
the on-disk `.queue` has the advanced content. On re-run, `advance()`'s
expected-issue guard detects that the active item has changed (advance already
ran) and is a no-op. `elevate_queue()` copies the (now-advanced) on-disk
`.queue` to the slot root. The advance survives the crash.

This is the **only** function that writes to `.queue` during close. No other
step reads, writes, or deletes the queue file.

#### Orchestration

```python
def close(workspace: Path) -> CloseResult:
    targets = resolve(workspace)

    # Guard: refuse to proceed with no targets
    if not targets:
        return CloseResult(success=False,
            errors=["no targets found — branch may not exist or has no commits"])

    queue = read_queue(workspace)
    closing_issue = queue.active_item().ref

    # Write ephemeral state with session ID and closing issue.
    # If .close-state exists from a prior session, verify it matches
    # this ceremony's issue — refuse if another session is running.
    write_close_state(workspace, {
        "step": "resolving",
        "closing_issue": closing_issue,
        "session_id": generate_session_id(),
        "repos": format_repo_list(targets),
    })

    pre = preflight(targets)
    if pre["errors"]:
        remove_close_state(workspace)
        return CloseResult(success=False, errors=pre["errors"])

    try:
        landed = {}
        for target in targets:
            sha = land(target)
            landed[target] = sha

        for target, sha in landed.items():
            stamp(target, sha)

        # Queue advancement: slot and non-slot paths differ because
        # .queue accessibility depends on the workspace transport mode.
        slot_root = detect_slot_root(workspace)

        if slot_root:
            # SLOT PATH: advance while on feature branch (where .queue
            # exists — stamp-only workspace was never merged to base).
            # Then elevate the ADVANCED queue to slot root.
            next_item = advance(workspace, closing_issue)
            elevate_queue(workspace, slot_root)
            checkout_all(targets)
            # No commit_and_push needed — slot root is outside git,
            # persists on disk across sessions. The next work-start
            # reads from slot root.
        else:
            # NON-SLOT PATH: checkout base first (where .queue exists,
            # merged there by land()). Advance on base, then commit
            # and push to persist the change.
            checkout_all(targets)
            next_item = advance(workspace, closing_issue)
            commit_and_push_queue(workspace, closing_issue)

        remove_close_state(workspace)
        return CloseResult(
            success=True,
            landed=landed,
            next_item=next_item,
            rescued=pre["rescued"],
        )
    except Exception:
        # Ensure repos are on a known branch even on failure.
        # Don't remove .close-state — it signals interrupted ceremony.
        checkout_all(targets)
        raise
```

Each step is idempotent. Re-running after a partial failure picks up where it
left off by checking what's already done (landed? stamped? advanced?). The
error handler ensures repos aren't left on mixed branches after a failure —
`checkout_all()` runs before re-raising.

**Queue persistence:** `commit_and_push_queue()` commits the `.queue` change
to the base branch and pushes. This ensures queue advancement survives session
termination, `git checkout .`, or `git reset`. Without this commit, the
advancement would be an uncommitted modification lost on any working directory
reset. Mirrors the current `fork_next_branch.py` behavior (line 106:
`_git(workspace, "add", ".plan")` then `_git(workspace, "commit", ...)`).

**Concurrent session protection:** `write_close_state()` checks for an
existing `.close-state` file. If one exists with a different `session_id`,
the ceremony refuses to proceed — another session is already running.
If the same `session_id` (re-run), it continues.

### Post-Close Phase

After ceremony returns successfully, the SKILL.md runs cleanup through
normal tool calls:

1. **Close GitHub issues** — `gh issue close` for completed queue items
2. **Archive slot** — if slot and queue is drained, mark for archival
3. **Summary** — print what was landed, where, what's next

Post-close failures are logged but non-fatal. The branch is already landed
and stamped.

## Data Model

### `.queue` — Issue Queue

Replaces `.plan`. Lives in workspace root. Survives across branch close
cycles. Never touched by close ceremony except the `advance` step.

```markdown
- [x] Hortora/soredium#381 — Implement batch processing
- [ ] Hortora/soredium#382 — Add retry logic        ← active
- [ ] Hortora/soredium#383 — Dashboard metrics

## State
branch: issue-382-retry-logic
issue-repo: Hortora/soredium
status: active
```

The `branch:` field tracks the current feature branch. It changes when a new
queue item is activated (each item may use a different branch name).

**Status values:** `active` | `paused` | `drained` | `idle`

- `active` — branch exists, work in progress or close ceremony running
- `paused` — branch exists, work suspended (pause stack)
- `drained` — last item completed, no more work, queue persists for reference
- `idle` — no active work (fresh queue before first `work start`)

**Interaction with work-start:** When `work start` begins on an `idle` queue,
it sets status to `active` and writes the `branch:` field. If work-start is
interrupted, the queue is left in `idle` with no branch — distinguishable
from a completed queue (`drained`) by the absence of completed items. No
`scaffolded` state is needed; the work-start skill checks for the branch's
existence directly.

**Queue I/O module:** `project/queue_io.py` — the single reader/writer for
`.queue` files. All queue mutations go through this module. There is no
`remove_queue()` function — the queue is never deleted during normal operation.

**Deferred section and batches:** Preserved from current `.plan` format. The
queue file may contain `## Deferred` and batch structure. These are orthogonal
to the close ceremony and managed by `plan_manager.py` (renamed to
`queue_manager.py`).

### `.close-state` — Ephemeral Ceremony State

Created on ceremony entry, deleted on success. If present at session start,
it means a ceremony was interrupted.

```
started: 2026-11-04T12:00:00Z
session_id: a3f7c1
closing_issue: Hortora/soredium#382
repos: soredium:issue-382,cc-praxis:issue-382
step: land
```

**`closing_issue`:** The queue item being closed. Used by `advance()` as the
expected-issue guard — prevents crash-then-re-run from skipping a queue item.

**`session_id`:** Random ID for this ceremony invocation. Used for concurrent
session protection — if `.close-state` exists with a different `session_id`,
the ceremony refuses to proceed.

**Recovery from interrupted ceremony:** The user runs `work end` again. The
ceremony detects `.close-state`, checks idempotency conditions (already
landed? already stamped? already advanced?), and continues from where it left
off. There is no reconciliation engine or progress dictionary — just
idempotent git state checks at each step. This is lightweight reconciliation
via committed state, not the progress-dict-based reconciliation engine that
the current system uses.

### Migration from `.plan`

On first read, if `.plan` exists:
1. Rename to `.queue`
2. Read existing `state:` field to determine migration path:
   - `active`, `scaffolded` → set `status: active`
   - `paused` → set `status: paused`
   - `drained` → set `status: drained`
   - `closing:promoted` or later (`closing:pushed`, `closing:merged`,
     `closing:stamped`) → a ceremony was in progress. Create a `.close-state`
     file preserving the ceremony context (closing issue from active queue
     item, current step inferred from the `closing:*` suffix). Set
     `status: active`. The next `work end` invocation will detect
     `.close-state` and resume the ceremony via idempotency checks.
   - `closing:review`, `closing:verified` → pre-close was in progress but
     no mechanical work has happened. Set `status: active`. Pre-close items
     will need to be re-done.
3. Strip all close-ceremony fields from `## State` (remove `state:`)
4. Add `status:` field with the determined value

The `.plan` filename is retired. `plan_manager.py` becomes `queue_manager.py`
with the same API. The lifecycle guard hook updates to protect `.queue`.

## What Gets Deleted

| Current file | LOC | Fate |
|---|---|---|
| `work_end_orchestrator.py` | 2,250 | Replaced by `close.py` (~80 LOC) |
| `land_flow.py` | 990 | Replaced by `land()` + helpers in `close.py` |
| `work_end_execute.py` | 612 | Deleted — no execution engine |
| `orchestrator_engine.py` | 440 | Deleted — no engine loop |
| `lifecycle.py` | 776 | `status` field in `.queue` (~30 LOC) |
| `corruption.py` | 620 | ~50 LOC of pre-flight checks |
| `close_progress.py` | ~150 | Deleted — no progress tracking |
| `close_resume.py` | 148 | Deleted — re-run from scratch |
| `close_artifacts.py` | 361 | Moves to pre-close skill |
| `work_end_context.py` | 204 | `CloseTarget` dataclass (~10 LOC) |
| `verify_*.py` (3 files) | ~350 | Replaced by `verify_content_landed()` in ceremony |
| `handlers/*.md` (8 files) | ~400 | Deleted — no handler dispatch |
| `branch_recon.py` | 224 | `resolve()` function (~20 LOC) |
| `progress_summary.py` | 441 | Deleted — ceremony is short enough to report inline |
| `hygiene_scan.py` | 319 | Moves to pre-close checklist |
| `loose_ends_sweep.py` | 322 | Moves to pre-close checklist |
| `epic_handoff.py` | 324 | Moves to pre-close (handover skill) |
| `fork_next_branch.py` | 129 | `advance()` handles queue; branch creation is work-start's job |
| `upstream_push.py` | 66 | Fork-model push logic moves into `land()` via `push_target`/`mirror_target` |
| `verification/` (8 files) | ~400 | `close_checks.py`, `close_verify.py`, `cross_checks.py`: replaced by `preflight()` and post-merge `verify_content_landed()`. `postconditions.py`, `step_postconditions.py`: eliminated — ceremony steps are self-postconditioned. `outcomes.py`, `repo_checks.py`, `slot_checks.py`: slot-specific checks move to `resolve()` preconditions. |

**Before:** ~10,800 LOC across ~58 files, 53 pipeline steps
**After:** Ceremony core is ~200 LOC in `close.py` + `queue_io.py` +
pre-flight, 7 ceremony steps. Helper functions (`squash_merge`, `push_two_hop`,
`branch_already_landed`, `verify_content_landed`, fork-model logic, two-hop
relay) add ~150-200 LOC of focused git operations. Total: ~400 LOC.

## What Survives

| File | Reason |
|---|---|
| `work.py` | Pipeline engine for start/continue/pause/resume — unaffected |
| `work_chain.py` | Chaining engine — updated to use `.queue` instead of `.plan` |
| `ctx.py` | Context resolution — updated to read `.queue` |
| `plan_manager.py` → `queue_manager.py` | Queue CRUD — rename, same API |
| `stack.py` | Pause stack — updated to reference `.queue` |
| `artifact_promote.py` | Moves to pre-close, otherwise unchanged |
| `shared_steps.py` | Shared mechanical steps — review for relevance |
| `audit_work_end.py` | Audit tool — rewritten for new ceremony |
| `work-end/SKILL.md` | Rewritten as pre-close checklist + ceremony invocation |

## Impact on Other Systems

### `ctx.py`
- Read `.queue` instead of `.plan`
- `META_STATE` output replaced by `QUEUE_STATUS` (4 values instead of 12)
- `HAS_PLAN` → `HAS_QUEUE`
- Remove `PLAN_BATCH`, `PLAN_POSITION` — queue position derived from item list

### Corruption triage

**Eliminated by design** (no `closing:*` states, no lifecycle file leak path):
- S4 `CLOSING_POSTCONDITION` — no closing:* states to check
- S7 `STALE_PLAN_ON_MAIN` — queue never auto-deleted, lifecycle files stripped
- S8–S11 (closing substates) — no substates exist
- S14 `STALE_LANDED_SHA` — no landed SHA tracking in queue
- S15 `PLAN_BRANCH_STALE` — advance() validates expected issue

**Surviving scenarios** (external corruption that the ceremony can't prevent):
- S1 `MISSING_STATE` — queue file exists but status field absent (hand-edit)
- S5 `BRANCH_MISMATCH` — queue says branch X, git is on branch Y
- S6 `BRANCH_NOT_EXIST` — queue references a deleted branch
- S13 `MERGE_CONFLICT` — queue file has merge conflict markers (rebase)

**Eliminated `auto_action="remove_plan"`:** Queue is never auto-deleted.
Corruption recovery for queue issues is always interactive.

- Total: 17+ scenarios → 4 scenarios

### `work_chain.py`
- Read `.queue` status instead of `.plan` state
- `chain_to_next` directive when `advance()` returns a next item
- `guard_continue` when queue is drained

### Pre-push hook (`pre_push_hook.py`)
- Check `.queue` status instead of lifecycle state
- Block push to base branch if `.close-state` exists (ceremony in progress)
- **Intentional change from current behavior:** The current hook blocks pushes
  until `closing:pushed` (enforcing that review/promotion happened). The new
  hook only blocks during interrupted ceremony. Pre-close is advisory — the
  ceremony is correct regardless of whether review happened. If organizational
  policy requires mandatory pre-close, enforce it via CI checks on the base
  branch, not via the push hook. This separation is deliberate: the ceremony
  owns mechanical correctness, CI owns process enforcement.

### work-start, work-pause, work-resume
- Read/write `.queue` instead of `.plan`
- Simpler — no lifecycle state machine to interact with

### Tests
- All `test_lifecycle.py` tests rewritten for status field
- All `test_pre_push_hook.py` tests updated for `.queue`
- New tests for `close.py` — one per step + integration
- Ceremony tests are simple: set up git state, run `close()`, verify result

## Risk and Migration

### Migration risk
The `.plan` → `.queue` rename affects every consumer. Mitigation: the queue
I/O module reads both filenames during a transition period. If `.plan` exists
and `.queue` doesn't, migrate on first read.

### Feature parity
Pre-close checklist must cover everything the current orchestrator does.
Mitigation: audit current step list against the checklist before deleting
orchestrator code.

### Slot complexity
Slot close is the most complex current mode. The new design handles it via
`resolve()` returning multiple `CloseTarget`s. Mitigation: test with
real slot topology before cutting over.

### Backward compatibility
Branches created before the migration will have `.plan` files. The migration-
on-read handles this transparently.

## References

- Hortora/soredium#498 — work-end deletes .plan, wiping remaining queue items
- Hortora/soredium#499 — this redesign issue
- Hortora/soredium#443 — prior spec "Robust Pipeline Architecture" proposing an
  evolutionary approach (event-sourced lifecycle, classify-once context,
  outcome-based verification). This spec (#499) proposes revolution instead
  of evolution. The #443 approach preserved existing code structure and fixed
  problems in-place; #499 discards the structure entirely. Revolution is
  preferred because #443's evolutionary approach still couples the queue to
  ceremony state (the .plan file remains the hub) and preserves the
  orchestrator loop pattern that generates loop/stall bugs. The structural
  problems (#443 Phase 1–4) are sound analysis but the incremental fix path
  leaves too many interaction surfaces intact.
- ADR-0013 — unified .plan file (this design reverses the coupling it
  introduced). **A new ADR (ADR-0017) will be written to document this
  reversal** with the full rationale and the 12 plan-destruction bugs that
  motivated it.
- ADR-0016 — workspace merge strategy in branch mode (lifecycle file stripping
  order, non-ff merge for workspace repos)
- ADR-0009 — automatic workflow orchestration by project type
- PP-20260827 — SKILL.md minimal orchestrator loop protocol. **This protocol
  is retired by this design.** The new SKILL.md pattern (pre-close checklist
  + ceremony invocation) replaces the orchestrator loop + handler dispatch
  pattern. PP-20260827's principle (keep SKILL.md minimal, load handler
  details lazily) is preserved in spirit — the SKILL.md remains a thin
  entry point — but the mechanism changes from loop+dispatch to
  checklist+invocation.
- Architecture analysis fork — 80 issues categorised, 7 deletion paths identified
- `decisions.md` — 6 design decisions with rationale and trade-offs
