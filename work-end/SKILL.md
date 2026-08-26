---
name: work-end
description: >
  Use when the current branch is complete and ready to close — user says
  "work end", "close this branch", or "wrap up this issue". Must be invoked
  from a branch with active work or from main with a .plan. On main, skips
  branch-specific steps (merge, stamp, rebase, squash). Replaces "epic close".
---

# work-end

The orchestrator drives the close sequence. Call it in a loop. Follow
its output. That is the job.

<HARD-GATE>
**Orchestrator errors are hard stops.** Do NOT edit `.close-progress`.
Do NOT manually execute steps. Do NOT work around errors. Fix the root
cause or escalate.

**Postconditions are enforced.** Review sub-steps require `produced=N`.
The forcing function verifies no open findings remain. The orchestrator
rejects `step_done` without evidence.

**Never defer work-end.** Session-bound items are lost if the session
ends. All other steps are Python scripts. Session length is not a factor.
</HARD-GATE>

### Red Flags — thoughts that mean STOP

| Thought | Reality |
|---------|---------|
| "I'll do the review steps myself" | The orchestrator yields them. Call it. |
| "The orchestrator crashed, I'll do it manually" | Manual steps miss side effects. STOP. |
| "I'll edit .close-progress to unstick it" | State machine violation. |
| "Code review was clean so I'll skip branch audit" | Each sub-step is independent. |
| "I'd recommend skipping the sweep" | Present defaults ON. User decides. |
| "Session is getting long" | Not a reason to skip anything. |

---

## Pre-close

### Path Resolution

```bash
python3 ~/.claude/skills/project/ctx.py
```

Use: `WORKSPACE`, `PROJECT`, `CURRENT_BRANCH`, `PROJECT_SHA`, `ISSUE_N`,
`COVERS`, `OWNER_REPO`, `BASE_BRANCH`, `META_STATE`, `HAS_PLAN`,
`PLAN_PATH`, `ON_MAIN`, `IN_SLOT`, `SLOT_PATH`.

### Lifecycle Entry

Auto-resolve transient states:

| `META_STATE` | Action |
|-------------|--------|
| `scaffolded` | Transition `auto_setup` → `active` |
| `transitioning` | Transition `auto_refresh` → `active` |
| `active` | Ready |
| `closing:*` | Offer to continue from that gate |

Then fire: `python3 ~/.claude/skills/project/lifecycle.py transition <PLAN_PATH> work_end`

### Context

```bash
python3 work-end/work_end_context.py workspace=<WORKSPACE> project=<PROJECT>
```

Handle preconditions from JSON output:
- `branch_alignment` fail → hard stop
- `clean_tree` fail → `git stash push -u` or WIP commit (NEVER `git reset --hard`)
- `meta_exists` `no-meta` → infer issue from branch name
- `meta_exists` `stale-plan` → remove stale .plan, proceed without lifecycle

**Queue gate:** If mid-queue, redirect to `work next`.

---

## Close Sequence — The Loop

Call the orchestrator in a loop until `ACTION=complete`:

```bash
python3 work-end/work_end_orchestrator.py \
    workspace=$WORKSPACE project=$PROJECT branch=$BRANCH \
    base_branch=$BASE meta_state=$META_STATE \
    [covers=$COVERS] [issue_repo=$OWNER_REPO] \
    [in_slot=$IN_SLOT] [slot_path=$SLOT_PATH] \
    [on_main=$ON_MAIN] [plan_path=$PLAN_PATH] \
    [family_root=$FAMILY_ROOT] [slot_num=$SLOT_NUM] \
    [sweep_selected=<CSV>] [skip_step=<NAME>] \
    [step_done=<NAME> produced=<N>] \
    [abort=yes] [conflict_resolved=yes]
```

### Action Dispatch

| ACTION | What to do |
|--------|-----------|
| `code_review` | Read `handlers/review.md` § code_review |
| `branch_audit_*` | Read `handlers/review.md` § branch_audit_dimension |
| `loose_ends` | Read `handlers/review.md` § loose_ends |
| `forcing_function` | Read `handlers/review.md` § forcing_function |
| `review_rebase` | Read `handlers/review.md` § review_rebase |
| `sweep_config` | Read `handlers/sweep_config.md` |
| `forage` | Invoke forage SWEEP |
| `protocol` | Invoke protocol SWEEP |
| `update_claude_md` | Invoke update-claude-md |
| `impl_doc_sync` | Invoke implementation-doc-sync |
| `adr` | Invoke adr |
| `write_content` | Invoke write-content (diary type) |
| `trajectory` | Read `handlers/execute.md` § trajectory |
| `squash` | Read `handlers/execute.md` § squash |
| `verify_recover` | Read `handlers/execute.md` § verify_recover |
| `user_input` | Read `handlers/user_input.md`, dispatch by CONTEXT |
| `error` | Report to user. Do NOT work around it. |
| `complete` | Run completion (below) |

For `sweep_selected`: pass user selections back after sweep_config.
For `skip_step`: only when user explicitly asks or step_failed.

### Completion

When `ACTION=complete`, run both and print verbatim:

```bash
python3 work-end/progress_summary.py $WORKSPACE mode=close
python3 work-end/verify_slot_close.py $PROJECT branch=$BRANCH workspace=$WORKSPACE covers=$COVERS issue_repo=$OWNER_REPO [on_main=yes] [slot_dir=$SLOT_PATH]
```

---

## Skill Chaining

**Invoked by:** `work`, `executing-plans`, `subagent-driven-development`

**Invokes:** `code-review`, `branch-audit`, `forage`, `protocol`,
`update-claude-md`, `implementation-doc-sync`, `adr`, `write-content`,
`publish-blog`, `git-squash` — all via orchestrator dispatch

**Reads from:** `ctx.py`, `.plan`, `.close-progress`, `findings.jsonl`
