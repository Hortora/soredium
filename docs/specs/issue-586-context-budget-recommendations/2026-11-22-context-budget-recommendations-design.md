# Context Budget Recommendations

**Issue:** Hortora/soredium#586
**Branch:** issue-586-context-budget-recommendations
**Date:** 2026-11-22

## Problem

The wrap-vs-continue decision after finishing an item is LLM-driven but
data-poor: the pipeline prints `OFFER=wrap_or_continue` with no information
about the next item's size, complexity, or the session's context state.
The LLM guesses. Mid-task, there is no prompt to suggest wrapping before
context is exhausted.

## Design

### 1. Queue item metadata

Queue items gain optional scale and complexity fields, written inline:

```
- [ ] o/r#42 — Title (S/Med)        ← active
- [ ] o/r#43 — Other task (M/High)
```

Format: `(<scale>/<complexity>)` after the title, before any marker.
Both are optional; an item without them renders as today.

**Population:** `plan_manager.py append` reads scale and complexity from
GitHub issue labels when available (labels `scale:S`, `complexity: Med`).
If labels are absent, the fields are omitted.

**Sync:** A new `plan_manager.py set-scale` command updates an item's
scale and complexity by ref. The work skill text instructs the LLM to
call this whenever it changes a scale or complexity label on the GitHub
issue.

**Parser changes:** `queue_io.py` gains parsing for the `(S/Med)` suffix.
`QueueItem` gets `scale: str = ""` and `complexity: str = ""` fields.
`write_queue` renders them when present.

### 2. Pipeline data delivery

When the pipeline prints `OFFER=wrap_or_continue` (after `done`, or when
done items are waiting), it also prints:

```
NEXT_ITEM=hortora/soredium#589
NEXT_TITLE=Read-only survey command
NEXT_SCALE=S
NEXT_COMPLEXITY=Med
DONE_WAITING=2
```

Source: the next open item in the queue after the one just finished.
`NEXT_SCALE` and `NEXT_COMPLEXITY` come from the queue item's metadata.
If not populated, they read `unknown`.

**Where produced:** `work.py:apply_route()`, in the same block that
prints `OFFER=wrap_or_continue`. The queue is already read at that
point; the next open item is the one after the active/done item.

### 3. THEN= extension

After wrap/end completes, `sequence_report()` already prints `THEN=`.
It gains the same next-item data:

```
THEN=python3 .../work.py continue   (scaffold the next item; do not begin it)
NEXT_ITEM=hortora/soredium#589
NEXT_TITLE=Read-only survey command
NEXT_SCALE=S
NEXT_COMPLEXITY=Med
DONE_WAITING=0
```

This lets the LLM make the continue-or-stop decision without re-querying.

### 4. Work skill text — between items

The existing `## Wrap-vs-continue decision` section in `work/SKILL.md`
is updated. The recommendation table becomes:

| Situation | Recommend |
|-----------|-----------|
| Enough room, no done items waiting | **Continue** |
| Enough room, done items piling up (DONE_WAITING >= 2) | **End then continue** |
| Not enough room for next item, done items waiting | **End and stop** |
| Not enough room for next item, nothing done waiting | **Wrap and stop** |

The LLM combines NEXT_SCALE/NEXT_COMPLEXITY with its context estimate
(counting issues worked, not trusting `<total_tokens>`) to judge "enough
room." The existing guidance about topic relevance and compressed context
stays.

### 5. Work skill text — mid-task monitoring

A new section in `work/SKILL.md`:

```markdown
## Mid-task context monitoring

While working on an item, watch for signs that the context is running
long relative to what remains on the task. If the item has consumed a
large share of the context window and there is still substantial work
ahead, suggest `work wrap` before context is exhausted — not after.

Signals: you can no longer recall details from the start of the session
without re-reading; the task is growing beyond its original scale
estimate; you are on your third or fourth sub-problem within the same
item.

This is a judgment call, not a hard threshold. A short item that is
almost done should finish. A large item with hours of work ahead should
wrap early enough for the handoff to capture context while it is fresh.
```

### 6. worktrace logging

After the user decides, the work skill text instructs the LLM to record:

```python
worktrace.record("context-budget",
    repo=workspace, branch=branch,
    recommendation="continue",   # or "end-then-continue" or "wrap"
    next_issue="hortora/soredium#589",
    next_scale="S",
    chosen="continue")           # what the user actually picked
```

This is a single worktrace call in the LLM's response, not a pipeline
step. The work skill text includes the template.

## Files changed

| File | Change |
|------|--------|
| `project/queue_io.py` | Parse and render `(S/Med)` on queue items; add `scale`/`complexity` to `QueueItem` |
| `work-slot/plan_manager.py` | `append` reads labels for scale/complexity; new `set-scale` command |
| `project/work.py` | `apply_route()` prints NEXT_ITEM/SCALE/COMPLEXITY; `sequence_report()` extends THEN= |
| `project/work_route.py` | `Route` gains `next_item`, `next_title`, `next_scale`, `next_complexity` |
| `work/SKILL.md` | Updated wrap-vs-continue section; new mid-task monitoring section |
| `tests/test_queue_io.py` | Parse/render round-trip for scale/complexity |
| `tests/test_work_wrap_end.py` | NEXT_ITEM lines present in OFFER output |

## Out of scope

- Automatic context window measurement (no reliable API for this)
- Hard thresholds or circuit breakers
- Changes to enrichment.py or the GitHub issue cache
- Changes to CLAUDE.md (this is work-skill-specific behavior)

## References

- Hortora/soredium#586 — issue
- `work/SKILL.md` — wrap-vs-continue decision section
- `project/work.py:apply_route()` — OFFER= production (line ~402)
- `project/work.py:sequence_report()` — THEN= production (line ~1100)
- `project/work_route.py:route()` — routing logic
- `project/queue_io.py` — queue item parsing/rendering
- `work-slot/plan_manager.py` — queue manipulation
- `project/worktrace.py` — event recording
