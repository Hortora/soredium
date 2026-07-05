# Alignment and Unification Audit: Superpowers + Soredium

**Date:** 2026-07-05
**Issue:** Hortora/soredium#78

## Verdict

No structural merges needed. The skills are genuinely distinct. The problems
are routing clarity, missing cross-references, and one skill (fix-ci) that
claims to be part of a toolkit but operates as an island.

## Area 1: Review Pipeline Overlap

**Skills:** code-review, requesting-code-review, design-review

### Current state

| Skill | Mechanism | Scope | When | Duration |
|-------|-----------|-------|------|----------|
| code-review | In-session, language checklist | Staged changes | Every commit | Seconds |
| requesting-code-review | Fresh subagent | Feature branch | After significant work | Minutes |
| design-review | External orchestration (2 claude -p sessions) | Design spec | User-invoked | 10-30 min |

Clean separation. Only friction is routing clarity and the Phase 4 replacement plan.

### Findings

1. **Frontmatter ambiguity.** "Review this" could route to either code-review
   or requesting-code-review. Fix: make descriptions explicit about scope
   ("staged changes" vs "feature branch").

2. **Language checklist gap in subagent path.** requesting-code-review's
   template tells the subagent to apply language-specific checklists but
   doesn't include the checklist content. The subagent has no access to
   `~/.claude/skills/code-review/java.md`.

3. **Double review on SDD→work-end path.** SDD runs requesting-code-review
   (branch review), then work-end runs code-review (same diff, lesser depth).
   No deduplication.

4. **Phase 4 spec says "replaces code-review + requesting-code-review" but
   also says "they layer."** Replacing the fast checklist with a 10-minute
   external process breaks every commit workflow. Phase 4 should replace
   requesting-code-review only; code-review survives as the fast gate.

### Recommendations

- Fix frontmatter descriptions (zero effort, high clarity)
- Wire language checklists into the subagent prompt template
- Revise Phase 4 spec: replaces requesting-code-review, not code-review
- Defer SDD→work-end deduplication until Phase 4 lands

## Area 2: Execution Pipeline vs Work Lifecycle

**Skills:** writing-plans, SDD, executing-plans, work-start, work-end

### Current state

Two orthogonal pipelines sharing work-end as terminal node:
- **Work lifecycle:** work → work-start → [user works] → work-end
- **Execution pipeline:** writing-plans → SDD/executing-plans → work-end

### Findings

1. **Missing link: brainstorming → writing-plans.** work-start offers
   brainstorming (Step 12) but doesn't mention writing-plans. The intended
   chain (brainstorm → plan → execute) has an implicit middle step.

2. **SDD invoking work-end is correct, not duplication.** SDD operates in
   continuous execution mode — ending with work-end is logical completion.

3. **Handoff from writing-plans to SDD/EP is smooth.** Explicit "Execution
   Handoff" section with two options. Works for users who go through
   writing-plans; no discovery mechanism for users with plans from elsewhere.

### Recommendations

- Add one line to work-start's done report mentioning the pipeline
- Verify brainstorming's skill chaining hands off to writing-plans
- No structural changes needed

## Area 3: Debugging Toolkit vs fix-ci

**Skills:** systematic-debugging, dispatching-parallel-agents, fix-ci

### Current state

All three declare themselves as "the debugging toolkit" with identical framing.
But fix-ci operates as an island — `Invokes: Nothing`.

### Findings

1. **fix-ci reinvents root-cause analysis.** Step 3 is a compressed version of
   systematic-debugging Phases 1-2, lacking the rigorous hypothesis-test cycle
   and the "question the architecture" safety valve.

2. **No escalation path.** When a CI failure has a deep, non-obvious root
   cause, fix-ci has no handoff to systematic-debugging.

3. **Asymmetric cross-references.** dispatching-parallel-agents claims fix-ci
   invokes it; fix-ci doesn't mention dispatching-parallel-agents.

### Recommendations

- Add escalation trigger to fix-ci Step 3: "If root cause is not mechanical
  → invoke systematic-debugging"
- Add multi-failure dispatch to fix-ci Step 1: "If 3+ independent subsystems
  failing → invoke dispatching-parallel-agents"
- Update fix-ci's Skill Chaining from "Invokes: Nothing" to reflect the
  two escalation paths
- Make all three skills' cross-references symmetric

## Area 4: Verification Gates

**Skills:** TDD, VBC, code-review, requesting-code-review, SDD

### Current state — gates per SDD task

1. TDD red-green-refactor (unit scope)
2. Implementer self-review (no rubric)
3. Task reviewer: spec compliance + code quality (one dispatch, two verdicts)
4. VBC (whole-task verification)
5. Final branch review via requesting-code-review (after all tasks)
6. work-end code-review (same diff as #5, lesser depth)
7. work-end VBC (re-runs after #4 already passed)

### Findings

| Gate pair | Redundant? | Verdict |
|-----------|-----------|---------|
| TDD vs VBC | No — different scope | Keep both |
| Self-review vs task review | Partial — self-review has no rubric | Drop or define |
| Task review vs branch review | No — different scope | Keep both |
| Branch review (SDD) vs code-review (work-end) | Yes — same diff | Deduplicate |
| VBC per-task vs VBC at work-end | Conditional | Make conditional |

### Recommendations

- Drop self-review or give it a 3-item rubric
- SDD should write a `.review-complete` marker; work-end checks it
  and skips code-review if HEAD matches
- Make work-end VBC conditional on HEAD change since last VBC pass

## Area 5: Knowledge Integration

**Skills:** forage, protocol, brainstorming, systematic-debugging, writing-plans,
TDD, code-review, work-start

### Current state

| Skill | Searches forage? | Searches protocols? |
|-------|-----------------|-------------------|
| brainstorming | Yes | Yes |
| systematic-debugging | Yes | No |
| work-start | Yes | Yes |
| writing-plans | **No** | **No** |
| code-review | No | **No** |
| TDD | No (static ref only) | No |

### Findings

1. **writing-plans should search forage.** The plan writer has the broadest
   view of upcoming work. A garden entry about a known pitfall with the
   target library could change the entire plan approach.

2. **code-review should search protocols.** Project-specific rules should
   inform the review checklist. Currently only language-specific checklists
   are loaded.

3. **forage/protocol split is clear in the docs** but the shared word
   "convention" creates user ambiguity. Forage has a "convention" entry type;
   protocol has "standing rules and conventions."

### Recommendations

- Add forage SEARCH to writing-plans before writing tasks
- Add protocol SEARCH to code-review alongside language checklists
- Clarify: forage convention = pattern observed across projects; protocol =
  rule enforced in this project

## Area 6: Workspace Concepts

**Skills:** workspace-init, using-git-worktrees, work-start, EnterWorktree (native)

### Current state

Four concepts, genuinely distinct:
- workspace-init: one-time companion directory for methodology artifacts
- using-git-worktrees: per-branch code isolation (tries native, falls back to git)
- work-start: branch creation + scaffold in both repos
- EnterWorktree: Claude Code harness isolation

### Findings

- using-git-worktrees already has a distinction table vs workspace-init
- workspace-init's scope has grown to "project onboarding" (1100 lines)
- The trigger for when worktree isolation is needed vs plain branching is unclear

### Recommendations

- No merges needed
- Add decision rule to using-git-worktrees: "Use when preserving uncommitted
  work on another branch, or when plan execution modifies build/config files"
- Consider renaming workspace-init to project-onboard (wide blast radius, defer)

## Summary of Actionable Recommendations

| # | Area | Recommendation | Effort | Impact |
|---|------|---------------|--------|--------|
| 1 | Review | Fix code-review / requesting-code-review frontmatter descriptions | XS | High |
| 2 | Review | Wire language checklists into subagent prompt template | S | Med |
| 3 | Review | Revise Phase 4 spec: replaces requesting-code-review only | XS | High |
| 4 | Debugging | Add escalation triggers to fix-ci (systematic-debugging, dispatching-parallel-agents) | S | Med |
| 5 | Debugging | Make fix-ci cross-references symmetric | XS | Low |
| 6 | Gates | Drop or define SDD self-review rubric | XS | Low |
| 7 | Gates | Add .review-complete marker for work-end deduplication | S | Med |
| 8 | Knowledge | Add forage SEARCH to writing-plans | S | High |
| 9 | Knowledge | Add protocol SEARCH to code-review | S | Med |
| 10 | Workspace | Add worktree decision rule to using-git-worktrees | XS | Low |
| 11 | Pipeline | Add pipeline mention to work-start done report | XS | Low |
