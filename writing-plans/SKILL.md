---
name: writing-plans
description: >
  Use when you have a spec or requirements for a multi-step task, before
  touching code. Writes a structured plan file to docs/plans/ with TDD steps
  and task decomposition. This is NOT the built-in EnterPlanMode — use this
  skill instead of plan mode for implementation planning.
---

# Writing Plans

## Overview

Write comprehensive implementation plans assuming the engineer has zero
context for the codebase and questionable taste. Document everything they
need: which files to touch for each task, code, testing, docs they might
need to check, how to test it. Give them the whole plan as bite-sized
tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about the
toolset or problem domain. Assume they don't know good test design
very well.

**Announce at start:** "I'm using the writing-plans skill to create the
implementation plan."

**Save plans to:** `docs/plans/YYYY-MM-DD-<feature-name>.md`
(user preferences for plan location override this default)

## Scope Check

If the spec covers multiple independent subsystems, it should have been
broken into sub-project specs during brainstorming. If it wasn't, suggest
breaking this into separate plans — one per subsystem. Each plan should
produce working, testable software on its own.

## File Structure

Before defining tasks, map out which files will be created or modified
and what each one is responsible for. This is where decomposition
decisions get locked in.

**IntelliJ MCP is required.** Before writing the plan, verify IntelliJ
is available:
```bash
# Check via ide_index_status — if this fails, STOP
```
If IntelliJ MCP is unavailable, **stop and tell the user**. Do not write
a plan that assumes bash for code operations — the plan's implementer
will use the tools the plan specifies, and bash file operations bypass
reference updates.

If IntelliJ becomes unavailable mid-session (MCP connection drops), stop
plan execution immediately and inform the user. Do not fall back to bash.

When exploring the existing codebase to determine file paths and
understand current architecture, use ide-tooling for navigation
(`ide_find_class`, `ide_find_symbol`, `ide_find_references`,
`ide_type_hierarchy`) rather than bash grep/find. For refactoring
operations (rename, move), use `ide_refactor_rename` and `ide_move_file`.

- Design units with clear boundaries and well-defined interfaces. Each
  file should have one clear responsibility.
- Prefer smaller, focused files over large ones that do too much.
- Files that change together should live together. Split by
  responsibility, not by technical layer.
- In existing codebases, follow established patterns. If a file you're
  modifying has grown unwieldy, including a split in the plan is
  reasonable.

This structure informs the task decomposition. Each task should produce
self-contained changes that make sense independently.

## Task Right-Sizing

A task is the smallest unit that carries its own test cycle and is worth
a fresh reviewer's gate. When drawing task boundaries: fold setup,
configuration, scaffolding, and documentation steps into the task whose
deliverable needs them; split only where a reviewer could meaningfully
reject one task while approving its neighbor. Each task ends with an
independently testable deliverable.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" — step
- "Run it to make sure it fails" — step
- "Implement the minimal code to make the test pass" — step
- "Run the tests and make sure they pass" — step
- "Commit" — step

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> subagent-driven-development (recommended) or executing-plans to
> implement this plan task-by-task. Each task follows TDD
> (test-driven-development) and uses ide-tooling for structural
> editing. Steps use checkbox (`- [ ]`) syntax for tracking.

**Focal issue:** #[N] — [title]
**Issue group:** #[N1], #[N2], ... (if branch covers multiple issues)

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

## Global Constraints

[The spec's project-wide requirements — version floors, dependency
limits, naming and copy rules, platform requirements — one line each,
with exact values copied verbatim from the spec. Every task's
requirements implicitly include this section.]

---
```

## Task Structure

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Move: `old/path.py` → `new/path.py` (use `ide_move_file`)
- Delete: `exact/path/to/old.py` (use `ide_refactor_safe_delete`)
- Rename: `OldName` → `NewName` (use `ide_refactor_rename`)
- Test: `tests/exact/path/to/test.py`

**Interfaces:**
- Consumes: [what this task uses from earlier tasks — exact signatures]
- Produces: [what later tasks rely on — exact function names, parameter
  and return types. A task's implementer sees only their own task; this
  block is how they learn the names and types neighboring tasks use.]

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

Use `ide_insert_member` for new methods, `ide_replace_member` for fixing
existing implementations. See ide-tooling for the full editing preference
hierarchy.

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## No Placeholders

Every step must contain the actual content an engineer needs. These are
**plan failures** — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — the engineer may be reading
  tasks out of order)
- Steps that describe what to do without showing how (code blocks
  required for code steps)
- References to types, functions, or methods not defined in any task
- **Bash cp/rm/mv for source files** — use `ide_move_file`, `ide_refactor_safe_delete`,
  `ide_refactor_rename` instead. Bash bypasses reference updates and breaks imports.
  Only use bash for non-code files (config, docs, scripts).

## Remember
- Exact file paths always
- Complete code in every step — if a step changes code, show the code
- Exact commands with expected output
- DRY, YAGNI, TDD, frequent commits

## Self-Review

After writing the complete plan, look at the spec with fresh eyes and
check the plan against it. This is a checklist you run yourself — not
a subagent dispatch.

**1. Spec coverage:** Skim each section/requirement in the spec. Can
you point to a task that implements it? List any gaps.

**2. Placeholder scan:** Search your plan for red flags — any of the
patterns from the "No Placeholders" section above. Fix them.

**3. Type consistency:** Do the types, method signatures, and property
names you used in later tasks match what you defined in earlier tasks?
A function called `clearLayers()` in Task 3 but `clearFullLayers()` in
Task 7 is a bug.

**4. Tooling safety scan:** Search every task for bash file operations on
source files. Any `cp`, `rm`, `mv`, `mkdir` targeting `.java`, `.ts`,
`.tsx`, `.py`, `.kt` files is a plan failure. Replace with:
- File moves → `ide_move_file`
- File deletes → `ide_refactor_safe_delete`
- Renames → `ide_refactor_rename`
- New members → `ide_insert_member`
- Body rewrites → `ide_replace_member`

Bash is only acceptable for non-code files (config, docs, scripts, test
fixtures) and for git/build commands.

If you find issues, fix them inline. No need to re-review — just fix
and move on. If you find a spec requirement with no task, add the task.

Optionally, dispatch a plan reviewer subagent using the template at
[plan-document-reviewer-prompt.md](plan-document-reviewer-prompt.md)
for an independent review.

## Execution Handoff

After saving the plan, offer execution choice:

**"Plan complete and saved to `docs/plans/<filename>.md`. Two execution
options:**

**1. Subagent-Driven (recommended for plans with 3+ independent tasks
or when review between tasks adds value)** — dispatch a fresh subagent
per task, two-stage review between tasks, fast iteration.

**2. Inline Execution (for simple sequential plans or when subagent
overhead isn't justified)** — execute tasks in this session, batch
execution with checkpoints.

**Which approach?"**

**If Subagent-Driven chosen:**
- Invoke subagent-driven-development
- Fresh subagent per task + two-stage review

**If Inline Execution chosen:**
- Invoke executing-plans
- Batch execution with checkpoints for review

## Success Criteria

Plan is complete when:

- ✅ Spec reviewed and understood (gaps identified and resolved)
- ✅ Tasks decomposed with clear acceptance criteria
- ✅ Dependencies between tasks identified
- ✅ Plan written to file and path communicated to execution skill
- ✅ User approved the plan

**Not complete until** the user confirms and an execution skill is invoked.

## Skill Chaining

**Invoked by:**
- `brainstorming` — primary upstream. Brainstorming produces the spec;
  this skill produces the plan.

**Invokes:**
- `subagent-driven-development` — premium execution mode (recommended
  for 3+ independent tasks)
- `executing-plans` — direct execution mode (sequential plans, low
  overhead)

**Complements:**
- `test-driven-development` — every implementation task in the plan
  follows TDD. The plan encodes this in its step structure (write
  failing test → verify fail → implement → verify pass).
- `ide-tooling` — plans note structural editing as the preferred code
  authoring approach. Implementers use Navigate tools for understanding
  code, Edit tools for writing it.
- `verification-before-completion` — after each task in the plan, verify
  before marking done.
