---
name: work-end
description: >
  Use when the current branch is complete and ready to close — user says
  "work end", "close this branch", or "wrap up this issue". Must be invoked
  from a branch with active work or from main with a .plan. On main, skips
  branch-specific steps (merge, stamp, rebase, squash). Replaces "epic close".
---

# work-end

Closes the current branch cleanly. The orchestrator drives the close
sequence — Python decides what's next, the LLM executes one action
at a time. The LLM cannot skip what it cannot see.

<HARD-GATE>
**Review is mandatory before any push.** The review action runs
code-review, branch-audit, loose ends sweep, and forcing function
before Execute pushes anything. No exempt branches.

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

## Pre-close

### Path Resolution (run first, always)

```bash
python3 ~/.claude/skills/project/ctx.py
```

Use the printed values as concrete strings in all subsequent commands.
`WORKSPACE`, `PROJECT`, `CURRENT_BRANCH`, `PROJECT_SHA`, `ISSUE_N`,
`COVERS`, `OWNER_REPO`, `BASE_BRANCH`, `META_STATE`, `HAS_PLAN`,
`PLAN_PATH`, `ON_MAIN`, `IN_SLOT`, `SLOT_PATH`.

### Lifecycle State Machine Integration

work-end uses the lifecycle state machine to track closing progress:

```
active -> closing:review -> closing:verified -> closing:promoted -> closing:pushed -> closing:merged -> closing:stamped -> idle
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

**Abort:** from `closing:review` or `closing:verified` only. Pass
`abort=yes` to the orchestrator. Post-promotion states are forward-only.

### Main-mode detection

Read `ON_MAIN` from ctx.py. If `ON_MAIN=yes`, work-end runs in
**main mode** — same ceremony minus branch-specific steps:

| Step | Branch mode | Main mode |
|------|-------------|-----------|
| Context | Check branch alignment | Check .plan exists |
| Review | Diff against base branch | Diff against `drained-sha` from `.plan` |
| Sweep | Identical | Identical |
| Promote | Identical | Identical |
| Rebase | Rebase onto base | **Skip** |
| Squash | Classify branch commits | **Skip** |
| Land | Push, stamp, merge | Push only |
| Verify | Check merged + stamped | Check pushed |
| Close issues | Identical | Identical |
| Checkout main | Switch to main | **Skip** (already there) |
| Cleanup | Remove .plan | Keep .plan, fire `cleanup_main` (-> `drained`) |

**Main-mode diff base:** Read `drained-sha` from `.plan`'s `## State`.
Diff against this SHA: `git -C "$PROJECT" diff <drained-sha>..HEAD`.
If no `drained-sha` exists (first close), diff against `project-sha`.

### Context

```bash
python3 work-end/work_end_context.py workspace=<WORKSPACE> project=<PROJECT>
```

Parse the JSON output. Handle preconditions:

| Precondition | Status | Action |
|-------------|--------|--------|
| `branch_alignment` | `fail` | Hard stop — both repos must be on the same branch |
| `clean_tree` | `fail` | Hard stop — see DIRTY TREE PROTOCOL below |
| `meta_exists` | `needs_input` (detail: `no-meta`) | Graceful degradation: infer issue from branch name, confirm with user |
| `meta_exists` | `needs_input` (detail: `stale-plan`) | Stale .plan from a different branch. Remove it, infer issue from current branch name, proceed without lifecycle metadata |
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

## Close Sequence — Orchestrator Loop

After context is resolved and `closing:review` is entered, the
orchestrator drives the close sequence. Call it in a loop until
`ACTION=complete`:

```
loop:
  output = run("python3 work-end/work_end_orchestrator.py
    workspace=$WORKSPACE project=$PROJECT branch=$BRANCH
    base_branch=$BASE meta_state=$META_STATE
    [covers=$COVERS] [issue_repo=$OWNER_REPO]
    [in_slot=$IN_SLOT] [slot_path=$SLOT_PATH]
    [on_main=$ON_MAIN] [plan_path=$PLAN_PATH]
    [family_root=$FAMILY_ROOT] [slot_num=$SLOT_NUM]
    [sweep_selected=<CSV>] [skip_step=<NAME>]
    [abort=yes] [conflict_resolved=yes]")
  parse ACTION= from output

  if ERROR= in output:
    FALLBACK_TRIGGERED=<STEP from output>
    FALLBACK_REASON=<ERROR value>
    log both to conversation
    append fallback_<STEP>=<REASON> to .close-progress
    use fallback instructions for this step (see Fallback section)
    go to loop

  if ACTION=complete        -> run progress summary (see below), done
  if ACTION=user_input      -> dispatch by CONTEXT (see Handler: user_input)
  if ACTION=review          -> Handler: review
  if ACTION=review_rebase   -> Handler: review_rebase
  if ACTION=sweep_config    -> Handler: sweep_config
  if ACTION=squash          -> Handler: squash
  if ACTION=trajectory      -> Handler: trajectory
  if ACTION=verify_recover  -> Handler: verify_recover
  if ACTION=forage          -> invoke forage SWEEP
  if ACTION=protocol        -> invoke protocol SWEEP
  if ACTION=update_claude_md -> invoke update-claude-md
  if ACTION=impl_doc_sync   -> invoke implementation-doc-sync
  if ACTION=adr             -> invoke adr
  if ACTION=write_content   -> Handler: write_content
  go to loop
```

After executing an action, call the orchestrator again with the same
arguments. The orchestrator reads `.close-progress` to determine the
next action. When the LLM marks a judgment step done (by calling the
orchestrator again after executing it), the orchestrator advances.

### Completion — Progress Summary

When `ACTION=complete`, run the mechanical summary and print it verbatim:

```bash
python3 work-end/progress_summary.py $WORKSPACE mode=close
```

**Do not compose your own summary.** The script reads `.close-progress`
and outputs a deterministic report showing every step's status. Print
the script's output as-is — the user sees exactly what Python reported.

For `sweep_selected`: after the user responds to `sweep_config`,
pass their selections back: `sweep_selected=forage,protocol,...`

For `skip_step`: when the user declines a step, pass `skip_step=<name>`
to mark it skipped and advance.

For `conflict_resolved`: after the user resolves a rebase conflict,
pass `conflict_resolved=yes` to re-run rebase verification.

---

## Action Handlers

### Handler: review

Code review, branch audit, loose ends sweep, and forcing function.
All four sub-steps are hard gates — review does not complete until
the forcing function has resolved all findings.

**Budget limits are not gates.** If code-review or branch-audit reports
a budget warning ("coverage may be incomplete"), proceed to the next
sub-step. The forcing function processes whatever findings were
collected. Do not restart the review, do not block, do not retry.
Surface the warning in the close summary.

#### Code review

Invoke `code-review` on the diff specified by DIFF_RANGE.

**Security-audit suppression:** Do NOT offer security-audit escalation —
branch-audit Robustness dimension handles security escalation.

After code-review completes, persist any unresolved findings to
`$WORKSPACE/.audit/findings.jsonl` via `append_finding` from
`project/findings.py` with `category: "review"` and `source: "code-review"`.

#### Branch audit

Invoke `branch-audit` on the full branch diff. Four dimensions:
Conformance, Coherence, Structure, Robustness.

Findings are appended to `findings.jsonl` after each dimension completes
(not batched). This ensures partial progress survives session interruption.

#### Loose ends sweep

```bash
python3 work-end/loose_ends_sweep.py workspace=$WS project=$PROJ branch=$BRANCH cycle_start=<ISO>
```

Pass `cycle_start` as the timestamp when the review action started — this
filters out findings just written by code-review and branch-audit.

Supplement script output with conversation-context items
("I'll come back to this") and append those to `findings.jsonl`.

#### Forcing function (HARD GATE)

Read all open findings from `$WORKSPACE/.audit/findings.jsonl` via
`read_findings` from `project/findings.py`. Present grouped by category:

```
Open findings — N items require resolution before branch close

AUDIT (branch-audit):
  1. [conformance/WARNING] ...

REVIEW (code-review):
  2. [WARNING] ...

LOOSE-END:
  3. [WARNING] ...
```

**Resolution options per finding:**

| Option | What happens |
|--------|-------------|
| **Fix** | Fix the issue now. Status -> resolved, resolution includes commit SHA |
| **File** | Create a GitHub issue. Status -> filed, resolution includes issue number |
| **Dismiss** | Not a real problem. Status -> dismissed, resolution includes reason |

**Severity constraints:**

| Severity | Fix | File | Dismiss |
|----------|-----|------|---------|
| CRITICAL | Yes | Yes  | No      |
| WARNING  | Yes | Yes  | Yes     |
| NOTE     | Yes | Yes  | Yes     |

**Re-review after fixes:** When "Fix" creates new commits, re-run
code-review on those commits only. New findings join the queue.
Branch-audit does not re-run.

**Batch operations:**
- "File all remaining as single issue" — one issue with checklist
- "File each remaining" — one issue per finding
- "Dismiss all NOTEs" — blanket dismiss with user-provided reason

Each resolution is persisted to `findings.jsonl` immediately.
No finding survives branch close with status `open`.

### Handler: review_rebase

Code-review ONLY on the conflict-resolution diff specified by DIFF_RANGE.

Scope constraint: NO branch-audit, NO loose-ends sweep, NO forcing function.
This is a scoped review of conflict-resolution commits only.

If findings: mini-gate with Fix/File/Dismiss (same severity constraints as
the full review handler). Persist to findings.jsonl. All findings must be
resolved before the orchestrator continues.

### Handler: sweep_config

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

Report selected items back to orchestrator via sweep_selected= argument:
```
python3 work-end/work_end_orchestrator.py ... sweep_selected=forage,protocol,update_claude_md,impl_doc_sync,adr,write_content
```

**Journal validation:** If JOURNAL_DRIFT or UNANCHORED_ENTRIES in
orchestrator output, present decisions interactively before proceeding.

### Handler: forage

Invoke forage SWEEP. Run while conversation context is full — this is
why forage runs first in the sweep order.

### Handler: protocol

Invoke protocol SWEEP.

### Handler: update_claude_md

Invoke update-claude-md.

### Handler: impl_doc_sync

Invoke implementation-doc-sync.

### Handler: adr

Invoke adr to record architectural decisions made during this branch.

### Handler: write_content

Invoke write-content (diary type) to capture the branch narrative.
This runs LAST in the sweep — it synthesises the full narrative from
everything that happened on the branch, including forage and protocol
discoveries from earlier sweep steps.

Session-bound — cannot be deferred to another session.

### Handler: trajectory

After artifacts are promoted and before the branch is pushed. Non-blocking —
if this step fails or the user declines, the orchestrator continues.

1. Draft a one-line trajectory note for each completed issue.
2. Propose enrichment updates — assess how completed work shifts the
   strategic landscape for 2-3 sibling/related issues.
3. Present table for user confirmation. On YES:
   ```bash
   python3 scripts/enrichment.py trajectory --issue <N> --repo <REPO> --text "<note>" --branch <BRANCH>
   python3 scripts/enrichment.py upsert --issue <N> --repo <REPO> --readiness ready
   ```
4. Failure is non-blocking.

### Handler: squash

For each repo listed in REPOS: classify commits and write
`.squash-plan-<repo>.json`. Repos with existing plan files are
skipped (restart safety).

**Slot mode marker:** If in_slot=yes, the orchestrator writes the
.phase-a-complete marker mechanically after squash completes — the
LLM does not need to handle this.

### Handler: user_input (parameterised by CONTEXT=)

**CONTEXT=arc42_scan:**
If ARC42STORIES.MD exists, scan for stale statuses and offer fixes.

**CONTEXT=session_rename:**
Suggest a descriptive session name if auto-generated.

**CONTEXT=garden_feedback:**
Skeptical review of garden entries retrieved this session. The script is
the source of truth for what was retrieved — not conversation context.

1. Run the feedback table script:
   ```bash
   python3 scripts/garden_feedback_table.py <PROJECT_PATH> hours=4
   ```
   Read the output — it lists every GE-ID retrieved from the tracking DB
   with mechanical flags (version mismatches, missing verified_on, stale
   last_reviewed).

2. If `NO_ENTRIES=true`: skip silently — no garden entries were retrieved.

3. Present the table with inverted default — all entries default to RELEVANT:
   ```
   Garden feedback — N entries retrieved this session

     1.   GE-20260824-c09677  "Stateless re-entrant script pattern"     → RELEVANT
     2.   GE-20260821-ebba3b  "work-end can stamp without merging"      → RELEVANT
     3. ⚠️ GE-20260809-96d41c  "gitignore trailing-slash skips symlinks" → RELEVANT
          verified_on: git 2.43 — project uses git 2.47
     4.   GE-20260813-f7d73e  "merge-slot needs .phase-a-complete"      → RELEVANT

   Be skeptical — which should NOT go back as RELEVANT?
   Downgrade any? (e.g. "3 OUTDATED 4 NOT_RELEVANT", or "go" to send all as RELEVANT)
   ```

4. The LLM's job is to be skeptical about the unflagged entries — find
   the ones that weren't actually useful. Mechanically flagged entries
   (version mismatch, stale) are already surfaced; the LLM adds judgment
   about whether unflagged entries were genuinely used.

5. After user responds, group by outcome and call gardenFeedback:
   - Entries not downgraded → RELEVANT
   - User-downgraded entries → the specified outcome (NOT_RELEVANT,
     PARTIALLY_RELEVANT, OUTDATED)
   - For OUTDATED: include stack parameter from the script's PROJECT_STACK
   ```
   gardenFeedback(geIds: "GE-...|GE-...", outcome: "RELEVANT",
       issueRepo: "<OWNER_REPO>", issueNumber: <ISSUE_N>)
   gardenFeedback(geIds: "GE-...", outcome: "OUTDATED",
       stack: "<from PROJECT_STACK>",
       issueRepo: "<OWNER_REPO>", issueNumber: <ISSUE_N>)
   ```
6. MCP unavailable → warn once, continue (never block)

**CONTEXT=notes:**
Surface most recent date section from $WORKSPACE/.notes/NOTES.md.
Offer to append. If user provides notes, append under today's date
and commit to orphan notes branch.

**CONTEXT=step_failed:**
Judgment step failed after 3 retries. Present STEP, ATTEMPTS, REASON.
Options: skip / retry / abort.

<SKIP-ISOLATION>
**Skipping is scoped to the failed step ONLY.** A failure in one sweep step
(e.g. forage) does not justify skipping other sweep steps (e.g. write_content).
Each step is independent — skip only the step named in STEP=.

The orchestrator enforces this: `skip_step=` is validated against the last
yielded step. Skipping a step that was not yielded returns ERROR=invalid_skip.

**When you may pass skip_step:**
- The orchestrator returned `CONTEXT=step_failed` for that specific STEP
- The user explicitly asked to skip that specific step

**When you may NOT pass skip_step:**
- A different step failed and you want to "skip the rest of the sweep"
- You think the step is unnecessary based on session context
- You want to save time or tokens
</SKIP-ISOLATION>

**CONTEXT=rebase_conflict:**
Rebase conflict needs manual resolution. User resolves, then pass
conflict_resolved=yes to the orchestrator.

### Handler: verify_recover

Verify returned VERIFIED=no. Present per-check failures from FAILURES=.
Offer recovery: re-run the failing Execute sub-step, then re-run verify.

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
- `code-review` — review action, mandatory gate
- `branch-audit` — review action, mandatory gate (four dimensions)
- `loose-ends-sweep` — review action, via `loose_ends_sweep.py`
- `forage` — SWEEP (sweep_config action)
- `protocol` — SWEEP (sweep_config action)
- `update-claude-md` — sweep action
- `implementation-doc-sync` — sweep action
- `adr` — sweep action
- `write-content` — sweep action (last)
- `publish-blog` — promote step (via close_artifacts.py)
- `git-squash` — squash action

**Complements:**
- `work` — routing entry point
- `work-pause` — alternative (pause vs. close)
- `work-start` — opens branches; work-end closes them
- `work-slot` — slot detection triggers per-repo loop in Execute
- `using-git-worktrees` — worktree isolation before plan execution;
  work-end closes the branch regardless of isolation method
- `evidence-before-claims` (protocol) — per-boundary evidence gate;
  the forcing function at review is additive, not a replacement

**Reads from:** `ctx.py`, `.plan`, `.pause-stack`, CLAUDE.md, `.execute-progress`,
`.close-progress`, `.squash-plan-*.json`, `verify_slot_close.py` output, `findings.jsonl`
