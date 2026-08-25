# Decisions — #271 Mechanise work-end close sequence

## D1: Orchestration model

**Choice:** Stateless re-entrant Python script
**Alternatives:**
- Long-running coroutine (stdin/stdout streaming) — fights Claude Code's execution model; no bidirectional streaming support
- Claude Code Workflow (JavaScript) — loses accumulated conversation context; each Workflow step spawns a fresh agent with no memory of prior steps. Review findings, sweep discoveries, and user decisions would not carry forward. Also a poor abstraction fit — Workflows are optimised for multi-agent fan-out, not single-agent state machines.
**Rationale:** Each invocation reads `.close-progress`, runs mechanical steps until a judgment point, prints one action, exits. The LLM calls it again after doing the work. Simple, crash-safe, matches how Claude Code already runs scripts. Critically, the LLM's conversation context persists across yield points — review findings inform sweep, sweep informs squash analysis, user decisions carry forward. This context preservation is the decisive architectural reason for rejecting Workflows.
**Trade-offs:** Re-entry overhead (re-reading progress, re-resolving paths) on each call — negligible vs correctness gains.
**Sources:** Issue #271, Claude Code Workflows docs, work-end restructure spec
**Exploration:** quick
**Status:** revised (R1-08: rationale strengthened — context preservation is the decisive factor for rejecting Workflows, not the "wrong layer" category argument)

## D2: Control inversion — LLM sees one action at a time

**Choice:** The SKILL.md is a ~20-line loop. The LLM calls the orchestrator, reads one ACTION, executes it, loops. The LLM never knows the full step sequence.
**Alternatives:**
- LLM reads full sequence from SKILL.md (current model) — LLM skips steps; 4/4 audited slots had failures
- LLM reads step list but scripts enforce order — partial fix; LLM can still skip calling scripts
**Rationale:** The LLM cannot skip what it cannot see. Python decides what's next. The 660-line SKILL.md becomes ~20 lines.
**Trade-offs:** The LLM loses situational awareness of the full close sequence. Mitigated by the orchestrator providing context in each action's output.
**Sources:** Issue #271 (audit evidence), Oracle AI Agent Loop, AgenticStateMachines (GitHub), Google Cloud agentic AI patterns
**Exploration:** quick
**Status:** captured

## D3: Action granularity — typed actions, fine-grained progress

**Choice:** 6 core LLM action types (review, sweep_config, squash, trajectory, verify_recover, user_input) plus per-sweep-sub-step actions (forage, protocol, update_claude_md, impl_doc_sync, adr, write_content) yielded individually after sweep_config. Fine-grained sub-step tracking in `.close-progress` for crash recovery. `user_input` is parameterised via CONTEXT= to specify what input is needed (e.g., arc42_scan, session_rename, garden_feedback, notes).
**Alternatives:**
- 5 coarse actions with sweep as a single undifferentiated block — contradicts D2; LLM can skip individual sweep sub-steps (see D4 revision)
- Monolithic single action (LLM does everything in one turn) — no validation checkpoints
**Rationale:** A typical close fires ~8-10 actions: review, sweep_config, 3-4 selected sweep sub-steps, squash, trajectory, 1-2 cleanup interactions. Sweep sub-steps are conditional on user selection (via sweep_config). verify_recover fires only when verify fails. Post-rebase re-review is a conditional invocation of the existing review action with DIFF_RANGE= scoped to conflict resolution. Step 1 context resolution is pre-close — the orchestrator's close sequence starts after context is already resolved.

**Lifecycle state mapping:**

| Lifecycle state | Actions that fire | Event to advance |
|---|---|---|
| `closing:review` | review, sweep_config, [selected sweep sub-steps] | `review_pass` |
| `closing:verified` | promote (mechanical) | `promote_pass` |
| `closing:promoted` | squash, rebase (mechanical), land (mechanical), [post-rebase review if conflicts] | `push_pass` → `merge_pass` → `stamp_pass` |
| `closing:pushed` | — (transient, rapid succession) | `merge_pass` |
| `closing:merged` | — (transient, rapid succession) | `stamp_pass` |
| `closing:stamped` | trajectory, user_input (arc42, session_rename, garden_feedback, notes) | `cleanup_pass` |

Note: `closing:verified` covers the promotion phase after review+sweep complete. The name implies review verification but semantically represents "review gate passed." State naming is a lifecycle.py concern, not a close-orchestrator decision — renaming would affect all lifecycle consumers.

**Trade-offs:** More action types than 5 coarse actions. Mitigated by conditional firing — most actions don't fire every close. Round-trip overhead (milliseconds per yield) is negligible vs execution time (minutes per judgment step).
**Sources:** Work-end SKILL.md current step inventory, lifecycle.py transition table
**Exploration:** quick
**Status:** revised (R1-04: added verify_recover, parameterised user_input, classified pre-close items. R1-03/D4: sweep sub-steps now individual actions. R1-11: lifecycle state mapping added.)

## D4: Sweep ownership — orchestrator-sequenced, LLM-executed

**Choice:** The orchestrator first yields `ACTION=sweep_config`. The LLM presents the toggle UI and reports which sub-steps the user selected (e.g., `SELECTED=forage,protocol,write_content`). The orchestrator then yields each selected sub-step individually (`ACTION=forage`, `ACTION=protocol`, etc.), validating outputs after each. This maintains D2's principle: the orchestrator controls sequencing, the LLM owns the creative execution.
**Alternatives:**
- LLM owns all sweep sub-steps as a single block (original D4) — contradicts D2's core principle; LLM sees 6 sub-steps and can skip individuals. Issue #271 audit evidence (slot 149): blog uncommitted in attic, not promoted — a sweep sub-step the LLM skipped. The re-yield mitigation is exactly the "scripts enforce order + skip detection" pattern that D2 rejects.
- Orchestrator presents toggle UI via structured output — over-engineering; LLM handles toggle naturally
**Rationale:** Sweep sub-steps take minutes each (forage, write-content); orchestrator re-yield takes milliseconds. The round-trip overhead is negligible relative to execution time. The LLM's conversation context persists across yield points, so forage discoveries are available during protocol, and protocol captures inform write-content. No creative context is lost. Each sub-step gets individual output validation, directly addressing the slot 149 failure mode.
**Trade-offs:** Up to 7 yield points during a full sweep (sweep_config + 6 sub-steps) vs 1 in the original design. Acceptable given per-sub-step execution time and the proportional safety gain.
**Sources:** Current SKILL.md Step 3 sweep implementation, issue #271 audit (slot 149)
**Exploration:** quick
**Status:** revised (R1-03: split sweep into individual yield points to maintain D2 consistency and address observed slot 149 failure)

## D5: Validation stack — mechanical heuristics primary, Haiku optional secondary

**Choice:** Python structural checks (file exists, frontmatter valid, JSON schema, git status, findings resolved) as the primary validation layer. Content quality heuristics (word count > threshold, no placeholder text, required sections present) for write-content and ADR outputs. Haiku via Vertex AI as an optional secondary semantic validation layer — used only when available and only where heuristic checks are proven insufficient during implementation.
**Alternatives:**
- Haiku validation for every step — unnecessary cost, latency, and availability dependency for mechanically validatable steps
- No semantic validation (mechanical only) — misses content quality issues (placeholder blog entries, hallucinated findings)
- LLM self-assessment (yield ACTION=validate) — weak; the LLM produced the output, self-assessment has limited value for quality assurance
**Rationale:** Most judgment steps produce mechanically validatable artifacts. Content quality is addressed by heuristic checks (word count, structure, no placeholders) that run locally without network dependencies. Haiku earns its place only if heuristics prove insufficient — proven during implementation, not assumed upfront. When Haiku is unavailable (offline development, CI, quota exhaustion), heuristic-only validation is sufficient; the close sequence is never blocked by external API availability. Authentication uses Application Default Credentials from the existing Vertex AI setup.
**Trade-offs:** Heuristic checks may miss subtle content quality issues that Haiku would catch. Acceptable — the current system has zero validation, so heuristics alone are a major improvement. Haiku adds setup requirements (Vertex AI credentials) and per-call cost when used.
**Sources:** Vertex AI Haiku availability in current environment
**Exploration:** quick
**Status:** revised (R1-06: promoted heuristic checks as primary quality layer, made Haiku optional with graceful degradation, addressed offline/CI/quota failure modes)

## D7: Protocol format — action-specific context

**Choice:** KEY=VALUE lines with action-specific context only. The orchestrator provides values the LLM needs to execute THIS action correctly (diff range, repo list, resume point). Does not repeat generic context already in the conversation (project path, workspace path, branch name).
**Alternatives:**
- Full context every time (Option A) — verbose, repeats what the LLM already knows
- Minimal ACTION + RESUME_FROM only (Option C pure) — risks LLM hallucinating action-specific values like diff ranges or repo lists
**Rationale:** The LLM can't be trusted to derive action-specific values correctly. The orchestrator has computed them from progress state and ctx.py. Generic paths are already in conversation context and don't need repeating. KEY=VALUE format is consistent with the soredium script ecosystem.
**Trade-offs:** Requires judgment about what's "action-specific" vs "already known" — but the rule is clear: if getting it wrong causes a failure, include it.
**Sources:** ctx.py output format, existing soredium script conventions
**Exploration:** quick
**Status:** captured

## D8: Progress file format

**Choice:** Flat KEY=VALUE, one line per sub-step. Atomic write-then-rename: write to `.close-progress.tmp`, then `os.replace()` to `.close-progress`. Same KEY=VALUE convention as `.execute-progress`, with the crash-safety fix applied to both files.
**Alternatives:**
- JSON object — easier atomic read/write but inconsistent with existing `.execute-progress` format
- Append-only (open with mode 'a', scan for last value per key on read) — truly crash-safe against partial writes, but more complex read logic and `.execute-progress` doesn't use this pattern
- Read-modify-write with `path.write_text()` (current `.execute-progress` pattern) — NOT crash-safe; `write_text()` truncates the file first, then writes. Process crash between truncation and write completion loses ALL earlier progress entries.
**Rationale:** Atomic write-then-rename is crash-safe: partial writes go to `.close-progress.tmp`; the old file survives until `os.replace()` completes atomically (POSIX guarantee). `lifecycle.py` already uses this exact pattern in `write_state()` (line ~230: `tmp_path.replace(plan_path)`). The existing `write_progress()` in `work_end_execute.py` and `_write_progress()` in `land_flow.py` use the unsafe read-modify-write pattern — both must be fixed to use atomic write-then-rename as part of this work.
**Trade-offs:** Slightly more code than raw `write_text()`. The `.tmp` file is briefly visible on disk. Both negligible.
**Sources:** work-end/work_end_execute.py `write_progress()`, work-end/land_flow.py `_write_progress()`, project/lifecycle.py `write_state()` (correct pattern)
**Exploration:** quick
**Status:** revised (R1-02: fixed false "append-only" claim. Existing write_progress is read-modify-write, not append-only. Adopted atomic write-then-rename from lifecycle.py.)

## D9: Slot mode handling — unified sequence

**Choice:** Single orchestrator, same sequence for slots and non-slots. Slot-specific mechanics (two-hop transport, merge into original, `.landed` marker) are already encapsulated in the existing scripts (`land_flow.py`, `slot_manager.py`). The orchestrator calls the same scripts — they handle the mode difference internally.
**Alternatives:**
- Two orchestrator scripts (slot vs non-slot) — duplicates sequence logic for no gain
- Slot-aware branching in orchestrator — unnecessary for internal mechanics; the scripts already handle two-hop transport, `.landed` markers, etc.
**Rationale:** Slots and non-slots follow the same sequence. The only difference is the extra merge into the original repo, which is already handled by the landing scripts. The orchestrator doesn't need to know internal mode differences.
**Trade-offs:** The orchestrator needs routing conditional logic at 5+ decision points: Step 4.3 `.phase-a-complete` marker write (slot only), Step 4.4 `slot_manager.py merge-slot` vs `work_end_execute.py land` (different entry points by mode), Step 5 `slot_dir=` argument to verify (slot only), Step 6.1 `archive-slot` (slot only), Step 6.2b `.plan` cleanup vs retention (branch mode removes `.plan`, main mode retains for `drained` state). This is strictly routing — which script to call and which arguments to pass — not duplicated business logic. The unified sequence is still simpler than maintaining two orchestrator scripts with shared logic.
**Sources:** land_flow.py, slot_manager.py, prior unification work, SKILL.md Steps 4-6
**Exploration:** quick
**Status:** revised (R1-07: acknowledged routing trade-offs — the orchestrator is simpler than two scripts but has non-zero conditional complexity)

## D10: Error and retry policy

**Choice:** Two-tier policy based on step type:

- **Judgment steps** (review, sweep sub-steps, trajectory): re-yield with REASON= explaining what failed validation, max 3 attempts. After 3 failures, yield `ACTION=user_input CONTEXT=step_failed STEP=<name>` — escalate to the user for skip/retry/abort decision. Never silently skip judgment work.
- **Mechanical steps** (push, merge, stamp, promotion): re-yield with REASON=, max 3 attempts, then skip-with-warning. The orchestrator records the skip in `.close-progress` and `verify_slot_close.py` catches it downstream.

**Alternatives:**
- Uniform skip-with-warning for all steps — unsafe for judgment steps; `verify_slot_close.py` checks merged, stamped, landing SHA, pushed, issues closed, but does NOT check review completion, sweep outputs, trajectory, or findings resolution
- Re-yield indefinitely — risks infinite loops
- Hard stop after 3 — too disruptive for mechanical steps; forces manual intervention for transient failures
**Rationale:** Judgment-step failures indicate a problem the LLM can't resolve mechanically — the user needs to decide whether to skip, retry differently, or abort. Mechanical-step failures are caught by `verify_slot_close.py`'s defence-in-depth checks: `project_merged`, `project_stamped`, `landing_sha`, `main_pushed`, `workspace_stamped`, `issues_closed`, `landed_marker`, `original_sync`, `archive_status`. Review and sweep outputs have no downstream verification gate — skipping them silently would leave the gap undetected.
**Trade-offs:** Judgment-step escalation may block the close sequence waiting for user input. Acceptable — the alternative (silently skipping review or sweep) is worse. The user can still choose to skip.
**Sources:** Current work-end non-blocking patterns (trajectory, forage), verify_slot_close.py check inventory (exhaustively verified)
**Exploration:** quick
**Status:** revised (R1-05: split policy by step type. Judgment steps escalate to user instead of silent skip, because verify_slot_close.py has no downstream catch for review/sweep outputs.)

## D6: Existing scripts reused as-is

**Choice:** The orchestrator calls the existing 17 work-end Python scripts without modification. It is a wrapper/sequencer, not a rewrite.
**Alternatives:**
- Rewrite scripts into monolithic orchestrator — high risk, no gain; scripts already work correctly
- Partial rewrite (merge some scripts) — premature; scripts are independently testable as-is
**Rationale:** The scripts are not the problem. The LLM skipping calls to scripts is the problem. The orchestrator adds sequencing and validation around scripts that already work.
**Trade-offs:** More subprocess calls (orchestrator → script → subprocess) — negligible latency. The orchestrator introduces a new failure class: sequencing errors (wrong script at wrong step, incorrect arguments, validation false positives/negatives, progress tracking issues, mode branching errors). This is a risk shift from "LLM skips steps" (observable in conversation) to "orchestrator mis-sequences steps" (opaque in script internals). Mitigated by: (a) orchestrator-specific test suite covering full sequence, mode branching, crash recovery, and edge cases, and (b) `verify_slot_close.py` as defence-in-depth for Execute-phase steps.
**Sources:** work-end/*.py inventory (17 scripts), issue #271 audit evidence
**Exploration:** quick
**Status:** revised (R1-09: acknowledged new failure surface — risk shifts from LLM skip to orchestrator mis-sequence, requiring dedicated test suite)

## D11: Forward-only Execute — no rollback

**Choice:** Post-promotion states are forward-only. The lifecycle state machine rejects `abort_close` from `closing:promoted` onward. Partial Execute failures (e.g., push succeeds but stamp fails) are recovered by retrying the failed step forward, not by rolling back completed steps.
**Alternatives:**
- Rollback capability for partial Execute — more dangerous than forward completion; rolling back a pushed commit requires force-push to shared remotes
- Allow abort from any closing state — artifacts already promoted to destination repos would become orphaned; pushed content can't be safely retracted
**Rationale:** Partial rollback of pushed content is more dangerous than forward completion. `verify_slot_close.py` detects incomplete forward progress (unpushed, unstamped, unmerged). `.execute-progress` enables retry from the last completed sub-step. Forward-only is the standard pattern for distributed commit protocols (prepare → commit, never rollback after commit). The lifecycle transition table enforces this: `abort_close` is valid only from `closing:review` and `closing:verified`.
**Trade-offs:** A forward-only design cannot recover from a fundamentally broken state (e.g., remote repository deleted mid-push). These scenarios require manual intervention regardless of design choice.
**Sources:** lifecycle.py transition table (INVALID_MESSAGES for abort from promoted/pushed/merged/stamped), SKILL.md "Post-promotion states are forward-only"
**Exploration:** quick (implicit decision surfaced by reviewer, now explicit)
**Status:** captured

## D12: Concurrent session protection — lifecycle state machine

**Choice:** Concurrent session protection is provided by the lifecycle state machine's compare-and-swap pattern in `commit_transition()`. The `.close-progress` file has no independent locking mechanism because it doesn't need one — lifecycle serialises access.
**Alternatives:**
- Advisory lock via `fcntl.flock()` on `.close-progress` — adds complexity and platform-specific behaviour for a scenario already prevented by lifecycle
- PID-stamped progress file detecting stale ownership — adds staleness detection complexity for marginal benefit
- No protection — concurrent sessions could corrupt progress state
**Rationale:** `commit_transition()` reads the current state and raises `ConcurrentModification` if it has changed since `transition()`. If session A is driving the close (e.g., state `closing:review`), session B's `work_end` event fails because there is no `(closing:review, work_end)` transition in the table. If both sessions somehow read the same closing state, the second `commit_transition()` finds the state already advanced and raises `ConcurrentModification`. The TOCTOU window between read and write in `commit_transition()` is sub-millisecond on a single machine — acceptable for a single-developer tool.
**Trade-offs:** The TOCTOU window is theoretically present but practically negligible. A multi-machine deployment would need distributed locking, but the platform targets single-developer single-machine use.
**Sources:** lifecycle.py `commit_transition()` (ConcurrentModification exception), DIRTY-TREE-PROTOCOL in SKILL.md ("dirty files may belong to another session")
**Exploration:** quick (implicit decision surfaced by reviewer, now explicit)
**Status:** captured

## D13: Mechanical wiring specification format

**Choice:** Step definition tables — structured block per step with exact CLI invocation, output keys, success/failure criteria, evidence construction, mode routing, and progress key
**Alternatives:**
- Pseudocode per step — more precise but risks becoming a second implementation that diverges from the actual code
- Executable spec (Python dataclass definitions) — clever but couples spec to runtime, premature
**Rationale:** Tables are precise enough to prevent stubs (the exact failure mode from #275), auditable enough to verify completeness (greppable, every step must have all fields), and decoupled enough from code to remain a stable reference. The prior spec's prose descriptions ("orchestrator calls promote") left room for stub implementations.
**Trade-offs:** Tables are verbose — one block per step across ~25 steps is substantial. Acceptable because the alternative (prose ambiguity) caused the revert.
**Sources:** Issue #275 (stubbed steps evidence), prior spec design.md (prose descriptions that didn't prevent stubs)
**Exploration:** quick
**Status:** captured

## D14: Capability audit approach

**Choice:** Exhaustive capability matrix in the spec — walk every section of the current SKILL.md, extract every discrete capability, map each to orchestrator step / SKILL.md action handler / dropped (with justification). Matrix serves as implementation checklist and post-deployment audit artifact.
**Alternatives:**
- Diff-based audit at the end — text diffs can't catch behavioral capabilities (ordering constraints, mode-specific behavior) spread across multiple sections
- Test-based verification — most rigorous at runtime but requires implementation to exist first; doesn't prevent gaps during spec writing
**Rationale:** The matrix is the spec's primary defense against capability loss. Written before implementation, it catches gaps early. Capabilities aren't lines of text — they're behaviors. Only an explicit enumeration can guarantee coverage.
**Trade-offs:** Extracting capabilities from a 662-line SKILL.md is labor-intensive. Acceptable because the user's hard requirement is "no loss of capabilities."
**Sources:** Current work-end/SKILL.md (662 lines), user requirement ("no loss of capabilities, post-audit")
**Exploration:** quick
**Status:** captured

## D15: Cross-session state recovery

**Choice:** Evidence-based reconstruction on every start — every orchestrator invocation begins with a reconciliation pass. For each step marked "done" in .close-progress, check mechanical evidence (file exists, git state, remote state, issue state). If evidence contradicts progress, correct the file and report corrections. ~10 evidence checks, each a fast local operation (<2s total).
**Alternatives:**
- Trust progress file, verify only on explicit recover=yes — faster but resumes from false position silently (the exact failure mode #275 identified)
- Delete progress file every start, re-derive from evidence — most robust but expensive (network calls for late-stage checks) and loses retry attempt counts
**Rationale:** Balances correctness (evidence-checked) with efficiency (fast local checks) and preserves retry state. The reconciliation report gives visibility into corrections before continuing.
**Trade-offs:** Adds ~2s startup overhead per orchestrator invocation. Acceptable — the orchestrator is called ~15-20 times per close sequence, adding ~30-40s total across a multi-minute process.
**Sources:** Issue #275 (recovery scenarios table, evidence checks table), lifecycle.py commit-transition CAS pattern
**Exploration:** quick
**Status:** captured

## D16: SKILL.md action handler detail level

**Choice:** Verbatim extraction with mapping — the spec extracts every judgment instruction from the current SKILL.md and maps it to its target action handler. The spec says "the review action handler contains THESE exact instructions." The implementer copies, doesn't summarize.
**Alternatives:**
- Topic-level specification — says "handler covers: security-audit suppression, budget limits..." but implementer writes content. Risk: missed nuances or rephrased behavior.
- Reference-only — says "extract from current SKILL.md lines 170-280." Lightest but requires implementer to parse 662 lines and decide relevance.
**Rationale:** The prior implementation proved that leaving content decisions to the implementer results in incomplete work. Verbatim extraction removes judgment from the step that went wrong last time. This is D14 (capability matrix) applied to LLM-facing content.
**Trade-offs:** The spec will be longer — including verbatim SKILL.md content adds ~200 lines. Acceptable because completeness is the explicit goal.
**Sources:** Current work-end/SKILL.md (judgment instructions in Steps 2-6), revert commit ("stubs all mechanical steps"), D14 (capability audit approach)
**Depends on:** D14 (capability audit)
**Exploration:** quick
**Status:** captured

## D17: Rollout strategy

**Choice:** Shadow mode with fallback — the new SKILL.md keeps old step-by-step instructions as a hidden fallback section. Dispatch loop is primary path. If orchestrator returns error or unexpected output, LLM falls back to old instructions for that step. Once all steps verified, a follow-up commit removes the fallback. SKILL.md is always deployable.
**Alternatives:**
- Big bang cutover — wire everything, swap in one commit. Requires complete orchestrator before any of it is used. High risk — the implementer may think "everything" is done when it isn't (exactly what happened with #275).
- Incremental promotion per step — wire one step at a time, update SKILL.md per commit. Safest but creates long series of SKILL.md edits with complex merge potential.
**Rationale:** Shadow mode means no capability loss even with an incomplete orchestrator. The fallback is explicitly temporary — the spec includes "remove fallback" as the final task. This directly addresses the revert scenario: if the orchestrator stubs a step, the LLM executes it via the fallback path instead of skipping it.
**Trade-offs:** The SKILL.md is temporarily larger (dispatch loop + fallback instructions). The fallback may mask orchestrator bugs during testing — mitigated by the post-deployment audit which verifies the orchestrator path was taken, not the fallback.
**Sources:** Revert commit 151b7a8 ("stubs all mechanical steps"), issue #275 (scope of missing wiring)
**Exploration:** quick
**Status:** captured

## D18: Post-deployment audit design

**Choice:** Scripted dry-run audit — a Python script (audit_work_end.py) runs the orchestrator in dry_run=yes mode against synthetic workspaces for each mode (branch, slot, main). Checks: every step reached, every script call has correct arguments, every lifecycle transition fires with valid evidence, every capability from D14 matrix exercised. Output is PASS/FAIL per capability. Runnable after every implementation commit.
**Alternatives:**
- Manual audit checklist — markdown checklist worked through by hand. Thorough but manual, error-prone, not repeatable.
- Real work-end runs across test repos — most realistic but expensive to set up and maintain.
**Rationale:** A scripted dry-run is repeatable, fast, and integrates into the development loop. D14 capability matrix provides the checklist — the script mechanically verifies each row. Real runs are valuable as a final smoke test but not the primary audit mechanism.
**Trade-offs:** Dry-run mode must be implemented in the orchestrator (extra code path). Mitigated by making dry_run a thin wrapper that captures calls without executing them — same pattern as test mocking.
**Depends on:** D14 (capability audit matrix provides the checklist)
**Sources:** User requirement ("post audit for this, to be sure"), D14 (capability matrix)
**Exploration:** quick
**Status:** captured

## D17: Rollout strategy (REVISED — R1-02, R1-17)

**Choice:** Shadow mode with fallback AND explicit fallback telemetry. When the orchestrator returns an error and the LLM falls back to old instructions, it emits `FALLBACK_TRIGGERED=<step>` as a structured marker before executing the fallback path. The post-deployment audit greps for FALLBACK_TRIGGERED across real closes. Zero triggers after N closes = evidence-based fallback removal. Non-zero triggers = identifies exactly which steps need fixing.
**Revision:** Original D17 had silent fallback — no way to distinguish "orchestrator ran" from "LLM fell back." The fallback would mask orchestrator bugs (the exact pattern from the first implementation where stubs passed tests). Adding the marker makes the fallback observable and the removal decision evidence-based.
**Status:** revised (R1-02: fallback telemetry added to close the observability gap)

## D15: Cross-session state recovery (REVISED — R1-04)

**Choice:** Two-tier evidence reconciliation. Local-only checks (file existence, git state, progress file consistency) run on every orchestrator invocation (<1s). Network-dependent checks (gh issue view, git ls-remote for remote SHA verification) run ONCE on the first invocation of a close sequence only, then cache results in .close-progress.
**Revision:** Original D15 claimed "<2s all-local" but the evidence check table includes gh issue view (1-3s per issue, network-dependent) and remote state verification (git ls-remote). Running these on every invocation across 15-20 calls would add minutes. Two-tier split: local checks are cheap and run always; network checks run once and cache.
**Status:** revised (R1-04: local/network split with caching)

## D14: Capability audit approach (REVISED — R1-12)

**Choice:** Exhaustive capability matrix pinned to a specific SKILL.md git SHA. The spec records the SHA. Before implementation begins, the implementer diffs the current SKILL.md against the pinned SHA. Any new capabilities since the pin are added to the matrix before proceeding. The "no loss of capabilities" guarantee covers the SKILL.md at implementation time, not just at spec time.
**Revision:** Original D14 assumed the SKILL.md is stable between spec writing and implementation. The SKILL.md is continuously refined — new capabilities (notes 6.8, garden feedback 6.6, trajectory 4.1b) could appear between spec and implementation. Pinning to SHA + diff eliminates the temporal drift window.
**Status:** revised (R1-12: SHA pinning + diff-before-implementation gate)
