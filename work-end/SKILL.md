---
name: work-end
description: >
  Use when the current branch is complete and ready to close — user says
  "work end", "close this branch", or "wrap up this issue". Must be invoked
  from a branch with active work or from main with a .plan. On main, skips
  branch-specific steps (merge, stamp, rebase, squash). Replaces "epic close".
---

# work-end

Closes the current branch cleanly. Five steps: Context → Sweep → Execute →
Verify → Close.

<HARD-GATE>
**Review is mandatory before any push.** Step 2 runs code-review,
branch-audit, loose ends sweep, and forcing function before Execute
pushes anything. No exempt branches.

**Doc sync is mandatory.** `update-claude-md` and `implementation-doc-sync`
default to ON in the Sweep. They catch convention drift.

**Main-branch mutations go through work-end only.** Never run
`git checkout main && git merge <branch>` manually.

**Never suggest deferring work-end to another session.** Session-bound items
(forage SWEEP, write-content) are permanently lost if the session ends without
them. All other steps are Python scripts that consume no meaningful context.
Execute the full sequence every time. Session length is not a factor.
</HARD-GATE>

### Red Flags — thoughts that mean STOP

| Thought | Reality |
|---------|---------|
| "This branch was mechanical" | Mechanical changes have mechanical bugs. Review catches them. |
| "The diff is small" | Small diffs have the highest bug-per-line ratio. |
| "I'll promote artifacts manually" | Run close_artifacts.py. The verification gate catches you. |
| "I'd recommend skipping the sweep" | Present defaults ON. The user decides. |
| "Session is getting long" | Session length is never a reason to skip session-bound items. |

---

## Path Resolution (run first, always)

```bash
python3 ~/.claude/skills/project/ctx.py
```

Use the printed values as concrete strings in all subsequent commands.
`WORKSPACE`, `PROJECT`, `CURRENT_BRANCH`, `PROJECT_SHA`, `ISSUE_N`,
`COVERS`, `OWNER_REPO`, `BASE_BRANCH`, `META_STATE`, `HAS_PLAN`,
`PLAN_PATH`.

---

## Lifecycle State Machine Integration

work-end uses the lifecycle state machine to track closing progress:

```
active → closing:review → closing:verified → closing:promoted → closing:pushed → closing:merged → closing:stamped → idle
```

**On entry:** Read `META_STATE` from ctx.py.

Auto-resolve transient states first (same as `work continue`):

| `META_STATE` | Action |
|-------------|--------|
| `scaffolded` | `python3 ~/.claude/skills/project/lifecycle.py transition <PLAN_PATH> auto_setup` then `commit-transition ... from_state=scaffolded new_state=active event=auto_setup` |
| `transitioning` | `python3 ~/.claude/skills/project/lifecycle.py transition <PLAN_PATH> auto_refresh` then `commit-transition ... from_state=transitioning new_state=active event=auto_refresh` |
| `active` | Ready — proceed below |
| `closing:*` | Already closing — offer to continue from that gate |

Then fire:
```bash
python3 ~/.claude/skills/project/lifecycle.py transition <PLAN_PATH> work_end
```
Enters `closing:review`.

**At each gate:**
```bash
python3 ~/.claude/skills/project/lifecycle.py transition <PLAN_PATH> <event>
# execute effects, then:
python3 ~/.claude/skills/project/lifecycle.py commit-transition <PLAN_PATH> from_state=<FROM> new_state=<NEW> event=<EVENT>
```

**Abort:** from `closing:review` or `closing:verified` only:
```bash
python3 ~/.claude/skills/project/lifecycle.py transition <PLAN_PATH> abort_close
```
Returns to `active`. Post-promotion states are forward-only.

---

## Main-mode detection

Read `ON_MAIN` from ctx.py. If `ON_MAIN=yes`, work-end runs in
**main mode** — same ceremony minus branch-specific steps:

| Step | Branch mode | Main mode |
|------|-------------|-----------|
| 1. Context | Check branch alignment | Check .plan exists |
| 2. Review | Diff against base branch | Diff against `drained-sha` from `.plan` |
| 3. Sweep | Identical | Identical |
| 4.1 Promote | Identical | Identical |
| 4.2 Rebase | Rebase onto base | **Skip** |
| 4.3 Squash | Classify branch commits | **Skip** |
| 4.4 Land | Push, stamp, merge | Push only |
| 5. Verify | Check merged + stamped | Check pushed |
| 5b. Close issues | Identical | Identical |
| 6.2 Checkout main | Switch to main | **Skip** (already there) |
| 6.2b Cleanup | Remove .plan | Keep .plan, fire `cleanup_main` (→ `drained`) |

**Main-mode diff base:** Read `drained-sha` from `.plan`'s `## State`.
Diff against this SHA: `git -C "$PROJECT" diff <drained-sha>..HEAD`.
If no `drained-sha` exists (first close), diff against `project-sha`.

**Main-mode cleanup:** Fire `cleanup_main` event instead of
`cleanup_pass`. This transitions state to `drained` (plan persists,
can be re-activated via `work find`).

Textual guidance when work is done on main: "Consider a feature branch
for non-trivial work (`work start #N`). `quick-fix` for small changes."

---

## Step 1 — Context

```bash
python3 work-end/work_end_context.py workspace=<WORKSPACE> project=<PROJECT>
```

Parse the JSON output. Handle preconditions:

| Precondition | Status | Action |
|-------------|--------|--------|
| `branch_alignment` | `fail` | Hard stop — both repos must be on the same branch |
| `clean_tree` | `fail` | Hard stop — see DIRTY TREE PROTOCOL below |
| `meta_exists` | `needs_input` | Graceful degradation: infer issue from branch name, confirm with user |
| `meta_exists` | `pass` | Proceed — read context values from output |

<DIRTY-TREE-PROTOCOL>
**When `clean_tree` fails, the ONLY acceptable actions are:**

1. `git stash push -u -m "work-end: stashing uncommitted changes"` — preserves ALL changes (staged, unstaged, untracked) in a named stash entry
2. `git add -A && git commit -m "wip: uncommitted changes before work-end"` — commits everything on the current branch

**NEVER use any of these to clean a dirty tree:**
- `git reset --hard` — DESTROYS all uncommitted changes permanently
- `git checkout -- .` — DESTROYS all unstaged changes permanently
- `git clean -fd` — DESTROYS all untracked files permanently
- `git reset HEAD` followed by ignoring the changes

**Why:** The dirty files may belong to another session working in the same repo.
A `git reset --hard` destroyed hours of work in a real incident (Aug 2026).
The rebase and land scripts now include a `safety_stash()` call as defense-in-depth,
but the LLM must never attempt destructive cleanup either.
</DIRTY-TREE-PROTOCOL>

**Queue gate** (if `HAS_PLAN=yes`): Run `plan_manager.py detect` to check
queue state. If mid-queue (remaining uncompleted items exist), STOP and
redirect: "Queue has N remaining issues. Run `work next` to advance, or
pass `confirm-partial` to close the branch with remaining work."

**Issue-complete emission** (if `HAS_PLAN=yes`): Run
`complete_active_issue` after confirming close.

---

## Step 2 — Review

Code review, branch audit, loose ends sweep, and forcing function.
All four sub-steps are hard gates — Step 2 does not complete until
the forcing function has resolved all findings.

**Budget limits are not gates.** If code-review or branch-audit reports
a budget warning ("coverage may be incomplete"), proceed to the next
sub-step. The forcing function processes whatever findings were
collected. Do not restart the review, do not block, do not retry.
Surface the warning in the Step 6 close summary.

### 2.1 Code review

Invoke `code-review` on the branch diff. Per-line checklist (safety,
types, async, testing, performance).

**Security-audit suppression:** Do NOT offer security-audit escalation —
branch-audit Step 2.2 Robustness dimension handles security escalation.
During per-commit development review (outside work-end), code-review
continues to offer security-audit escalation as today.

After Step 2.1 completes, persist any unresolved findings to
`$WORKSPACE/.audit/findings.jsonl` via `append_finding` from
`project/findings.py` with `category: "review"` and `source: "code-review"`.

### 2.2 Branch audit

Invoke `branch-audit` on the full branch diff. Four dimensions:
Conformance, Coherence, Structure, Robustness.

Findings are appended to `findings.jsonl` after each dimension completes
(not batched). This ensures partial progress survives session interruption.

### 2.3 Loose ends sweep

```bash
python3 work-end/loose_ends_sweep.py workspace=<WS> project=<PROJ> branch=<BRANCH> cycle_start=<ISO>
```

Pass `cycle_start` as the timestamp when Step 2 started — this filters
out findings just written by Steps 2.1 and 2.2 to prevent double-counting.

The LLM supplements script output with conversation-context items
("I'll come back to this") and appends those to `findings.jsonl`.

### 2.4 Forcing function (HARD GATE)

Read all open findings from `$WORKSPACE/.audit/findings.jsonl` via
`read_findings` from `project/findings.py`. Present grouped by category:

```
Open findings — N items require resolution before branch close

AUDIT (branch-audit):
  1. [conformance/WARNING] ...
  2. [robustness/NOTE] ...

REVIEW (code-review):
  3. [WARNING] ...

LOOSE-END:
  4. [WARNING] ...

HYGIENE:
  5. [WARNING] ...

Prior sessions (accumulated):
  6. [WARNING] ...
```

**Triage filtering:** Only present findings whose status is `open` after
the review process. Findings already rejected by verification (reviewer
raised it, implementor proved it invalid) are not presented.

**Resolution options per finding:**

| Option | What happens |
|--------|-------------|
| **Fix** | Fix the issue now. Status → `resolved`, resolution includes commit SHA |
| **File** | Create a GitHub issue. Status → `filed`, resolution includes issue number |
| **Dismiss** | Not a real problem. Status → `dismissed`, resolution includes reason |

**Severity constraints:**

| Severity | Fix | File | Dismiss |
|----------|-----|------|---------|
| CRITICAL | Yes | Yes  | No      |
| WARNING  | Yes | Yes  | Yes     |
| NOTE     | Yes | Yes  | Yes     |

**Re-review after fixes:** When "Fix" creates new commits, re-run
code-review on those commits only. New findings join the queue.
Branch-audit does not re-run — fixes are scoped responses.

**Batch operations:**
- "File all remaining as single issue" — one issue with checklist
- "File each remaining" — one issue per finding
- "Dismiss all NOTEs" — blanket dismiss with user-provided reason

Each resolution is persisted to `findings.jsonl` immediately. If the
session aborts mid-forcing-function, already-resolved findings remain
resolved. Restart reads `findings.jsonl` and presents only remaining
`open` findings.

No finding survives branch close with status `open`.

**Duration estimate:** 10–30 minutes depending on branch size and
accumulated findings. code-review: 2–5 min, branch-audit: 5–10 min,
loose ends sweep: 1–2 min, forcing function: 2–15 min.

---

## Step 3 — Sweep

Present the pre-close checklist with all items ON:

```
Pre-close sweep — create before closing?

[x] 1  Knowledge capture   (forage then protocol — sequential)
[x] 2  ADR                 record architectural decisions
[x] 3  Doc sync            (update-claude-md then implementation-doc-sync)
[x] 4  write-content       capture branch narrative as diary entry

Type numbers to toggle, "all" to toggle all, or "go" to proceed:
```

<NEVER-RECOMMEND-SKIPPING>
Present all items ON. Do not recommend skipping. The user decides.
"Go" means proceed with current selections — all ON by default.
Session-bound items (1, 4) cannot be deferred.
</NEVER-RECOMMEND-SKIPPING>

**Run order:**
1. Forage sweep — while context is full
2. Protocol sweep
3. update-claude-md
4. implementation-doc-sync
5. ADR
6. write-content — last, synthesises full narrative

**Journal validation:** Context output includes journal state. Present
decisions interactively if `section_drift` or `unanchored_entries`
are non-empty.

**Slot mode per-repo sweep:** When in a slot, run protocol/update-claude-md/
impl-doc-sync per-repo (primary then secondaries). Session-bound items
(forage, ADR, write-content) run once after the per-repo loop.

---

## Step 4 — Execute

The LLM orchestrates script calls and subagent dispatches. Scripts handle
the mechanical per-repo loop.

### Sequence

```
1. Promote artifacts    — work_end_execute.py promote (once per workspace)
2. Phase A: Rebase      — work_end_execute.py rebase (all repos)
3. Phase B: Squash      — LLM per-repo loop (writes .squash-plan-<repo>.json)
4. Phase C: Land        — work_end_execute.py land (all repos: push, stamp)
```

**Lifecycle transitions at Execute milestones:**

| After | Fire | New state |
|-------|------|-----------|
| Review pass (Step 2) | `review_pass` | `closing:verified` |
| Promote done | `promote_pass` | `closing:promoted` |
| Land done (push) | `push_pass` | `closing:pushed` |
| Land done (merge) | `merge_pass` | `closing:merged` |
| Land done (stamp) | `stamp_pass` | `closing:stamped` |

### 4.1 Promote artifacts

```bash
python3 work-end/work_end_execute.py promote workspace=<WS> project=<PROJ> branch=<BRANCH>
```

Calls `close_artifacts.py` per unique workspace. In multi-repo slots,
deduplicates: each workspace promoted once, not per-repo. Never passes
`covers=` — issue closing happens once after all repos complete.

After success: fire `promote_pass` lifecycle transition.

### 4.1b Trajectory capture (enrichment)

After artifacts are promoted and before the branch is pushed. Non-blocking —
if this step fails or the user declines, continue to Phase A.

1. **Generate trajectory note** — using the full session context, draft a
   one-line trajectory note for each completed issue: "This work suggests
   X next because Y" (e.g., "Schema landed — #192 and #193 are now ready
   to implement").

2. **Propose enrichment updates** — assess how completed work shifts the
   strategic landscape for 2-3 sibling/related issues. Present in a table:

   | Issue | Field | Old | New | Reason |
   |-------|-------|-----|-----|--------|
   | #192 | readiness | needs-design | ready | Schema it depends on just landed |

3. **User confirms** — present the table. On YES, persist:

   ```bash
   python3 scripts/enrichment.py trajectory --issue <N> --repo <REPO> --text "<note>" --branch <BRANCH>
   python3 scripts/enrichment.py upsert --issue <N> --repo <REPO> --readiness ready
   ```

4. **Failure is non-blocking** — if enrichment.py fails or the user
   declines, continue to Phase A. Enrichment capture is valuable but
   never gates branch closure.

### 4.2 Phase A — Rebase

```bash
python3 work-end/work_end_execute.py rebase project=<PROJ> branch=<BRANCH> base_branch=<BASE>
```

If `REBASE_CONFLICT`: user resolves, re-runs.

**Post-rebase re-review:** If rebase was non-fast-forward (conflicts
resolved), re-run code-review on the conflict resolution diff only.
If findings: mini-gate with Fix/File/Dismiss (same severity constraints
as Step 2.4). Persist to `findings.jsonl`. All findings must be resolved
before proceeding to Step 4.3.

### 4.3 Phase B — Squash analysis (LLM loop)

For each repo: spawn a squash analysis subagent that classifies commits
and writes `.squash-plan-<repo>.json`. Repos with existing plan files
are skipped on restart.

**Slot mode marker:** After squash completes for all repos, if `IN_SLOT=yes`:

```bash
python3 work-end/work_end_execute.py write-marker slot_path=<SLOT_PATH> branch=<BRANCH>
```

This writes `.phase-a-complete` to the slot root, enabling `merge-slot`
in Phase C. Read `MARKER_WRITTEN=` from output. If error, report and
offer to retry — the squash is already done, only the marker failed.

### 4.4 Phase C — Land

**Branch mode (IN_SLOT=no):**

```bash
python3 work-end/work_end_execute.py land project=<PROJ> branch=<BRANCH> base_branch=<BASE> workspace=<WS>
```

Pushes main, stamps branch (via `land_branch.py stamp`), merges and
pushes workspace branch content to workspace main, stamps workspace branch.
Progress tracked in `.execute-progress` for crash recovery.

**Slot mode (IN_SLOT=yes):**

Requires `.phase-a-complete` marker (written in Step 3.4). Do NOT call
`work_end_execute.py land` in slot mode — that path is for branch mode only.

```bash
python3 work-slot/slot_manager.py merge-slot <SLOT_PATH>
```

merge-slot delegates to the shared land flow (`land_flow.py`). Builds
a batch of `RepoDescriptor`s for all repos in the slot (project +
workspace) and calls `land_batch()` — same 5-step flow used by branch
mode: preflight, rebase, merge+push, stamp. Two-hop transport
(clone → original → GitHub), SHA verification, `.landed` marker.

**Lifecycle:** After land returns, fire `push_pass`, `merge_pass`,
`stamp_pass` in rapid succession.

---

## Step 5 — Verify

```bash
python3 work-end/verify_slot_close.py <PROJ> branch=<BRANCH> workspace=<WS> [covers=<CSV>] [slot_dir=<SLOT_PATH>]
```

Defense-in-depth audit. Checks per-repo: merged, stamped, landing SHA,
main pushed. Checks workspace: stamped.

**Slot mode:** pass `slot_dir=<SLOT_PATH>` to enable slot-specific checks:
`.landed` marker, original repo sync (compares landed SHAs against
originals), archive status. Original repo paths resolved from slot
clone `local` remote URLs.

**Hard gate:** `VERIFIED=no` blocks Step 6. Present per-check failures
and offer recovery (re-run the failing Execute sub-step).

After success: fire lifecycle transition:
- **Branch mode:** `cleanup_pass` (→ `idle`)
- **Main mode:** `cleanup_main` (→ `drained` — plan persists)

---

## Step 5b — Close Issues

After verify passes, close all covered GitHub issues. This is a mechanical
gate — not optional, not LLM-dependent.

```bash
python3 work-end/work_end_execute.py close-issues repo=<OWNER_REPO> covers=<COVERS>
```

Read `CLOSED=N` from output. If `ERROR=`: report and offer retry.

**Verify gate:** Step 5 (verify_slot_close.py) checks `issues_closed` when
`covers=` and `issue_repo=` are passed. If issues are still open after
close-issues, verify will catch it.

```bash
python3 work-end/verify_slot_close.py <PROJ> branch=<BRANCH> workspace=<WS> covers=<COVERS> issue_repo=<OWNER_REPO>
```

---

## Step 6 — Close

### 6.1 Archive slot (slot mode only)

If `IN_SLOT=yes`, archive the slot:

```bash
python3 work-end/work_end_execute.py archive-slot slot_path=<SLOT_PATH> family_root=<FAMILY_ROOT> slot_num=<N>
```

Read `ARCHIVED=yes` from output. If `ERROR=`: report and offer retry or `force=yes`
to skip SHA verification.

### 6.2 Return to base branches

```bash
python3 work-end/branch_cleanup.py checkout-main <PROJECT> <WORKSPACE>
```

### 6.2b Scaffold cleanup

**Branch mode:** Remove `.plan` and `JOURNAL.md` from workspace to
prevent stale state detection in subsequent sessions.

```bash
python3 work-end/branch_cleanup.py cleanup-scaffold <WORKSPACE>
```

**Main mode:** Keep `.plan` (state is already `drained` from the
`cleanup_main` transition). Remove only `JOURNAL.md` and other
non-plan scaffold files.

### 6.3 Stack cleanup

If the closed branch was in `.pause-stack`, remove it.

### 6.4 ARC42 stale scan

If `ARC42STORIES.MD` exists, scan for stale statuses and fix.

### 6.5 Session rename

Suggest a descriptive session name if auto-generated.

### 6.6 Garden retrieval feedback

Record which garden entries were useful — both from this session and from
earlier sessions that propagated GE-IDs through HANDOFF.md.
Non-blocking — if the MCP server is unavailable, skip silently and continue.

1. **This session's entries:** Review `gardenSearch` results from this
   session's conversation context. Collect all GE-IDs that appeared.
2. **Propagated entries:** Read the `## Garden Entries Consulted` section
   from HANDOFF.md (if it exists). These are GE-IDs from earlier sessions
   whose usefulness was deferred to work-end.
3. Combine both lists. If empty, skip silently.
4. For each GE-ID, assess its relevance to the completed work:
   - **HIGHLY_RELEVANT** — directly solved the problem or was the key piece of context
   - **RELEVANT** — useful and informed the work
   - **PARTIALLY_RELEVANT** — tangentially related but not central
   - **NOT_RELEVANT** — appeared in results but wasn't useful for this task
5. Group GE-IDs by outcome and call `gardenFeedback` once per group:
   ```
   gardenFeedback(geIds: "GE-...|GE-...", outcome: "RELEVANT")
   ```
6. If the call fails (MCP unavailable, server not responding, connection
   refused, timeout), log a single warning and continue — never block
   work-end completion. Do not retry.

### 6.7 Session close summary

```
Session close complete.

✅ Code review       passed
✅ Artifacts         promoted (N files)
✅ Rebase            clean
✅ Squash            N → M commits
✅ Push + stamp      all repos
✅ Verify            VERIFIED=yes
✅ Branch closed     <branch-name>
```

### 6.8 Notes — surface and offer to append

If `$WORKSPACE/.notes/NOTES.md` exists and has content, surface the most
recent date section after the close summary:

```
Notes (2026-08-10):
  - Remember to check auth token expiry after the migration
  - [engine] reindex needed after next schema change
```

Then offer to append:
> "Anything worth noting for future sessions? (Enter to skip)"

If the user provides notes, append under today's date header and commit
to the orphan `notes` branch:
```bash
# Append to $WORKSPACE/.notes/NOTES.md under today's date
git -C $WORKSPACE/.notes add NOTES.md
git -C $WORKSPACE/.notes commit -m "notes: work-end"
```

This captures context that matters beyond the closed branch but isn't
a CLAUDE.md convention yet — e.g. "slot 107 has a stale .m2 cache",
"the enrichment DB needs a manual refresh after the next casehub slot".

Skip silently if no `.notes/` directory exists.

---

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Skip code review | #1 failure mode | Review is a HARD GATE |
| Manual artifact promotion | Leaves orphans | Run close_artifacts.py |
| Recommend skipping sweep | Loses session-bound content | Present defaults ON |
| Stamp before squash | SHAs become unreachable | Execute enforces stamp-after-squash |
| Push main without verify | Broken content on remote | Verify gate blocks close |
| Stamp without verified push | Branch falsely marked "landed" when content never reached remote | `cmd_stamp` verifies SHA on remote before writing stamp |
| Skip workspace stamp | Branch looks live to hygiene | land subcommand stamps both |
| `git reset --hard` to clean dirty tree | Destroys uncommitted work from other sessions | `git stash push -u -m "..."` — ALWAYS stash, NEVER reset |

---

## Skill Chaining

**Invoked by:**
- `work` — routing skill, when user says "work end"
- `executing-plans` — after all plan tasks complete
- `subagent-driven-development` — final close step

**Invokes:**
- `code-review` — Step 2.1, mandatory gate
- `branch-audit` — Step 2.2, mandatory gate (four dimensions)
- `loose-ends-sweep` — Step 2.3, via `loose_ends_sweep.py`
- `forage` — SWEEP (Step 3)
- `protocol` — SWEEP (Step 3)
- `update-claude-md` — Step 3
- `implementation-doc-sync` — Step 3
- `adr` — Step 3
- `write-content` — Step 3 (last)
- `publish-blog` — Step 4.1 (via close_artifacts.py)
- `git-squash` — Step 4.3 squash analysis

**Complements:**
- `work` — routing entry point
- `work-pause` — alternative (pause vs. close)
- `work-start` — opens branches; work-end closes them
- `work-slot` — slot detection triggers per-repo loop in Execute
- `using-git-worktrees` — worktree isolation before plan execution;
  work-end closes the branch regardless of isolation method
- `evidence-before-claims` (protocol) — per-boundary evidence gate;
  the forcing function at Step 2.4 is additive, not a replacement

**Reads from:** `ctx.py`, `.plan`, `.pause-stack`, CLAUDE.md, `.execute-progress`,
`.squash-plan-*.json`, `verify_slot_close.py` output, `findings.jsonl`
