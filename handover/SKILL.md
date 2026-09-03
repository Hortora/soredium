---
name: handover
slash-command: false
description: >
  Use when ending a mid-work session (branch stays open) and wanting to preserve
  context for resumption, OR when a session is beginning and needing to resume
  from where things left off — says "create a handover", "end of session",
  "update the handover", "write a handover", "wrap", or "resume handover".
  NOT for branch closure (use work-end — it includes the full wrap).
  NOT for project narrative (use write-content, diary type).
---

# Session Handover

| Situation | Skill |
|-----------|-------|
| Branch **done** — closing, merging | `work-end` |
| Branch **not done** — ending session | `handover` (this) |
| **Continuing** work | `work continue` |

---

## Resuming

When the user says "resume handover": read `handlers/resume.md`.

---

## Creating a Handover

Call the orchestrator. Follow its output. That is the job.

<HARD-GATE>
A hook blocks HANDOFF.md commits without orchestrator completion.
Session-bound steps (forage, protocol, write-content, garden feedback)
depend on conversation context — they cannot be deferred. "Defer to
next session" means "lose forever."
</HARD-GATE>

### Step 1 — Context

```bash
python3 ~/.claude/skills/project/ctx.py
```

**Structural integrity gate:** If `CORRUPTION_COUNT` > 0, stop and report.
A handover written against a corrupted workspace captures wrong state.

### Step 2 — The Loop

```bash
python3 handover/wrap_orchestrator.py \
    workspace=$WORKSPACE project=$PROJECT branch=$BRANCH \
    [covers=$COVERS] [issue_repo=$OWNER_REPO] \
    [plan_path=$PLAN_PATH] [has_arc42=$HAS_ARC42STORIES] \
    [has_plan=$HAS_PLAN] \
    [sweep_selected=<csv>] [skip_step=<name>]
```

Call in a loop until `ACTION=complete`. Dispatch:

| ACTION | Do |
|--------|----|
| `loose_ends` | Mechanical — runs automatically |
| `wrap_sweep_config` | Read `handlers/sweep_config.md` |
| `forage` | Invoke forage SWEEP |
| `protocol` | Invoke protocol SWEEP |
| `update_claude_md` | Invoke update-claude-md |
| `write_content` | Invoke write-content (diary) |
| `user_input` (epic_hygiene) | Run `hygiene_scan.py`, present findings |
| `user_input` (journal_entry) | Write JOURNAL.md entries |
| `user_input` (arc42_scan) | Read `handlers/arc42_stale_scan.md` |
| `user_input` (garden_feedback) | Run `garden_feedback_table.py`, present table |
| `user_input` (notes) | Notes prompt |
| `user_input` (handoff_write) | Read `handlers/handoff_write.md` |
| `wip_commit` | Mechanical — runs automatically |
| `error` | Report to user. STOP. |
| `complete` | Step 3 |

Skipping is scoped to the failed step ONLY. `skip_step=` is validated
against the last yielded step. Do not skip steps the orchestrator hasn't
yielded.

### Step 3 — Summary

```bash
python3 work-end/progress_summary.py $WORKSPACE mode=wrap
```

Print verbatim.

---

## Skill Chaining

**Invoked by:** User ("wrap", "end of session", "create a handover")

**Invokes:** forage, protocol, write-content, update-claude-md (via orchestrator)
