---
name: work-end
description: >
  Use when the current branch is complete and ready to close — user says
  "work end", "close this branch", or "wrap up this issue". Must be invoked
  from the working branch, not main. Replaces "epic close".
---

# work-end

Closes the current branch cleanly. Five steps: Context → Sweep → Execute →
Verify → Close.

<HARD-GATE>
**Code review is mandatory before any push.** Invoke `code-review` on the
branch diff before Execute pushes anything. No exempt branches.

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

**On entry:** Read `META_STATE` from ctx.py. If already `closing:*`,
offer to continue from that gate. If `active`, fire
`transition(meta, 'work_end')` to enter `closing:review`.

**At each gate:** fire `transition()` for the corresponding event,
execute effects, then `commit_transition()`.

**Abort:** from `closing:review` or `closing:verified` only. Fire
`transition(meta, 'abort_close')` to return to `active`.
Post-promotion states are forward-only.

---

## Step 1 — Context

```bash
python3 work-end/work_end_context.py workspace=<WORKSPACE> project=<PROJECT>
```

Parse the JSON output. Handle preconditions:

| Precondition | Status | Action |
|-------------|--------|--------|
| `clean_tree` | `fail` | Hard stop — commit or stash changes first |
| `meta_exists` | `needs_input` | Graceful degradation: infer issue from branch name, confirm with user |
| `meta_exists` | `pass` | Proceed — read context values from output |

**Queue gate** (if `HAS_PLAN=yes`): Run `plan_manager.py detect` to check
queue state. If mid-queue, require `confirm-partial` to proceed.

**Issue-complete emission** (if `HAS_PLAN=yes`): Run
`complete_active_issue` after confirming close.

---

## Step 2 — Sweep

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

## Step 3 — Execute

The LLM orchestrates script calls and subagent dispatches. Scripts handle
the mechanical per-repo loop.

### Sequence

```
1. Code review          — LLM subagent gate (HARD GATE — must pass)
2. Promote artifacts    — work_end_execute.py promote (once per workspace)
3. Phase A: Rebase      — work_end_execute.py rebase (all repos)
4. Phase B: Squash      — LLM per-repo loop (writes .squash-plan-<repo>.json)
5. Phase C: Land        — work_end_execute.py land (all repos: push, stamp)
```

**Lifecycle transitions at Execute milestones:**

| After | Fire | New state |
|-------|------|-----------|
| Code review pass | `review_pass` | `closing:verified` |
| Promote done | `promote_pass` | `closing:promoted` |
| Land done (push) | `push_pass` | `closing:pushed` |
| Land done (merge) | `merge_pass` | `closing:merged` |
| Land done (stamp) | `stamp_pass` | `closing:stamped` |

### 3.1 Code review (HARD GATE)

Invoke `code-review` on the branch diff. If critical findings: fix, re-run.
For structural diffs (new modules, major refactors): use
`design-review --mode final-review` instead.

### 3.2 Promote artifacts

```bash
python3 work-end/work_end_execute.py promote workspace=<WS> project=<PROJ> branch=<BRANCH>
```

Calls `close_artifacts.py` per unique workspace. In multi-repo slots,
deduplicates: each workspace promoted once, not per-repo. Never passes
`covers=` — issue closing happens once after all repos complete.

After success: fire `promote_pass` lifecycle transition.

### 3.2b Trajectory capture (enrichment)

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

### 3.3 Phase A — Rebase

```bash
python3 work-end/work_end_execute.py rebase project=<PROJ> branch=<BRANCH> base_branch=<BASE>
```

If `REBASE_CONFLICT`: user resolves, re-runs.

### 3.4 Phase B — Squash analysis (LLM loop)

For each repo: spawn a squash analysis subagent that classifies commits
and writes `.squash-plan-<repo>.json`. Repos with existing plan files
are skipped on restart.

### 3.5 Phase C — Land

**Branch mode (IN_SLOT=no):**

```bash
python3 work-end/work_end_execute.py land project=<PROJ> branch=<BRANCH> base_branch=<BASE> workspace=<WS>
```

Pushes main, stamps branch (via `land_branch.py stamp`), merges and
pushes workspace branch content to workspace main, stamps workspace branch.
Progress tracked in `.execute-progress` for crash recovery.

**Slot mode (IN_SLOT=yes):**

```bash
python3 work-slot/slot_manager.py merge-slot <SLOT_PATH>
```

Uses the existing `merge_slot()` implementation which correctly handles:
per-repo rebase loop with retry, two-hop push (slot clone → original repo
→ GitHub), landing SHA stamps on all project branches, workspace branch
stamps and push, `.landed` marker with SHA audit trail.

**Lifecycle:** After land returns, fire `push_pass`, `merge_pass`,
`stamp_pass` in rapid succession.

---

## Step 4 — Verify

```bash
python3 work-end/verify_slot_close.py <PROJ> branch=<BRANCH> workspace=<WS> [covers=<CSV>]
```

Defense-in-depth audit. Checks per-repo: merged, stamped, landing SHA,
main pushed. Checks workspace: stamped.

**Hard gate:** `VERIFIED=no` blocks Step 5. Present per-check failures
and offer recovery (re-run the failing Execute sub-step).

After success: fire `cleanup_pass` lifecycle transition.

---

## Step 5 — Close

### 5.1 Archive slot (slot mode only)

Prompt before archiving:

> Slot `<N>` (`<branch-name>`) landed and verified.
> Archive to `slots/attic/<N>/`? **(y/n)**

- **y** → archive via `slot_manager.py remove-slot`
- **n** → leave slot active (user may want to inspect artifacts or continue work)

Do not archive without explicit confirmation.

### 5.2 Return to base branches

```bash
python3 work-end/branch_cleanup.py checkout-main <WORKSPACE> <PROJECT>
```

### 5.2b Scaffold cleanup

Remove `.meta` and `JOURNAL.md` from workspace to prevent stale state
detection in subsequent sessions.

```bash
python3 work-end/branch_cleanup.py cleanup-scaffold <WORKSPACE>
```

### 5.3 Stack cleanup

If the closed branch was in `.pause-stack`, remove it.

### 5.4 ARC42 stale scan

If `ARC42STORIES.MD` exists, scan for stale statuses and fix.

### 5.5 Write HANDOFF.md

Invoke the handover skill's Steps 2-6 to write HANDOFF.md to workspace
main with the close summary.

### 5.6 Session rename

Suggest a descriptive session name if auto-generated.

### 5.7 Session close summary

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

### 5.8 Surface notes

If `$WORKSPACE/.notes/NOTES.md` exists and has content, surface the most
recent date section after the close summary:

```
Notes (2026-08-10):
  - Remember to check auth token expiry after the migration
  - [engine] reindex needed after next schema change
```

Reminds the user of persistent context before they decide what to do next.
Skip silently if no notes exist or `.notes/` worktree is absent.

---

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Skip code review | #1 failure mode | Review is a HARD GATE |
| Manual artifact promotion | Leaves orphans | Run close_artifacts.py |
| Recommend skipping sweep | Loses session-bound content | Present defaults ON |
| Stamp before squash | SHAs become unreachable | Execute enforces stamp-after-squash |
| Push main without verify | Broken content on remote | Verify gate blocks close |
| Skip workspace stamp | Branch looks live to hygiene | land subcommand stamps both |

---

## Skill Chaining

**Invoked by:**
- `work` — routing skill, when user says "work end"
- `executing-plans` — after all plan tasks complete
- `subagent-driven-development` — final close step

**Invokes:**
- `code-review` — Step 3.1, mandatory gate
- `design-review` — Step 3.1 (`--mode final-review`), for structural diffs
- `forage` — SWEEP (Step 2)
- `protocol` — SWEEP (Step 2)
- `update-claude-md` — Step 2
- `implementation-doc-sync` — Step 2
- `adr` — Step 2
- `write-content` — Step 2 (last)
- `publish-blog` — Step 3.2 (via close_artifacts.py)
- `git-squash` — Step 3.4 squash analysis

**Complements:**
- `work` — routing entry point
- `work-pause` — alternative (pause vs. close)
- `handover` — work-end includes the full wrap (Step 5.6)
- `work-start` — opens branches; work-end closes them
- `work-slot` — slot detection triggers per-repo loop in Execute

**Reads from:** `ctx.py`, `.meta`, `.pause-stack`, CLAUDE.md, `.execute-progress`,
`.squash-plan-*.json`, `verify_slot_close.py` output
