# Decisions — Robust Pipeline Architecture (#443)

## D1: Migration approach

**Choice:** Evolve existing infrastructure
**Alternatives:**
- Clean-room pipeline — higher upfront cost, long integration tail, large blast radius
- Layered facade — wraps old code without changing it, but adds indirection without fixing root causes
- Strangler fig — builds new primitives alongside old, runs both in parallel, switches over. At this infrastructure scale (~560 lines lifecycle.py, ~200 lines plan_io.py), the overhead of parallel verification exceeds incremental fix cost. Converges to evolution in practice — individual primitives are replaced while the state machine stays
**Rationale:** The primitives exist (worklog DB events table, lifecycle.py state machine with CAS, RepoState classification). Two categories of problems exist: (1) primitives that are sound but bypassed — components that don't use plan_io.py or lifecycle.py when they should; (2) primitives with quality bugs — postcondition logic errors (#436), false-pass verification (#375), edge-case handling gaps (#435). Evolution addresses both: fix the bugs in-place, enforce the modules. Rebuilding risks reintroducing the same logical errors in new code.
**Completion criteria:**
1. All .plan writes route through plan_io.py (enforcement — zero direct file manipulation)
2. All lifecycle transitions route through lifecycle.py (already true)
3. All state reads use DB events, not .plan parsing (D3 dependency)
4. Evidence gating active for all closing sequences (evidence-era: true)
5. Zero primitive-quality bugs open in the postcondition/verification layer
**Trade-offs:** Must maintain backward compatibility during migration. Coexistence of old and new patterns until completion criteria are met.
**Sources:** worklog DB schema (events table), project/lifecycle.py (CAS writes), project/repo_state.py (classify_repo). Issues #436 (postcondition quality), #375 (verification quality), #435 (edge-case quality)
**Exploration:** quick
**Status:** captured

## D2: Unit of lifecycle tracking

**Choice:** Single lifecycle with per-repo orchestration
**Alternatives:**
- Per-repo lifecycle — N independent state machines (one per repo) plus a slot-level coordinator. Creates N+1 consistency boundaries with cross-machine synchronization requirements. The coordinator logic (the hardest part) was never designed
- Work-item lifecycle with per-repo sub-fields — simpler coordination with one consistency boundary. Essentially what the revised choice implements
- Single lifecycle (current) — one lifecycle per .plan with skip predicates for inactive repos. The cited bugs (#437, #438, #431) are implementation quality issues in the existing single-lifecycle model, not structural granularity issues
**Rationale:** One state machine per work item. The orchestrator fans out within each lifecycle state for per-repo concerns. The existing infrastructure already supports this: PER_REPO_EXECUTE_STEPS (rebase, land), PER_REPO_SWEEP_STEPS (protocol, update_claude_md, impl_doc_sync, doc_freshness_gate), repo_state.classify_repos() for disposition classification, and composite progress keys (rebase:engine=done). The worklog DB already has per-repo work_items via repo_id FK. What's missing is the orchestrator consistently using this per-repo data: #437 needs active-repo filtering in sweep fan-out, #438 needs peer-repo precondition checks before archive, #431 needs slot-aware project resolution in ctx.py.
**Trade-offs:** Per-repo tracking stays at the orchestrator level (composite progress keys) rather than the lifecycle level. The lifecycle state machine tracks the work item's progress, not individual repo progress.
**Sources:** Issues #437, #438, #431, #387, #368, #361 (multi-repo bugs). work_end_orchestrator.py (existing per-repo fan-out). repo_state.py (existing classification)
**Exploration:** quick
**Status:** revised (R1-04, R1-05: reviewer demonstrated cited issues are orchestrator bugs, not lifecycle-granularity bugs; per-repo lifecycle creates N+1 state machine coordination complexity without solving the actual problems)

## D3: State source of truth

**Choice:** Events primary, .plan derived
**Alternatives:**
- Single-writer .plan with events as audit — simpler migration but .plan still vulnerable to git corruption (rebase, merge conflicts) and has no schema enforcement. Enforcement via plan_io.py fixes the bypass problem but not the git-corruption vector: lifecycle.py's _commit_plan_to_git commits .plan to git, making it subject to rebase during work-end
- Dual-source with reconciliation — both authoritative with conflict resolution. Most complex but most resilient
**Rationale:** Eliminates the multi-writer problem entirely — only the event emitter writes .plan (as a derived snapshot). Pipeline reads state from DB events only. Fresh clones bootstrap from .plan + start new event sequence. The DB is more reliable than .plan for this use case: not in git (immune to rebase corruption), WAL mode (concurrent reads), schema-enforced (no format corruption), atomic transactions (no partial writes). The current @safe decorator and best-effort wrapping must be removed from primary-path write operations — error handling replaces silent drops. Recovery from .plan snapshot handles DB corruption/loss (a defined disaster-recovery path, not an active dual-source model). The derived .plan is committed to git for visibility and clone bootstrap, but is regenerated from DB state after any git operation that could corrupt it (post-rebase, post-merge). This ensures the recovery snapshot stays consistent with the DB even though .plan participates in git operations — corruption from rebase is immediately overwritten by the next DB-derived snapshot.
**Trade-offs:** DB must be available for pipeline decisions. If DB is lost, state history is gone (but .plan snapshot provides recovery point — best-effort, since .plan is itself subject to git corruption between regeneration points). DB is local — doesn't travel with repo clones. Reliability inversion requires removing @safe from write-path operations, adding busy_timeout for write contention, and adding explicit error handling for DB unavailability. Post-rebase .plan regeneration adds a new step to the rebase pipeline but eliminates the asymmetry between primary-store protection and recovery-snapshot exposure.
**Sources:** Worklog DB events table (already captures transitions, just write-only). .plan file (7 writers, 28+ readers, 12+ issues). Issues #441, #434, #410, #398, #396, #392 (state management failures). lifecycle.py line 208-223 (_commit_plan_to_git — .plan participation in git operations)
**Exploration:** quick
**Status:** captured
**Depends on:** D1 (evolve existing — the DB and lifecycle.py are the infrastructure being evolved)

## D4: LLM interaction model

**Choice:** Formalize the existing pipeline-drives pattern
**Alternatives:**
- Current model unchanged — keeps the ad-hoc action_context_fn/verify_fn pattern without explicit typed contracts. The existing StepDef already implements Python-drives-LLM-assists; the remaining gaps are: no JSON schema for judgment request/response (just key=value pairs), judgment steps lack explicit input/output contracts (action_context_fn returns ad-hoc dicts), verify_fn only validates counts not structured content
- Typed contracts on yield/callback — adds JSON schema contracts to the existing mechanism without changing the interaction model. Closest to a pure formalization, but the yield/callback pattern still passes state through the LLM
**Rationale:** The work_end_orchestrator.py docstring already describes this pattern: "Python drives, LLM assists. The LLM cannot skip what it cannot see." The existing architecture has StepDef with step_type (mechanical/judgment/lifecycle), action_context_fn providing structured context, verify_fn validating responses, and run_loop orchestrating the sequence. What remains is to complete the formalization: define JudgmentRequest/JudgmentResponse as typed interfaces with JSON schemas, replace ad-hoc context dicts with structured contracts, and extend verify_fn from count validation to content validation. This is refinement and completion, not a direction change.
**Trade-offs:** Requires typed interfaces for every judgment step. Handler .md files still exist for guidance but the interface is a contract, not free text. Migration requires updating SKILL.md orchestrator loops.
**Sources:** work_end_orchestrator.py docstring (line 3-7, existing pattern). Issues #434 (meta_state bounce), #391 (missing completion hint), #393 (step_done missing), #433 (unnecessary round-trips)
**Exploration:** quick
**Status:** revised (R1-09: reviewer demonstrated the architecture already exists; D4 reframed from "new direction" to "formalize and complete existing pattern")
**Depends on:** D1 (evolve existing — modifies the orchestrator engine, not replaces it)

## D5: Verification model

**Choice:** Git state + events, three-valued (PASS/FAIL/UNKNOWN)
**Alternatives:**
- Git state only — simpler but no audit trail. If git history rewritten, no backup. Can't distinguish "we landed this" from "someone else pushed to main"
- Stamps + git fallback — least disruptive but maintains the proxy layer that causes failures
**Rationale:** Verify actual git state (tree SHA match, commit reachable from main, issue closed on GitHub) AND event sequence (land event exists with SHA). Three-valued: PASS when positive evidence exists, FAIL when counter-evidence exists, UNKNOWN when insufficient evidence. UNKNOWN never collapses to PASS — follows a three-step resolution path: (1) deterministic check, (2) deterministic fallback/retry, (3) LLM escalation as last resort. UNKNOWN conditions are enumerable with specific deterministic fallbacks: (a) partial landing (some repos landed, others not) → retry unfinished repos (transient errors like dirty worktree may resolve on retry); (b) ambiguous branch state (unexpected topology) → attempt known resolutions (detached HEAD → reattach, rebase-in-progress → abort and retry), escalate only if topology is truly unknown; (c) missing evidence (expected git state doesn't match) → wait-and-recheck with backoff (evidence may be propagating from remote push), escalate only after N retries. LLM judgment is reserved for genuinely ambiguous situations where deterministic resolution has been exhausted. Each UNKNOWN condition provides the specific ambiguity context to the LLM, making the judgment decision auditable and debuggable — unlike the current silent-True pattern (#436) where incorrect verification is invisible.
**Trade-offs:** Stamp files eliminated — all consumers must migrate. Git state checks are slower than stamp file existence checks (subprocess vs stat). UNKNOWN deterministic fallbacks add retry logic to the verification layer (consistent with the existing MAX_MECHANICAL_RETRIES = 3 pattern in the orchestrator). LLM escalation remains for genuinely ambiguous cases but should be rare in practice.
**Sources:** Issues #436 (empty = success), #435 (stamp never written), #375 (negative check), #386 (skip path missing SHA), #388 (ordering bug)
**Exploration:** quick
**Status:** captured
**Depends on:** D3 (events primary — verification reads event log), D2 (per-repo — verification is per-repo)

## D6: SQLite suitability as primary state store

**Choice:** SQLite with WAL mode
**Alternatives:**
- Embedded key-value store (e.g., shelve, dbm) — simpler but no schema enforcement, no concurrent-read support, no relational queries
- File-based state (JSON/YAML per work item) — git-trackable but re-introduces the multi-writer and git-corruption problems that D3 solves
- External database (PostgreSQL, etc.) — unnecessary for a single-user local tool; adds deployment complexity
**Rationale:** For a single-user local CLI tool with occasional concurrent sessions: SQLite with WAL provides concurrent reads with serialized writes. Write lock duration is milliseconds for the small transactions involved (single INSERT/UPDATE). busy_timeout handles rare write contention between concurrent sessions. The existing worklog.py already uses SQLite with WAL (line 169: PRAGMA journal_mode=WAL) and foreign keys — this is proven infrastructure.
**Trade-offs:** DB file is local — doesn't travel with repo clones. Write serialization could become a bottleneck if transaction sizes grow (not expected at current scale). Recovery from corruption requires .plan snapshot bootstrap (D3's recovery path).
**Sources:** worklog.py connect() (line 165-173, existing WAL configuration). SQLite documentation on WAL mode and concurrent access
**Exploration:** quick (surfaced by review R1-13)
**Status:** captured
**Depends on:** D3 (events primary — SQLite is the implementation choice for the event store)
