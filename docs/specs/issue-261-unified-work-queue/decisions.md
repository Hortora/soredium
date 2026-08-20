# Decisions — #261 Unified Work Queue

## D1: Bidirectional chaining direction

**Choice:** Commands chain both forward (fallthrough) and backward (guard)
**Alternatives:**
- Forward-only chaining — simpler but allows skipping unfinished work
- No chaining (current) — commands error in wrong context, user must know the right one
**Rationale:** Ensures no matter which command is invoked, the user lands at the right place. Forward prevents dead ends, backward prevents skipping.
**Trade-offs:** More complex routing logic, but implemented in Python so it's testable
**Sources:** Conversation with user, current work/SKILL.md routing table
**Exploration:** deep-analysis
**Status:** captured

## D2: .plan on main

**Choice:** Allow .plan files on main, with the same queue semantics as branches
**Alternatives:**
- Branch-only .plan (current) — main has ad-hoc what-next via enrichment.py
- Separate main-queue mechanism — different format/logic for main vs branch
**Rationale:** Unifies queue semantics. Same commands work identically regardless of context. Eliminates the branch/main routing split.
**Trade-offs:** .plan lifecycle on main is different (no merge/stamp at close)
**Sources:** lifecycle.py audit, ctx.py audit, conversation
**Exploration:** deep-analysis
**Status:** captured

## D3: Chaining logic in Python, not LLM

**Choice:** All mechanical chaining decisions (forward/backward routing, guards, state checks) implemented in Python
**Alternatives:**
- LLM-driven routing (current) — skill instructions tell Claude what to check
- Hybrid — some checks in Python, some in skill
**Rationale:** Python is deterministic, testable, doesn't hallucinate. The LLM reads directives and executes them.
**Trade-offs:** More Python code to maintain, but dramatically more reliable
**Sources:** User directive, evidence-before-claims protocol
**Exploration:** quick
**Status:** captured
**Depends on:** D1 (chaining design determines what the Python needs to implement)

## D4: New `drained` state in lifecycle

**Choice:** Add `drained` state (renamed from `ended` per R1-02) — queue empty, ceremony done, .plan persists, can transition back to `active` via `work find`
**Alternatives:**
- `ended` — collides with worklog `ended` semantics (permanent branch close via `idle → ended` mapping)
- Reuse `idle` — but idle means "no .plan exists"
- Delete .plan after end — but then we lose queue history and can't chain to find
**Rationale:** `drained` is semantically precise (queue is empty, waiting for refill) and avoids the worklog collision. The `drained → transitioning → active` path via `work_find` reuses existing context-loading infrastructure.
**Trade-offs:** One more state in the machine, but semantically clean
**Sources:** lifecycle.py audit, R1-02 review finding
**Exploration:** deep-analysis
**Status:** revised (renamed from `ended` to `drained`)
**Depends on:** D2 (.plan on main requires a state for "done but plan persists")

## D5: work-end on main

**Choice:** work-end works on main with same ceremony minus merge/stamp
**Alternatives:**
- Branch-only work-end (current) — requires a branch to close
- Separate main-close command — different ceremony for main
**Rationale:** Unifies the close experience. Closing issues, updating docs, creating blogs are not branch-specific. Only merge/stamp are branch-specific.
**Trade-offs:** work-end becomes context-aware (branch mode vs main mode). Several steps become conditional.
**Sources:** work-end/SKILL.md audit — 12 touchpoints identified
**Exploration:** deep-analysis
**Status:** captured
**Depends on:** D4 (main needs `drained` state since there's no branch to stamp)

## D6: `work find` as new verb

**Choice:** Add `work find` as a discovery/population command, separate from queue execution
**Alternatives:**
- Keep enrichment/what-next inline in `work` routing (current Step 2a)
- Auto-populate queue on every `work` invocation
**Rationale:** Separates "execute the queue" from "populate the queue." Clean chain terminal: end → find discovers new work and appends to .plan.
**Trade-offs:** One more verb to learn, but the chain means you're naturally guided to it
**Sources:** Conversation, current Step 2a logic
**Exploration:** quick
**Status:** captured

## D7: Corruption recovery in Python

**Choice:** Python-based triage that detects inconsistencies and outputs resolution directives
**Alternatives:**
- LLM-driven triage (current) — CorruptedState exception, LLM figures it out
- Hard fail on corruption — stop and require manual intervention
**Rationale:** Python can check state against reality (GitHub issue status, git branch existence, uncommitted changes) and propose specific resolutions. The LLM presents the resolution to the user.
**Trade-offs:** Need to enumerate corruption scenarios, but they're finite and testable
**Sources:** lifecycle.py audit — 5 exception types, stale .plan on main encountered this session
**Exploration:** deep-analysis
**Status:** captured
**Depends on:** D3 (Python-driven routing is the foundation for Python-driven recovery)

## D8: No self-transitions for routing (R1-03)

**Choice:** Router reads state directly and emits directives — no round-trip through state machine for chaining decisions
**Alternatives:**
- Self-transitions in transition table — `(drained, work_continue) → drained` with no effects
**Rationale:** Self-transitions with zero effects violate the state machine's design principle. Routing decisions belong in `work_chain.py`. State machine events are reserved for actual state changes.
**Trade-offs:** Routing logic and state machine are separate concerns — cleaner separation but two modules to maintain
**Sources:** R1-03 review finding, lifecycle.py:8 design principle
**Exploration:** quick
**Status:** captured
**Depends on:** D3 (chaining in Python), D4 (drained state)

## D9: Diff base via drained-sha (R1-06)

**Choice:** Store `drained-sha: <HEAD>` in `.plan`'s `## State` when entering `drained` state
**Alternatives:**
- Git tags — adds ceremony and namespace pollution
- Timestamp-based — imprecise, doesn't map to git history
**Rationale:** SHA is exact, cheap to store, cheap to diff against. Written by `write_plan_drained` effect. First close with no prior SHA falls back to `project-sha:` field.
**Trade-offs:** One more field in .plan state, but existing consumers (ctx.py, plan_manager) ignore unknown fields
**Sources:** R1-06 review finding
**Exploration:** quick
**Status:** captured
**Depends on:** D4 (drained state triggers the write)

## D10: Corruption recovery is separate issue (R1-14)

**Choice:** Extract corruption recovery (§7 from original spec) into a follow-up issue
**Alternatives:**
- Bundle with this issue — all-in-one delivery
**Rationale:** 8 distinct scenarios with detection/resolution/output is a full protocol. Bundling dilutes focus and makes review harder. The unified work queue can ship without it.
**Trade-offs:** Corruption recovery ships later, but the new states it needs (drained) exist first
**Sources:** R1-14 review finding
**Exploration:** quick
**Status:** captured
