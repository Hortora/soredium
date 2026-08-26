# Decisions — #291 Duplicate Slot Guard

## D1: Rollback strategy for partial slot creation failures

**Choice:** Internal rollback — refactor `create_slot()` error paths from `sys.exit(1)` to raised exceptions, wrap the body in try/except, clean up directory and transition DB to `state='failed'` before re-raising. Use `fail_slot()` (state transition) instead of deletion — the `events` table references `slots.id` with no `ON DELETE CASCADE`, so deletion would hit FK constraints. The `failed` state preserves the audit trail and is naturally handled by reconcile.
**Alternatives:**
- External cleanup command — adds a `cleanup-failed-slot` subcommand callable from SKILL.md or reconciliation; more complex, problem should be prevented at source
**Rationale:** The failure should be cleaned up where it happens. `sys.exit(1)` in a library function is an anti-pattern — errors should propagate and let the caller decide. `reconcile_slots.py` already handles orphaned state for edge cases (SIGKILL, power loss) where internal cleanup can't run.
**Trade-offs:** Refactoring `sys.exit` to exceptions is a larger change than "wrap in try/except" but is the correct design. The caller (`main()`) catches and exits.
**Sources:** `work-slot/slot_manager.py:599-747` (create_slot), `scripts/reconcile_slots.py`
**Review refinements:** R1-02 (sys.exit vs exceptions), R1-03 (post-confirmation scope)
**Exploration:** quick
**Status:** revised

## D2: Pending slot number reuse on retry

**Choice:** Auto-reuse — if the most recent DB entry for this family_root is `state='pending'`, reuse that number instead of allocating a new one. Before reusing, verify the pending slot's directory is empty or absent; if it has partial clones from the failed attempt, remove the directory first.
**Alternatives:**
- Warn and ask — push the decision to the SKILL.md layer with a user prompt; adds friction for a case where the user has already decided to retry
- Always allocate new — wastes numbers, leaves orphan pending rows accumulating in the DB
**Rationale:** The pending row is definitionally abandoned: allocate succeeded, confirm never ran, so no work exists on that number. Retrying is the user's explicit intent. Cleaning the directory before reuse prevents stale .m2/ or half-cloned repos from the old attempt contaminating the new slot.
**Trade-offs:** The pending row has no branch column, so reuse can't verify it was for the same operation. Acceptable: the user just ran the command and knows what they're retrying. If they abandoned the first attempt for a different branch, the directory cleanup prevents contamination.
**Assumption:** Concurrent slot creation is not a supported use case. Two sessions running `create-slot` simultaneously for the same family_root is undefined behavior. This is a single-user CLI tool.
**Sources:** `worklog.py:220-235` (reserve_slot_number), `slot_manager.py:331-343` (allocate_slot_number)
**Review refinements:** R1-05 (branch identity), R1-06 (concurrency), R1-07 (dependency framing)
**Exploration:** quick
**Depends on:** D1 (when D1's rollback cannot execute — SIGKILL, power loss — pending orphans remain for D2 to clean up on retry)
**Status:** revised

## D3: Duplicate branch guard — detection mechanism

**Choice:** Disk scan using `parse_slot_md` — iterate active slot directories, call existing `parse_slot_md()` to extract branch, refuse creation if a match exists. Runs BEFORE `allocate_slot_number` to avoid wasting a slot number on a duplicate. Error: "Slot N already has branch `<name>`. Use that slot or archive it first."
**Alternatives:**
- Use `list_slots()` directly — battle-tested but does expensive extras (workspace validation, drift checks) unnecessary for a guard check
- DB join via `work_items` table — branch isn't recorded until `confirm_slot_create`, so misses retry-after-failure
- Add `branch` column to `slots` table — schema migration for a check that disk scan handles natively
**Rationale:** `.slot` is the source of truth for what branch a slot owns. `parse_slot_md` is the existing parser — no custom header parsing needed. Running before allocation prevents number waste and avoids interaction with D1/D2 rollback paths.
**Trade-offs:** TOCTOU race between guard check and directory creation. Acceptable: concurrent slot creation is not supported (see D2 assumption).
**Sources:** `slot_manager.py:574-596` (write_slot_md), `slot_manager.py:987-1042` (parse_slot_md)
**Review refinements:** R1-09 (use parse_slot_md not custom scan), R1-10 (guard before allocation)
**Exploration:** quick
**Status:** revised

## D4: Ghost slot directories — quarantine via enhanced reconcile

**Choice:** Enhance existing `reconcile_slots.py` quarantine flow with: (1) meaningful-content checking in strategy phase (repos with commits ahead of main, worklog DB records), (2) `.claude/projects` conversation relocation in execute phase, (3) derive quarantine status from `quarantine/` directory location — no new DB state column. Additionally, add a defensive one-liner to `list_slots` (`if not (d / ".slot").exists(): continue`) so existing ghosts stop showing as "active" immediately, before the next reconcile run.
**Alternatives:**
- Silent skip in `list_slots` only — hides the problem, debris accumulates, no audit trail
- Delete immediately — too aggressive, could destroy work if the ghost has meaningful contents
- Add `state='quarantined'` to DB — diverges from unified-work-state direction of deriving state from disk reality
**Rationale:** `reconcile_slots.py` already detects ghosts and proposes quarantine (lines 154-161, 211-216, 252-261). This decision enhances the existing flow rather than building parallel infrastructure. Deriving quarantine status from directory location aligns with the unified-work-state principle: "stop caching and start deriving." The `list_slots` one-liner is belt-and-suspenders for the gap between discovery and reconcile execution.
**Trade-offs:** Adds `quarantine/` directory concept alongside `attic/`. Quarantine is for debris of unknown provenance; attic is for completed work.
**Sources:** `slot_manager.py:1628-1710` (list_slots), `scripts/reconcile_slots.py` (lines 143-321), issue #291 (slots 54/67), `docs/specs/2026-08-06-unified-work-state-design.md`
**Review refinements:** R1-12 (existing quarantine capability), R1-13 (derive from disk not DB), R1-14 (defensive list_slots check)
**Exploration:** quick
**Status:** revised
