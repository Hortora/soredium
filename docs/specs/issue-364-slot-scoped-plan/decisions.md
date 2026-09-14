# Decisions — #364 Slot-Scoped .plan

## D1: .plan persistence mechanism for slots

**Choice:** Elevate .plan to slot root at work-end time
**Alternatives:**
- Skip checkout_main when remaining items — wrong workspace for next repo, stamp contradiction
- Slot-root .plan from creation (full migration) — more invasive, changes scaffold.py + all consumers
- Copy to slot root with dual-source — two sources of truth, sync/stale risk
- Workspace-to-main merge for .plan — breaks stamp-only workspace invariant
- Symlink from workspace to slot root — git tracks symlinks as content, dangling references
**Rationale:** Minimal change (2 code files + 1 skill update). Non-slot workflows unchanged. Consistent with existing slot-root file pattern (.slot, .landed, .occupant-pid). Single source of truth after elevation — workspace branch copy is closed, slot root is the only live copy.
**Trade-offs:** Slot root .plan is not version-controlled (filesystem only). Acceptable because .slot and .landed follow the same pattern without issues.
**Sources:** branch_cleanup.py:76-129 (cleanup_scaffold), ctx.py (PLAN_PATH resolution), work_end_execute.py:347 (workspace stamp-only comment)
**Exploration:** deep-analysis
**Status:** captured

## D2: Branch field handling for elevated .plan

**Choice:** Set branch field to `pending` after elevation
**Alternatives:**
- Leave stale branch name — triggers BRANCH_MISMATCH in ctx.py
- Clear branch field entirely — plan_io might fail on missing field
- Set to `main` — confusing semantics (active work on main = drained state)
**Rationale:** `pending` is a clear signal that the .plan is between branches. ctx.py can suppress mismatch detection for this sentinel value. plan_io won't fail because the field exists.
**Trade-offs:** New sentinel value that all branch-field consumers must handle. Limited blast radius — only ctx.py's mismatch check reads this field for routing.
**Sources:** ctx.py (BRANCH_MISMATCH logic), branch_cleanup.py:62-73 (_reset_plan_state)
**Exploration:** quick
**Depends on:** D1 (elevation mechanism)
**Status:** captured
