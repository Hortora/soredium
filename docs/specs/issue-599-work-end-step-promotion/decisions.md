# Decisions — #599 work end step promotion

## D1: Step type for promote and squash_review

**Choice:** Mechanical steps
**Alternatives:**
- Judgment steps — more flexible but adds LLM turns where deterministic execution suffices
- Hybrid (promote mechanical, squash judgment) — squash does require git-squash invocation but the step itself only checks status; the LLM handles the error output
**Rationale:** close.py already has `unpromoted_artifacts()` and `squash_marker.review_status()` as pure functions. Extracting them into scope.py commands keeps the pipeline deterministic. The LLM handles failure output, not the step execution.
**Trade-offs:** The LLM must interpret ERROR output and run the fix commands itself; the step can't invoke git-squash directly.
**Sources:** `work-end/close.py:1118-1136`, `work-end/scope.py:154-180`
**Exploration:** quick
**Status:** captured

## D2: Preflight location

**Choice:** Extend sequence_preflight()
**Alternatives:**
- New close_preflight step in _CLOSE_STEPS — cleaner separation but blockers aren't visible until after judgment steps (review, diary, item_finished)
**Rationale:** sequence_preflight() already runs before any step of wrap/end. Adding blocker detection there means the session sees everything that will block landing before it even starts the review step, saving all the judgment-step LLM turns.
**Trade-offs:** sequence_preflight() grows larger; it now needs to resolve targets and check promotion/squash state, which requires reading the queue and discovering repos.
**Sources:** `project/work.py:1075-1143` (sequence_preflight), `work-end/close.py:1064-1144` (_close checks)
**Exploration:** quick
**Status:** captured

## D3: item_finished re-answer guard

**Choice:** Skip with diagnostic (ITEM_FINISHED_REUSED=yes)
**Alternatives:**
- Skip silently — the progress file has the answer, but no visibility into what happened
- Refuse and stop — forces explicit clearing, too disruptive for normal retry flow
**Rationale:** On retry after a mechanical failure (e.g. land fails), item_finished has already been answered. The saved answer should be reused without re-asking. The diagnostic line lets the LLM know it was reused, which matters for context.
**Trade-offs:** If the answer was wrong (marked finished when it wasn't), the user must manually clear the progress file to re-answer.
**Sources:** `project/work.py:982-983,1362-1376` (item_finished handling), `project/progress.py:53-118` (Progress API)
**Exploration:** quick
**Status:** captured

## D4: Scope — all 5 deliverables in one branch

**Choice:** All 5 in this branch
**Alternatives:**
- Split audit (4) and exit_1 fix (5) to separate issues — keeps branch focused but adds overhead
**Rationale:** The audit informs the guard design (D3) and the exit_1 fix is small. Keeping them together means the design is informed by the investigation.
**Trade-offs:** Branch is M-scale with both pipeline restructure and investigation work.
**Sources:** Hortora/soredium#599 body
**Exploration:** quick
**Status:** captured
