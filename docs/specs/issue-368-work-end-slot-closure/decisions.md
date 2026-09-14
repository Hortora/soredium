# Decisions — issue-368-work-end-slot-closure

## D1: Mechanical step failure handling

**Choice:** Auto-skip mechanical steps after MAX retries (implement spec D10)
**Alternatives:**
- User-confirmed skip — fix dead end by setting `last_yielded`, require LLM to pass `skip_step=`. Adds friction, relies on LLM instruction-following (the failure class the orchestrator was built to eliminate).
- Auto-skip + notification — auto-skip but yield a non-blocking notification on the next judgment step. Middle ground but adds complexity without clear value since `verify_slot_close.py` already catches gaps.
**Rationale:** The original close orchestrator spec (issue-271, section D10) explicitly designed this: mechanical steps auto-skip after 3 failures, `verify_slot_close.py` catches gaps downstream. The implementation deviated by treating mechanical and judgment failures identically, creating the slot 181 dead end. The user has no useful action to take when a mechanical step fails structurally — retrying a deterministic failure is wasted effort.
**Trade-offs:** Auto-skip means the LLM has no visibility into the failure until verify_recover at the end. If verify_slot_close is also broken (see D2), the failure is silent. Mitigated by fixing verify scoping (D2) in the same change.
**Sources:** issue-271 spec section D10, slot 181 `.close-progress` (4 promote retries, dead end), `orchestrator_engine.py:234-244`
**Exploration:** deep-analysis
**Status:** captured

## D2: Verify scoping to covered repos

**Choice:** Parse `Covers:` line from `.slot` file for repo names, scope all verification to those repos
**Alternatives:**
- Pass `covers_repos=` as CLI argument — works but requires all callers to parse and pass the data. `.slot` is already available via `slot_dir=`, better to parse once inside `verify_slot_close.py`.
- Only check repos with changes on branch — too complex, requires git diffing across all repos. `Covers:` is the authoritative scope declaration.
**Rationale:** The `.slot` file's `Covers:` line already contains repo:issue pairs that define the work scope. Repos not in `Covers:` were in the slot for potential use but never had work. Checking them produces false failures that obscure real problems.
**Trade-offs:** If a repo had work but wasn't in `Covers:`, verification would miss it. Mitigated by the fact that `Covers:` is written at slot creation from the epic's issue list — it's authoritative.
**Sources:** slot 181 `.slot` file (`Covers: platform:276,engine:1049,...` vs 25 total repos), `verify_slot_close.py:381-394` (`_resolve_original_repos`), `verify_slot_close.py:286-298` (`check_landed_completeness`)
**Exploration:** quick
**Status:** captured
