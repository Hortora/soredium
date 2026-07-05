# ADR Four-Phase Review Pipeline

## Problem

The adversarial design review tool currently handles one phase: spec review.
The full lifecycle from brainstorming to implementation has review gaps at
every other stage. Separate tools (code-review skill, superpowers) partially
cover final code review, but with single-pass approaches that miss what
multi-round adversarial review catches.

The evidence from production use is clear: spec review alone caught real
bugs (P-256 sign selection, alsoKnownAs population, faultFeedback guard),
but only at the spec level. Implementation divergence from the reviewed
spec is undetected. And some specs go through 10 rounds of detailed review
only to discover the fundamental approach was wrong — effort that a
lightweight pre-review would have caught early.

## Proposal

Extend the ADR tool from one review mode to four, covering the full
design-to-implementation lifecycle. Same PM core, same state machine,
same evidence-based confirmation model, same tracker format. Different
reviewer briefs, round counts, and artifacts per phase.

### The four phases

| Phase | Question | Artifact under review | Rounds | When |
|-------|----------|-----------------------|--------|------|
| 1. Pre-review | Is this the best approach? | Brainstorming output / outline | 2–3 | After brainstorming, before detailed spec |
| 2. Spec review | Is this spec correct and complete? | Design spec | 4–10 | After detailed spec written |
| 3. Code review | Does the implementation match the spec? | Source code + reviewed spec | 2–4 | After implementation, before merge |
| 4. Final review | Is the code production-ready? | Source code | 2–3 | After code review passes, final gate |

### Relationship to superpowers

Superpowers and ADR phases are complementary layers, not competing tools:

| Superpowers step | ADR phase | Relationship |
|------------------|-----------|-------------|
| Brainstorming | → Pre-review | Brainstorming generates the approach, pre-review challenges it |
| Writing plans | (none) | No overlap — ADR doesn't produce implementation plans |
| TDD + implementation | (none) | No overlap — ADR doesn't write code |
| Code review (quick) | → Code review + Final review | Superpowers does a single-pass quick check. ADR does multi-round adversarial review. They layer: superpowers catches obvious issues first, ADR catches deep ones after. |

The superpowers skills have been integrated as first-party soredium
citizens (epic #68). `requesting-code-review` is now a soredium skill
with Skill Chaining to `subagent-driven-development` and `work-end`.
ADR phases 3-4 are a heavier gate that runs separately when the user
explicitly asks for it. When #66 lands, it replaces the improved
`requesting-code-review` with ADR-style multi-round review.

**Future direction:** Brainstorming itself may evolve into a structured debate
tool — each design question gets its own file and a mini adversarial debate
(reviewer/implementor) to find the best answer. The output would be per-question
debate artifacts rather than a conversation blob, feeding naturally into
pre-review with a full evidence trail. See `~/adr/IDEAS.md` §
"Fork superpowers:brainstorming into structured design debates".

## Workspace structure

### Current (single-phase, flat)

```
~/adr/{project}/{title}-{timestamp}/
  context.md
  tracker.md
  .spec-path
  .source-dirs
  progress.log
  responses/
    reviewer-1.md
    implementor-1.md
  agents/
    reviewer/CLAUDE.md
    implementor/CLAUDE.md
  decisions/
  handovers/
```

### Proposed (multi-phase, hierarchical)

One workspace per review engagement. One subfolder per phase.

```
~/adr/{project}/{title}-{timestamp}/
  .spec-path                         ← shared: the artifact being reviewed
  .source-dirs                       ← shared: project directories
  .issue                             ← shared: GitHub issue reference
  .phases                            ← which phases are enabled (one per line)
  progress.log                       ← shared: cross-phase progress log
  context.md                         ← shared: project sources, structured output format
  spec.md                            ← symlink to the spec

  pre-review/                        ← phase 1
    .mode                            ← "pre-review"
    .status                          ← current phase status: pending|running|done|skipped
    tracker.md                       ← phase-specific tracker
    responses/
      reviewer-1.md
      implementor-1.md
    agents/
      reviewer/CLAUDE.md             ← approach reviewer constraints
      implementor/CLAUDE.md          ← approach author constraints
    decisions/
    handovers/

  spec-review/                       ← phase 2
    .mode
    .status
    tracker.md
    responses/
    agents/
      reviewer/CLAUDE.md             ← adversarial spec reviewer constraints
      implementor/CLAUDE.md          ← spec implementor constraints
    decisions/
    handovers/

  code-review/                       ← phase 3
    .mode
    .status
    tracker.md
    responses/
    agents/
      reviewer/CLAUDE.md             ← spec-vs-code reviewer constraints
      implementor/CLAUDE.md          ← developer constraints
    decisions/
    handovers/

  final-review/                      ← phase 4
    .mode
    .status
    tracker.md
    responses/
    agents/
      reviewer/CLAUDE.md             ← production-readiness reviewer constraints
      implementor/CLAUDE.md          ← developer constraints
    decisions/
    handovers/
```

### Design rationale

**Why subfolders, not separate workspaces?** Phases share context — the spec
path, source directories, issue reference. A single workspace keeps them
together and avoids duplicating shared state. The progress log is shared so
`tail -f` shows the entire review lifecycle in one stream.

**Why per-phase trackers?** Each phase tracks different concerns at different
granularity. Pre-review tracks approach-level challenges. Spec review tracks
section-level issues. Code review tracks implementation gaps. Mixing them in
one tracker would conflate severity levels and make convergence detection
unreliable.

**Why per-phase agents?** The CLAUDE.mds are the hardest-to-get-right part of
the system (8 iterations to get spec review right). Each phase needs different
reviewer briefs — what to look for, what severity threshold to apply, what
"done" means. Sharing one CLAUDE.md across phases would force compromises
that degrade every phase.

## Phase lifecycle

### Phase status

Each phase has a `.status` file: `pending` → `running` → `done` (or `skipped`).

### Phase selection (SKILL.md UX)

When the user invokes `/design-review`, present a phase checklist:

```
Review phases — toggle to select:

[ ] 1  Pre-review     Approach validation (2-3 rounds, lightweight)
[x] 2  Spec review    Full adversarial review (4-10 rounds)
[ ] 3  Code review    Implementation vs reviewed spec
[ ] 4  Final review   Production-readiness check

Type numbers to toggle, "go" to proceed:
```

**Defaults:**
- "design review" / "review this spec" → spec review only (phase 2). Skip the
  checklist entirely — current behavior preserved.
- "pre-review this" / "validate the approach" → pre-review only (phase 1).
- User explicitly mentions phases or asks to choose → show checklist.

**`.phases` file:** Stores enabled phases (one per line). Written at workspace
creation. The PM reads this to know which phases to run and in what order.

### Phase chaining

Selected phases run in sequence. Between phases, the PM:

1. Writes the phase's final status (`done`)
2. Logs a phase completion summary to `progress.log`
3. Sends a desktop notification
4. Pauses for user confirmation before starting the next phase

The pause is important: after pre-review the user may want to revise the spec
before spec review begins. After code review they may want to fix issues
before final review. The PM does not auto-advance.

### Phase resume

Resume works at two levels:

1. **Resume a phase** — `--workspace {ws} --phase spec-review` resumes the
   spec-review phase mid-round (same as current `--workspace` behavior but
   scoped to the phase subfolder).
2. **Resume the pipeline** — `--workspace {ws}` with no `--phase` finds the
   first non-done enabled phase and resumes it.

### Backward compatibility

The current `--mode spec-review` (or no `--mode`) with a flat workspace
continues to work. The PM detects the workspace format:

- If `{ws}/spec-review/` exists → hierarchical workspace, use phase subfolders
- If `{ws}/responses/` exists at root → legacy flat workspace, behave as today

No migration needed. Old workspaces resume as they always have.

## The PM (manager)

### Current responsibilities (unchanged)

- Parse structured output from both agents
- Maintain state machine per issue (OPEN → ADDRESSED → VERIFIED, etc.)
- Write `tracker.md` from parsed structured output
- Detect premature convergence
- Commit review artifacts to the ADR repo
- Commit spec changes to the project repo
- Handle timeouts (soft 600s / hard 1800s)
- Handle HIL pauses and DECISION_NEEDED escalations
- Desktop notifications

### New responsibilities

- **Phase orchestration** — read `.phases`, run enabled phases in order,
  manage inter-phase pauses
- **Cross-phase progress** — log phase transitions to `progress.log`,
  track overall status (which phases done, which pending)
- **Phase-specific defaults** — apply the right round counts, budget,
  effort level per phase
- **Phase-specific setup** — generate the right CLAUDE.mds per phase

### Phase-specific defaults

| Setting | Pre-review | Spec review | Code review | Final review |
|---------|-----------|-------------|-------------|-------------|
| `max_rounds` | 3 | 10 | 4 | 3 |
| `min_rounds` | 2 | 4 | 2 | 2 |
| `budget_per_session` | $3 | $5 | $5 | $5 |
| `effort` (round 1–3) | high | high | high | high |
| `effort` (round 4+) | — | xhigh | xhigh | — |

## Agent CLAUDE.mds per phase

Each phase has its own reviewer and implementor CLAUDE.md, assembled from
the composable constraint system in `setup.py`. The existing system uses
14 shared constant strings (`_CORE_APPROACH_REVIEWER`, `_INTELLIJ_OPEN`,
`_NARRATION`, etc.) assembled per role by `_assemble_constraints()`. Each
phase picks the shared elements it needs and adds phase-specific ones.

This is proven — the spec review constraints took 8 iterations to get right,
and the composable approach was what made it manageable. See `setup.py` and
`~/adr/2026-06-28-mdp-adversarial-review-prompt-engineering.md` for the
full history.

### Shared constraints (all phases)

Infrastructure constraints reused across every phase — existing constants:

| Constant | Purpose |
|----------|---------|
| `_INTELLIJ_OPEN` | Open project via `ide_open_project`, not workspace |
| `_INTELLIJ_USE` | Use IntelliJ index MCP for navigation, never bash |
| `_NARRATION` | Write status to `.status` file for progress monitoring |
| `_ARCH_DOCS` | ARC42STORIES, PLATFORM.md, APPLICATIONS.md |
| `_SPECS_AND_ADRS` | Prior specs, ADRs, research in docs/ folders |
| `_DIARIES` | Published diaries with architectural decisions |
| `_GIT_ISSUES` | `git log`, `git blame`, `gh issue view` |
| `_INTERNET` | Search when information is insufficient |
| `_NO_END_USERS` | No end users — prefer fixing design over protecting callers |
| `_DESIGN_QUALITY` | Quality over cost, no workarounds, no backward-compat shims |
| `_DEFERRED_ITEMS` | Deferred concerns must be captured as GitHub issues |

### Phase-specific constraints

Each phase adds its own core approach, starting points, and role-specific
constants. New constants are added to `setup.py` alongside the existing ones.

### Phase 1: Pre-review

**Reviewer assembly:**
- `_PRE_REVIEW_APPROACH_REVIEWER` — challenge the approach, not details (NEW)
- `_PRE_REVIEW_STARTING_POINTS` — simpler alternatives, trajectory, patterns, scope (NEW)
- Shared: IntelliJ, narration, context sources, design philosophy

**Implementor assembly:**
- `_PRE_REVIEW_APPROACH_IMPLEMENTOR` — defend or pivot the approach (NEW)
- `_PRE_REVIEW_IMPLEMENTOR_SKEPTICISM` — verify alternatives are genuinely better (NEW)
- Shared: IntelliJ, narration, context sources, design philosophy
- `_IMPLEMENTOR_STAND_GROUND` — existing, reused

**Reviewer role: Approach Reviewer**

Challenge the approach, not the details. The artifact may be an outline
or early draft. Focus on whether this is the right way to solve the problem.

**Implementor role: Approach Author**

Defend the approach where it's sound, pivot where the reviewer raises a
genuine concern. The goal is to commit to the right approach before
investing in detailed spec writing.

### Phase 2: Spec review (current)

**Reviewer assembly:**
- `_CORE_APPROACH_REVIEWER` — existing
- `_TODO_CHECK` — existing
- `_REVIEWER_STARTING_POINTS` — existing
- `_DEFERRED_ITEMS` — existing
- Shared: IntelliJ, narration, context sources, design philosophy

**Implementor assembly:**
- `_CORE_APPROACH_IMPLEMENTOR` — existing
- `_IMPLEMENTOR_SKEPTICISM` — existing
- `_DEFERRED_ITEMS` — existing
- Shared: IntelliJ, narration, context sources, design philosophy
- `_IMPLEMENTOR_STAND_GROUND` — existing

No changes — this is the current proven configuration.

### Phase 3: Code review against spec

**Reviewer assembly:**
- `_CODE_REVIEW_APPROACH_REVIEWER` — check implementation against reviewed spec (NEW)
- `_CODE_REVIEW_STARTING_POINTS` — spec promises vs code reality, scope creep (NEW)
- `_TODO_CHECK` — existing, reused
- Shared: IntelliJ, narration, context sources, design philosophy

**Implementor assembly:**
- `_CODE_REVIEW_APPROACH_IMPLEMENTOR` — fix divergence or update spec (NEW)
- `_IMPLEMENTOR_SKEPTICISM` — existing, reused
- Shared: IntelliJ, narration, context sources, design philosophy
- `_IMPLEMENTOR_STAND_GROUND` — existing, reused

**Reviewer role: Spec Compliance Reviewer**

Read the reviewed spec and the implementation. Check whether the
implementation delivers what the spec promised.

**Implementor role: Developer**

Fix code where the reviewer found genuine spec divergence. Update the spec
if the code reveals a gap that should be acknowledged.

### Phase 4: Final code review

**Reviewer assembly:**
- `_FINAL_REVIEW_APPROACH_REVIEWER` — production readiness (NEW)
- `_FINAL_REVIEW_STARTING_POINTS` — architecture, correctness, perf, security, tests (NEW)
- `_TODO_CHECK` — existing, reused
- Shared: IntelliJ, narration, context sources, design philosophy

**Implementor assembly:**
- `_FINAL_REVIEW_APPROACH_IMPLEMENTOR` — fix code issues, final gate (NEW)
- `_IMPLEMENTOR_SKEPTICISM` — existing, reused
- Shared: IntelliJ, narration, context sources, design philosophy
- `_IMPLEMENTOR_STAND_GROUND` — existing, reused

**Reviewer role: Production Readiness Reviewer**

Full code review — architecture, correctness, edge cases, error handling,
performance, concurrency, security, naming, structure, layer compliance.
Also reviews test code: coverage, assertion quality, missing scenarios,
test isolation.

**Implementor role: Developer**

Fix code issues. This is the final gate before merge.

### Constraint inventory summary

| Constant | Pre-review | Spec review | Code review | Final review |
|----------|:---:|:---:|:---:|:---:|
| `_INTELLIJ_OPEN` | R+I | R+I | R+I | R+I |
| `_INTELLIJ_USE` | R+I | R+I | R+I | R+I |
| `_NARRATION` | R+I | R+I | R+I | R+I |
| `_ARCH_DOCS` | R+I | R+I | R+I | R+I |
| `_SPECS_AND_ADRS` | R+I | R+I | R+I | R+I |
| `_DIARIES` | R+I | R+I | R+I | R+I |
| `_GIT_ISSUES` | R+I | R+I | R+I | R+I |
| `_INTERNET` | R+I | R+I | R+I | R+I |
| `_NO_END_USERS` | R+I | R+I | R+I | R+I |
| `_DESIGN_QUALITY` | R+I | R+I | R+I | R+I |
| `_DEFERRED_ITEMS` | — | R+I | — | — |
| `_TODO_CHECK` | — | R | R | R |
| `_CORE_APPROACH_REVIEWER` | — | R | — | — |
| `_CORE_APPROACH_IMPLEMENTOR` | — | I | — | — |
| `_REVIEWER_STARTING_POINTS` | — | R | — | — |
| `_IMPLEMENTOR_SKEPTICISM` | — | I | I | I |
| `_IMPLEMENTOR_STAND_GROUND` | I | I | I | I |
| `_PRE_REVIEW_APPROACH_REVIEWER` | R | — | — | — |
| `_PRE_REVIEW_STARTING_POINTS` | R | — | — | — |
| `_PRE_REVIEW_APPROACH_IMPLEMENTOR` | I | — | — | — |
| `_PRE_REVIEW_IMPLEMENTOR_SKEPTICISM` | I | — | — | — |
| `_CODE_REVIEW_APPROACH_REVIEWER` | — | — | R | — |
| `_CODE_REVIEW_STARTING_POINTS` | — | — | R | — |
| `_CODE_REVIEW_APPROACH_IMPLEMENTOR` | — | — | I | — |
| `_FINAL_REVIEW_APPROACH_REVIEWER` | — | — | — | R |
| `_FINAL_REVIEW_STARTING_POINTS` | — | — | — | R |
| `_FINAL_REVIEW_APPROACH_IMPLEMENTOR` | — | — | — | I |

R = reviewer, I = implementor, R+I = both

## Implementation plan

### Phase 1: Pre-review (#64)

1. Add `--mode` parameter to `review.py` CLI
2. Add `--phase` parameter for hierarchical workspace phase targeting
3. Workspace format detection (hierarchical vs legacy flat)
4. Phase subfolder setup in `setup.py`
5. Pre-review constraint elements and assembly in `setup.py`
6. Pre-review prompt variants in `prompts.py`
7. Phase status management (`.status` files)
8. Phase selection logic in SKILL.md (with defaults that preserve current UX)
9. `.phases` file read/write
10. Cross-phase progress logging
11. Inter-phase pause (user confirmation before advancing)
12. Tests for all of the above

### Phase 2: Code review against spec (#65)

Blocked by #64. Requires:
- `--code-dir` or `--diff-base` parameter (code review operates on code, not spec)
- Code review constraint elements
- Code review prompt variants
- Spec-to-code alignment checking logic

### Phase 3: Final code review (#66)

Blocked by #64, #65. Requires:
- Final review constraint elements (production readiness)
- Test review sub-phase (4a main code, 4b test code)
- Migration path from existing `code-review` skill
- Migration path from `superpowers:requesting-code-review`

## Open questions

1. **Shared vs separate context.md** — should each phase have its own
   context.md or share one? The structured output format is the same across
   phases, but the "what you're reviewing" framing differs.

2. **Cross-phase issue references** — if pre-review raises R1-03 "approach
   doesn't handle failure X" and spec review later finds the same gap, should
   the spec review tracker reference the pre-review finding? Or are they
   independent?

3. **Model selection per phase** — should pre-review use Sonnet (lighter
   reasoning) while spec review uses Opus? Or is approach validation
   actually harder than it looks?

4. **Phase 4 sub-phases** — the starting spec proposed 4a (main code) and
   4b (test code) as separate sub-phases with their own rounds. Is this
   worth the complexity, or should they be one phase where the reviewer
   naturally covers both?

5. **adr-status.py** — currently derives status from a flat workspace.
   Needs updating for hierarchical workspaces. Should it show per-phase
   status or just overall status?
