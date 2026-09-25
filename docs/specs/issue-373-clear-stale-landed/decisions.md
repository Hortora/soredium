## D1: How work-end handles slots with remaining queue items

**Choice:** Queue-aware orchestrator with auto-detect — work-end checks `.plan`
for remaining items at the terminal phase. If items remain, it cycles (syncs
code to canonical, closes current issue, advances queue) instead of terminating
(no `.landed`, no stamp, no archive). Terminal closure is hard-gated on an
empty `.plan` — the user must explicitly empty it to force-close.

**Alternatives:**
- Extend `work next` with sync — clear semantic separation but duplicates
  orchestrator logic and makes `work next` much heavier
- Explicit `--cycle` flag — fragile, LLM-dependent, orchestrator already
  has the queue information

**Rationale:** The orchestrator already has queue awareness via `elevate_plan`
(step 40) — it just acts on it too late (after `.landed` and archive). Moving
the queue check earlier is a targeted change. Hard-gating on `.plan` emptiness
prevents accidental closure — "I can only close this if you agree we empty
the .plan" — with no ambiguous force flags.

**Trade-offs:** No way to close a slot with remaining items without explicitly
emptying the `.plan` first. This is intentional — the `.plan` is the source
of truth for slot liveness.

**Sources:** work_end_orchestrator.py (step pipeline), slot_state.py (state
machine), plan_manager.py (advance/append), issue #373 description

**Exploration:** quick
**Status:** captured

## D2: Review scope in cycle mode

**Choice:** Full review — run all review/audit/sweep steps before syncing.
Code lands on canonical with the same quality gate as a terminal close.

**Alternatives:**
- Sync only (skip review) — fastest but bypasses quality gates
- Configurable (flag to skip) — adds complexity for marginal benefit

**Rationale:** The review pipeline catches issues before code lands on
canonical repos. Skipping it in cycle mode would create a quality gap
between "code that lands mid-slot" and "code that lands at slot close."
The review is the point of work-end — removing it makes cycle mode just
a push script.

**Trade-offs:** Cycle takes longer (~12 review steps). Acceptable because
the user chose work-end for its quality gates, not just for syncing.

**Sources:** work_end_orchestrator.py steps 1-17 (review phase)
**Exploration:** quick
**Depends on:** D1
**Status:** captured

## D3: Post-cycle lifecycle state

**Choice:** Transition `closing:pushed → active` via a new `issue_cycle`
lifecycle event. The slot is immediately ready for new work after the cycle.

**Alternatives:**
- `transitioning` — forces context refresh, more conservative but adds
  an unnecessary intermediate step
- `scaffolded` — forces full re-setup, overkill for a cycle

**Rationale:** After a cycle, the branch, workspace, and IntelliJ context
are all still valid. The only thing that changed is which issue is active.
Going through `transitioning` or `scaffolded` would re-run setup steps
that add no value when the slot infrastructure hasn't changed.

**Trade-offs:** No forced context refresh — the session that just ran
work-end already has full context, so this is a feature, not a gap.

**Sources:** project/lifecycle.py (state machine), slot_state.py (slot states)
**Exploration:** quick
**Depends on:** D1
**Status:** captured

## D4: Retroactive .landed cleanup in append_to_queue

**Choice:** `append_to_queue()` checks for `.landed` in the slot directory
and removes it when adding new items. Belt-and-suspenders — the primary
fix (D1) prevents `.landed` from being written, this catches the edge case
where it already exists.

**Alternatives:**
- Primary fix only — treat `.landed` + non-empty queue as corruption to
  be flagged, not silently fixed

**Rationale:** The retroactive case is rare but real (slot 198 in the issue).
Silently cleaning up a stale marker is safer than leaving it for archive
tooling to trip over. The marker is the lie — the queue is the truth.

**Trade-offs:** Silent cleanup means the user doesn't see a warning about
the stale state. Acceptable because the `.landed` was wrong — removing
it restores correctness, not masks a problem.

**Sources:** plan_manager.py (append_to_queue), slot 198 incident (issue #373)
**Exploration:** quick
**Depends on:** D1
**Status:** captured
