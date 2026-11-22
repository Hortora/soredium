# Decisions — Context Budget Recommendations (#586)

## D1: Recommendation architecture

**Choice:** Pipeline supplies data, LLM decides
**Alternatives:**
- Pipeline computes a recommendation — more testable but adds a script for a judgment call
**Rationale:** Matches the current architecture (pipeline is mechanical, LLM handles judgment). The LLM already makes the wrap-vs-continue decision; it just needs better data.
**Trade-offs:** Not unit-testable as a script; recommendation quality depends on LLM reasoning
**Sources:** work/SKILL.md wrap-vs-continue section, project/work.py OFFER= logic
**Exploration:** quick
**Status:** captured

## D2: Where scale/complexity lives

**Choice:** On the queue item, populated at creation, synced on revision
**Alternatives:**
- GitHub issue labels only (via enrichment cache) — requires cache freshness, external lookup at decision time
- Both queue + cache fallback — more complex, two sources of truth
**Rationale:** Self-contained data at the point of use. No external lookup needed when the pipeline runs. plan_manager.py append already takes issue metadata.
**Trade-offs:** Queue items grow slightly; must keep in sync when LLM revises labels
**Sources:** work-slot/plan_manager.py, scripts/enrichment.py, project/queue_io.py
**Exploration:** quick
**Status:** captured

## D3: Data delivery format

**Choice:** KEY=VALUE lines alongside OFFER=wrap_or_continue
**Alternatives:**
- Structured block or handler file — breaks the established pattern
**Rationale:** Every other pipeline output uses KEY=VALUE. Consistent, easy to parse, easy to extend.
**Trade-offs:** Slightly verbose output
**Sources:** project/work.py sequence_report(), apply_route()
**Exploration:** quick
**Status:** captured

## D4: Mid-task monitoring placement

**Choice:** Work skill text (work/SKILL.md), LLM judges threshold relative to remaining scope
**Alternatives:**
- CLAUDE.md as a project-wide rule — too general for work-lifecycle-specific behavior
- Hard threshold (e.g. 40%) — too rigid, doesn't account for task scope
**Rationale:** Work-specific behavior belongs in the work skill. The LLM can judge remaining scope better than a fixed number.
**Trade-offs:** No mechanical enforcement; depends on LLM attention
**Sources:** work/SKILL.md, issue #586 design notes
**Exploration:** quick
**Status:** captured

## D5: Three-way recommendation

**Choice:** Continue / end-then-continue / wrap-or-end-and-stop
**Alternatives:**
- Binary continue/wrap — misses the "land what's done, keep working" case
**Rationale:** "End then continue" handles the common case of 2-3 finished items waiting while there's still room to work. Avoids both premature session end and unbounded accumulation.
**Trade-offs:** Slightly more complex decision table for the LLM
**Sources:** issue #586 requirement 2
**Exploration:** quick
**Status:** captured
