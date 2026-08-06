# Unified Work State — Design Spec

**Issue:** #188
**Addresses:** #118 (Evaluate splitting HANDOFF.md roles: history, state, and planning)
**Date:** 2026-08-06
**Status:** Draft

## Problem

The work lifecycle system has 13 state locations tracking overlapping facts
with no consistency guarantees between them. Five places track "is this issue
done?" Five track "is this branch closed?" Three provide cross-cutting
validation that re-derives the same facts. Each is maintained independently. When external actors change state
(another session closes an issue, another context merges a branch), the caches
go stale silently. Validation is scattered across skills that run at different
lifecycle moments, covering different slices with different logic.

The WI 490 case is representative: a HANDOFF.md item described a casehub
branch as "not merged, not stamped" for days after the branch was already
merged. No validation path existed to catch it — the resume cross-check only
validates GitHub issue state, not git branch state.

**The 13 state locations:**

"Is this issue done?" — five locations:
1. `.plan` `[x]` markers (branch queue)
2. `.meta` `covers:` field (completed issue list)
3. HANDOFF.md What's Left (negative signal: absent = possibly done)
4. HANDOFF.md What's Next (implicit: items here are future work)
5. Handover resume cross-check (Step R3) — validates `#N` against GitHub

"Is this branch closed?" — five locations:
6. EPIC-CLOSED.md marker file on workspace branch
7. Stamp commit on project branch (`chore: branch closed`)
8. Stamp commit on workspace branch
9. `verify_slot_close.py` (5 checks: merged, stamped, landing SHA, pushed, workspace stamped)
10. `audit_slot_merges.py` (independent merged/stamped checks)

Cross-cutting validation that re-derives the above:
11. Handover epic hygiene checks 7+8 (unrecovered artifacts, unstamped branches)
12. `work_router.py` HANDOFF reference detection (infers branch liveness)
13. `.meta` `state:` closing:* sequence (tracks closure progress in-session)

Each is maintained independently. When external actors change state (another
session closes an issue, another context merges a branch), cross-location
consistency is never re-established until a validation path happens to run.

**Root cause:** The system caches state that has authoritative sources
elsewhere (GitHub for issues, git for branches, .plan for queue position),
then adds reactive validation to detect cache staleness. The fix is to stop
caching and start deriving — each fact has one source of truth, everything
else queries it.

## Relationship to Prior Specs

**Supersedes** `2026-08-05-work-end-restructure-and-slot-audit-design.md` on
two specific points:

1. **EPIC-CLOSED.md** — the work-end restructure spec creates it in Step 5.
   This spec eliminates it. The stamp commit is the single closure signal.
2. **`verify_slot_close.py` as standalone gate** — the work-end restructure
   spec designs it as the verification gate for work-end. This spec absorbs
   its check functions into `work_health.py --scope close`. The script
   continues to exist as a library; its CLI entry point is deprecated.

The work-end restructure spec's 5-step architecture (Context → Sweep →
Execute → Verify → Close), its scripts (`work_end_context.py`,
`work_end_execute.py`), and its multi-repo slot close fix are orthogonal
and coexist. `work_health.py --scope close` composes with the existing
`verify_slot_close.py` check functions — it calls them, it doesn't
reimplement them.

**Implementation order:** The work-end restructure can proceed first. When
this spec's Phase 6 lands, work-end's Step 5.1 (`create-epic-closed`) is
removed. When Phase 9 lands, work-end's Step 4 invokes `work_health.py
--scope close` instead of `verify_slot_close.py` directly.

## Design

Four components, designed to be implemented in phases but forming a unified
whole.

### Component 1: `is_closed(branch)` predicate

A single function in `lifecycle.py` that answers "is this branch done?"
definitively. Replaces five different closure-checking implementations.

**Signature:**

```python
def is_closed(project: str, branch: str,
              workspace: str | None = None,
              base_branch: str = "main") -> ClosureState
```

**Returns** a `ClosureState` (enum or named object):

| State | Meaning | Criteria |
|-------|---------|----------|
| `CLOSED` | Fully done | Merged to main + stamped |
| `MERGED_UNSTAMPED` | Content landed, no stamp | Zero non-stamp commits ahead of main, no stamp commit |
| `STAMPED_UNMERGED` | Stamp exists, content not landed | Stamp commit present but non-stamp commits ahead of main |
| `OPEN` | Neither merged nor stamped | Non-stamp commits ahead of main, no stamp |
| `DELETED` | Branch doesn't exist | `git branch --list` returns empty |

**Checks (all local git, sub-second):**

1. Branch exists? `git -C <project> branch --list <branch>`
2. Commits ahead of main? `git -C <project> log --oneline <base>..<branch>`
   — filter out commits starting with `chore: branch closed`
3. Stamp commit? Last commit starts with `chore: branch closed`
4. Landing SHA valid? If stamp contains `landed as <SHA>`,
   run `git merge-base --is-ancestor <SHA> <base>`.
   **Advisory only** — a mismatch is logged as a warning but does not
   alter the returned `ClosureState`. Known cases include landing SHAs
   rewritten by post-stamp squash (pre-ordering fix, now prevented by
   Execute's stamp-after-squash sequence). `work_health.py` logs
   mismatches at `STATUS=warn` for investigation.
5. Workspace branch? If workspace provided, check workspace branch
   with same logic

**Replaces:**
- `verify_slot_close.py` checks 1-3 (branch_merged, branch_stamped, landing_sha)
- `audit_slot_merges.py` merged/stamped logic
- Handover epic hygiene checks 7+8 (unrecovered artifacts, unstamped branches)
- Handover resume Step R2b (EPIC-CLOSED.md open-branch detection)
- `work_router.py` HANDOFF reference detection (infers branch liveness)

**`STAMPED_UNMERGED` recovery:** This state means a stamp commit exists but
content never landed on main — a corrupted close sequence. `work_health.py`
reports it as a WARNING with: "Branch X is stamped but content appears not
merged. Investigate whether content was cherry-picked to a different base or
the stamp was premature." No auto-fix — the state is ambiguous and requires
manual investigation. The user can either (a) remove the stamp and re-run
work-end, or (b) verify the content did land (e.g., via squash-merge with
different SHAs) and re-stamp with a valid landing SHA.

**Scope: local git only.** `is_closed()` deliberately does not check remote
refs (`git ls-remote`). All checks use local git state for sub-second
performance and offline capability. `DELETED` means "no local branch ref" —
callers that care about remote-only branches (e.g., cross-machine hygiene
scans) supplement with their own remote check. The predicate's contract is
local branch lifecycle, not distributed branch state.

**EPIC-CLOSED.md eliminated.** The stamp commit on the project branch is the
single closure signal. Work-end stops creating EPIC-CLOSED.md. All tools that
checked for it use `is_closed()` instead. Workspace-side closure is determined
by checking the workspace branch with `is_closed()`.

**Slot topology:** `is_closed()` always operates on the authoritative
project repo — the original on-disk repo, not a slot clone. Slot clones
are ephemeral workspaces whose `origin` points to the original repo, not
GitHub. Callers in slot mode pass the original repo path. The git checks
(`branch --list`, `log`, `merge-base`) all work correctly against the
original repo. `work_health.py` resolves the original repo from `.slot`
metadata before calling `is_closed()`.

**Migration:** Existing branches with EPIC-CLOSED.md but no stamp can be
detected by `is_closed()` returning `MERGED_UNSTAMPED` and auto-stamped by
`work_health.py`.

### Component 2: Unified validation — `work_health.py`

Single check registry replacing scattered validation across handover epic
hygiene, resume cross-check, ARC42 stale scan, verify_slot_close.py, and
audit_slot_merges.py.

**Check registry:**

| Check | What it validates | Scopes | Auto-fix |
|-------|------------------|--------|----------|
| `plan_state` | .plan items vs GitHub issue state (batch API call) | entry, wrap | Yes — mark closed items `[x]` in .plan; report but do not remove queue entries |
| `branch_closure` | `is_closed()` on known branches (`.pause-stack` + `.meta` branch + `.plan` refs) | entry, wrap, close | Report + offer stamp for MERGED_UNSTAMPED; report STAMPED_UNMERGED |
| `pause_stack` | Each .pause-stack entry's branch exists | entry | Report — user decides |
| `meta_consistency` | .meta state matches actual branch/git state | entry | Report |
| `workspace_alignment` | Workspace and project on expected branches | entry | Report |
| `arc42_refs` | ARC42STORIES.MD issue refs vs GitHub | wrap | Yes — update on confirmation |
| `slot_state` | Active slots: repos exist, branches exist, .slot valid | entry | Report |
| `main_divergence` | Local main vs origin/main | entry, wrap | Report |
| `stale_branches` | Open branches with no commits in 7+ days | wrap | Report |
| `journal_anchors` | Mid-epic journal entries have §Section anchors | wrap | Report |
| `dirty_main` | Project main working tree has staged/unstaged changes | entry | Report |
| `artifact_recovery` | Closed branches with unrecovered artifacts (blogs, specs not on main) | wrap | Report + offer cherry-pick |
| `partial_pause` | `.pausing` intent file present (with pre-condition validation) | entry | Report + offer recovery |
| `partial_resume` | `.resuming` intent file present (with pre-condition validation) | entry | Report + offer recovery |
| `closing_recovery` | `.meta` state is `closing:*` — interrupted work-end | entry | Report gate + offer continue or abort (pre-promotion only) |

**Invocation:**

```bash
python3 project/work_health.py --scope entry  --project P --workspace W
python3 project/work_health.py --scope wrap   --project P --workspace W
python3 project/work_health.py --scope close  --project P --workspace W --branch B
```

**Output format:**

```
CHECK=plan_state STATUS=changed DETAIL=#142 now CLOSED, #155 now CLOSED
CHECK=branch_closure STATUS=fix DETAIL=issue-142-foo stamped (was MERGED_UNSTAMPED)
CHECK=pause_stack STATUS=ok
CHECK=meta_consistency STATUS=ok
FIXED=1 WARNINGS=0 ERRORS=0
```

**Auto-fix policy:** Safe items (marking closed issues as `[x]` in .plan)
are fixed automatically. Queue removal and branch stamping require user
confirmation. Risky items (discarding a pause stack entry, archiving a
slot) are reported for user decision.

**`plan_state` batch validation:** One `gh issue list --repo R --state all
--json number,state,title --limit 500` call returns all issue state. Compare
against every `#N` in .plan. After the batch call, any `.plan` issue numbers
not present in the result set are validated individually via
`gh issue view <N>`. This handles repos with >500 issues where older issues
fall outside the batch window. Sub-second for most repos; individual
lookups add latency only when needed.

**Network failure handling:** The `plan_state` and `arc42_refs` checks
require GitHub API access. On network timeout (5-second limit) or error:
emit `CHECK=plan_state STATUS=skip DETAIL=network unavailable` and proceed.
The stale `.plan` `[x]` markers are harmless — they reflect the last known
state and are re-validated on the next successful session start. The
3-second success criterion applies to the common case (network available);
offline sessions skip API-dependent checks and run local-only checks. If any `.plan` item
is not found in the batch result (possible for repos with 500+ issues),
fall back to individual `gh issue view <N>` calls for unmatched items only.
The common case (all items within the most recent 500) completes in one call;
the edge case adds one call per unmatched item.

**API failure graceful degradation:** If the GitHub API call fails (no
network, rate limiting, expired token), `plan_state` reports
`STATUS=skipped DETAIL=GitHub API unavailable` and the remaining checks
proceed. Entry-scope is advisory, not a gate — session start must not
block on API availability. The `.plan` queue is displayed from its last
known state without live validation. A warning is shown: "GitHub
unavailable — issue states not validated this session."

**Integration points:**
- `project` skill (session start) → `--scope entry`
- `handover` skill (wrap) → `--scope wrap` (replaces epic hygiene + ARC42 scan)
- `work-end` skill (close) → `--scope close` (replaces/wraps verify_slot_close.py)

**Slot mode:** When running against a slot workspace, `work_health.py`
reads `.slot` metadata to discover all repos in the slot. For each check:
- `branch_closure` iterates over all slot repos, calling `is_closed()` on
  each repo's branch (resolving to the original repo, not the slot clone)
- `plan_state` validates the slot-level `.plan` (which lives at
  `$SLOT_WORKSPACE/design/.plan`, not per-repo). The slot-level `.plan`
  uses the same format, parser, sole-writer constraint (`plan_manager.py`),
  and GitHub-issue-reference requirement as workspace `.plan` — no
  separate variant exists. `plan_manager.py detect()` receives the slot
  workspace path and resolves `design/.plan` relative to it (line 499)
- `slot_state` verifies per-repo structural integrity (`.slot` valid,
  repos exist on disk, branches exist)
- `main_divergence` checks each repo's main independently

The slot resolution uses the same `_resolve_clone_origin()` pattern from
`pause_exec.py` — follow origin URL to the original on-disk repo.

### Component 3: `.plan` as single orchestration layer

`.plan` becomes the single local cache for work state. Exists on main
(global queue) and on branches (active work queue).

#### Main `.plan` — global curated queue

Lives at `$WORKSPACE/design/.plan` on the `main` branch. A curated,
ordered subset of open GitHub issues — not a parallel backlog.

**Relationship to GitHub issues:** Every item in Main `.plan` is a GitHub
issue reference (`#N`). GitHub is authoritative for issue state (open/closed);
`.plan` is authoritative for priority ordering. Items that are not GitHub
issues cannot appear. `work_health.py` validates every `#N` against GitHub
on session start and marks closed items as `[x]`.

**Curation model:** Items are added explicitly — during triage ("add #N to
the queue"), when filing new issues ("file and queue"), or when the `work`
skill on main offers to seed from open GitHub issues. Items are marked complete
automatically when closed (via `plan_state` check) or removed manually by the user.
Priority order is changed by the user or LLM during planning. This replaces
the current model where HANDOFF.md's What's Left/What's Next are
synthesised from conversational context at session end — a process that
loses items when context is stale and creates items that don't correspond
to GitHub issues.

**Branch .plan vs Main .plan:** Same file path (`$WORKSPACE/design/.plan`),
different git branches. On main, `plan_manager.py detect()` finds Main
`.plan`. On a feature branch, it finds Branch `.plan`. These serve different
purposes: Main `.plan` is the project priority queue; Branch `.plan` is the
issue iteration queue for the current branch's work. They use the same
format and parser. No ambiguity — git branch determines which is active.

**No flow-back on branch close:** Intentional. Automatic flow-back creates
the same accumulation problem as HANDOFF.md What's Left — items pile up
without curation. When a branch closes, uncompleted items are already
open GitHub issues. The user decides which to add to Main `.plan` during
their next triage session. This is a curation discipline, not a gap.

#### Format

```markdown
# Work Plan — soredium

## Queue
- [x] #142 — some completed issue
- [ ] #123 — active issue ← active
- [ ] #155 — another issue

## Session State
Current: #123
Started: 2026-08-06
Last wrap: 2026-08-06T14:30:00Z
```

No state cache in the file. GitHub issue state is queried live by
`work_health.py` on session start (batch API call) and consumed in-session.
The `[x]` markers in Queue are a completion record written by
`plan_manager.py` when an issue advances — not a cache of GitHub state.
`plan_manager.py` is the sole writer of `.plan` content (Queue and Session
State sections). `work_health.py`'s `plan_state` auto-fix delegates to
`plan_manager.py` for the actual file write — `work_health.py` never
writes `.plan` directly. The delegation API:
`plan_manager.mark_completed(plan_path, issue_number)` marks an issue
`[x]` in the queue. The import is one-directional
(`project/work_health.py` → `work-slot/plan_manager.py`); no reverse
dependency exists. `plan_manager.py` already exposes the needed
primitives: `parse_plan()`, `rewrite_plan()`, and the `_mark_completed()`
internal (to be promoted to public API for `work_health.py`).

#### Resume flow

The resume path reads two sources in sequence and presents them as a
combined output:

1. **Slim HANDOFF.md** — read for session narrative context (Last Session,
   Immediate Next Step, Cross-Module). This tells the next session *why*
   things are the way they are.
2. **Main `.plan`** — read for work queue state. `work_health.py --scope
   entry` validates issue state live against GitHub before display. This
   tells the next session *what* to work on.

The combined resume output:

```
## Last Session
Implemented is_closed() predicate and wrote 47 tests. Hit an edge
case with superseded stamps — filed #189.

## Immediate Next Step
Start Phase 2: work_health.py entry-scope checks.

## Queue (3 items, 1 complete, 1 active):
  ✅ #142 — some completed issue
  → #123 — active issue (current)
  ⚠️  #155 — now CLOSED on GitHub (marked [x])

  work_health: 1 item marked complete (CLOSED on GitHub)
```

HANDOFF.md sections appear first (session context), then .plan queue
summary. If HANDOFF.md is missing or empty, only the queue is shown.
If `.plan` doesn't exist yet (pre-Phase 4), the resume path falls back
to the current HANDOFF.md-only flow — the skill reads whatever sections
exist and presents them.

#### What `.plan` replaces

| Previously in | Now in | Mechanism |
|---------------|--------|-----------|
| HANDOFF.md What's Left | Main `.plan` or GitHub issues | Trailing items become issues, enter .plan |
| HANDOFF.md What's Next | Main `.plan` | Curated queue with priority |
| .meta `covers:` | Derived from `.plan` `[x]` items | `reconcile_covers()` removed |
| HANDOFF.md Queue Progress | `.plan` Session State | Already exists |

**"Trailing items become issues" is a deliberate process decision.** The
current HANDOFF.md What's Left contains free-form items that aren't GitHub
issues (e.g., "run audit script against casehub", "archive orphaned slots",
"hygiene debt across 3 repos"). This spec mandates that all such items
become GitHub issues before entering `.plan`. Rationale: free-form items
in HANDOFF.md are exactly the kind of state that goes stale — they have
no closure signal, no cross-session visibility, and no way to validate
whether they're still relevant. Filing them as issues gives each item a
lifecycle (open → closed), a repo home, and automated staleness detection
via `plan_state`. Cross-repo operational tasks are filed in the repo that
owns the tooling (e.g., soredium for hygiene scripts). This is a forcing
function by design — the friction of filing an issue is the cost of
trackability.

#### Branch close — no flow-back

When a branch closes, the stamp commit is the sole closure signal — no
separate `.plan` closure marker is needed. The `write_plan_closed` effect
in the lifecycle transition table (`lifecycle.py` line 101) is vestigial:
it has no implementation, and adding one would either require a commit after
the stamp (breaking `is_closed()`) or reordering the transition table.
Since this spec establishes the stamp commit as the single closure signal
(Component 1), `write_plan_closed` should be removed from the transition
table. Uncompleted `.plan` items remain as open GitHub issues. Main `.plan`
is independently curated — branch close does not automatically append items
to it.

**Single-repo mode protection:** In single-repo mode (`workspace == project`),
the branch `.plan` at `design/.plan` would be merged to main during the
rebase-merge in `land_branch.py`, overwriting main's `.plan`. To prevent this,
the skill layer saves main's `.plan` content before calling `land_branch.py
rebase`, then restores it after the rebase completes:
`plan_manager.save_plan(plan_path)` returns the raw bytes;
`plan_manager.restore_plan(plan_path, saved)` writes them back. This avoids
reliance on reflog position (`HEAD@{1}`), which is fragile — `cmd_stamp()`
in `land_branch.py` performs two additional `git checkout` operations (lines
178, 193) and `cmd_land()` in `work_end_execute.py` performs a workspace
checkout (line 183), any of which would shift the reflog entry and cause
the restore to retrieve the wrong file.
This is a mechanical step in the Land phase, not a user decision.

#### HANDOFF.md shrinks to session context

```markdown
# HANDOFF — <project>

## Last Session
2-3 lines: what was done, what was tried, key reasoning.

## Immediate Next Step
Single specific action.

## Cross-Module
Only if active cross-repo blockers exist with tracked issues.
Omit entirely if none.

## References
Paths only, no content inline.
```

Target: under 200 tokens. No work tracking. No backlog. Session context
and narrative reasoning only — the "why" that connects commits and .plan
items into a coherent story for the next session.

**Commit mechanism simplifies:** HANDOFF.md is write-once-per-session at
wrap time. The resume path no longer mutates it (closed-issue removal moves
to `.plan` validation via `work_health.py`). This eliminates the main source
of mid-session HANDOFF.md churn and reduces the commit-to-main dance to a
single write at session end.

### Component 4: Crash recovery for work-pause and work-resume

Intent marker files track in-progress operations. Detected by `work_health.py`
on next session start.

**Atomic writes:** Intent file updates use the same write-to-temp-then-rename
pattern as `lifecycle.py`'s `write_state()`: write to `.pausing.tmp`, then
`os.replace()` (POSIX atomic rename). If an intent file exists but is
unparseable (truncated by a crash during a non-atomic write in older code),
treat as "operation in progress at step 0" — offer full recovery or full
abort. The YAML parser must not crash on malformed input.

**Pre-condition validation before offering recovery:** Before presenting
recovery options, validate that recovery actions are still applicable:
- For `.pausing`: check if the branch is still checked out AND the stack
  entry is missing. If the branch is not checked out and the stack entry
  exists, the pause completed successfully — remove the stale intent file
  silently with a log message.
- For `.resuming`: check if the session is on main AND the stack entry is
  still present. If the session is already on the feature branch and the
  stack entry is absent, the resume completed — remove the intent file.
This prevents spurious recovery offers after manual resolution.

**Intent files are untracked working-directory files** — never `git add`ed,
never committed. This is critical: untracked files persist across `git
checkout` because git does not modify untracked files during branch switches.
A `.pausing` file written while on a feature branch survives checkout to
main. A `.resuming` file written while on main survives checkout to a feature
branch. Even if a crash occurs mid-checkout (leaving HEAD in an indeterminate
state), the untracked intent file remains in the working directory.
`work_health.py --scope entry` checks for these files on the current working
tree regardless of which branch HEAD points to.

#### `.pausing` intent file

Written to `$WORKSPACE/design/.pausing` before pause starts. Updated as each
step completes. Removed on successful pause.

```yaml
branch: issue-123-foo
started: 2026-08-06T14:30:00Z
wip_project: pending|done
wip_workspace: pending|done
stack_push: pending|done
checkout_main: pending|done
```

**Recovery on detection:**
- Offer to complete pause (push stack, checkout main)
- Or abort (reset WIP commits, stay on branch)

#### `.resuming` intent file

Written to `$WORKSPACE/design/.resuming` before resume starts.

```yaml
branch: issue-123-foo
started: 2026-08-06T14:30:00Z
stack_pop: pending|done
checkout: pending|done
rebase: pending|done
wip_reset: pending|done
```

**Recovery on detection:**
- Offer to complete resume (checkout, rebase, reset WIP)
- Or abort — **state-dependent steps:**
  - If `checkout: pending`: re-push stack entry, stay on main (no branch switch needed)
  - If `checkout: done`: switch both project and workspace repos back to
    main/base (`git checkout main`), then re-push stack entry. Handle
    asymmetric state: if only one repo's checkout completed (crash between
    the two checkouts in `resume_exec.py`), switch only that repo back.
  - If `rebase: done`: switch back to main, re-push stack entry. The
    rebase is on the feature branch and does not affect main.

**Why intent files, not lifecycle states:** The alternative is adding
`pausing` and `resuming` as transient states to the lifecycle state machine
(analogous to `transitioning` and `closing:*`). This was evaluated and
rejected for a specific reason: the lifecycle state machine provides
coarse-grained phase tracking (one state per phase), but pause/resume
operations have multiple independently-failable sub-steps (WIP commit on
project, WIP commit on workspace, push stack, checkout main). A lifecycle
state `pausing` would tell you the operation started but not which sub-steps
completed. Intent files track per-step completion — the same pattern as
`.execute-progress` for the close sequence. The close sequence uses
lifecycle states for the coarse phases AND `.execute-progress` for per-repo
granularity within phases. Intent files are the pause/resume equivalent of
`.execute-progress` — not a competing mechanism, but the same architecture
applied to a different operation.

## Implementation Phases

| Phase | What | Depends on |
|-------|------|-----------|
| 1 | `is_closed()` predicate in lifecycle.py + tests | Nothing |
| 2 | `work_health.py` with entry-scope checks (plan_state, branch_closure, pause_stack, meta_consistency) | Phase 1 |
| 3 | .plan batch validation integration + human-readable resume display | Phase 2 |
| 4 | Main .plan support — curated global queue | Phase 3 |
| 5 | HANDOFF.md simplification — remove What's Left, What's Next | Phase 4 |
| 6 | Stop creating EPIC-CLOSED.md — work-end Step 5.1 removed. Existing consumers unchanged until Phase 9 migrates them to `is_closed()` | Phase 1 |
| 7 | Remove .meta covers — derive from .plan | Phase 3 |
| 8 | Crash recovery — .pausing/.resuming intent files | Phase 2 |
| 9 | Wrap-scope and close-scope checks in work_health.py — replace handover epic hygiene, verify_slot_close.py | Phase 2 + 6 |
| 10 | Update audit_slot_merges.py to use is_closed() | Phase 1 |
| 11 | Persistent scratchpad — NOTES.md + handover/resume integration | Phase 5 |
| 12 | Trellis worklog bridge — JDBC reader + WorklogModelProvider (Hortora/trellis) | Phase 2 |

Phases 1, 6, 10 can run in parallel (is_closed + dependents).
Phases 2-5 are sequential (each builds on the previous).
Phase 8 is independent after Phase 2.
Phase 9 is independent after Phases 2 + 6.
Phase 11 depends on Phase 5 (HANDOFF.md slim format must land first so NOTES.md doesn't overlap).
Phase 12 is a separate repo (Hortora/trellis), independent after Phase 2 establishes the validation layer.

## Migration

**EPIC-CLOSED.md:** Existing branches with EPIC-CLOSED.md are handled by
`is_closed()` — it checks stamp commits, not marker files. During Phase 6,
any branch with EPIC-CLOSED.md but no stamp gets auto-stamped by
`work_health.py` (auto-fix safe: branch is already merged).

**HANDOFF.md:** Phase 5 changes the handover skill to write the slim format.
Old-format HANDOFF.md files are still readable — the resume path gracefully
handles missing sections.

**.meta covers:** Phase 7 stops writing to `.plan` instead of `.meta
covers:`. Three removal targets in `plan_manager.py`: `reconcile_covers()`
(line 477), `_update_meta_covers()` (line 443), and the
`_update_meta_covers()` call in `advance()` (line 347). All `.meta
covers:` writes are eliminated. Any skill that previously read `.meta
covers:` now reads `.plan` `[x]` items via `plan_manager.py`.

## What Gets Deleted

| Artifact | Replaced by |
|----------|------------|
| EPIC-CLOSED.md (creation + all checks) | `is_closed()` predicate |
| HANDOFF.md What's Left section | Main `.plan` / GitHub issues |
| HANDOFF.md What's Next section | Main `.plan` |
| HANDOFF.md Queue Progress section | `.plan` Session State |
| .meta `covers:` field + `reconcile_covers()` | `.plan` `[x]` items |
| Handover epic hygiene (8 checks) | `work_health.py --scope wrap` |
| Handover resume issue cross-check | `work_health.py --scope entry` |
| Handover ARC42 stale scan (Step 2c) | `work_health.py --scope wrap` |
| verify_slot_close.py (standalone) | `work_health.py --scope close` |

### Component 5: Persistent scratchpad — `$WORKSPACE/NOTES.md`

Cross-session state has three lifetimes, and the first two have clear homes:

| Lifetime | Home | Example |
|----------|------|---------|
| Branch-scoped | `.meta`, `.plan`, `JOURNAL.md` | "Issue #123 is blocked on API change" |
| Session-scoped | HANDOFF.md | "Tried approach X, failed because Y" |
| Persistent | **nowhere today** | "Remember to check if trellis reads worklog.db" |

Persistent items — things to come back to later, observations that span
sessions, notes that aren't actionable enough to be issues yet — currently
have no home. They end up in HANDOFF.md (overwritten next session), CLAUDE.md
(wrong purpose — project conventions, not scratch notes), or auto-memory
(behavioural, not task-level).

**`$WORKSPACE/NOTES.md`** fills this gap:

- **Append-only** — new items added at the top, never overwritten
- **Committed to workspace main** — survives across sessions and branches
- **Not a queue** — no checkboxes, no ordering, no validation. Free-form
  text with timestamps
- **Promotion path** — items that become actionable get filed as GitHub
  issues and optionally added to `.plan`. Items that become conventions
  get moved to CLAUDE.md or protocols

**Format:**

```markdown
# Notes — soredium

## 2026-08-06
- Check if trellis reads worklog.db — may need JDBC bridge
- The handover commit-to-main dance (8 git operations) is fragile —
  revisit if HANDOFF.md write-once-per-session isn't enough

## 2026-08-04
- audit_slot_merges.py --fix only handles UNSTAMPED, not UNMERGED
```

**Integration:**
- Handover wrap checklist adds an optional item: "Anything to note for
  later?" — appends to NOTES.md if the user has items
- `work_health.py --scope entry` surfaces recent notes (last 7 days)
  in the resume output so they don't disappear
- `idea-log` skill can append to NOTES.md instead of maintaining a
  separate file (consolidation, not duplication)

**What NOTES.md is NOT:**
- Not a backlog (that's `.plan` + GitHub issues)
- Not a design journal (that's `JOURNAL.md`)
- Not project conventions (that's CLAUDE.md)
- Not a session narrative (that's HANDOFF.md)

### Component 6: Trellis worklog bridge

Trellis (Quarkus UI sidecar) currently has no reader for soredium's
`worklog.db`. The Python MCP server (#157) gives Claude Code agents
read access, but trellis — which displays the work timeline UI — reads
only its own filesystem scanner state.

**Gap:** `worklog.db` captures structured lifecycle events (branch starts,
pauses, closes, issue completions) via `worklog.py`. Trellis's
`FileWatcherService` captures filesystem snapshots (slot directories,
branch existence). These are complementary views of the same work, but
trellis never sees the lifecycle events.

**Design:**
- **JDBC reader in trellis sidecar** — direct SQLite read via JDBC.
  No REST layer needed since `worklog.db` is local
  (`~/.claude/worklog.db`)
- **Read-only** — trellis never writes to `worklog.db`. Writes go
  through `lifecycle.py` → `worklog.py` (Python side)
- **Schema contract** — document the `worklog.db` schema in a shared
  location so the Python writer and Java reader stay in sync. The schema
  is simple (work_items, work_events tables) but cross-language contracts
  need explicit documentation
- **ModelProvider integration** — a `WorklogModelProvider` in trellis
  that exposes lifecycle events through the existing `ModelProvider` SPI,
  making worklog data available to the MCP tools and SSE push

**Scope:** This is a Hortora/trellis concern, not a soredium change. Filed
here as a downstream dependency of the unified work state design — once
`work_health.py` is the validation layer and `.plan` is the queue,
trellis benefits from reading the same structured data.

**Issue:** File on Hortora/trellis after this spec is approved.

## Open Design Points

**Main .plan bootstrapping:** When main `.plan` doesn't exist yet, `work`
on main offers to create one via a single prompt:

```
No work queue found. Create one?
  [S] Seed from open GitHub issues (fetches and presents for curation)
  [E] Empty (curate from scratch)
  [N] Not now (skip — ask again next session)
```

Option S fetches open issues, presents them, and lets the user select
which to include and in what order. Option E creates the file with an
empty Queue section. During the Phase 5 transition, the handover skill
migrates any HANDOFF.md What's Next items to `.plan` automatically on
first wrap after Phase 5 lands — one-time migration, not an ongoing
process.

**Close scope is a hard gate:** `work_health.py --scope close` inherits
verify_slot_close.py's hard-gate semantics. Unlike entry/wrap scope
(report + auto-fix), close scope returns `VERIFIED=yes|no` and work-end
blocks on `VERIFIED=no`. The check registry distinguishes advisory checks
(entry/wrap) from gate checks (close).

Close scope runs exactly these checks (all must pass):
- `branch_closure` — `is_closed()` returns `CLOSED` for project branch
  (covers verify_slot_close.py's project_merged, project_stamped,
  landing_sha checks)
- `branch_closure` (workspace) — `is_closed()` returns `CLOSED` for
  workspace branch (covers workspace_stamped check)
- `main_divergence` — local main not ahead of origin/main (covers
  main_pushed check)

This is a complete superset of verify_slot_close.py's five checks. In
slot mode, `branch_closure` iterates over all repos listed in `.slot`
metadata — each repo's branch must be `CLOSED`.

## Success Criteria

- Single `is_closed()` call answers "is this branch done?" — no other tool
  implements its own closure check
- Session start runs `work_health.py --scope entry` in under 3 seconds
  in the common case (network available; one GitHub API call + local git
  checks). When GitHub is unavailable, API-dependent checks are skipped
  and local-only checks complete in under 1 second
- .plan on main is the single source of work priority — HANDOFF.md contains
  zero work items
- Interrupted pause/resume detected and recovery offered on next session start
- EPIC-CLOSED.md no longer created or checked anywhere
- .meta covers no longer written; .plan is the single completion record
- HANDOFF.md under 200 tokens
