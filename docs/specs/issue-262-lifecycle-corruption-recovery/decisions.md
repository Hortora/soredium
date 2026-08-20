## D1: Detection timing — proactive scan at session start

**Choice:** Proactive scan integrated into the routing path (ctx.py / work_health.py), not reactive guards inside transition()
**Alternatives:**
- Reactive (inside transition()) — couples transition() to git/GitHub; can't catch environmental corruption until user tries an action
- Both proactive + reactive — redundant; read_state() already backstops file-level corruption (scenarios 1-2)
**Rationale:** 6 of 8 scenarios involve environmental state (branch existence, GitHub issue status, git position) that only makes sense to check proactively. Corruption is a routing concern — when state is incoherent, the user should enter a triage flow, not the normal work menu.
**Trade-offs:** Adds latency to session start (git + GitHub checks). Mitigated by keeping checks local-only where possible.
**Sources:** project/lifecycle.py (read_state, CorruptedState), project/work_health.py (existing health checks), issue #262 scenario list
**Exploration:** quick
**Status:** captured

## D2: Recovery model — report-only, no auto-fix

**Choice:** diagnose() reports structured findings with recommended actions; never mutates state. User confirms before any fix is applied.
**Alternatives:**
- Auto-fix simple cases silently — risks cascading corruption when assumptions are already broken
- Hybrid (auto-fix trivial, ask for complex) — creates an implicit trust boundary that's hard to audit
**Rationale:** Corruption means assumptions have broken down. Auto-fixing based on those same assumptions compounds the problem. Report everything, let the human confirm. Exception: scenario 1 (missing state field) is already handled by read_state()'s legacy migration default, which is well-tested and predates this work.
**Trade-offs:** User must confirm even obvious fixes. Acceptable — corruption is rare, and the confirmation cost is low compared to the cost of a wrong auto-fix.
**Sources:** issue #262 ("structured directives for resolution"), docs/protocols/evidence-before-claims.md
**Exploration:** quick
**Status:** captured

## D3: Module architecture — new corruption.py in project/

**Choice:** New `project/corruption.py` module with `diagnose(plan_path, project, workspace, base_branch)` function, called by ctx.py
**Alternatives:**
- Extend work_health.py with triage scope — mixes advisory (warn/ok) with directive (action required) semantics; work_health.py already 540 lines with partial overlap on some scenarios
- Extend lifecycle.py with diagnose() — couples the pure state machine to subprocess/GitHub calls; violates the spec's design boundary
**Rationale:** Clean separation: lifecycle.py owns transitions, corruption.py owns state-vs-environment coherence, work_health.py stays advisory. Each scenario is a pure function (state, environment) → Optional[Finding]. corruption.py imports from lifecycle.py (read_state, VALID_STATES) without lifecycle.py knowing about corruption. base_branch threading (#263) integrates naturally as a parameter.
**Trade-offs:** One more module in project/. Acceptable — the alternative is tangling three different concerns in one file.
**Sources:** project/lifecycle.py (480 lines, pure state machine), project/work_health.py (540 lines, advisory checks), project/ctx.py (routing data gatherer)
**Exploration:** quick
**Depends on:** D1 (proactive scan — corruption.py is the scan implementation)
**Status:** captured

## D4: Output format — list of Finding dataclasses, KEY=VALUE serialisation

**Choice:** `diagnose()` returns `list[Finding]` where each Finding has scenario ID, severity, detail, and ordered actions list. ctx.py serialises as indexed KEY=VALUE lines (CORRUPTION_COUNT, CORRUPTION_0, CORRUPTION_0_SEVERITY, etc.). First action in list is the recommended one.
**Alternatives:**
- Single worst-finding-wins — loses information when multiple corruptions coexist (common in mid-ceremony crashes where branch mismatch + stale closing state happen together)
**Rationale:** Multiple findings are the norm in real corruption, not the exception. The indexed KEY=VALUE format matches ctx.py's existing contract. Stable scenario IDs (S1_MISSING_STATE, S3_ACTIVE_ALL_CLOSED, etc.) enable testing and documentation. Actions list with recommendation-first ordering lets the LLM present choices consistently.
**Trade-offs:** More verbose output than single-line. Acceptable — corruption is rare, and when it happens you want maximum information.
**Sources:** project/ctx.py (KEY=VALUE output contract), work/SKILL.md (routing table consumes ctx.py output)
**Exploration:** quick
**Depends on:** D3 (corruption.py returns Finding objects that ctx.py serialises)
**Status:** captured

## D5: work_health.py overlap — corruption.py owns detection, health delegates

**Choice:** corruption.py owns the detection logic for overlapping scenarios. work_health.py's check_meta_consistency, check_stale_scaffold_on_main, and the overlap portion of check_plan_state call into corruption.py detection functions and wrap results in advisory format.
**Alternatives:**
- Keep both independent — two implementations of "is the branch mismatched?" will diverge; health check re-reporting what corruption already found is noise
- Remove overlapping checks from work_health.py — loses advisory coverage at wrap scope and for non-corrupt misalignment situations
**Rationale:** Single detection implementation, dual consumers. Fixing a detection bug fixes both paths. work_health.py retains its advisory role (warn/ok for wrap scope, non-corrupt edge cases) while corruption.py adds directive semantics (action required for triage route).
**Trade-offs:** Coupling between corruption.py and work_health.py. Acceptable — it's one-way (health imports from corruption, not reverse) and the alternative is duplicate logic.
**Sources:** project/work_health.py:69 (check_meta_consistency), project/work_health.py:167 (check_stale_scaffold_on_main), project/work_health.py:277 (check_plan_state)
**Exploration:** quick
**Depends on:** D3 (corruption.py as the detection owner)
**Status:** captured
