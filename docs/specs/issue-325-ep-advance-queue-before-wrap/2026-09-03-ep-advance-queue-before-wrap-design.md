# EP: Advance Queue Before Wrap/Continue Choice

**Issue:** Hortora/soredium#325
**Date:** 2026-09-03
**Scale:** XS | **Complexity:** Low

## Problem

When executing-plans completes all tasks (ALL_DONE=True) and the `.plan` queue has remaining issues, Step 4 directs the LLM to "Run `work next`". In practice, the LLM offers wrap/continue as a session choice before advancing, and choosing wrap invokes the handover skill without advancing the queue. The completed issue remains `← active` with all tasks checked but not marked done — the next session sees a stale active issue with nothing to do.

## Fix

Rewrite Step 4 as a three-phase sequence that separates mechanical advancement from human session choice.

### Current Step 4 (broken)

```markdown
**4. Route to next step:**

- **If `HAS_PLAN=yes` and the queue has remaining issues** → Run `work next`
- **If no plan, or the queue is complete** → invoke work-end
```

### New Step 4

```markdown
**4. Route to next step:**

Run ctx.py. Read `HAS_PLAN` and `PLAN_POSITION`.

**4a. Advance queue (unconditional, mechanical):**

If `HAS_PLAN=yes` and the queue has remaining issues:

1. Run `work next` immediately — this advances the queue, closes the
   GitHub issue, and sets the next issue as active.
2. Report: "Advanced to #<next>. Issue #<completed> closed."

This is not a user choice. Queue advancement is a mechanical consequence
of task completion.

**4b. Offer session choice:**

After advancing (or if no advance was needed):

- If queue has remaining issues (just advanced):
  - **Continue** → proceed to next issue's plan
  - **Wrap** → invoke handover (queue already advanced, next session
    starts clean at the new active issue)

- If queue is complete, or no plan exists:
  - Invoke work-end for final review, squash, push, and branch closure.
```

### What doesn't change

- **Step 2 batch completion** — already correct. Wrap is only offered when "more batches remain"; ALL_DONE proceeds directly to Step 3.
- **Step 3 completeness audit** — unchanged.
- **`work` skill D4 (mid-session done-detection)** — complementary detection from the router side, unaffected.

## Files to modify

| File | Change |
|------|--------|
| `executing-plans/SKILL.md` | Rewrite Step 4 (lines 180-193) with the three-phase sequence above |

## References

- Hortora/soredium#325 — reproducer and root cause analysis
- `executing-plans/SKILL.md:180-193` — current Step 4
- `executing-plans/SKILL.md:96-102` — Step 2 batch completion (already correct)
- `work/SKILL.md` Step 4 D4 — complementary mid-session done-detection
