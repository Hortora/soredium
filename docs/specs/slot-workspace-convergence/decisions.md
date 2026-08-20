# Slot Workspace Convergence — Decisions

## D1: Workspace layout in slots

**Choice:** Per-repo workspace clones, flat in the slot directory, using actual git repo names (e.g., `wsp-casehub-connectors/`)
**Alternatives:**
- Family workspace clone with subdirectories (current) — ambiguous ownership, cross-cutting vs per-repo split unclear
- Fresh empty directories — loses git history and merge path
**Rationale:** Identical structure to outside slots. Skills follow `wksp` symlink and see the same shape regardless of context. No slot-specific workspace logic needed.
**Trade-offs:** More clones per slot (one per repo instead of one family clone). Marginal disk cost with `--shared`.
**Sources:** Slot 138 disk structure, `slot_manager.py` create-slot function, `topology.py` layout detection
**Exploration:** deep-analysis
**Status:** captured

## D2: Naming convention

**Choice:** Use actual git repo names from the workspace remote (e.g., `wsp-casehub-connectors`), no `work-` prefix
**Alternatives:**
- `work-connectors/` prefix — collides with `work-work` pattern, fragile symlinks, historical problems
**Rationale:** Names already unique (GitHub repo names). No translation layer needed. Eliminates the `work-` prefix problems that caused symlink corruption.
**Trade-offs:** Longer directory names. Slot directory listing is less visually grouped (project and workspace interleaved alphabetically).
**Sources:** `git remote -v` on workspace repos showing `wsp-casehub-*` naming
**Exploration:** deep-analysis
**Status:** captured

## D3: Cross-cutting artifacts

**Choice:** Cross-cutting files go in primary's workspace. Tagged if the file format supports tagging. Repo-specific files go in that repo's workspace.
**Alternatives:**
- Separate cross-cutting directory — another location to check, more ambiguity
- Duplicate across workspaces — violates single-source-of-truth
**Rationale:** One file, one place. Tagging handles multi-repo scope without duplication.
**Trade-offs:** Primary workspace carries more content. Consumers must check tags to know if a file in primary's workspace applies to them.
**Sources:** Conversation — user's rule: "cross cutting files go in primary, will be cross tagged if the file supports tagging"
**Exploration:** deep-analysis
**Status:** captured

## D4: Migration strategy

**Choice:** Three-phase approach:
1. Detection bootstrap + attic: place `.workspace` markers on all workspace clones across all slots; update detection code to use `.workspace` marker as primary signal (D7); bulk-migrate archived slots
2. Active slot migration: rename workspace clones from `work-casehub/<repo>/` to `wsp-casehub-<repo>/`, with symlink bridge for loaded sessions. Detection is already name-independent from Phase 1, so renamed clones are correctly identified.
3. Code path convergence + sunset: update skills to single code path. 14-day hard sunset — auto-migrate any remaining unmigrated active slots with a warning (not silently).

**Alternatives:**
- Two code paths coexisting (old + new) — rejected as reliability disaster
- Flag-day cutover — too risky for active slots with loaded sessions
- Rename before detection update (original Phase 2→3 ordering) — rejected: creates window where renamed workspace clones pass `is_project_repo()` and could be pushed to GitHub as project repos (R1-01)
**Rationale:** Bootstrapping structural detection before any renaming eliminates the misidentification window entirely. The `.workspace` marker makes detection name-independent, so Phase 2 renaming cannot cause misidentification. The symlink bridge lets old sessions continue working. The 14-day sunset bounds the transition period — no indefinite two-code-path coexistence (R1-04).
**Trade-offs:** Phase 1 requires touching all slots (including attic) to place markers before any renaming. Migration script must handle marker placement, detection code update, file moves, and symlink creation in strict order.
**Depends on:** D1 (layout), D2 (naming), D7 (detection mechanism)
**Sources:** 21 active slots on disk, slot_manager.py archive logic, R1-01 code analysis of Phase 2→3 misidentification window
**Exploration:** deep-analysis
**Status:** revised (R1-01, R1-04: reordered phases to bootstrap structural detection before renaming; added 14-day sunset)

## D5: Work-end convergence

**Choice:** Same per-repo logical flow regardless of slot: promote → squash → merge workspace → merge project → push. Shared orchestration with topology-specific transport.
**Alternatives:**
- Keep separate merge-slot orchestrator — rejected as unnecessary divergence that causes unreliable behavior
**Rationale:** With per-repo workspace clones, the workspace interaction is identical and the per-repo logical flow converges fully. The slot-specific concerns fall into two categories: (a) **converging** — workspace interaction, squash analysis, artifact promotion, branch stamping; (b) **remaining as topology-specific transport** — original-repo preflight sync (lines 1211-1277), two-hop push clone→original→remote (lines 1340-1380), `updateInstead` configuration (line 951), SHA verification via `.landed` markers (lines 1402-1408), `ensure_clone_layout()` legacy migration (line 1168). Category (b) is encapsulated as transport helpers called from the shared flow — they don't define a separate orchestration path.
**Trade-offs:** merge-slot logic must be decomposed into shared orchestration (category a) and topology-specific transport (category b). Transport helpers remain slot-specific but are called from the shared flow, not from a parallel orchestrator.
**Depends on:** D1 (layout), D2 (naming)
**Sources:** work-end/SKILL.md divergence audit (12 points), slot_manager.py merge-slot function (~300 lines), work_end_execute.py cmd_land function (~130 lines), R1-03 code analysis of structural concerns
**Exploration:** deep-analysis
**Status:** revised (R1-03: clarified convergence scope — distinguished converging concerns from topology-specific transport that remains slot-specific)

## D6: Migration safety gate

**Choice:** Lifecycle-based migration triggers instead of idle detection:
- New slots: use new layout from creation (no migration needed)
- Session start: detect unmigrated slot and offer migration before work begins
- Work-end: migrate as part of closing sequence
- 14-day sunset: any slot not opened since migration rollout gets auto-migrated with a warning (not silently)

**Alternatives:**
- Idle detection (>1 hour, no file changes) — rejected: "no file changes" doesn't mean "no active session" (R1-05). A Claude instance reading code, brainstorming, or waiting for input writes no files but holds old paths in its context window. No reliable session-liveness signal exists in the worklog DB.
- Migrate all at once — risks corrupting a slot with an active session
- Only migrate at work-end — delays convergence, keeps two code paths longer
**Rationale:** Lifecycle-based triggers fire at well-defined points where session state is known: session start (no work in progress), work-end (work is being closed). This eliminates the need for idle detection entirely. The 14-day sunset (from D4 Phase 3) handles slots that aren't opened.
**Trade-offs:** Slots not opened for 14 days get migrated without user review. Acceptable because migration is layout-only — no content changes, no data loss.
**Depends on:** D4 (migration strategy)
**Sources:** Conversation — user's safety constraint, R1-05 analysis of idle detection gaps
**Exploration:** deep-analysis
**Status:** revised (R1-05: replaced idle-time detection with lifecycle-based triggers — session start, work-end, 14-day sunset)

## D7: Workspace clone detection mechanism

**Choice:** Structural detection via `.workspace` marker file as primary signal. Name-based detection (`work-*` prefix check in `is_project_repo()`) becomes redundant and is removed after all workspace clones have markers.
**Alternatives:**
- Name-based detection only (`wsp-*` prefix) — swaps one fragile naming convention for another (R1-02). Any future rename breaks detection.
- Dual detection (name + structural permanently) — unnecessary complexity once markers are universal
- `proj` symlink as primary — unreliable: `create_proj_symlink()` creates `proj` inside workspace subdirectories (e.g., `work/engine/proj`), not at the workspace clone root. `is_workspace_clone()` checks `repo_path / "proj"` at root level, which misses workspace clones in family-structured slots.
**Rationale:** The `.workspace` marker is name-independent, position-independent, and explicitly intentional — it can only be present if something deliberately placed it. This makes `get_slot_repos()` filtering robust against any naming changes. The marker was introduced in #239 but is never placed during `create_slot()` (R1-07). This decision makes marker placement mandatory: during slot creation, during migration (D4 Phase 1), and during workspace-init.
**Trade-offs:** Requires placing markers on all existing workspace clones before any naming changes (one-time migration cost in D4 Phase 1).
**Depends on:** None
**Sources:** `is_workspace_clone()` (slot_manager.py:880), `create_slot()` (slot_manager.py:570), `create_proj_symlink()` (slot_manager.py:442), R1-02, R1-07
**Exploration:** deep-analysis (surfaced during review)
**Status:** captured
