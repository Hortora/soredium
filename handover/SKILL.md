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
| Branch **done** — closing, merging | `work-end` (includes full wrap) |
| Branch **not done** — ending session | `handover` (this skill) |
| **Continuing** work | `work continue` (auto-reads HANDOFF.md) |

---

## Resuming a Handover

When the user says "resume handover", locate and read HANDOFF.md.

### Step R1 — Find HANDOFF.md

```bash
python3 ~/.claude/skills/project/ctx.py
```

Use `WORKSPACE` from output. HANDOFF.md is at `<WORKSPACE>/HANDOFF.md`.
Do not scan CLAUDE.md for workspace path — use ctx.py.

### Step R2 — Check freshness, then read

```bash
git -C "$WORKSPACE" log -1 --format="%ar" -- HANDOFF.md
```

If older than a week, flag: "HANDOFF.md is N days old — verify key assumptions."

Read the file, then run entry-scope validation:
```bash
python3 ~/.claude/skills/project/work_health.py --scope entry --project "$PROJECT" --workspace "$WORKSPACE"
```

Check for open branch via `.plan` and `is_closed()`. If branch is open:
> "Branch `<name>` is still open for #`<issue>`. Run `/work` to continue."

### Step R3 — Display .plan queue

If `.plan` exists, display via `format_resume_display()`.

Present resume output: **Last Session** (2-3 lines), **Immediate Next Step**
(specific action), **Cross-Module** (only active blockers with tracked issues),
**Queue** (if .plan), **work_health findings** (if any).

---

## Creating a Handover — Orchestrator Loop

<HARD-GATE>
**The orchestrator controls the wrap sequence.** Call it in a loop until
`ACTION=complete`. Do not skip the orchestrator. Do not jump ahead to
writing HANDOFF.md. The orchestrator ensures sweep steps (forage,
protocol, write-content) run while session context is live.

A hook blocks HANDOFF.md commits without orchestrator completion.
</HARD-GATE>

### Path Resolution

```bash
python3 ~/.claude/skills/project/ctx.py
```

Use `WORKSPACE`, `PROJECT`, `CURRENT_BRANCH`, `COVERS`, `OWNER_REPO`,
`HAS_PLAN`, `PLAN_PATH`, `HAS_ARC42STORIES`.

### The Loop

```bash
python3 handover/wrap_orchestrator.py \
    workspace=$WORKSPACE project=$PROJECT branch=$BRANCH \
    [covers=$COVERS] [issue_repo=$OWNER_REPO] \
    [plan_path=$PLAN_PATH] [has_arc42=$HAS_ARC42STORIES] \
    [has_plan=$HAS_PLAN] \
    [sweep_selected=<csv>] [skip_step=<name>]
```

Call in a loop until `ACTION=complete`:

| ACTION | What to do |
|--------|-----------|
| `loose_ends` | Mechanical — runs automatically |
| `user_input` (CONTEXT=epic_hygiene) | Run `hygiene_scan.py`, present findings |
| `wrap_sweep_config` | Present sweep checklist, pass selections via `sweep_selected=` |
| `forage` | Invoke forage SWEEP |
| `protocol` | Invoke protocol SWEEP |
| `update_claude_md` | Invoke update-claude-md |
| `user_input` (CONTEXT=journal_entry) | Write JOURNAL.md entries |
| `user_input` (CONTEXT=arc42_scan) | Read `handlers/arc42_stale_scan.md`, follow it |
| `write_content` | Invoke write-content (diary) |
| `user_input` (CONTEXT=garden_feedback) | Same handler as work-end (run `garden_feedback_table.py`) |
| `user_input` (CONTEXT=notes) | Notes prompt |
| `user_input` (CONTEXT=handoff_write) | **Read `handlers/handoff_write.md` and follow it** |
| `wip_commit` | Mechanical — commits all WIP |
| `complete` | Run progress summary (see below) |

**Sweep checklist** (ACTION=wrap_sweep_config): present all items ON.
Pass back: `sweep_selected=forage,protocol,update_claude_md,write_content`

<SESSION-BOUND-ITEMS>
Forage, protocol, write-content, garden feedback depend on conversation
context. They cannot be deferred — "defer to next session" = "lose forever."
</SESSION-BOUND-ITEMS>

<SKIP-ISOLATION>
Skipping is scoped to the failed step ONLY. The orchestrator validates
`skip_step=` against the last yielded step.
</SKIP-ISOLATION>

### Completion — Progress Summary

```bash
python3 work-end/progress_summary.py $WORKSPACE mode=wrap
```

Print the output verbatim. Do not compose your own summary.

---

## Red Flags — thoughts that mean STOP

| Thought | Reality |
|---------|---------|
| "I'll just write HANDOFF.md directly" | The orchestrator ensures sweeps run first. Call it. |
| "The user said wrap, so write the handover" | Wrap = orchestrator loop, not just HANDOFF.md. |
| "Sweeps aren't needed for a short session" | Session-bound items are lost if skipped. |
| "I'll skip the orchestrator to save time" | A hook blocks HANDOFF.md commits without it. |

---

## Common Pitfalls

| Mistake | Fix |
|---------|-----|
| Skip orchestrator, write HANDOFF.md directly | Call the orchestrator loop — hook blocks commits without it |
| Restate unchanged context | Write `*Unchanged — git show HEAD~1:HANDOFF.md*` |
| Skip the commit | Commit is mandatory — the archive mechanism |
| Load files to reference them | Write the path; next session reads on demand |
| Copy CLAUDE.md content | Auto-loaded; omit entirely |
| Write "continue work" as next step | Be specific — name the file, command, or section |

---

## Success Criteria

- Orchestrator loop ran to `ACTION=complete`
- Sweep steps executed (forage, protocol, write-content, update-claude-md)
- HANDOFF.md exists, committed, under 200 tokens
- Unchanged sections reference git history
- Immediate next step is specific enough to act on
- Progress summary printed (mechanical, not LLM-composed)

---

## Skill Chaining

**Invoked by:** User ("wrap", "end of session", "create a handover")

**Invokes:** forage, protocol, write-content, update-claude-md (via orchestrator),
handlers/handoff_write.md (for HANDOFF.md writing)

**Complements:** work-end (branch closure includes full wrap), work-pause
(switches branches mid-session, different intent)
