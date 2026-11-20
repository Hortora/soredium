# Decisions — Outcome-Based Verification (#450)

## D1: Verification layer unification

**Choice:** Unify into a single verification layer
**Alternatives:**
- Keep two layers, upgrade both — postconditions stay as fast-path (VerifyResult instead of bool), close-checks stay as reporting layer (Verification instead of Finding). Preserves separation but maintains the duplication that caused #436
- Replace postconditions, extend close-checks — eliminate postconditions, preserve Finding pattern for close-time reports. Hybrid approach but close-checks still diverge from the orchestrator's verification needs
**Rationale:** The two-layer split (step_postconditions.py returning bool, close_checks.py returning Finding) is historical accident. Both check overlapping things (content_landed, branch_stamp, etc.) and edge-case fixes need to happen in two places — exactly the problem that caused #436 (empty = success). A single verification/outcomes.py with verify_*() returning Verification gives the orchestrator PASS/FAIL/UNKNOWN for check-execute-verify, and close_verify.py composes the same functions for reporting.
**Trade-offs:** Migration touches both the orchestrator engine (postcondition_fn signature changes) and close_verify.py (swaps Finding composition for Verification composition). Larger blast radius per step, but each step is self-contained.
**Sources:** verification/step_postconditions.py (15 bool functions), verification/close_checks.py (Finding functions), verification/close_verify.py (composed reporter). Issues #436, #375, #435
**Exploration:** quick
**Status:** captured

## D2: UNKNOWN resolution ownership

**Choice:** Engine-level resolution
**Alternatives:**
- Per-check resolution — each verify_*() function embeds its own retry/fallback logic (e.g., verify_content_landed() does wait-and-recheck internally). Engine only sees PASS/FAIL after resolution. Simpler engine contract but scatters retry policies across N functions, making them harder to test and harder to change the retry policy
**Rationale:** Keep verify functions pure — they observe git/event state and report what they see (PASS/FAIL/UNKNOWN with evidence). The orchestrator engine's run_loop() handles UNKNOWN centrally: retry up to MAX_MECHANICAL_RETRIES, then yield to LLM via the existing ACTION=user_input pattern with UNKNOWN condition details. This centralizes retry/escalation policy in one place. The UNKNOWN conditions table from the parent spec (partial landing → retry unfinished repos, ambiguous branch state → reattach/abort, missing evidence → wait-and-recheck with backoff) maps to engine-level retry with condition-specific backoff.
**Trade-offs:** Engine becomes slightly more complex (three-way dispatch instead of binary). But verify functions become simpler and fully testable without mocking retries.
**Sources:** project/orchestrator_engine.py run_loop() (current binary dispatch), shared_steps.py MAX_MECHANICAL_RETRIES=3. Parent spec D5 (UNKNOWN conditions table)
**Exploration:** quick
**Status:** captured
**Depends on:** D1 (unified layer — engine consumes Verification, not bool)

## D3: Verification cardinality per step

**Choice:** Single Verification return per step
**Alternatives:**
- list[Verification] return — each step produces multiple independent verification results. Richer reporting but engine must decide what to do when some are PASS and others UNKNOWN (partial success semantics). Adds complexity without clear benefit since current postconditions are already 1:1 with steps
**Rationale:** One step, one verification. postcondition_fn becomes verify_fn: (ctx) -> Verification. Compound checks (e.g., "content landed AND pushed") compose inside the verify function and return the most serious result (FAIL > UNKNOWN > PASS). Close-verify can still call individual verify_*() functions directly for its multi-check reporting view — the composition happens at different levels for different consumers.
**Trade-offs:** A step that checks multiple things must pick a single result to return. But "first non-PASS wins" is the current behavior (postcondition returns False on first failure) — no semantic change.
**Sources:** shared_steps.py StepDef.postcondition_fn, orchestrator_engine.py run_loop() binary dispatch
**Exploration:** quick
**Status:** captured
**Depends on:** D1 (unified layer), D2 (engine-level resolution — engine needs a single VerifyResult to dispatch on)

## D4: Stamp file migration strategy

**Choice:** Dual-read during migration, remove stamps after
**Alternatives:**
- Hard cutover per stamp — replace each stamp file's write and all reads in a single commit. No fallback. Cleaner but higher risk — if git-state checks have edge cases the stamp covered, failure surfaces in production rather than during migration
- Event log required first — wait until Phase 1 event-sourced lifecycle is fully primary before eliminating stamps. Safest but blocks Phase 3 on full Phase 1 completion, which defeats the independently-shippable phase design
**Rationale:** New verify_*() functions check git state first (primary evidence). If git state returns UNKNOWN (e.g., SHA not found, branch deleted before check), fall back to reading the stamp file as secondary evidence — the stamp contributes to UNKNOWN → PASS when git state is insufficient. Two-phase removal: (1) migrate all consumers to verify_*() with dual-read, stop writing stamps; (2) once tests pass without stamps being written, remove the reads. This gives a safety net during migration while the git-state checks prove themselves against real close sequences.
**Trade-offs:** Stamp files persist longer during migration. Dual-read adds a fallback code path that itself needs eventual removal. But the alternative (hard cutover) risks discovering edge cases in production.
**Sources:** work-end/land_branch.py (writes .landed), work-end/artifact_promote.py (writes .artifacts-promoted), verification/step_postconditions.py (reads stamps), verification/close_checks.py (reads stamps). Phase 1 partial landing: get_lifecycle_state() exists but events not yet primary for all state
**Exploration:** quick
**Status:** captured
**Depends on:** D1 (unified layer — verify functions are the consumer being migrated)

## D5: close_verify.py output compatibility

**Choice:** Verification → Finding adapter
**Alternatives:**
- Replace Finding entirely — close_verify.py works directly with Verification objects, new formatting logic, new output format. Cleaner long-term but breaks downstream parsing of VERIFIED=, FAILURE_N=, BLOCKING_FAIL= output that the orchestrator SKILL.md and close_resume.py already depend on
**Rationale:** Add a to_finding() method (or standalone function) that maps Verification to list[Finding]: PASS → [], FAIL → [Finding("ERROR", check, evidence summary)], UNKNOWN → [Finding("WARN", check, evidence summary)]. close_verify.py calls verify_*() functions, converts via to_finding(), and existing reporting logic (blocking categories, emoji formatting, KEY=VALUE output) stays unchanged. Finding becomes a presentation concern; Verification is the domain model.
**Trade-offs:** Adapter is one more mapping layer. But the output format is a stable contract consumed by multiple callers — changing it requires migrating all parsers simultaneously, which is out of scope for this phase.
**Sources:** verification/close_verify.py (output format), work-end/close_resume.py (parses VERIFIED=, FAILURE_N=), work-end/work_end_orchestrator.py SKILL.md (parses BLOCKING_FAIL=)
**Exploration:** quick
**Status:** captured
**Depends on:** D1 (unified layer — adapter bridges Verification to Finding)
