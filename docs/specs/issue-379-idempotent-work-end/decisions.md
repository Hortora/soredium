# Decisions — #379 Idempotent Work-End Pipeline

## D1: Implementation scope

**Choice:** All 4 phases — journal-based progress, postcondition checks, honest reporting, convergence testing
**Alternatives:**
- Phase 2+3 first — fixes the bugs but defers journal and tests
- Phase 1+2+3, defer tests — everything except convergence testing
- Phase 1 only — foundational but doesn't fix any bugs by itself
**Rationale:** The four phases are complementary and relatively self-contained. Doing them together ensures the pipeline is crash-safe end-to-end in one branch.
**Trade-offs:** Larger change, longer review. But each phase is independently testable.
**Sources:** Issue #379 implementation approach section
**Exploration:** quick
**Status:** captured

## D2: State model — journal + markers coexist

**Choice:** Journal (.execute-progress) tracks step completion for resume. Disk markers (.landed, .phase-a-complete, .artifacts-promoted) remain independent files but are written only after postcondition verification.
**Alternatives:**
- Journal as sole authority — .execute-progress becomes the single source of truth, all markers derived from it. Eliminates disagreement by construction but requires rewriting all marker consumers (verify_slot_close, archive-slot, reconcile_slots, auditor).
- Postcondition-only — no journal change, just add checks. Least disruptive but no resume improvement.
**Rationale:** Phase 2+3 (postconditions + honest reporting) make markers reliable — they're only written after verification. Once markers are honest, coexistence with the journal is not a problem. The journal-as-authority approach has a large blast radius (all marker consumers must change) for a problem that honest reporting already solves.
**Trade-offs:** State can still theoretically disagree if a postcondition check has a bug. But this is a testing concern, not an architectural one.
**Sources:** work-end/verify_slot_close.py (marker consumer), work-end/work_end_execute.py (marker writer), scripts/reconcile_slots.py (marker consumer)
**Exploration:** deep-analysis
**Status:** captured

## D3: Postcondition code location

**Choice:** New file verification/step_postconditions.py in the existing verification/ library
**Alternatives:**
- Inline in each script — logic scattered across land_flow.py, close_artifacts.py, work_end_execute.py
- New postconditions.py in work-end/ — co-located but separate from shared verification library
**Rationale:** The verification/ library already has repo_checks and slot_checks. Step postconditions are the same category of concern. The orchestrator engine imports from verification/ to call checks in the check-execute-verify pattern.
**Trade-offs:** Adds a cross-directory dependency (orchestrator engine -> verification/). But this is a natural dependency direction — the engine verifies, the verification library provides the checks.
**Sources:** verification/__init__.py, verification/postconditions.py (existing lifecycle gate checks)
**Exploration:** quick
**Status:** captured

## D4: Testing approach

**Choice:** Pytest with mock filesystem — unit tests using tmp_path and mocked git/subprocess calls
**Alternatives:**
- Integration tests with real git repos — higher confidence but slower, more complex setup
- Both unit and integration — most thorough but largest test suite
**Rationale:** Fast, deterministic, fits existing test patterns (tests/ already uses tmp_path extensively). Simulate failures by injecting errors at specific steps, verify the pipeline converges on re-run. The postcondition functions themselves are pure (check state -> return bool) and easy to unit test.
**Trade-offs:** Mocked git behavior may diverge from real git. But the postcondition functions check real filesystem state (file existence, git commands), which tmp_path captures faithfully.
**Sources:** tests/test_lifecycle.py (existing pattern), tests/test_work_end_orchestrator.py (existing orchestrator tests)
**Exploration:** quick
**Status:** captured

## D5: Integration approach — step wrapper in orchestrator engine

**Choice:** Add a `postcondition_fn` field to StepDef. The run_loop engine enforces check-execute-verify mechanically: before executing, call postcondition to check if already done (skip); after executing, call postcondition to verify the side effect (fail if not met).
**Alternatives:**
- Per-script postcondition checks — each script adds its own pre/post checks. More flexible but no mechanical guarantee; a new step could forget checks. This is the current approach and led to the failure modes in the issue.
- Pipeline-as-data with external runner — declarative pipeline definition. Over-engineered; the current STEPS list is already data-like.
**Rationale:** The engine already owns step iteration and progress tracking. Adding postconditions there means one code change enforces the pattern for all ~40 steps. Honest reporting becomes a mechanical consequence — success output moves inside the engine, after the verify call. Each step's script only returns raw results; the engine decides whether to declare success.
**Trade-offs:** All postcondition logic must fit the same interface (workspace, step_name -> bool). Steps with unusual postconditions (e.g., judgment steps) need special handling.
**Sources:** work-end/orchestrator_engine.py (run_loop), work-end/shared_steps.py (StepDef with existing verify_fn)
**Exploration:** deep-analysis
**Status:** captured
