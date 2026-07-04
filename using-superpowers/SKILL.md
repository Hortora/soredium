---
name: using-superpowers
description: Use when starting any conversation - establishes how to find and use skills, requiring skill invocation before ANY response including clarifying questions
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, ignore this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.

IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.

This is not negotiable. You cannot rationalize your way out of this.
</EXTREMELY-IMPORTANT>

## The Rule

**Invoke relevant or requested skills BEFORE any response or action** — including clarifying questions, exploring the codebase, or checking files. If it turns out wrong for the situation, you don't have to use it.

**Before entering plan mode:** if you haven't already brainstormed, invoke the brainstorming skill first.

Then announce "Using [skill] to [purpose]" and follow the skill exactly. If it has a checklist, create a todo per item.

## Process Skills and Their Gates

Process skills enforce discipline. They come before implementation skills — always.

| Process Skill | Gate | Trigger |
|---|---|---|
| **brainstorming** | No implementation without approved design | "Let's build X", any creative work |
| **systematic-debugging** | No fix without root cause | "Fix this bug", unexpected behaviour |
| **test-driven-development** | No production code without failing test | Any implementation task |
| **verification-before-completion** | No "done" claim without evidence | Before any commit, PR, or completion claim |
| **writing-plans** | No execution without detailed plan | After brainstorming, before implementation |

## Common Flows

These are the typical skill chains. Don't skip intermediate skills.

- **Build:** brainstorming → writing-plans → subagent-driven-development (or executing-plans) → work-end
- **Fix:** systematic-debugging → test-driven-development → domain skill → verification-before-completion
- **Multi-failure:** systematic-debugging → dispatching-parallel-agents → verification-before-completion
- **Close:** verification-before-completion → code-review → git-commit → work-end

## Lifecycle Integration

Skills fire at specific lifecycle points — not only on user request:

- **Session start:** work (detects state, routes to work-start or work-resume)
- **Mid-session:** forage SWEEP and protocol SWEEP for knowledge capture at natural pauses
- **Pre-commit:** code-review, verification-before-completion
- **Branch close:** work-end (includes artifact promotion, review gate, issue closure)

## Red Flags

These thoughts mean STOP — you're rationalizing:

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
| "Let me gather information first" | Skills tell you HOW to gather information. |
| "This doesn't need a formal skill" | If a skill exists, use it. |
| "I remember this skill" | Skills evolve. Read current version. |
| "This doesn't count as a task" | Action = task. Check for skills. |
| "The skill is overkill" | Simple things become complex. Use it. |
| "I'll just do this one thing first" | Check BEFORE doing anything. |
| "This feels productive" | Undisciplined action wastes time. Skills prevent this. |
| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |

## User Instructions

User instructions (CLAUDE.md, AGENTS.md, GEMINI.md, etc, direct requests) take precedence over skills, which in turn override default behavior. Only skip skill workflows or instructions when your human partner has explicitly told you to.
