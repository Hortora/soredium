# Decisions — #382 Unified Mechanical Pipeline

## D1: Design approach

**Choice:** Full architecture design first, then implement in phases
**Alternatives:**
- Incremental hardening — fix urgent gaps first, design rest later
**Rationale:** The pieces (state management, pipeline engine, sync, auto-recovery) are interdependent. Designing them together ensures coherence.
**Trade-offs:** More upfront design before first code lands.
**Exploration:** quick
**Status:** captured

## D2: State storage — .plan stays versioned, commit state changes to git

**Choice:** Keep `.plan` on the feature branch in git. Every `commit_transition` call also commits `.plan` to git (not just writes to disk). `.plan` removed from LIFECYCLE_FILES strip list — it stays on the branch permanently, providing full lifecycle history.
**Alternatives:**
- Untracked file — survives branch ops but loses history, durability, auditability
- Split .plan into queue + state files — cleaner separation but more files to manage
- Keep in .plan but don't commit state changes — still vulnerable to working tree operations
**Rationale:** First-principles analysis showed the problem isn't versioning — it's that state changes are written to disk but not committed. Any git operation (checkout, rebase, merge) discards uncommitted working tree changes. Committing state changes makes them durable. Rebase replays commits. Merge preserves them. Pause/resume works because the state travels with the branch. The strip was destroying state by removing .plan before post-land lifecycle transitions could complete.
**Trade-offs:** Post-squash lifecycle commits remain on the branch (not squashed). Acceptable — branch is closed after work-end, commits serve durability not readability. `.plan` reaches main temporarily during merge; cleanup removes it.
**Sources:** lifecycle.py (VALID_STATES, commit_transition), plan_io.py (write_field — no validation), land_flow.py (LIFECYCLE_FILES strip), work_end_orchestrator.py (elevate_plan_inline — bypasses lifecycle)
**Exploration:** deep-analysis
**Depends on:** D1
**Status:** captured

## D3: One gate for state writes

**Choice:** All state mutations go through `lifecycle.py commit_transition()`. Close bypass paths: remove `plan_manager.py set-state` command, add VALID_STATES validation to `write_field` as safety net, replace `elevate_plan_inline` string manipulation with a proper lifecycle transition.
**Alternatives:**
- Keep multiple write paths, add validation to each — more code, same problem with future bypass paths
**Rationale:** `closing:landed` was written by a bypass path. The lifecycle guard hook blocks the LLM from writing .plan directly, but Python scripts (plan_manager set-state, elevate_plan_inline) bypass it. One gate eliminates the category of bug.
**Trade-offs:** Slightly more ceremony for legitimate state changes (must define transitions in the table). But that's the point — undeclared transitions are bugs.
**Sources:** plan_manager.py (set-state command), work_end_orchestrator.py line 517 (elevate_plan_inline)
**Exploration:** quick
**Depends on:** D2
**Status:** captured

## D4: Sync as a first-class operation

**Choice:** `work sync` — runs the close ceremony (review, promote, rebase, push, close issues) but does NOT stamp the branch as closed, does NOT archive the slot. Resets state to `active`. Promotes `.plan-next` if it exists. Same pipeline as `work end`, different exit point.
**Alternatives:**
- Cycle mode only — requires next batch queued in .plan before work-end. Fragile because you must plan the next batch during the current session under time pressure.
**Rationale:** Separates "land completed work" from "close the branch." Users want to land work and then decide what's next, not plan the next batch as a prerequisite for landing.
**Trade-offs:** New lifecycle event and transition path. But shares 90% of the work-end pipeline.
**Sources:** Issue #382 comment (work sync design note), user feedback on .plan-next promotion failure
**Exploration:** deep-analysis
**Status:** captured

## D5: .plan-next / HANDOFF-next pattern

**Choice:** Before sync/end, build `.plan-next` (next queue) and `HANDOFF-next` (continuation context) while session context is fresh. The sync/end ceremony lands the work, then atomically promotes `-next` files to active. If ceremony fails, `-next` files survive.
**Alternatives:**
- Build next-session artifacts during work-end ceremony — risks context loss if ceremony is long or crashes
- LLM remembers to promote — failed in the .plan-next incident
**Rationale:** Separates "prepare the continuation" from "land the completed work." The promotion is a mechanical pipeline step with a postcondition (active files exist), not something the LLM must remember.
**Trade-offs:** Two extra files to manage during the session. But they're created by the pipeline, not by the user.
**Exploration:** quick
**Depends on:** D4
**Status:** captured

## D6: Auto-recovery for deterministic situations

**Choice:** When the system can diagnose a situation deterministically (all issues CLOSED + .plan in closing state = interrupted work-end), it recovers without asking. Human intervention only when genuinely ambiguous.
**Alternatives:**
- Always ask the user — current approach, blocks autonomous operation
**Rationale:** The corruption triage already diagnoses correctly (it identified the .plan-next incident perfectly). The diagnosis is deterministic — if all issues are CLOSED and the .plan is in a closing state, the answer is always "remove_plan." Asking is ceremony that blocks automation.
**Trade-offs:** Risk of auto-recovering when the situation is misdiagnosed. Mitigated by making the diagnosis conservative — only auto-recover when ALL signals agree.
**Exploration:** quick
**Status:** captured

## D7: Pipeline engine scope

**Choice:** Extend the orchestrator_engine pattern to cover the full lifecycle (start, continue, sync, end). Skills become thin wrappers that invoke the pipeline. LLM called only for judgment steps.
**Alternatives:**
- Keep skills as orchestrators, harden scripts — doesn't fix the LLM-routing-decisions problem
- Full rewrite — unnecessary; the orchestrator pattern already works for close
**Rationale:** `work_end_orchestrator.py` proves the pattern works. Python drives, LLM assists at judgment points. Extending this to start/continue/sync gives the same robustness guarantees across the lifecycle.
**Trade-offs:** Large change. Skills lose orchestration logic. But skills keep judgment logic (review, content writing, debugging).
**Sources:** orchestrator_engine.py (run_loop), work_end_orchestrator.py (STEPS list)
**Exploration:** deep-analysis
**Depends on:** D2, D3
**Status:** captured

## D8: Conflict resolution tiers

**Choice:** Three-tier resolution: (1) auto-resolve lifecycle file conflicts, (2) LLM resolves semantic conflicts, (3) human resolves complex conflicts. The pipeline attempts each tier in order before escalating.
**Alternatives:**
- Always yield to human on conflict — blocks autonomous operation
- Always yield to LLM — LLM may make wrong choices on complex conflicts
**Rationale:** Most rebase conflicts are lifecycle files (.plan, JOURNAL.md) or non-overlapping changes. These are mechanically resolvable. The LLM can handle semantic conflicts (import additions, non-overlapping edits in the same file). Only complex structural conflicts need a human.
**Trade-offs:** Auto-resolution could make a wrong choice on a conflict it mis-classifies as lifecycle. Mitigated by conservative classification — only auto-resolve files that are explicitly listed as lifecycle files.
**Exploration:** quick
**Status:** captured
