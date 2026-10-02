# Decisions — #384 Pipeline Engine Lifecycle

## D1: Branch scope

**Choice:** All four sub-phases in one branch — start, pause, resume orchestrators + unified work.py + conflict resolution tiers
**Alternatives:**
- Start only — lowest risk, but pause/resume are already 95% externalized
- Start + pause/resume — natural grouping, but leaves unified entry point for later
**Rationale:** Pause/resume are nearly mechanical already (externalized scripts exist). The unified work.py ties them together. Doing all four avoids multi-branch coordination overhead.
**Trade-offs:** Large branch. Mitigated by existing externalized scripts and proven orchestrator pattern.
**Exploration:** quick
**Status:** captured

## D2: Engine location — project/

**Choice:** Move `orchestrator_engine.py` and `shared_steps.py` from `work-end/` to `project/`, co-located with `lifecycle.py`, `ctx.py`, `work_chain.py`
**Alternatives:**
- New top-level `orchestrator/` — clean separation but adds a new module
- Keep in `work-end/` — least churn but misleading location
**Rationale:** All lifecycle infrastructure belongs in `project/`. The engine is used by all lifecycle commands, not just work-end.
**Trade-offs:** Import path changes in work-end and all consumers. Incremental migration handles this.
**Sources:** project/lifecycle.py, project/ctx.py, work-end/orchestrator_engine.py
**Exploration:** quick
**Depends on:** D1
**Status:** captured

## D3: Progress tracking — single .work-progress

**Choice:** Single `.work-progress` file with command-scoped keys (e.g., `start:create_branch=done`). Cleared when the command completes.
**Alternatives:**
- Per-command files (.start-progress, .close-progress, etc.) — current pattern extended
- Reuse .close-progress for all — confusing name
**Rationale:** One file to check for interrupted state. Simpler debugging. Command-scoped keys prevent cross-contamination.
**Trade-offs:** All commands share one file — concurrent commands (not a current scenario) would conflict. Acceptable since lifecycle commands are sequential.
**Sources:** work-end/close_progress.py, work-pause/pause_exec.py (.pausing intent), work-resume/resume_exec.py (.resuming intent)
**Exploration:** quick
**Depends on:** D2
**Status:** captured

## D4: work-end migration — incremental

**Choice:** Move engine + shared_steps to project/. Update work-end imports. `work_end_orchestrator.py` stays in `work-end/` with its step list — just imports from the new location. New orchestrators import from `project/`. Full unification into work.py happens when work-end's step list is proven stable under new imports.
**Alternatives:**
- Rewrite work-end into work.py — high risk, 1644 lines reorganized alongside new features
- Leave work-end separate — divergence risk
**Rationale:** The existing work-end orchestrator is proven and stable. Moving the shared engine is low-risk. Rewriting work-end's step list is high-risk with no immediate benefit.
**Trade-offs:** work-end's step list stays in work-end/ temporarily. Full unification is a follow-up.
**Sources:** work-end/work_end_orchestrator.py (1644 lines), work-end/orchestrator_engine.py (322 lines)
**Exploration:** quick
**Depends on:** D2
**Status:** captured

## D5: SKILL.md role — handler guide

**Choice:** work.py is the orchestrator. SKILL.md shrinks to: (1) call work.py, (2) dispatch table mapping ACTIONs to handler/*.md files. Follows the skill-md-minimal-orchestrator-loop protocol.
**Alternatives:**
- work.py replaces SKILL.md entirely — requires LLM to know about work.py without skill trigger
- SKILL.md calls per-command orchestrators — no single dispatch
**Rationale:** The SKILL.md trigger mechanism is how Claude discovers and loads skills. Removing it breaks discovery. But the SKILL.md should not contain orchestration logic — that's work.py's job.
**Trade-offs:** SKILL.md still exists but is minimal. Handler files are loaded lazily per the protocol.
**Sources:** docs/protocols/skill-md-minimal-orchestrator-loop.md
**Exploration:** quick
**Depends on:** D1
**Status:** captured

## D6: Backward compatibility — read both, write new

**Choice:** work.py reads `.close-progress` OR `.work-progress` (whichever exists). New operations write `.work-progress` only. In-flight work-end operations finish naturally.
**Alternatives:**
- Hard cut — ignore .close-progress, interrupted work-end must restart
- Auto-migrate on first run — explicit migration step
**Rationale:** No explicit migration needed. In-flight operations complete using their existing progress file. New operations use the new file. Convergence happens naturally.
**Trade-offs:** Temporary dual-read code. Can be removed once no .close-progress files exist in the wild.
**Depends on:** D3
**Exploration:** quick
**Status:** captured

## D7: Architecture — monolithic work.py with inline step lists

**Choice:** One `project/work.py` file containing command parsing, pipeline selection (`PIPELINES = {"start": [...], ...}`), step definitions inline, and thin wrapper functions that delegate to existing externalized scripts (`branch_create.py`, `scaffold.py`, `pause_exec.py`, `resume_exec.py`). Calls `orchestrator_engine.run_loop()`.
**Alternatives:**
- Separate orchestrator per command (work_start_pipeline.py, etc.) with thin work.py dispatcher — more files, harder to see full lifecycle, large diff moving work-end
**Rationale:** Existing scripts already contain the mechanical logic. work.py is primarily a wiring layer. Starting monolithic and splitting if needed is lower risk than starting split and discovering coupling. Proven pattern from work_end_orchestrator.py.
**Trade-offs:** Could grow large. Mitigated by: most steps delegate to existing scripts; can extract command pipelines later if needed.
**Sources:** work-end/work_end_orchestrator.py (pattern), work-start/branch_create.py, work-start/scaffold.py, work-pause/pause_exec.py, work-resume/resume_exec.py
**Exploration:** quick
**Depends on:** D2, D5
**Status:** captured
