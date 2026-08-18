## D1: Where should baseline .gitignore management live?

**Choice:** Rename `setup_maven_config()` → `setup_slot_repo()` and expand to include gitignore baseline
**Alternatives:**
- Extract a new `ensure_gitignore_baseline()` — clean separation but adds a fourth gitignore touchpoint, doubles call sites (four total), scatters ownership further
- Per-repo `post_clone_setup()` hook — most extensible but YAGNI for two callers
**Rationale:** Single function owns all per-repo infrastructure setup (Maven config + gitignore baseline). No new call sites — existing callers already call `setup_maven_config` at the right point. Name is honest about the broader scope. Avoids the ownership conflict where two functions both manage `.gitignore` entries.
**Trade-offs:** Function does two things (Maven + gitignore), but they're both "slot repo infrastructure" — coherent at that level.
**Sources:** slot_manager.py:361-403 (current setup_maven_config), GE-20260809-96d41c (trailing-slash symlink gotcha), decision review R1-03 (rename alternative)
**Exploration:** quick → revised after light decision review
**Status:** revised

## D2: When and how should the .gitignore changes be committed?

**Choice:** Caller commits after calling `setup_slot_repo()` — function modifies files only
**Alternatives:**
- Commit inside the function — breaks codebase precedent (no setup function commits), makes tests heavier (requires git repo instead of tmp dir)
- Batch commit after all repos — adds complexity, add_repo needs separate logic
**Rationale:** Follows codebase precedent — every setup function in slot_manager.py modifies files without committing (setup_maven_config, _exclude_symlinks, _symlink_gitignored_assets, configure_slot_remotes, _unignore_subdir, replicate_claude_md). Caller owns lifecycle context and knows when setup is complete. Tests stay lightweight (tmp_path + text file).
**Trade-offs:** Commit logic in two callers (create_slot, add_repo). Acceptable — both are in the same file at adjacent code positions.
**Depends on:** D1 (setup_slot_repo exists as the renamed/expanded function)
**Sources:** slot_manager.py:536-582 (create_slot flow), slot_manager.py:699-736 (add_repo flow), decision review R1-07 (precedent), R1-10 (caller-level commit)
**Exploration:** quick → revised after light decision review
**Status:** revised
