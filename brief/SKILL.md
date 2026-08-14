---
name: brief
description: >
  Use when the user says "/brief", "give a brief", "what's the state",
  "where are we", or "orient" — provides an orientation summary of the
  current work state, branch, issue, plan progress, and health status.
  Not for writing content (use write-content for that).
---

# brief

Orientation summary — what's the current state of work?

Runs `brief.py` to collect structured data, then formats it for the terminal.

---

## Steps

**Step 1 — Collect data**

```bash
python3 ~/.claude/skills/brief/brief.py
```

Read all output lines. Parse KEY=VALUE scalars, COMMIT= lines, CHECK= lines,
and CLOSED_BRANCH= lines.

**Step 2 — Format and present**

Adapt output to the STATE field:

### When STATE=feature_branch

```
Branch: <BRANCH>  Issue: #<ISSUE>
<HANDOFF_SUMMARY if non-empty>

Plan: <PLAN_POSITION> (<PLAN_BATCH>)  Active: #<ACTIVE_ISSUE>
  — or "No plan" if HAS_PLAN=no

Recent commits (<RECENT_COMMITS>):
  <COMMIT lines, indented>

Health:
  <CHECK lines, formatted as "✓ name" or "⚠ name: detail">

<NOTES_SUMMARY if non-empty — show as-is, most recent date section>
```

### When STATE=main_with_stack

```
On main — <STACK_DEPTH> paused branch(es) in stack.

Use `work resume` to restore one, or `work` to start something new.
```

### When STATE=main_idle

```
On main — no active work.

Recently closed:
  <CLOSED_BRANCH lines, formatted as "• <branch> #<issue> (<closed>)">
  — or "None" if empty

Use `work` to start something new.

<NOTES_SUMMARY if non-empty — show as-is, most recent date section>
```

---

## Skill Chaining

**Invoked by:** User via `/brief`, "brief me", "what's the state", "where are we"

**Does not invoke:** Any other skill — purely informational, no side effects.

**Related to:** `work` (routes lifecycle actions), `handover` (writes HANDOFF.md that brief reads)
