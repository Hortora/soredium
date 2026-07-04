# Superpowers Fork Integration into Soredium

## Problem

The original obra/superpowers ships 14 skills. All 14 were copied into
soredium's working directory but none are committed to git. They sit as
untracked files alongside soredium's committed skills. Four were lightly
edited to reference soredium conventions; nine are identical to the
original; one (`finishing-a-development-branch`) was replaced by
soredium's committed `work-end`.

The result: soredium has two skill layers that don't talk to each other.
The superpowers fork provides the process discipline (brainstorming,
TDD, debugging, verification) and execution pipeline (subagent-driven
development, plan execution). Soredium provides the work lifecycle
(work-start/end/pause/resume), knowledge systems (forage, protocol,
harvest), language-specific tooling (java-dev, ts-dev, python-dev),
quality infrastructure (code-review, security-audit, 19 validators),
and IDE integration (ide-tooling). Neither layer references the other.

A developer using soredium gets the lifecycle and tooling but not the
discipline. The forked superpowers skills reference each other but are
blind to soredium's conventions, workspace model, issue tracking,
knowledge garden, and IntelliJ MCP capabilities.

## Proposal

Rewrite all 14 forked superpowers skills as first-class soredium citizens.
Each rewrite preserves the original intent and core methodology but
integrates with soredium's ecosystem: work lifecycle, knowledge layer,
testing infrastructure, issue tracking, IDE tooling, and workspace
conventions. Then commit them to git as tracked, validated skills.

This is not a patch. Each skill is rewritten from scratch, informed by
the original but not constrained to incremental changes.

### Design principles

1. **Preserve the methodology, change the wiring.** The superpowers
   skills encode hard-won behavioural discipline (TDD's red-green-refactor,
   systematic-debugging's root-cause-first, verification-before-completion's
   evidence gate). These methodologies are proven. What changes is how they
   connect to soredium's infrastructure.

2. **One issue group, one focal issue.** A branch covers 1..n issues
   (batched work). At any given moment during the pipeline — brainstorming,
   planning, implementing, reviewing — there is a focal issue from that
   group. Skills reference the focal issue, not "the issue" (singular) or
   all issues (unfocused).

3. **IntelliJ structural editing is the default for code authoring.**
   The IntelliJ MCP now provides structural editing tools
   (`ide_edit_member`, `ide_replace_member`, `ide_insert_member`)
   alongside its existing navigation and refactoring capabilities. Skills
   that involve code authoring (TDD, debugging, subagent-driven
   development, executing-plans) should prefer structural editing over
   text tools. The editing preference hierarchy:
   - Structural edits (ide_edit_member, ide_replace_member, ide_insert_member)
     for class members
   - Semantic refactoring (ide_refactor_rename, ide_move_file,
     ide_refactor_safe_delete) for cross-cutting reference updates
   - Text edits (Edit tool) for non-structural changes (config, markdown,
     non-class code)

4. **ide-tooling is the single reference.** All skills that involve IDE
   operations point to ide-tooling rather than re-documenting tool usage.
   ide-tooling itself is restructured around capability layers (Navigate,
   Read, Edit, Refactor, Verify, Project) rather than MCP server identity.

5. **Soredium conventions for paths and structure.** Spec output paths,
   plan paths, and artifact locations follow soredium's workspace model,
   not the original superpowers conventions (`docs/superpowers/specs/`).

6. **No duplication with CLAUDE.md.** Where soredium's CLAUDE.md already
   covers a topic (CSO rules, naming conventions, frontmatter format),
   skills reference it by pointer rather than restating.

### Rewrite conventions

Every rewritten skill follows these conventions in addition to the
design principles above:

- **Bare skill names.** Strip `hortora:` prefix from all skill
  references. Soredium skills use bare names (`test-driven-development`,
  not `hortora:test-driven-development`). Six skills currently use the
  prefix: executing-plans, fix-ci, subagent-driven-development,
  systematic-debugging, writing-plans, writing-skills.
- **Mermaid flowcharts.** Use `flowchart TD` notation, not
  `dot digraph`. Five skills currently use dot format: brainstorming,
  dispatching-parallel-agents, subagent-driven-development,
  test-driven-development, writing-skills. Soredium validators
  check flowchart format.
- **Supporting files get the same treatment.** Prompt templates
  (`implementer-prompt.md`, `task-reviewer-prompt.md`,
  `code-reviewer.md`), technique documents (`root-cause-tracing.md`,
  `defense-in-depth.md`, `condition-based-waiting.md`,
  `testing-anti-patterns.md`), and scripts (`scripts/`) are all
  in scope. They must follow soredium conventions: bare skill names,
  no stale references.
- **IntelliJ fallback.** Skills reference ide-tooling for IntelliJ
  capabilities. ide-tooling handles unavailability — when IntelliJ
  MCP is not available, skills fall back to text tools (Edit, Write).
  Individual skills do not need their own fallback logic.
- **Focal issue** is descriptive, not a new tracking mechanism.
  When a branch covers issues #42, #43, #44 and the current task
  is implementing #43, then #43 is the focal issue. Skills that
  reference the focal issue mean "the issue currently being worked
  on." It is not stored separately — the implementor determines it
  from the active task context.

### Relationship to ADR four-phase pipeline

The four-phase pipeline spec (`docs/specs/2026-07-02-adr-four-phase-review-pipeline.md`,
epic #63) and this spec are complementary:

- **This spec** rewrites superpowers skills as soredium citizens.
  requesting-code-review becomes a better-integrated skill.
- **Phase 4** (#66) replaces both `code-review` and
  `requesting-code-review` with ADR-style multi-round review.

**Sequencing:** This spec should land first. It improves the skills
for current use. When #66 lands later, it replaces the improved
versions. The four-phase pipeline spec's statement that superpowers
"continues to run as it does now" should be updated to note that
the superpowers skills will have been integrated into soredium by
that point.

No conflict exists — this spec makes the skills better soredium
citizens, #66 later replaces some of them with a heavier gate.

## The 14 skills — current state and rewrite approach

### Group A: The Pipeline

These five skills form a sequential chain from idea to shipped code:
brainstorming → writing-plans → (subagent-driven-development |
executing-plans) → verification-before-completion.

#### 1. brainstorming

**Original intent:** Turn ideas into design specs through collaborative
dialogue. Hard gate: no implementation without approved design.

**Current gaps:**
- Does not know about work-start's pre-gathered context (active issues,
  relevant protocols, garden search results, IntelliJ status)
- No forage SEARCH to surface relevant prior knowledge before ideation
- Visual companion system adds token cost and complexity
- Uses `dot digraph` flowchart format (soredium convention: Mermaid
  `flowchart TD`)
- Supporting files (`visual-companion.md`, `spec-document-reviewer-prompt.md`,
  `scripts/`) need evaluation for integration or removal

**Rewrite approach:**
- Accept work-start context when available: if work-start has run,
  read `$WORKSPACE/design/.meta` for `issue` and `covers` (the
  issue group). Protocols and garden results gathered by work-start
  are transient (conversation context, not persisted) — brainstorming
  re-gathers these itself via forage SEARCH and protocol SEARCH. If
  work-start hasn't run (no `.meta` exists), skill gathers all
  context itself (current behaviour).
- Add forage SEARCH step early in exploration — surface relevant garden
  entries (gotchas, techniques) before the user starts answering
  design questions.
- Spec output path is already `docs/specs/` (correct soredium path).
- Evaluate visual companion: if still actively used, keep as optional
  reference doc. If not, remove to reduce token cost.
  `spec-document-reviewer-prompt.md` stays if it adds value to the
  self-review step; otherwise fold into the main skill.
- Terminal state remains: invoke writing-plans.
- Convert `dot digraph` flowchart to Mermaid `flowchart TD`.

#### 2. writing-plans

**Original intent:** Convert approved specs into bite-sized implementation
plans. No placeholders, exact file paths, complete code in every step.

**Current gaps:**
- No reference to the active issue group or focal issue
- Plan output path uses `docs/plans/` — not workspace-aware
- Execution mode choice (subagent vs inline) is offered but not informed
  by any criteria

**Rewrite approach:**
- Plan header references the focal issue from the issue group.
- Plan output path: `docs/plans/` (soredium standard path, consistent
  with existing workspace conventions).
- Execution mode choice includes guidance: subagent-driven for plans
  with 3+ independent tasks or when review between tasks adds value;
  inline for simple sequential plans or when subagent overhead isn't
  justified.
- Implementation tasks should note that TDD applies to each task and
  that IntelliJ structural editing is the preferred code authoring
  approach.

#### 3. subagent-driven-development

**Original intent:** Execute plans using a fresh subagent per task with
two-stage review (spec compliance + code quality) between tasks. The
premium execution mode.

**Current gaps:**
- Does not reference verification-before-completion as a gate before
  marking tasks done
- Does not reference dispatching-parallel-agents for multi-failure
  recovery during execution
- Implementer and reviewer prompt templates (`implementer-prompt.md`,
  `task-reviewer-prompt.md`) reference `hortora:` prefixed skills
  and don't include soredium's code-review principles or garden
  approaches
- `scripts/review-package` and `scripts/task-brief` are Python
  scripts that need tests per `externalised-scripts-require-tests.md`
- No connection to issue tracking (task completion should update issue
  progress)
- No awareness of IntelliJ structural editing for implementer subagents
- No reference to ide-tooling
- Uses `dot digraph` flowchart format

**Rewrite approach:**
- Wire verification-before-completion as an explicit gate: VBC runs
  after the existing two-stage review (spec compliance + code quality)
  passes, as a third stage before marking the task done. The existing
  review process is preserved; VBC adds an evidence-based verification
  layer on top.
- Reference dispatching-parallel-agents: if multiple tasks fail during
  execution, dispatch parallel agents to investigate rather than
  fixing sequentially.
- Rewrite `implementer-prompt.md` to reference ide-tooling for
  IntelliJ structural editing and TDD for the development discipline.
  Strip `hortora:` prefixes.
- Rewrite `task-reviewer-prompt.md` to load relevant language-specific
  code-review checklist (from soredium's code-review router skill).
  Strip `hortora:` prefixes.
- Add tests for `scripts/review-package` and `scripts/task-brief`
  per protocol.
- Task completion updates the focal issue's progress.
- Convert `dot digraph` to Mermaid `flowchart TD`.

#### 4. executing-plans

**Original intent:** Lightweight inline plan execution. Load plan,
execute tasks sequentially, call work-end. The fallback when subagents
aren't available or the plan is simple.

**Current gaps:**
- No verification gate per task
- No TDD awareness during implementation
- No reference to code-review before final commit
- No IntelliJ structural editing awareness
- Says "use subagent-driven-development instead" — positioning is
  unclear (fallback vs alternative)

**Rewrite approach:**
- Add verification-before-completion gate per task.
- Reference TDD as the implementation discipline during execution.
- Reference code-review before the final commit.
- Reference ide-tooling for IntelliJ structural editing.
- Clarify positioning: this is the direct-execution path, not a
  lesser fallback. Use when the plan is sequential and the overhead
  of subagent dispatch and inter-task review isn't justified.
- Keep it lean — this skill is thin by design.

#### 5. verification-before-completion

**Original intent:** Universal evidence gate. No completion claims
without running the verification command, reading the output, and
confirming it supports the claim.

**Current gaps:**
- Not referenced by any committed soredium skill
- Standalone — no Skill Chaining section connecting it to the
  ecosystem

**Rewrite approach:**
- Add explicit Skill Chaining section listing all integration points:
  invoked by subagent-driven-development (per task), executing-plans
  (per task), work-end (before merge), git-commit (before commit).
- Keep universal — do not add language-specific content.
- Preserve the 24 documented failures as motivation.
- Reference TDD's red-green verification as a complementary check
  (verification-before-completion verifies the whole; TDD verifies
  each unit).

### Group B: Quality and Review

Three skills handling code quality through subagent-dispatched review.

#### 6. requesting-code-review

**Original intent:** Dispatch an independent reviewer subagent with git
SHAs and a focused prompt, isolated from the developer's session history.
Severity model: Critical/Important/Minor.

**Current gaps:**
- CSO description already documents the distinction from
  `code-review` (staged-changes review vs independent subagent
  review). The distinction exists but isn't reinforced in skill
  body or Skill Chaining.
- Reviewer subagent doesn't load soredium's language-specific
  review checklists
- No connection to work-end (Step 3c does mandatory code review)
- `code-reviewer.md` template needs evaluation for soredium
  integration

**Rewrite approach:**
- Clarify distinction: `code-review` = pre-commit checklist review
  of staged changes. `requesting-code-review` = independent subagent
  review for significant work (feature completion, pre-merge).
- Reviewer subagent prompt should reference the relevant
  language-specific checklist from soredium's code-review router.
- Add Skill Chaining: invoked by subagent-driven-development (per
  task), work-end (Step 3c), or manually for significant changes.

#### 7. receiving-code-review

**Original intent:** Handle review feedback with technical rigor, not
performative agreement. Verify before implementing. Push back when
justified. YAGNI check.

**Current gaps:**
- No reference to soredium's protocol system (check if a suggestion
  conflicts with a standing protocol before implementing)

**Rewrite approach:**
- Minimal changes — this skill is about developer behaviour, not
  tool integration.
- Add: before implementing a suggestion that changes architectural
  patterns, check relevant protocols (protocol SEARCH) to confirm
  the suggestion doesn't violate a standing convention.
- Keep the YAGNI check and pushback guidance intact.

#### 8. dispatching-parallel-agents

**Original intent:** When multiple independent failures arise, dispatch
one agent per problem domain. Work concurrently, integrate fixes.

**Current gaps:**
- CSO description says "2+ independent tasks" but body says "3+ test
  files failing" — inconsistent threshold. The CSO is correct (2+).
  The body's "3+" is an example, not a threshold requirement.
- Not referenced by any committed soredium skill
- No connection to systematic-debugging or fix-ci
- No connection to subagent-driven-development (failure recovery)
- Uses `dot digraph` flowchart format

**Rewrite approach:**
- Fix threshold inconsistency: align body with CSO. The trigger is
  2+ independent problems, not a hard count of 3+.
- Add Skill Chaining: invoked by systematic-debugging (when
  investigation reveals multiple independent root causes), fix-ci
  (multiple CI failures across subsystems), subagent-driven-development
  (failure recovery during execution).
- Each dispatched agent should be aware of ide-tooling and TDD.
- These three skills (systematic-debugging, dispatching-parallel-agents,
  fix-ci) form a debugging toolkit. fix-ci is developer-only and
  not marketplace-visible — the toolkit cross-references exist in
  skill documentation for ecosystem coherence, not for marketplace
  user discovery.
- Convert `dot digraph` to Mermaid `flowchart TD`.

### Group C: Development Discipline

Three skills enforcing development practices.

#### 9. test-driven-development

**Original intent:** Red-green-refactor cycle. Universal methodology,
not framework-specific. "If you didn't watch the test fail, you don't
know if it tests the right thing."

**Current gaps:**
- Soredium's language dev skills (java-dev, ts-dev, python-dev) each
  prescribe specific testing frameworks, assertion libraries, and
  mocking strategies. TDD prescribes the process but doesn't reference
  these skills for framework choices.
- testing-anti-patterns.md is a companion doc but the relationship
  isn't formalised
- Garden has `~/.hortora/garden/approaches/testing.md` that all three
  language skills mandate — TDD doesn't reference it
- No section on how TDD integrates with the execution pipeline
- No reference to IntelliJ structural editing for writing tests and
  production code

**Rewrite approach:**
- Position TDD explicitly as the process layer: TDD defines HOW to
  work (test first, watch fail, minimal code, refactor). Language
  skills define WHAT tools to use (JUnit, pytest, Vitest). Garden
  testing approaches provide universal principles.
- Reference testing-anti-patterns as a companion doc (the three Iron
  Laws complement TDD's cycle).
- Reference garden testing approaches as foundational reading.
- Add pipeline integration: "During subagent-driven-development or
  executing-plans, every implementation task follows TDD."
- Reference ide-tooling: use IntelliJ structural editing
  (ide_insert_member for new test methods, ide_replace_member for
  fixing implementations) during the red-green-refactor cycle.
- Remove framework-specific code examples (currently TypeScript
  throughout: npm test, .test.ts, React component examples). Replace
  with language-neutral process descriptions. The skill teaches the
  red-green-refactor cycle; code examples belong in language skills.
  `testing-anti-patterns.md` companion doc is also currently
  TypeScript-only — rewrite examples as language-neutral or remove
  language-specific syntax.

#### 10. systematic-debugging

**Original intent:** Four phases: investigate → pattern analysis →
hypothesis + test → implement fix. Root cause before fixes.

**Current gaps:**
- fix-ci is a soredium-committed skill with similar root-cause
  discipline but CI-specific. The relationship isn't documented.
- No reference to dispatching-parallel-agents for multi-failure
  scenarios
- No forage SEARCH to check if the garden has a known gotcha for
  this failure pattern
- No reference to TDD for the fix phase (write failing test
  reproducing the bug before fixing)
- Already references IntelliJ MCP tools (ide_call_hierarchy,
  ide_find_references, ide_find_definition, ide_type_hierarchy)
  in Phase 1 Step 5, but does not reference the ide-tooling skill
  for the full capability catalog
- Supporting files (`root-cause-tracing.md`, `defense-in-depth.md`,
  `condition-based-waiting.md`) need evaluation for soredium
  integration
- Uses `hortora:` prefix for skill references

**Rewrite approach:**
- Reference fix-ci: for CI-specific failures, use fix-ci which
  specialises in local reproduction and CI-specific patterns.
  Note: fix-ci is developer-only — the cross-reference is for
  skill ecosystem documentation, not marketplace visibility.
- Reference dispatching-parallel-agents: when investigation reveals
  multiple independent root causes, dispatch parallel agents.
- Add forage SEARCH early in Phase 1 (investigation): search the
  garden for known gotchas matching the failure pattern. A garden
  entry might have the exact bug documented.
- Reference TDD for Phase 4 (implementation): write a failing test
  that reproduces the bug before writing the fix.
- Retain existing IntelliJ MCP references in Phase 1. Add pointer
  to ide-tooling for the full capability catalog (structural
  editing tools for Phase 4 fixes).
- Supporting files stay as companion docs — they contain valuable
  technique documentation. Evaluate for soredium convention
  compliance (no `hortora:` prefixes, Mermaid flowcharts).
- These three form the debugging toolkit: systematic-debugging
  (single root cause), dispatching-parallel-agents (multiple
  independent root causes), fix-ci (CI-specific failures).

#### 11. using-git-worktrees

**Original intent:** Set up isolated workspaces for feature work.
Priority: detect existing isolation → native tools → git worktree
fallback.

**Current gaps:**
- work-start creates branches but doesn't set up worktrees
- workspace-init (companion methodology workspace) is a different
  concept but the distinction isn't documented
- The relationship to work-start's branch creation is unclear

**Rewrite approach:**
- Clarify distinction: workspace-init creates the companion
  methodology workspace (`~/claude/private/<project>/`).
  using-git-worktrees creates an isolated git worktree for the
  feature branch (`.worktrees/<branch>`). These are orthogonal.
- Reference work-start: worktree setup can happen as part of
  work-start's branch creation flow. using-git-worktrees remains
  standalone for cases where work-start isn't used (e.g., quick
  fixes, subagent isolation).
- Keep the detection-first approach (check existing isolation
  before creating new).

### Group D: Lifecycle and Meta

#### 12. finishing-a-development-branch

**Original intent:** Branch completion: verify tests → detect
environment → present options (merge/PR/keep/discard) → execute →
cleanup worktrees.

**Status:** Not present in soredium. Replaced by `work-end` which
is a committed, 12-step branch closure skill with artifact promotion,
journal merge, issue closing, and blog publishing.

**Approach:** Do not bring back as a separate skill. Audit work-end
to confirm it covers:
- Worktree cleanup (provenance-based — only clean up worktrees
  created by the tool, under `.worktrees/`)
- Structured option presentation (merge/PR/keep/discard)
- Discard confirmation (user must type "discard")
- Ordering: merge before worktree removal, cd to main root before
  removal, removal before branch deletion

If gaps exist, fold the missing logic into work-end.

#### 13. writing-skills

**Original intent:** Skill authoring as TDD. Pressure test before
writing, SDO for descriptions, bulletproofing against rationalisation.

**Current gaps:**
- 690 lines — substantial overlap with soredium's CLAUDE.md which
  covers CSO rules, naming conventions, frontmatter requirements,
  skill architecture, supporting files, and flowcharts
- No reference to soredium's validation infrastructure (validate_all.py,
  skill-validation.md, 2010 tests)
- Supporting files need evaluation:
  - `graphviz-conventions.dot` — dot-specific style rules; must be
    replaced with Mermaid conventions (settled decision: Mermaid for
    all flowcharts)
  - `render-graphs.js` — renders dot flowcharts to SVG; needs
    updating or removal after Mermaid migration
  - `testing-skills-with-subagents.md` — testing methodology;
    evaluate for soredium integration
  - `persuasion-principles.md` — research foundation for
    bulletproofing; keep as companion doc
  - `anthropic-best-practices.md` — official skill authoring
    guidance; keep as companion doc
  - `examples/CLAUDE_MD_TESTING.md` — example material; evaluate
    for currency

**Rewrite approach:**
- Remove content that duplicates CLAUDE.md: frontmatter format,
  naming conventions, section naming, flowchart guidance. Reference
  CLAUDE.md by pointer.
- Focus on what CLAUDE.md doesn't cover: the TDD-for-skills
  methodology (baseline → pressure test → write skill → close
  loopholes), pressure scenario design, bulletproofing against
  rationalisation, matching guidance to failure type.
- Reference soredium's validation infrastructure: after writing a
  skill, run `python3 scripts/validate_all.py --tier commit` for
  mechanical validation. Soredium's validators check structure;
  writing-skills' testing methodology checks behaviour.
- Reference SDO/CSO by pointer to CLAUDE.md's CSO section rather
  than restating the rules.
- Convert `dot digraph` flowcharts to Mermaid `flowchart TD`.
- Strip `hortora:` prefixes from skill references.
- Replace `graphviz-conventions.dot` with Mermaid-based conventions
  (or fold into main SKILL.md if the content is small enough).
  Remove or update `render-graphs.js` accordingly.

#### 14. using-superpowers

**Original intent:** Meta-skill. Force Claude to check for applicable
skills before any action.

**Current gaps:**
- Names only brainstorming and systematic-debugging as process skill
  examples (2 of 14 skills)
- No awareness of the work lifecycle, knowledge layer, quality gates,
  or testing discipline
- references/ directory contains stale cross-tool mappings
  (Antigravity, Codex, Pi) that don't serve soredium users

**Rewrite approach:**
- Name all process skills with their enforcement gates:
  brainstorming (no implementation without design), systematic-debugging
  (no fix without root cause), test-driven-development (no code
  without failing test), verification-before-completion (no done
  without evidence), writing-plans (no execution without plan)
- Add compact Common Flows showing multi-skill chains:
  Build, Fix, Multi-failure, Close
- Add Lifecycle Integration: when skills fire at session start,
  mid-session (forage/protocol sweeps), pre-commit, branch close
- Drop the references/ directory
- Keep under ~80 lines — concision is the power

**Status:** Rewrite already drafted (see implementation notes below).

## ide-tooling restructure

The IntelliJ MCP has expanded from navigation + refactoring to include
structural code editing. The current ide-tooling skill is organised by
MCP server (intellij-index vs intellij). It should be restructured
around capability layers:

| Layer | Tools | When |
|-------|-------|------|
| **Navigate** | find_references, find_definition, find_implementations, find_super_methods, type_hierarchy, call_hierarchy, find_class, find_file, find_symbol, search_text, file_structure | Understanding code before changing it |
| **Read** | read_file (with startLine/endLine from file_structure), get_active_file, open_file | Reading specific members or files |
| **Edit** | edit_member, replace_member, insert_member | Structural code changes (methods, fields, properties) |
| **Refactor** | refactor_rename, move_file, refactor_safe_delete, optimize_imports, reformat_code, convert_java_to_kotlin | Cross-cutting changes that update references |
| **Verify** | diagnostics, build_project, index_status, sync_files, reload_project | Checking correctness after changes |
| **Project** | open_project, open_workspace, import_modules, close_project, project_status, set_project_mode, lifecycle_log | Managing what's open and active |

### New structural editing tools

Three new tools for semantic code editing:

**ide_edit_member** — Replace entire member declaration (signature + body).
Use when changing a method's API and implementation together.

Parameters: file, class (optional), member, content (complete replacement),
parameterCount/line (disambiguation), reformat (default: true).

**ide_replace_member** — Replace only the body, signature preserved.
Use when fixing or rewriting a method's implementation without changing
its API.

Parameters: file, class (optional), member, content (new body WITHOUT
braces for methods, or new initializer expression), parameterCount/line
(disambiguation), reformat (default: true).

**ide_insert_member** — Insert new member at structural position.
Use when adding new methods, fields, or properties.

Parameters: file, class (optional), content (complete declaration),
position (before/after/first/last, default: last), anchor (existing
member name, required for before/after), reformat (default: true).

**ide_file_structure enhancement** — Now returns endLine alongside line
for each member, enabling targeted reads:
`ide_read_file(file, startLine=42, endLine=65)` to read exactly one
method.

**Error handling:** Ambiguous overloads return candidate list with
parameterCount and line for retry. Member not found returns clear error.
Abstract methods without bodies suggest ide_edit_member instead.

### Editing preference hierarchy

For skills that author code (TDD, systematic-debugging,
subagent-driven-development, executing-plans):

1. **Structural edits** (ide_edit_member, ide_replace_member,
   ide_insert_member) — for class members. Semantically aware,
   auto-reformats.
2. **Semantic refactoring** (ide_refactor_rename, ide_move_file,
   ide_refactor_safe_delete) — for cross-cutting reference updates.
3. **Text edits** (Edit tool) — for non-structural changes (config,
   markdown, non-class code, file-level changes).

### ide-tooling integration points

ide-tooling must be referenced by all skills that involve code operations:

| Skill | IDE operations used |
|-------|---------------------|
| test-driven-development | Edit: insert_member (new tests), replace_member (minimal code). Navigate: file_structure (find test methods). Verify: diagnostics, build. |
| systematic-debugging | Navigate: call_hierarchy, find_references, diagnostics (investigation). Edit: replace_member (fixes). Verify: build, diagnostics. |
| subagent-driven-development | Implementer subagents use all Edit + Navigate tools. Reviewer subagents use Navigate + Verify. |
| executing-plans | All Edit tools during task execution. Verify after each task. |
| dispatching-parallel-agents | Each dispatched agent needs IDE awareness for its domain. |
| brainstorming | Navigate only (exploring existing code during design). |
| writing-plans | None directly — but plans should note that implementation uses IDE tools. |

## Changes to soredium-native skills

The rewrite is primarily about the 14 forked skills, but some
soredium-native skills need modifications for integration:

- **work-end:** Audit against finishing-a-development-branch for
  worktree cleanup, structured options, discard confirmation.
- **code-review:** Add Skill Chaining section clarifying distinction
  from requesting-code-review. code-review = staged-changes checklist.
  requesting-code-review = independent subagent review.
- **fix-ci:** Add cross-reference to systematic-debugging and
  dispatching-parallel-agents (the debugging toolkit). fix-ci
  remains developer-only — the cross-reference is for ecosystem
  documentation, not marketplace visibility. Also strip `hortora:`
  prefix from its existing skill references.
- **java-dev, ts-dev, python-dev:** Add reference to TDD as the
  process layer above their framework-specific testing guidance.
  Add reference to ide-tooling for the new structural editing tools.
- **ide-tooling:** Full restructure around capability layers (see
  above).

## Impact on existing artifacts

### CLAUDE.md

The "Third-Party Skill Exclusion" section (line 318) explicitly says
to exclude `superpowers:*` skills and add them to `.gitignore`. After
this work, the rewritten skills ARE first-party soredium citizens —
they're committed to git, validated, and maintained here. The
Third-Party Skill Exclusion section must be updated post-implementation
to reflect that these are no longer third-party skills. The `.gitignore`
entry for `skill-creator/` (genuinely third-party) remains.

### ARC42STORIES.MD

S1, S3, and S7 reference "33 skills" / "33 Installed Skills". After
this work, the count becomes 46 (33 existing + 13 new). Update:
- S1: skill count
- S3: system context diagram
- S5: skill list (add 13 skills across appropriate categories)
- S7: installed skills count and container diagram
- Layer × Chapter matrix: this work touches the Skills layer and
  should be recorded as a new chapter or extension of the existing
  Journey.

### marketplace.json

Currently lists 30 marketplace-visible skills. Distribution decisions
for the 13 new skills:

| Skill | Marketplace | Rationale |
|-------|-------------|-----------|
| using-superpowers | Yes | Session-start meta-skill, universal |
| brainstorming | Yes | Process discipline, universal |
| writing-plans | Yes | Plan creation, universal |
| test-driven-development | Yes | Process discipline, universal |
| verification-before-completion | Yes | Quality gate, universal |
| systematic-debugging | Yes | Process discipline, universal |
| requesting-code-review | Yes | Review workflow, universal |
| receiving-code-review | Yes | Review behaviour, universal |
| executing-plans | Yes | Plan execution, universal |
| subagent-driven-development | Yes | Premium execution mode, universal |
| dispatching-parallel-agents | Yes | Multi-failure workflow, universal |
| using-git-worktrees | Yes | Workspace isolation, universal |
| writing-skills | Yes | Skill authoring, relevant to skill authors |

All 13 are marketplace-visible. These are universal process skills,
not project-type-specific or developer-only. fix-ci (existing,
developer-only) remains excluded.

### ADR

Create ADR-0012 documenting the integration decision:
- **Decision:** Integrate superpowers-forked skills as first-class
  soredium citizens
- **Alternatives considered:** (1) Keep as untracked overlay,
  (2) Fork into separate repo, (3) Maintain superpowers-specific
  layer, (4) Integrate as first-class citizens
- **Why integration:** Eliminates the two-layer problem, enables
  cross-referencing, brings skills under validation, and makes
  the full development pipeline a soredium-governed concern.

### GitHub issues

Create an epic issue for this work with child issues per
implementation group. The epic structure follows the implementation
order below. All commits reference their parent issue.

## Implementation order

Dependency-driven ordering. Each skill is written fresh, not patched.

1. **ide-tooling** — restructured first, since other skills reference it
2. **using-superpowers** — keystone meta-skill (draft exists)
3. **verification-before-completion** — universal gate, referenced by many
4. **test-driven-development** — process discipline, referenced by
   language skills and execution pipeline
5. **systematic-debugging + dispatching-parallel-agents** — debugging
   toolkit (natural pair)
6. **brainstorming + writing-plans** — design pipeline (sequential pair)
7. **subagent-driven-development + executing-plans** — execution pipeline
   (alternative modes)
8. **requesting-code-review + receiving-code-review** — quality layer
9. **using-git-worktrees** — workspace isolation
10. **writing-skills** — skill authoring (last because it references
    the conventions established by the other rewrites)
11. **finishing-a-development-branch** — audit work-end, fold gaps
12. **soredium-native cross-references** — update code-review, fix-ci,
    language dev skills
13. **cross-spec update** — update four-phase pipeline spec
    (`docs/specs/2026-07-02-adr-four-phase-review-pipeline.md`) to note
    superpowers integration has landed. File a comment on #66 noting
    that `requesting-code-review` is now a soredium citizen.
14. **commit and validate** — git add all, run validators, sync-local

## Verification

- All 13 skill directories committed to soredium git
  (finishing-a-development-branch is folded into work-end, not
  committed as a separate skill)
- `python3 scripts/validate_all.py --tier commit` passes
- `sync-local` propagates all skills to `~/.claude/skills/`
- Each skill's CSO description follows soredium conventions
- Skill Chaining sections are bidirectional
- No duplicate content between skills and CLAUDE.md
- Spec/plan output paths use soredium workspace conventions
- using-superpowers references all process skills correctly
- ide-tooling exhaustively catalogs all IntelliJ MCP tools
- All code-authoring skills reference ide-tooling and prefer
  structural editing
- Four-phase pipeline spec updated to note superpowers integration
- Comment filed on #66 noting `requesting-code-review` integration

## Token budget analysis

Adding 13 skills increases CSO description scanning by ~39% (from
33 to 46 descriptions). This is manageable:

- CSO descriptions are 100–300 characters each. 13 × 300 = ~3,900
  characters — negligible token cost for scanning.
- Skills load on demand via CSO matching, not all at once. The
  increase in loaded content per session is zero unless a matching
  skill is invoked.
- using-superpowers loads at every session start (it's the meta-skill).
  At 78 lines, this is small. It references other skills by name but
  does not load them.
- **CSO collision risk:** Ensure descriptions are distinct. The most
  likely collision: "Use when implementing" could match both TDD and
  language dev skills. TDD's description should focus on the process
  trigger ("before writing code"), not the activity ("implementing").

The aggregate cost of a full pipeline chain (using-superpowers →
brainstorming → writing-plans → subagent-driven-development →
verification-before-completion) is the sum of individually loaded
skills. This is the designed behaviour — the router pattern means
each loads only when triggered.

## Testing approach

### Structural validation

`python3 scripts/validate_all.py --tier commit` validates all 46
skills: frontmatter, CSO descriptions, flowchart format, naming
conventions, cross-references. This is the primary mechanical gate.

### Script testing

subagent-driven-development has `scripts/review-package` and
`scripts/task-brief`. Per the `externalised-scripts-require-tests.md`
protocol, these require unit tests. Add tests to
`tests/test_subagent_scripts.py`.

### Functional validation

Skills are markdown, not code — functional testing means running
them in real sessions. The verification section's `sync-local`
step enables this. No automated functional test framework exists
for skills; the existing 2010 tests cover Python tooling and
validators, not skill behaviour. Existing tests should not break
since the changes are additive (new skills) plus modifications
to existing skills' Skill Chaining sections.

## Implementation notes

**using-superpowers draft:** A rewritten version has been drafted at
`using-superpowers/SKILL.md` (75 lines). It adds the Process Skills
and Their Gates table, Common Flows section, and Lifecycle Integration
section. Pending: deletion of the stale `references/` directory.

**executing-plans status:** Currently untracked in soredium git (never
committed). Its own SKILL.md notes "if subagents are available, use
subagent-driven-development instead." The rewrite should clarify this
as a direct-execution alternative, not a lesser fallback.
