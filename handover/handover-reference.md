# HANDOFF.md Reference

Used by `handover` Step 5 (write HANDOFF.md) and by the next session
when resuming work. Contains the template, routing table, and git read patterns.

---

## HANDOFF.md Template

HANDOFF.md is session context only — no work tracking, no backlog. Work
state lives in `.plan` (curated queue) and GitHub issues (source of truth).

Target: under 200 tokens. The "why" that connects commits and .plan items
into a coherent story for the next session.

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

**What moved out of HANDOFF.md:**

| Previously in HANDOFF.md | Now in | Mechanism |
|--------------------------|--------|-----------|
| What's Left | Main `.plan` or GitHub issues | Trailing items become issues |
| What's Next | Main `.plan` | Curated queue with priority |
| Queue Progress | `.plan` Session State | Displayed via format_resume_display() |
| State Right Now | `.plan` + git + `work_health.py` | Derived, not cached |
| Open Questions / Blockers | GitHub issues | Filed as issues with labels |

**Resume path:** On resume, the handover skill reads HANDOFF.md for session
context, then runs `work_health.py --scope entry` and displays the `.plan`
queue via `format_resume_display()`. The combined output gives the next
session both narrative context and work state.

---

## What Goes in HANDOFF.md vs Other Files

| Information | Where it belongs |
|-------------|-----------------|
| Session narrative (what happened, reasoning) | HANDOFF.md |
| Immediate next action | HANDOFF.md |
| Cross-repo blockers with tracked issues | HANDOFF.md Cross-Module |
| Work items, backlog, trailing obligations | Main `.plan` + GitHub issues |
| Queue progress and priority ordering | `.plan` Session State |
| Branch/slot state validation | `work_health.py` (derived from git) |
| Why a design decision was made | write-blog or adr |
| Current architecture | design-snapshot (reference from handover) |
| Cross-project technical gotcha | garden (reference from handover) |
| Undecided possibilities, notes for later | `$WORKSPACE/.notes/NOTES.md` |
| Permanent conventions | CLAUDE.md (auto-loaded, don't repeat) |

---

## Surgical git Reads for the Next Session

When the next session needs context from a previous handover, use targeted
git commands rather than loading the whole file:

```bash
# Just the "Open Questions" section from two sessions ago
git show HEAD~2:HANDOFF.md | grep -A 15 "## Open Questions"

# What the "State Right Now" section said last week
git log --before="7 days ago" -1 --format="%H" -- HANDOFF.md \
  | xargs -I{} git show {}:HANDOFF.md | grep -A 10 "## State"

# Did anything change in the References table between sessions?
git diff HEAD~1 HEAD -- HANDOFF.md | grep "^[+-]" | grep "References" -A 20
```

The principle: prefer `grep -A N` over reading entire files. Git diffs show
only changed lines. Section reads are cheaper than full-file reads.

---

## When to Load a Previous Handover

Load `git show HEAD~1:HANDOFF.md` when:
- The current handover marks several sections as "Unchanged" and the task
  requires that context — retrieve only the relevant section
- The current handover is stale (>7 days) and an intermediate one might
  have more recent state

Do NOT preemptively load previous handovers at session start. Check freshness
first; load only when a specific task demands the missing context.
