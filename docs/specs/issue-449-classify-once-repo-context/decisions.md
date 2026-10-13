# Decisions — Classify-Once RepoContext (#449)

## D1: Where to place get_lifecycle_state()

**Choice:** Add to worklog.py
**Alternatives:**
- project/lifecycle.py — closer to state machine but lifecycle.py's query functions (read_state, is_transient, is_closing, is_closed) operate on .plan files and git state, not DB tables. get_lifecycle_state queries the DB events table — different data layer.
- New project/lifecycle_query.py — clean separation but adds indirection for a single function
**Rationale:** worklog.py is the DB access layer — all DB reads/writes belong there. Query functions like active_work() and find_work_item() already live there. Adding get_lifecycle_state() follows the same pattern.
**Trade-offs:** worklog.py lives in ~/.claude/lib/ (shared across projects). Changes there affect all projects. But this is a read-only query — low risk. Implementation note: existing get_lifecycle_state has a key mismatch bug — queries `$.to` but _emit_to_worklog stores the key as `to_state`. Fix to `$.to_state` during implementation.
**Sources:** worklog.py (line 749: active_work, line 200: find_work_item), lifecycle.py (line 286: _emit_to_worklog already imports worklog)
**Exploration:** quick
**Status:** captured

## D2: RepoContext construction approach

**Choice:** Two-phase construction — classify then enrich
**Alternatives:**
- Extend classify_repo() to return RepoContext directly — fewer subprocess calls but couples classification to DB access, violates single-responsibility
- RepoContext.from_state() classmethod — OOP-style, similar to chosen approach but less explicit
**Rationale:** Keeps classify_repo() focused on pure git classification. build_repo_context() wraps RepoState + computes tree_sha, main_tree_sha, remote_synced + queries lifecycle_state from DB. Callers who don't need lifecycle_state can skip the DB query. remote_synced must be derived from local refs (`git rev-parse origin/main`) after the fetch that pipeline entry already performs — not from a second `git ls-remote` call. build_repo_context accepts an optional `conn: sqlite3.Connection` parameter; callers open one connection, pass it for all repos, then close — consistent with worklog.py's existing API pattern.
**Trade-offs:** Two function calls instead of one. Extra git subprocess calls for tree SHAs (but these are cheap local operations — all derived from local refs, no network calls).
**Sources:** repo_state.py (classify_repo lines 47-138), parent spec Phase 2 design (RepoContext extends RepoState via composition)
**Exploration:** quick
**Status:** captured
**Depends on:** D1 (get_lifecycle_state lives in worklog.py, called by build_repo_context)

## D3: OrchestratorContext.repos type change

**Choice:** Change repos: list (currently untyped) → repos: list[RepoContext]
**Alternatives:**
- Keep list[RepoState], add parallel contexts: dict[str, RepoContext] — dual data structures with drift risk
**Rationale:** Single source of truth. RepoContext wraps RepoState via composition (context.state.disposition), so existing consumers update mechanically: r.disposition → r.state.disposition, r.path → r.state.path. No dual structures, no divergence risk. Both OrchestratorContextBase.repos (shared_steps.py:67) and OrchestratorContext.repos (work_end_orchestrator.py:159) are currently bare `list` with no type parameter — this change also serves as typing-hygiene improvement, surfacing any inconsistent usage across code paths.
**Trade-offs:** All existing RepoState access paths in the orchestrator must be updated. Mechanical but touches many lines.
**Sources:** work_end_orchestrator.py (OrchestratorContext line 134, repos usage at lines 277, 321, 1561, 1734, 1866)
**Exploration:** quick
**Status:** captured
**Depends on:** D2 (build_repo_context produces the RepoContext instances stored in repos)

## D4: lifecycle_state dependency handling

**Choice:** Build Phase 1b (get_lifecycle_state) as part of this issue
**Alternatives:**
- Defer lifecycle_state field — build RepoContext without it, add when Phase 1b lands later. Keeps Phase 2 unblocked but incomplete.
- Stub from .plan — read lifecycle_state from .plan's state: field as temporary bridge. Adds migration step later.
**Rationale:** User preference. The DB query function is small scope — one function in worklog.py. Building it now makes RepoContext complete from day one.
**Trade-offs:** Increases issue scope. log_transition does NOT have @safe — writes propagate, connection failures are caught by lifecycle.py's _emit_to_worklog (OSError/OperationalError catch at lines 303-305). Acceptable because lifecycle_state is informational in Phase 2 (not a control-flow gate). build_repo_context wraps the get_lifecycle_state call in try/except, degrading to lifecycle_state=None on failure — consistent with the informational role.
**Sources:** worklog.py events table schema (line 66-78), parent spec Phase 1b
**Exploration:** quick
**Status:** captured

## D5: Step 2d scope — skip predicates only

**Choice:** Replace skip predicates and fallback git-probe path with disposition checks; postconditions deferred to Phase 3
**Alternatives:**
- Skip predicates + postconditions — also refactor postconditions to use disposition where applicable. Increases scope but reduces Phase 3 surface area.
- Minimal (fallback path only) — only eliminate the git-probe fallback at lines 1770-1800. Leaves existing skip predicates unchanged.
**Rationale:** Skip predicates are the BEFORE-execution checks that should use classify-once data. Postconditions are AFTER-execution checks that verify outcomes — Phase 3 replaces them with VerifyResult three-valued logic. Mixing the two blurs the phase boundary.
**Trade-offs:** Postconditions continue to shell out to git independently until Phase 3. Acceptable — their correctness doesn't depend on classification.
**Sources:** step_postconditions.py (12 functions), _skip_empty_branch (line 315), _skip_multi_repo_partial_close (line 264), _close_per_repo_mechanical fallback (lines 1770-1800)
**Exploration:** quick
**Status:** captured

## D6: Empty repos handling

**Choice:** Make classify_repos robust against partial corruption, then hard error if still empty for non-main pipeline
**Alternatives:**
- Hard error only (no robustness) — simple but blocks pipeline when .slot file is corrupted/missing, even though repos exist on disk
- Keep fallback as safety net — defensive, but contradicts classify-once philosophy
- Warn and skip — no git fallback, no hard error, but silently drops steps
**Rationale:** The classify-once contract means repos are always populated at pipeline entry. For slot pipelines, if parse_slot returns None (corrupted/missing .slot file), classify_repos falls back to directory enumeration — list subdirectories with `.git` that do NOT have a `.workspace` marker file — before returning empty. Workspace directories (companion workspaces with `.workspace` marker) are excluded because they are not source repos and should not be processed through rebase/land/promote pipeline steps. This matches the pattern established in `_skip_multi_repo_partial_close` (work_end_orchestrator.py:287-290). This preserves the classify-once contract while handling partial corruption. An empty list after robust classification is a genuine classification failure. Error messages distinguish between "classification failed" (no .slot and no discoverable repos) and "no repos exist" (directory contains no git repositories).
**Trade-offs:** Must ensure classify_repos is robust. Directory enumeration fallback loses repo metadata from .slot (primary designation, branch info), so repos discovered this way get default RepoType.CLONE and require branch from the pipeline context.
**Sources:** _close_per_repo_mechanical fallback path (lines 1770-1800), classify_repos (repo_state.py lines 141-168), slot_io.parse_slot (slot_io.py:42-44)
**Exploration:** quick
**Status:** revised (R1-16: added directory-enumeration fallback; R2-02: workspace directories excluded from enumeration)
**Depends on:** D3 (repos: list[RepoContext] — empty check is on this list)

## D7: Disposition filtering on StepDef

**Choice:** Separate dispositions: frozenset[RepoDisposition] field on StepDef, paired with disposition_repo_types: frozenset[RepoType] for repo-type-aware filtering
**Alternatives:**
- Encode in skip_fn — keep modes as-is, per-step skip_fn checks disposition. Simple but distributed across lambda closures instead of declarative. Helper variant: `skip_when_all_repos(dispositions={...})` — more declarative than raw closures, but hides the disposition requirement inside skip_fn rather than making it visible in the step definition.
- Unified filter — replace both modes and skip_fn with a single predicate system. Most elegant but highest refactoring cost and risk.
- Dispositions without repo-type awareness — simpler but cannot replace `_skip_empty_branch`, which filters by RepoType.PROJECT before checking dispositions (a workspace with HAS_WORK for documentation-only changes would incorrectly keep code_review alive).
**Rationale:** PipelineMode (BRANCH/SLOT/MAIN/SYNC/CYCLE) and RepoDisposition (HAS_WORK/EMPTY_BRANCH/NO_BRANCH/ALREADY_LANDED) are orthogonal concepts. Separate fields keep them orthogonal. Semantics: dispositions on StepDef is a step-level aggregate check — "run this step if at least one repo with a type in `disposition_repo_types` has a disposition in `dispositions`." Steps like code_review set `disposition_repo_types={RepoType.PROJECT}` to match current `_skip_empty_branch` behavior (only project repos are considered). Default values follow the modes pattern: `dispositions` defaults to `ALL_DISPOSITIONS` (`frozenset(RepoDisposition)`), `disposition_repo_types` defaults to `ALL_REPO_TYPES` (`frozenset(RepoType)`). Steps without explicit disposition filtering run regardless of repo state — no behavioral change for existing StepDefs. The engine evaluates modes first (pipeline-level constant), then dispositions (step-level aggregate over repo state), then skip_fn (arbitrary conditions). Per-repo filtering within fan-out is a separate concern handled in the fan-out loop, not by the StepDef field.
**Trade-offs:** Adds two fields to StepDef (dispositions, disposition_repo_types). Engine run_loop needs updating to evaluate dispositions. The step-level aggregate semantics mean dispositions replaces _skip_empty_branch-style checks. Per-repo fan-out filtering (e.g., skip rebase for NO_BRANCH repos) remains in the fan-out loop where individual repo decisions belong.
**Sources:** shared_steps.py StepDef (line 31, modes field at line 43), RepoDisposition enum (repo_state.py line 22), _skip_empty_branch (work_end_orchestrator.py:315-329, filters by RepoType.PROJECT)
**Exploration:** quick
**Status:** revised (R2-01: added disposition_repo_types for repo-type-aware filtering; R2-03: explicit default values)

## D8: RepoContext is a classification-time snapshot

**Choice:** lifecycle_state (and all RepoContext fields) are snapshots at classification time, not live — RepoContext is not updated during the pipeline run
**Alternatives:**
- Re-read lifecycle_state during pipeline execution — adds DB coupling to mid-pipeline steps, breaks frozen=True contract
- Mutable RepoContext with live updates — removes frozen=True, adds complexity and concurrency concerns
**Rationale:** Phase 2 uses lifecycle_state informally (not as a control-flow gate). Staleness during the pipeline run is harmless for Phase 2 purposes. Phase 3 verification steps that need current lifecycle_state should re-query the DB directly via get_lifecycle_state, not rely on the snapshot.
**Trade-offs:** Consumers must understand that RepoContext fields reflect pipeline-entry state. Any mid-pipeline check that needs current state must query directly.
**Sources:** RepoState frozen=True (repo_state.py:29), lifecycle transitions during pipeline (closing:review → closing:verified → etc.)
**Exploration:** surfaced by review (R1-22)
**Status:** captured

## D9: Post-rebase RepoContext staleness

**Choice:** Accept staleness — Phase 2 skip predicates run before rebase, so the snapshot is valid for all Phase 2 decisions
**Alternatives:**
- Re-classify after rebase — breaks frozen=True, adds pipeline complexity, introduces partial-classification edge cases
- Defer tree_sha computation to Phase 3 — avoids the staleness window entirely but removes tree_sha from RepoContext
**Rationale:** tree_sha and commits_ahead are valid for their Phase 2 use (skip predicates run before rebase). After rebase, these fields are stale — tree_sha reflects the pre-rebase branch tip, commits_ahead reflects pre-rebase divergence. Phase 3 verification should re-derive any fields it needs for post-rebase checks. The classify-once contract means "classify once at pipeline entry, valid for entry-time decisions" — not "valid for the entire run regardless of mutations."
**Trade-offs:** Phase 3 must re-derive tree_sha and commits_ahead where needed rather than relying on the snapshot. This is explicit and correct — better than silently using stale data.
**Sources:** Rebase happens mid-pipeline (closing:promoted phase), repo_state.py RepoState frozen=True
**Exploration:** surfaced by review (R1-23)
**Status:** captured

## D10: Evaluation order — modes → dispositions → skip_fn

**Choice:** Engine evaluates modes first, dispositions second, skip_fn third
**Alternatives:**
- Dispositions after skip_fn — possible but evaluates a cheaper check later than necessary
- No fixed order — dispositions and skip_fn are both step-level filters without a guaranteed evaluation order
**Rationale:** Cheapest-to-most-expensive ordering. Modes are a set membership check (pipeline_mode in s.modes). Dispositions are an aggregate set check across repos (any(r.disposition in s.dispositions for r in repos)). skip_fn may call arbitrary code including git operations. Early-exit on cheaper checks avoids unnecessary computation. skip_fn should not override a disposition match — if a step's dispositions exclude it, skip_fn is never reached.
**Trade-offs:** Fixed evaluation order means skip_fn cannot relax a disposition filter. This is intentional — dispositions are a structural constraint (no relevant repos), not a soft preference.
**Sources:** orchestrator_engine.py run_loop (line 197), current modes filtering (line 228)
**Exploration:** surfaced by review (R1-24)
**Status:** captured
