# Soredium Skills Ecosystem Audit

**Date:** 2026-07-07
**Scope:** 47 skills, all supporting content files, CLAUDE.md, using-superpowers orchestrator
**Method:** 7 parallel deep-read agents, each analyzing a different dimension
**Raw findings:** 131 (20C / 53W / 58N) → Deduplicated: 13C / 32W / 38N after cross-agent consolidation
**Status:** All 7 agents completed

---

## CRITICAL — Will cause wrong behavior

### C1. Phantom skill names referenced throughout the ecosystem

**Found by 4 independent agents — single most pervasive issue.**

Skills that don't exist are referenced as if they do, across chaining sections, code, and CLAUDE.md:

| Phantom name | Referenced in | Correct name |
|---|---|---|
| `java-git-commit` | dependency-update/maven.md, implementation-doc-sync, code-review/SKILL.md, update-claude-md, idea-log | `git-commit` (routes to java.md) |
| `custom-git-commit` | update-claude-md, idea-log | `git-commit` (routes to custom.md) |
| `blog-git-commit` | git-commit/SKILL.md (Step 0 blog route) | Does not exist — no blog commit skill |
| `ts-code-review` | dependency-update/npm.md, security-audit/typescript.md | `code-review` (routes to typescript.md) |
| `python-code-review` | dependency-update/pip.md, security-audit/python.md | `code-review` (routes to python.md) |
| `java-code-review` | security-audit/java.md | `code-review` (routes to java.md) |
| `java-update-design` | implementation-doc-sync, java-dev, work-end, workspace-init, update-claude-md | `update-design` (routes to java.md) |
| `update-primary-doc` | workspace-init, project-refine | Does not exist |

**Impact:** An LLM trying to invoke `java-git-commit` via the Skill tool will fail. It then either halts or improvises — both wrong. CLAUDE.md's Key Skills section also lists `ts-code-review` and `python-code-review` as if they're real skills, compounding the confusion.

**Fix:** Global find-and-replace campaign across all affected files. Replace phantom names with the router skill name. Update CLAUDE.md Key Skills to describe content files, not phantom skills.

---

### C2. AI attribution hardcoded in implementation-doc-sync

`implementation-doc-sync/SKILL.md` Step 5 (line ~189) includes `Co-Authored-By: Claude Sonnet 4.6` in its commit template. This directly violates CLAUDE.md's most prominent rule: "NEVER add AI attribution to any commit message."

Additionally, the system-level Bash tool's commit instructions add `Co-Authored-By` by default — the skill-level and CLAUDE.md rules override this, but if skills are bypassed, the system prompt wins.

**Fix:** Remove the Co-Authored-By line from implementation-doc-sync's commit template.

---

### C3. SDD flowchart creates infinite loop for tightly-coupled plans

`subagent-driven-development` flowchart Q2 routes "tightly coupled" → "MANUAL (brainstorm first)." But by this point you already HAVE a plan from `writing-plans`. The writing-plans Execution Handoff offers exactly two choices: SDD or EP. Choosing SDD → SDD says "brainstorm first" → brainstorming → writing-plans → SDD → loop forever.

**Fix:** Route "tightly coupled" to `executing-plans`, not back to brainstorming.

---

### C4. executing-plans CSO description says "separate session" — it runs inline

The frontmatter description says "in a separate session" but the skill body says "you implement the tasks yourself in this session." The CSO description is the primary text an LLM reads to decide invocation. SDD's flowchart compounds this by labeling the EP edge as "parallel session." Both are factually wrong.

**Fix:** Update EP description to say "in the current session" or "inline." Fix SDD flowchart label from "parallel session" to "inline execution."

---

### C5. using-superpowers Close flow triggers double code review and premature commits

The Close flow: `verification-before-completion → code-review → git-commit → work-end`. But work-end already runs code-review internally at Step 3c (a HARD GATE). And git-commit before work-end creates commits that work-end's squash discards.

The actual execution based on chaining declarations is: `work-end` (which runs code-review, VBC, and commits internally).

**Fix:** Replace the Close flow with: `work-end` (includes verification, code-review, squash, and push internally). Or break it into two flows: pre-work-end (standalone commits) and branch-close (work-end).

---

### C6. work-end forces checkout of `main` regardless of PROJECT_BASE_BRANCH

work-end Step 10 runs `branch_cleanup.py checkout-main` described as "Switch both repos to main." But `PROJECT_BASE_BRANCH` can be `develop` or another branch. work-pause correctly differentiates (base-branch in project, main in workspace), but work-end doesn't.

**Fix:** Step 10 should switch workspace to `main` and project to `$PROJECT_BASE_BRANCH`. Update the text and script name if needed.

---

### C7. Deprecated requesting-code-review still has active CSO description

The skill body says "Deprecated: superseded by `design-review --mode final-review`." But the frontmatter description says "Use when completing tasks, implementing major features, or before merging." An LLM scanning available skills will invoke it, encounter the deprecation mid-execution, and not know whether to proceed or switch.

**Fix:** Either (a) update the CSO description to say "DEPRECATED — use design-review --mode final-review instead" or (b) remove the skill entirely.

---

### C8. Three incompatible severity/action models across review skills

| Source | Model | NOTE handling |
|---|---|---|
| code-review-principles | CRITICAL/WARNING/NOTE | ALL must be fixed |
| security-audit-principles | CRITICAL/WARNING/NOTE | NOTEs are "best practice suggestions" |
| requesting-code-review | Critical/Important/Minor | Minor noted for later |

An LLM operating across these in one session gets contradictory instructions about whether to fix non-critical findings.

**Fix:** Unify the action model. Recommended: CRITICAL = must fix before commit, WARNING = should fix, NOTE = advisory. Apply consistently to code-review-principles and security-audit-principles.

---

### C9. Handover forage sweep checks 3 of 4 categories

Handover Step 2b says "Review the session across all three categories" listing gotchas, techniques, undocumented. But forage SWEEP has FOUR categories — it includes Conventions (Step 4). Handover's Success Criteria also says "three categories."

Convention entries are systematically missed when the sweep runs through handover's wrap checklist.

**Fix:** Add "Conventions" as the fourth category in handover Step 2b and update the Success Criteria to say "four categories."

---

### C10. write-content mandatory-gates.md references wrong step numbers

`mandatory-gates.md` line 8 says gates are at "Step 5 (pre-draft gate) and Step 7 (quality check)." But SKILL.md defines Step 2 as pre-draft gate and Step 4 as quality check. Steps 5 and 7 don't exist. An LLM reading mandatory-gates.md could skip the gates entirely.

**Fix:** Update mandatory-gates.md to reference Step 2 and Step 4.

---

### C11. ide-tooling contains contradictory fallback instructions

First paragraph of "Editing preference hierarchy": "When IntelliJ MCP is unavailable: Fall back to text tools (Edit, Write)."
Final sentence: "If no MCP server is available for a semantic operation, stop and inform the user rather than silently falling back."

Two directly conflicting instructions for the same scenario.

**Fix:** Rewrite to separate cases: "For non-structural text edits (config, markdown), use Edit/Write directly. For semantic operations (rename, move, find-references), if no MCP is available, stop and inform the user."

---

### C12. Stacked branch close has no dependency guard

work-start supports stacking branches (B based on A). But work-end has no check that the stacking base has landed on `$PROJECT_BASE_BRANCH` before closing. Running work-end on B while A hasn't merged causes conflicts in every file touching A's work, with no guidance to "close A first."

**Fix:** work-end should check if a stacking base exists (from `.meta` or branch point) and verify it has landed. If not, warn: "Close `<base-branch>` first."

---

### C13. work-end rebase direction is non-standard

Step 8j does `git checkout main && git rebase feature-branch` — rebasing main onto feature, not the conventional direction. When main has diverged, this replays main's commits on top of feature's, reversing chronological order and surfacing conflicts in already-reviewed code.

**Fix:** Either (a) document this as intentional for the personal-fork model with rationale, or (b) use conventional direction: `git checkout $BRANCH && git rebase $BASE && git checkout $BASE && git merge --ff-only $BRANCH`.

---

## WARNING — Could cause confusion or inconsistency

### Workflow Orchestration

#### W1. using-superpowers flows are oversimplified vs actual skill behavior

The Build flow omits review steps that SDD/EP include. The Fix flow ends at VBC with no commit step. The Multi-failure flow has no path to git-commit. Flows are listed as independent, not composable — an LLM following Fix won't commit the fix.

**Fix:** Rewrite Common Flows to match actual skill chaining. Add a note that flows compose (Fix then Close). Include review steps in Build.

---

#### W2. TDD gate declared but never enforced via skill invocation

using-superpowers says "No production code without failing test." EP and SDD say "Follow TDD" as methodology but never invoke the TDD skill. The TDD skill says execution skills "invoke this skill" but they don't.

**Fix:** Clarify "invoke" semantics ecosystem-wide. Either (a) add explicit Skill tool invocation of TDD in EP/SDD, or (b) change TDD's chaining to say "referenced as methodology" not "invoked."

---

#### W3. systematic-debugging not referenced by execution skills

Neither EP nor SDD references systematic-debugging for mid-task failures. using-superpowers says it applies to all bugs, but the execution skills don't chain to it.

**Fix:** Add "When encountering unexpected failures, invoke systematic-debugging" to EP's blocker handling and SDD's BLOCKED state.

---

#### W4. SDD claims to invoke using-git-worktrees but has no step for it

Chaining says "ensures isolated workspace" but the actual process steps never set up isolation.

**Fix:** Either add a Step 0 for worktree setup in SDD, or remove the chaining claim.

---

### Commit & Issue Tracking

#### W5. Duplicate issue-tracking offers across entry points

git-commit Step 0b, java.md Step 0b, custom.md Step 0b, and update-claude-md Step 4b all independently offer to set up issue tracking. A commit in a fresh project could see the offer twice in one flow.

**Fix:** Add "skip if already offered this session" guards, or consolidate the offer to a single entry point.

---

#### W6. Overlapping pre-commit issue logic with divergent skip tokens

git-commit Step 2b adds `no-issue: <reason>` to the commit body. issue-workflow Phase 3 says "proceed without a footer." The commit-msg hook blocks commits lacking BOTH an issue reference AND the `no-issue` bypass. Following issue-workflow's path causes the hook to reject the commit.

**Fix:** Align the skip mechanism. issue-workflow Phase 3 should also insert `no-issue: <reason>` when skipping.

---

#### W7. java.md uses raw git instead of commit_exec.py

git-commit's generic path uses `commit_exec.py` with safety logic. java.md Step 5 uses raw `git commit`. Java commits bypass whatever safety commit_exec.py provides.

**Fix:** Have java.md use commit_exec.py, or document why the raw path is intentional.

---

#### W8. java.md blocks commits when ARC42STORIES.MD is missing

A Java project cannot make its first commit without an architecture document. The generic path has no such requirement.

**Fix:** Soften to a WARNING rather than a blocker, or add an escape hatch for initial project commits.

---

### Dev Skills & IDE

#### W9. fix-ci lists grep/find before IDE search and has no ide-tooling prerequisite

Inverts IntelliJ-first priority. Also the only dev-adjacent skill missing ide-tooling as a prerequisite.

**Fix:** Reorder to IDE tools first. Add Prerequisites section referencing ide-tooling.

---

#### W10. No dev skill chains to verification-before-completion

After implementing code, the LLM has no instruction to compile-check or run diagnostics before proceeding to code-review.

**Fix:** Add `verification-before-completion` to the Skill Chaining section of java-dev, ts-dev, python-dev, positioned between implementation and code-review.

---

#### W11. ts-dev and python-dev have shorter refactoring guidance than java-dev

Missing: "Never write scripts to manipulate source text" and "bulk structural edit" guidance. Equally applicable to all languages.

**Fix:** Add the same refactoring rules to ts-dev and python-dev.

---

#### W12. Maven invocation inconsistent across skills

`./mvnw` in maven.md, `scripts/mvn-test` in fix-ci Step 2, bare `mvn` in fix-ci Step 5, `/opt/homebrew/bin/mvn` in CLAUDE.md. Four patterns, no clear rule.

**Fix:** fix-ci should say "the project's Maven command (per CLAUDE.md)." maven.md should note `./mvnw` is the default but projects may declare otherwise.

---

### Content & Knowledge

#### W13. implementation-doc-sync references non-existent skill names

References `java-update-design` and `java-git-commit` — neither exists. (Related to C1.)

**Fix:** Replace with `update-design` and `git-commit`.

---

#### W14. handover-reference.md uses stale garden path

References `~/claude/knowledge-garden/GARDEN.md`. Actual path: `${HORTORA_GARDEN:-~/.hortora/garden}/`.

**Fix:** Update the path in handover-reference.md.

---

#### W15. Write-content Diary taxonomy inconsistency

Diary is a top-level form option in Q1, but implemented as a Note subtype (`entry_type: note, subtype: diary`). The routing tree conceals that Diary is actually a Note.

**Fix:** Either (a) document in write-content that Diary is a promoted Note subtype, or (b) make Diary a true top-level form with its own entry_type.

---

#### W16. design-review `--mode code-review` overlaps with code-review skill

design-review CSO says "NOT for code review" but Phase 3 IS code review (spec conformance). The distinction is undocumented in either skill's chaining.

**Fix:** Add boundary documentation: code-review = pre-commit checklist; design-review Phase 3 = spec-vs-implementation conformance check. Update both skills' chaining sections.

---

### Lifecycle

#### W17. work-resume omits garden search that work-start resume path includes

work-start detection state 2 runs garden search (Step 3b). work-resume Step 9 does not. A developer who paused and resumed gets no garden context refresh.

**Fix:** Add garden search to work-resume Step 9.

---

#### W18. BASE_BRANCH vs PROJECT_BASE_BRANCH naming inconsistency

ctx.py outputs `BASE_BRANCH`. work-end uses `PROJECT_BASE_BRANCH`. Same value, different names. LLM may treat as different variables.

**Fix:** Use one name consistently. Either rename in ctx.py or alias explicitly in work-end.

---

#### W19. work-resume pops stack entry before verifying branch switch succeeds

If checkout fails after pop, the entry is gone and recovery requires manual git inspection.

**Fix:** Verify branch existence (Step 3) passes AND checkout succeeds before committing the pop. Or document recovery procedure.

---

#### W20. Neither SDD nor EP verifies branch safety at start

"Never start on main" is advice in Remember/Red Flags sections, not an actual process step.

**Fix:** Add a Step 0 check: `if [ "$(git branch --show-current)" = "main" ]; then STOP`. Place in both SDD and EP.

---

### Review Skills

#### W21. Deprecation of requesting-code-review creates weight mismatch

requesting-code-review was lightweight (one subagent, quick). Its replacement, `design-review --mode final-review`, is heavyweight (multi-round, Python PM, 10-30 min). No lightweight "dispatch one reviewer" capability remains. SDD still references requesting-code-review for final review.

**Fix:** Either (a) keep a lightweight review path alongside design-review, or (b) update SDD to reference design-review and document the time/cost tradeoff.

---

#### W22. security-audit has no fallback for `generic` project type

code-review handles `generic` via file-extension detection. security-audit only handles java/ts/python with no fallback.

**Fix:** Add file-extension fallback to security-audit, or document that security-audit requires an explicit project type.

---

#### W23. code-review-principles and security-audit-principles look like skill names

All six language content files use backtick formatting: "Follow the `code-review-principles` workflow." These are garden approach files, not skills. An LLM may try to invoke them as skills.

**Fix:** Use full paths: "Follow the workflow in `~/.hortora/garden/approaches/code-review.md`" or "Load the code-review-principles garden approach."

---

## NOTE — Minor improvements

### Structural

- **N1.** workspace-init has duplicate Step 1 headers and is ~1130 lines (longest skill)
- **N2.** work-end close plan (Step 7) doesn't show code review status
- **N3.** work-start refers to `superpowers:brainstorming` using plugin-namespaced form unnecessarily
- **N4.** Ambiguous "invoke" vs "follow" semantics across skills — no convention for Skill tool call vs methodology reference
- **N5.** work-end Step 12a references handover "Steps 1-6" by number — fragile cross-reference
- **N6.** work-end Step 3b checklist numbering vs execution order mismatch
- **N7.** Single-repo mode under-specified for pause/resume
- **N8.** work-pause "Pause vs Wrap" table duplicates guidance from work Step 4
- **N9.** ctx.py runs twice (once in project, once in work-start) — wasteful but not incorrect
- **N10.** project skill Check 4 checks specific plugin ID that may change

### Coverage Gaps

- **N11.** No Kotlin dev skill despite IDE tooling support
- **N12.** No Gradle dependency-update content — only maven.md for Java
- **N13.** No Python test example in fix-ci (Maven and npm examples present)
- **N14.** ts-dev triggers on package.json which isn't TypeScript-specific
- **N15.** fix-ci missing Python test example despite complementing python-dev
- **N16.** ts-dev and python-dev have no tests/ directory unlike java-dev

### Cross-References

- **N17.** Garden consultation block duplicated verbatim across all 6 code-review/security-audit content files
- **N18.** issue-workflow Phase 2 missing success criteria
- **N19.** IntelliJ prerequisite only in code-review/java.md, not typescript.md or python.md
- **N20.** VBC not referenced by design-review (replacement for requesting-code-review)
- **N21.** requesting-code-review/code-reviewer.md references dev skills instead of review checklists

### Documentation

- **N22.** update-design java.md self-contradictory sentence ("ARC42STORIES.MD alongside ARC42STORIES.MD")
- **N23.** Forage REVISE contradicts itself (new GE-ID vs "no separate file created")
- **N24.** idea-log doesn't specify where IDEAS.md lives in workspace projects
- **N25.** java.md Step 0 duplicates project type detection that ctx.py already did
- **N26.** update-claude-md says "never modify Project Type section" but java.md Step 0 does
- **N27.** work-start detection state 1 routes back to work skill (circular but works)

### Content Taxonomy

- **N28.** forage convention entries vs protocol entries: terminology overlap ("conventions" in both)
- **N29.** write-content CSO says "any piece of content" but scope is narrower
- **N30.** publish-blog `type` vs `entry_type` field name overlap
- **N31.** `decisions` garden type vs ADR: no explicit boundary statement
- **N32.** implementation-doc-sync missing from handover wrap checklist

### Process

- **N33.** brainstorming can bypass work-start (no branch, no workspace, no tracking)
- **N34.** SDD "Continuous execution" contradicts EP's "Stop and Ask" philosophy — never explicitly contrasted
- **N35.** Plan file path handoff between writing-plans and EP/SDD is implicit
- **N36.** No model selection guidance in EP (SDD has detailed model selection)
- **N37.** EP has no final review mechanism comparable to SDD's design-review --mode final-review
- **N38.** Potential recursion between systematic-debugging and dispatching-parallel-agents

---

## Systemic Patterns

Three systemic patterns account for most findings:

### Pattern 1: Router skill names leaked into content files

When `code-review` was split into router + content files, the old monolithic skill names (`java-code-review`, `ts-code-review`) persisted in chaining sections, dependency-update, security-audit, implementation-doc-sync, and CLAUDE.md. **This is a single find-and-replace campaign** that resolves C1, W13, and several NOTEs.

### Pattern 2: using-superpowers flows are a stale snapshot

The Common Flows section describes a model that predates the current skill internals. work-end now subsumes the Close flow. EP and SDD have review steps the Build flow doesn't show. The Fix flow has no commit step. **These flows are the master reference an LLM consults first** — if they're wrong, everything downstream drifts.

### Pattern 3: Cross-file step number references are fragile

mandatory-gates.md → SKILL.md steps, work-end → handover steps, work-start → forage categories. Any renumbering silently breaks the reference. **Consider using named anchors or section titles instead of step numbers** for cross-file references.

---

## Recommended Fix Order

**Phase 1 — Mechanical fixes (low risk, high impact):**
1. C1 + W13: Global phantom skill name replacement
2. C2: Remove AI attribution from implementation-doc-sync
3. C10: Fix step numbers in mandatory-gates.md
4. C7: Update or remove deprecated requesting-code-review
5. C9: Add conventions as 4th category in handover sweep
6. W14: Fix stale garden path in handover-reference.md

**Phase 2 — Semantic fixes (medium risk, high impact):**
7. C3 + C4: Fix SDD flowchart loop and EP description
8. C5 + W1: Rewrite using-superpowers Common Flows
9. C11: Clarify ide-tooling fallback instructions
10. C8: Unify severity/action model across review skills
11. W6: Align skip tokens between git-commit and issue-workflow

**Phase 3 — Structural fixes (higher risk, important):**
12. C6: Fix work-end base branch checkout
13. C12: Add stacked branch dependency guard
14. C13: Document or fix rebase direction
15. W2 + W3: Clarify TDD/systematic-debugging enforcement
16. W9 + W10 + W11: Dev skill consistency (IDE priority, VBC chaining, refactoring rules)

**Phase 4 — Cleanup (low priority):**
17. All WARNING items not covered above
18. All NOTE items

---

## Appendix: CSO Quality and Structural Findings (Agent 7)

The final audit agent focused specifically on CSO quality, cross-reference integrity, and structural consistency. Phantom skill names are folded into C1 above. Remaining unique findings below.

### CSO Quality Issues

#### W24. Descriptions over 500 characters

- `design-review`: 511 chars. Includes workflow summary ("Orchestrates two independent Claude sessions...").
- `protocol`: 532 chars. Includes operation enumeration ("CAPTURE, SWEEP, SEARCH, HEALTH").
- `write-content`: 525 chars. Extensive trigger phrase list pushes it over.

**Fix:** Trim descriptions. Remove HOW details, keep WHEN triggers.

#### W25. Descriptions that don't start with "Use when..."

- `brainstorming`: Starts with "You MUST use this before any creative work."
- `ide-tooling`: Starts with "INVOKE IMMEDIATELY when mcp__intellij-index__* tools are visible."

Both are imperative/prescriptive rather than condition-describing. The CSO convention is "Use when..." to focus on triggering conditions.

**Fix:** Rewrite to condition form: "Use when starting any creative work..." / "Use when mcp__intellij-index__* tools are visible..."

#### W26. Descriptions containing workflow summaries (CSO violation)

- `design-review`: "Orchestrates two independent Claude sessions (reviewer + implementor) with a Python PM" — describes HOW, not WHEN.
- `requesting-code-review`: "Dispatches a fresh subagent for review" — describes HOW, not WHEN.

**Fix:** Remove HOW details from descriptions. Keep only triggering conditions.

### Bidirectional Cross-Reference Gaps

#### W27. design-review missing invokers in Skill Chaining

`design-review` says "Invoked by: User directly" but two skills declare they invoke it:
- `subagent-driven-development`: "Invokes: design-review --mode final-review"
- `work-end`: "Invokes: design-review --mode final-review -- Step 3c"

**Fix:** Add both as invokers in design-review's Skill Chaining section.

#### W28. work-start missing work-resume as invoker

`work-resume` says "Invokes: work-start (partial) -- Steps 0, 2, 3, 11 only." But work-start's Skill Chaining does not list work-resume.

**Fix:** Add work-resume as invoker in work-start's Skill Chaining.

#### W29. using-superpowers missing Skill Chaining section entirely

The only skill without a `## Skill Chaining` section. References many skills in its body but lacks the formal section.

**Fix:** Add a Skill Chaining section listing all referenced skills.

### Missing Structural Elements

#### W30. Artifact-producing skills missing Success Criteria

| Skill | Produces | Has Success Criteria? |
|---|---|---|
| `work-end` | Merged branches, closed issues, promoted artifacts | No |
| `work-start` | Branches, .meta files, design scaffolding | No |
| `work-pause` | WIP commits, pause stack entries | No |
| `work-resume` | Restored branches, removed stack entries | No |
| `writing-plans` | Implementation plan documents | No |
| `write-content` | Content files (diary entries, articles, etc.) | No |
| `design-review` | Review tracker, updated spec | No |
| `executing-plans` | Completed implementations | No |

Skills with correct Success Criteria: adr, forage, git-commit, handover, harvest, idea-log, issue-workflow, project-health, project-refine, protocol, publish-blog, retro-issues, update-claude-md, workspace-init.

**Fix:** Add Success Criteria sections to the missing skills. Priority: work-end (most complex), write-content (most used).

#### W31. Complex skills missing Common Pitfalls tables

- work-end, work-start, work-pause, work-resume (complex lifecycle, many edge cases)
- write-content, writing-plans (content generation)
- design-review (complex orchestration)
- subagent-driven-development (has "Red Flags" instead of "Common Pitfalls" — inconsistent naming)

**Fix:** Add Common Pitfalls tables to lifecycle skills at minimum. Rename SDD's "Red Flags" to "Common Pitfalls" for consistency.

### Triggering Overlap Risks

#### W32. Four review skills could trigger on "review this code"

| Skill | Trigger scenario | Intended use |
|---|---|---|
| `code-review` | Pre-commit staged changes | Checklist review |
| `requesting-code-review` (deprecated) | Before merging | Independent subagent |
| `design-review --mode code-review` | Spec conformance | Adversarial spec-vs-code |
| `design-review --mode final-review` | Production readiness | Branch-level review |

User saying "review this code before merging" could trigger any of these.

**Fix:** Update CSO descriptions to be more specific about triggering conditions. Remove requesting-code-review's active description (see C7).
