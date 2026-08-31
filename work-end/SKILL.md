---
name: work-end
description: >
  Use when the current branch is complete and ready to close — user says
  "work end", "close this branch", or "wrap up this issue". Must be invoked
  from a branch with active work or from main with a .plan. On main, skips
  branch-specific steps (merge, stamp, rebase, squash). Replaces "epic close".
---

# work-end

Call the orchestrator. Follow its output. That is the job.

<HARD-GATE>
**Do NOT edit `.close-progress`.** The orchestrator owns its state.
**Do NOT manually execute steps.** Fix the root cause or STOP.
**Do NOT defer.** Session-bound items are lost if the session ends.
</HARD-GATE>

## Step 1 — Context

```bash
python3 ~/.claude/skills/project/ctx.py
```

Use: `WORKSPACE`, `PROJECT`, `CURRENT_BRANCH`, `PROJECT_SHA`, `ISSUE_N`,
`COVERS`, `OWNER_REPO`, `BASE_BRANCH`, `META_STATE`, `HAS_PLAN`,
`PLAN_PATH`, `ON_MAIN`, `IN_SLOT`, `SLOT_PATH`.

```bash
python3 work-end/work_end_context.py workspace=$WORKSPACE project=$PROJECT
```

Handle preconditions from the JSON output. Read `handlers/pre_close.md`
if any precondition is not `pass`.

If `HAS_PLAN=yes`, run `complete_active_issue` after confirming close.

## Step 2 — Enter closing state

If `META_STATE` is already `closing:*`, check for an interrupted close:

```bash
python3 work-end/close_resume.py $WORKSPACE
```

If `INTERRUPTED=yes`, print the resume prompt verbatim and ask:
> "Resume from [NEXT_STEP]? (Y/n)"

On Y: skip the lifecycle transition (already in closing state), go
straight to Step 3 — the orchestrator reads `.close-progress` and
skips completed steps automatically.

On n: offer abort (`abort=yes`) if in `closing:review` or `closing:verified`.

If `META_STATE` is `active` (normal path):

```bash
python3 ~/.claude/skills/project/lifecycle.py transition $PLAN_PATH work_end
python3 ~/.claude/skills/project/lifecycle.py commit-transition $PLAN_PATH from_state=active new_state=closing:review event=work_end
```

Both calls are required. `transition` validates; `commit-transition` persists
the state to `.plan`. Without `commit-transition`, the orchestrator's
`is_stale()` sees `state: active` with `closing:review` progress entries,
detects a mismatch, and wipes `.close-progress` on every invocation — causing
the orchestrator to loop forever on `code_review`.

**Abort:** from `closing:review` or `closing:verified` only. Pass
`abort=yes`. Post-promotion states are forward-only.

## Step 3 — The Loop

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

Call in a loop until `ACTION=complete`. If the output includes
`META_STATE=<value>`, update `$META_STATE` for subsequent calls —
lifecycle transitions advance the state mid-loop.

Read the ACTION, dispatch:

| ACTION | Do |
|--------|----|
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
| `doc_freshness_gate` | Read `handlers/doc_freshness.md` |
| `adr` | Invoke adr |
| `write_content` | Invoke write-content (diary) |
| `trajectory` | Read `handlers/execute.md` § trajectory |
| `squash` | Read `handlers/execute.md` § squash |
| `verify_recover` | Read `handlers/execute.md` § verify_recover |
| `upstream_pr` | Read `handlers/upstream_pr.md` |
| `user_input` | Read `handlers/user_input.md`, dispatch by CONTEXT |
| `error` | Report to user. STOP. |
| `complete` | Step 4 |

## Step 4 — Summary and Audit

```bash
python3 work-end/progress_summary.py $WORKSPACE mode=close
python3 work-end/verify_slot_close.py $PROJECT branch=$BRANCH workspace=$WORKSPACE covers=$COVERS issue_repo=$OWNER_REPO [on_main=yes] [slot_dir=$SLOT_PATH]
```

Print both outputs verbatim. Do not compose your own summary.

---

## Skill Chaining

**Invoked by:** `work`, `executing-plans`, `subagent-driven-development`

**Invokes:** `code-review`, `branch-audit`, `forage`, `protocol`,
`update-claude-md`, `implementation-doc-sync`, `adr`, `write-content`,
`git-squash` — all via orchestrator dispatch
