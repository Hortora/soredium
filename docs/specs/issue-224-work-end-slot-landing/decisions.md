## D1: Slot landing mechanism

**Choice:** Write `.phase-a-complete` marker after squash, delegate to `merge-slot` for slot landing
**Alternatives:**
- Add slot-aware landing to `cmd_land()` in `work_end_execute.py` — duplicates merge-slot's push/verify/stamp logic
- Extract merge-slot's two-hop push logic into a reusable function callable by both `cmd_land()` and `merge_slot()` — right long-term direction (see restructure spec) but broader scope than issue #224
**Rationale:** SKILL.md already describes this flow. merge-slot has 287 lines of tested landing code (rebase retry, SHA verification, .landed audit). Only missing piece is a one-line marker file. Redundant rebase is a no-op. Note: merge_slot() has evolved beyond the original issue-85 spec — it now processes workspace repos via `get_all_slot_repos()` (fixed to prevent workspace artifact loss, per the two-hop push blog post).
**Marker schema:** The `.phase-a-complete` file contains `branch=<name>` and `timestamp=<ISO-8601>`, one per line. Both fields are consumed by `merge_slot()` (reads `branch=`) and `scan_ready()` (reads `timestamp=`).
**Trade-offs:** merge-slot rebases again after work-end's Phase A rebase — harmless no-op. Close sequence splits across work-end and slot_manager.py modules, coupled through the marker file (see D4).
**Exploration:** quick
**Status:** captured

## D2: Artifact promotion push in slot mode

**Choice:** Let promotion push through `updateInstead` to the original repo. Blog push operates independently to its own repo. merge-slot handles the GitHub push for workspace/project repos as part of landing.
**Alternatives:**
- Skip push entirely in slot mode — defers ALL push to merge-slot's two-hop landing, creating a durability gap where promoted artifacts exist only in the slot clone until landing
- Push to `local` remote during promotion — functionally identical to updateInstead but uses a different remote name
**Rationale:** `configure_update_instead()` is already called during `create_slot()` for both project repos (slot_manager.py:470) and workspace sources (slot_manager.py:500). This makes the original accept pushes to its checked-out main branch. Promotion push via `artifact_promote.py` succeeds immediately through this path, making artifacts durable on the original repo without waiting for merge-slot. merge-slot's subsequent push is a no-op for repos whose main already has the content. Blog publishing pushes to a separate repository (e.g., mdproctor.github.io) with its own GitHub origin — it is completely outside the slot's two-hop path and operates independently in all modes.
**Trade-offs:** Promotion push is an additional local-to-local push per workspace, but it is fast and eliminates the durability gap between promotion and landing. merge-slot's push for these repos becomes a verified no-op rather than the sole delivery mechanism.
**Exploration:** quick
**Status:** revised (R1-07, R1-08, R1-09 — changed from "skip push entirely" to "push through updateInstead")

## D3: Verification script approach

**Choice:** Extend existing `verify_slot_close.py` with slot-specific landing checks (original sync, .landed, archive status)
**Alternatives:**
- Replace with new comprehensive `verify_work_end.py` (20+ checks) — ambitious, includes unrelated checks (blog, HANDOFF, plans)
- Two focused scripts (one per landing topology) — `verify_branch_close.py` + `verify_slot_landing.py` — creates maintenance burden for shared checks
**Rationale:** Existing script checks are outcome-based and mode-agnostic (branch merged, stamped, SHA valid, main pushed, workspace stamped). Slot-specific extensions are incremental: iterate repos from `.slot` file, check `.landed` marker. Conditional logic is minimal. Broader verification is a follow-up.
**Deferred checks:** Blog publication, HANDOFF.md presence, plan archival, and build verification are not covered by the current script. These are real failure modes identified by the slot audit (27/73 slots had problems). A tracking issue should be filed for the comprehensive verification script from the restructure spec.
**Trade-offs:** Defers the comprehensive verification script to a future issue
**Exploration:** quick
**Status:** captured

## D4: Cross-module close sequence (implicit — surfaced by review)

**Choice:** Accept the cross-module split where work-end owns Phases A+B (rebase + squash + promotion) and `slot_manager.py merge_slot()` owns Phase C (landing). The modules are coupled through the `.phase-a-complete` marker file.
**Alternatives:**
- Single `cmd_land()` with pluggable push strategies (direct push for branch mode, two-hop push for slot mode) — keeps the entire close sequence in one module. This is the direction of the work-end restructure spec (`2026-08-05-work-end-restructure-and-slot-audit-design.md`), which plans `work_end_execute.py` with a slot-mode landing variant that bypasses `merge_slot()`.
- Make `merge_slot()` the sole orchestrator for the entire slot close — would require merge_slot to handle promotion, code review, and squash analysis, coupling slot_manager.py to the work-end lifecycle
**Rationale:** For issue #224 (a bug fix), the split is acceptable: merge_slot() is 287 lines of tested code with existing test coverage (`test_slot_manager.py`). The lifecycle state machine handles crash recovery (re-entry at `closing:promoted` re-invokes merge-slot). The restructure spec already plans the unified approach as a separate deliverable. The async `work-slot merge` use case (landing from the main repo after the slot session is gone) still requires merge_slot() regardless — the unified approach retains merge_slot() for async but removes it from the synchronous work-end path.
**Consequences:** Error recovery for merge-slot failure requires re-invocation from the SKILL.md (lifecycle state resumes at `closing:promoted`). The marker file is a leaky abstraction — merge_slot reads `branch=` but does not independently verify squash state (relies on work-end having completed Phase B before writing the marker). Integration testing across the boundary is an explicit requirement.
**Exploration:** surfaced by review
**Status:** captured

SETTLED: Async `work-slot merge` use case remains architecturally desired — merge_slot() must continue to work for landing from the main repo after the slot session ends (from R1-03, confirming A1)
