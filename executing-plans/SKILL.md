---
name: executing-plans
description: Use when you have a written implementation plan to execute in a separate session with review checkpoints
---

# Executing Plans

Load plan, review critically, execute all tasks with TDD and
verification, report when complete.

**Announce at start:** "I'm using the executing-plans skill to implement
this plan."

This is the direct-execution path — you implement the tasks yourself in
this session. Use when the plan is sequential and the overhead of
subagent dispatch and inter-task review isn't justified. For plans with
3+ independent tasks or when review between tasks adds value, use
subagent-driven-development instead.

## The Process

### Step 1: Load and Review Plan

1. Read the plan file
2. Review critically — identify any questions or concerns about the plan
3. If concerns: Raise them with your human partner before starting
4. If no concerns: Create todos for all plan items and proceed

### Step 2: Execute Tasks

For each task:
1. Mark as in_progress
2. Follow TDD: write failing test, verify it fails, write minimal code
   to pass, verify all green. See test-driven-development for the full
   red-green-refactor cycle.
3. Use ide-tooling for code operations: structural editing
   (`ide_insert_member`, `ide_replace_member`) for class members,
   semantic refactoring (`ide_refactor_rename`, `ide_move_file`) for
   cross-cutting changes, text edits (Edit tool) for non-structural
   files.
4. Run verification-before-completion: execute the verification command,
   read the full output, confirm it supports the claim that the task is
   complete.
5. Mark as completed

### Step 3: Complete Development

After all tasks complete and verified:
1. Run code-review on the staged changes
2. Invoke work-end to verify, close the branch, and push

## When to Stop and Ask for Help

**STOP executing immediately when:**
- Hit a blocker (missing dependency, test fails, instruction unclear)
- Plan has critical gaps preventing progress
- You don't understand an instruction
- Verification fails repeatedly

**Ask for clarification rather than guessing.**

## When to Revisit Earlier Steps

**Return to Review (Step 1) when:**
- Partner updates the plan based on your feedback
- Fundamental approach needs rethinking

**Don't force through blockers** — stop and ask.

## Remember

- Review plan critically first
- Follow plan steps exactly
- Follow TDD for every implementation task
- Use ide-tooling for code operations
- Run verification-before-completion after each task
- Stop when blocked, don't guess
- Never start implementation on main/master branch without explicit
  user consent

## Skill Chaining

**Invoked by:**
- `writing-plans` — execution handoff (for simple sequential plans or
  when subagent overhead isn't justified)

**Invokes:**
- `code-review` — before final commit
- `verification-before-completion` — after each task, verify before
  marking done
- `work-end` — complete development after all tasks

**Complements:**
- `test-driven-development` — every task follows TDD during execution.
- `ide-tooling` — all code operations use the editing preference
  hierarchy (structural → semantic → text).
- `subagent-driven-development` — alternative execution mode with
  per-task subagent dispatch and review gates.
- `writing-plans` — creates the plan this skill executes.
