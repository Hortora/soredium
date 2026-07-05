---
name: requesting-code-review
description: >
  Use when completing tasks, implementing major features, or before merging
  to verify work meets requirements. Dispatches a fresh subagent for review —
  distinct from the session-level code-review skill which reviews staged changes
  using language-specific checklists.
---

# Requesting Code Review

Dispatch a code reviewer subagent to catch issues before they cascade.
The reviewer gets precisely crafted context for evaluation — never your
session's history. This keeps the reviewer focused on the work product,
not your thought process, and preserves your own context for continued
work.

**Core principle:** Review early, review often.

## Distinction from code-review

Two review mechanisms exist — they complement each other:

| | `code-review` | `requesting-code-review` |
|---|---|---|
| **What** | Pre-commit checklist review of staged changes | Independent subagent review of a git range |
| **When** | Before every commit | After significant work (feature, pre-merge) |
| **How** | Session-level, uses language-specific checklists | Fresh subagent with isolated context |
| **Depth** | Checklist-driven: naming, patterns, test gaps | Architectural: design, plan alignment, integration |

Use `code-review` for the routine commit gate. Use this skill for
independent review of significant work.

## When to Request Review

**Mandatory:**
- After each task in subagent-driven-development
- After completing a major feature

**Optional but valuable:**
- When stuck (fresh perspective)
- Before refactoring (baseline check)
- After fixing complex bug

## How to Request

**1. Get git SHAs:**
```bash
BASE_SHA=$(git rev-parse HEAD~1)  # or origin/main
HEAD_SHA=$(git rev-parse HEAD)
```

**2. Dispatch code reviewer subagent:**

Dispatch a `general-purpose` subagent, filling the template at
[code-reviewer.md](code-reviewer.md).

The reviewer should apply the relevant language-specific code-review
checklist: `java-dev` for Java/Quarkus, `ts-dev` for TypeScript,
`python-dev` for Python. These cover framework-specific patterns,
assertion libraries, and testing conventions.

**Placeholders:**
- `{DESCRIPTION}` — brief summary of what you built
- `{PLAN_OR_REQUIREMENTS}` — what it should do
- `{BASE_SHA}` — starting commit
- `{HEAD_SHA}` — ending commit

**3. Act on feedback:**
- Fix Critical issues immediately
- Fix Important issues before proceeding
- Note Minor issues for later
- Push back if reviewer is wrong (with reasoning)

## Example

```
[Just completed Task 2: Add verification function]

You: Let me request code review before proceeding.

BASE_SHA=$(git log --oneline | grep "Task 1" | head -1 | awk '{print $1}')
HEAD_SHA=$(git rev-parse HEAD)

[Dispatch code reviewer subagent]
  DESCRIPTION: Added verifyIndex() and repairIndex() with 4 issue types
  PLAN_OR_REQUIREMENTS: Task 2 from docs/plans/deployment-plan.md
  BASE_SHA: a7981ec
  HEAD_SHA: 3df7661

[Subagent returns]:
  Strengths: Clean architecture, real tests
  Issues:
    Important: Missing progress indicators
    Minor: Magic number (100) for reporting interval
  Assessment: Ready to proceed

You: [Fix progress indicators]
[Continue to Task 3]
```

## Red Flags

**Never:**
- Skip review because "it's simple"
- Ignore Critical issues
- Proceed with unfixed Important issues
- Argue with valid technical feedback

**If reviewer wrong:**
- Push back with technical reasoning
- Show code/tests that prove it works
- Request clarification

See template at: [code-reviewer.md](code-reviewer.md)

## Skill Chaining

**Invoked by:**
- `subagent-driven-development` — final whole-branch review after all
  tasks complete

**Complements:**
- `code-review` — different scope. `code-review` is the routine
  pre-commit checklist. This skill is the independent subagent review
  for significant work.
- `receiving-code-review` — after this skill dispatches a review and
  findings come back, receiving-code-review governs how to handle the
  feedback (verify before implementing, push back when justified).
- `verification-before-completion` — review findings don't replace
  verification. Both are required before claiming done.
