## D1: Module boundaries

**Choice:** 11-module extraction matching natural call-graph clusters
**Alternatives:**
- 6-module coarser split — fewer files but `slot_infra.py` would be ~400 lines with 4 tangled concerns, recreating the original problem at smaller scale
- 8-module hybrid — merges maven+ISX into `slot_infra.py`, reasonable but ISX has its own lifecycle distinct from build tooling
**Rationale:** Each module should be small enough to reason about independently. 11 modules where each has a single clear purpose prevents re-accumulation. The extra files are cheap — clear names and focused imports.
**Trade-offs:** More import statements across the codebase; slightly more files to navigate
**Sources:** work-slot/slot_manager.py call graph audit, issue #306 responsibility inventory
**Exploration:** quick
**Status:** captured

## D2: Extraction order

**Choice:** Core-first — extract `slot_core.py` (utilities/resolution) as the first module, then follow dependency depth
**Alternatives:**
- Metadata-first — easier first win but requires duplicating `run_cmd` temporarily
- Core + metadata together — larger first commit, no duplication, but harder to review
**Rationale:** Core is the foundation that every other module imports. Extracting it first means every subsequent extraction is a clean cut with a stable import target. The 16 utility functions are small and the call-site updates are mechanical.
**Trade-offs:** Larger first commit since core is widely used (~20+ call sites for `run_cmd` alone)
**Depends on:** D1 (module boundaries)
**Sources:** Call graph analysis showing `run_cmd`, `parse_slot_md`, resolution helpers as most-called functions
**Exploration:** quick
**Status:** captured

Full extraction sequence:
1. `slot_core.py` — utilities, resolution, constants, exception
2. `slot_metadata.py` — parse/write .slot, stamps, landed markers
3. `slot_maven.py` — Maven settings, repo setup
4. `slot_isx.py` — ISX lifecycle
5. `slot_claude.py` — Claude project dirs
6. `slot_git.py` — clone, branch, hooks, alternates, migration
7. `slot_workspace.py` — workspace discovery, symlinks, CLAUDE.md
8. `slot_query.py` — list, scan, cross-deps, find
9. `slot_observability.py` — worklog wrapper, drift detection
10. `slot_lifecycle.py` — orchestrators (create, add, merge, archive, remove, restore)
11. `slot_cli.py` — main, parse_args, CLI dispatch

## D3: Test organization

**Choice:** Tests move with functions — each extraction creates a matching `test_slot_<module>.py` alongside the new module
**Alternatives:**
- Tests stay in `test_slot_manager.py` with updated imports, split in a final commit — simpler per-extraction commits but defers the organizational benefit and creates a long period where test file structure doesn't match source structure
**Rationale:** Matches "tests move with their code" principle. Each extraction is self-contained: new module + its tests arrive in one commit. Protocol `externalised-scripts-require-tests` reinforces this — new modules ship with tests. `test_slot_manager.py` shrinks from 4,315 lines to whatever covers `slot_lifecycle.py` + `slot_cli.py`, then gets renamed in the final extraction.
**Trade-offs:** Each extraction commit is larger (includes test moves). Test file identification requires careful grep to find which tests exercise which functions.
**Depends on:** D1 (module boundaries), D2 (extraction order)
**Sources:** Protocol PP-20260609-df21ed (externalised scripts require tests), user directive "tests move with their code"
**Exploration:** quick
**Status:** captured

## D4: create_slot/add_repo deduplication

**Choice:** Extract shared `_setup_repo_in_slot()` pipeline during lifecycle extraction (step 10)
**Alternatives:**
- Extract early into `slot_git.py` (step 6) — earlier dedup but the pipeline spans git + workspace + maven concerns and doesn't fit cleanly in a leaf module
**Rationale:** The shared 12-step repo-setup pipeline is orchestration — it calls into git, workspace, and maven. It belongs with the orchestrators in `slot_lifecycle.py`. By step 10, all leaf modules exist, so the pipeline imports cleanly from each. Doing it earlier would force cross-concern coupling in a leaf module.
**Trade-offs:** Duplication persists through steps 1-9. Acceptable because the duplicated code is being moved, not modified — no risk of divergence during migration.
**Depends on:** D1 (module boundaries), D2 (extraction order)
**Sources:** Audit confirming ~80% duplication between create_slot (lines 769-825) and add_repo (lines 928-1007)
**Exploration:** quick
**Status:** captured
