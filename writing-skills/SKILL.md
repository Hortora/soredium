---
name: writing-skills
description: Use when creating new skills, editing existing skills, or verifying skills work before deployment
---

# Writing Skills

## Overview

**Writing skills IS Test-Driven Development applied to process
documentation.**

Write test cases (pressure scenarios with subagents), watch them fail
(baseline behavior), write the skill (documentation), watch tests pass
(agents comply), and refactor (close loopholes).

**Core principle:** If you didn't watch an agent fail without the skill,
you don't know if the skill teaches the right thing.

**Required background:** You MUST understand test-driven-development
before using this skill. That skill defines the fundamental
RED-GREEN-REFACTOR cycle. This skill adapts TDD to documentation.

**Official guidance:** See [anthropic-best-practices.md](anthropic-best-practices.md)
for Anthropic's official skill authoring best practices.

## When to Create a Skill

**Create when:**
- Technique wasn't intuitively obvious to you
- You'd reference this again across projects
- Pattern applies broadly (not project-specific)
- Others would benefit

**Don't create for:**
- One-off solutions
- Standard practices well-documented elsewhere
- Project-specific conventions (put in CLAUDE.md or protocols)
- Mechanical constraints (if enforceable with regex/validation,
  automate it — save documentation for judgment calls)

## Frontmatter, Naming, and CSO

See CLAUDE.md for the authoritative rules on:
- Frontmatter format (name, description fields)
- Naming conventions (kebab-case, letters-numbers-hyphens)
- CSO description rules (triggering conditions only, no workflow
  summary)
- Section naming conventions
- Flowchart format (Mermaid `flowchart TD`)

This skill does not restate those rules. What follows is what CLAUDE.md
doesn't cover: the TDD methodology for skills.

## The Iron Law (Same as TDD)

```
NO SKILL WITHOUT A FAILING TEST FIRST
```

This applies to NEW skills AND EDITS to existing skills.

Write skill before testing? Delete it. Start over.
Edit skill without testing? Same violation.

**No exceptions:**
- Not for "simple additions"
- Not for "just adding a section"
- Not for "documentation updates"
- Don't keep untested changes as "reference"
- Delete means delete

## RED-GREEN-REFACTOR for Skills

### RED: Write Failing Test (Baseline)

Run pressure scenario with subagent WITHOUT the skill. Document exact
behavior:
- What choices did they make?
- What rationalizations did they use (verbatim)?
- Which pressures triggered violations?

This is "watch the test fail" — you must see what agents naturally do
before writing the skill.

### GREEN: Write Minimal Skill

Write skill that addresses those specific rationalizations. Don't add
extra content for hypothetical cases.

Run same scenarios WITH skill. Agent should now comply.

### REFACTOR: Close Loopholes

Agent found new rationalization? Add explicit counter. Re-test until
bulletproof.

### Micro-Test Wording Before Full Scenarios

Full pressure-scenario runs are the final gate, but they are slow and
expensive per iteration. Verify the wording itself first:

1. **One fresh-context sample per call** — system prompt = realistic
   context (full skill, not guidance in isolation); user message = a
   task that tempts the failure.
2. **Always include a no-guidance control.** If the control doesn't
   exhibit the failure, there is nothing to fix.
3. **5+ reps per variant.** Single samples lie.
4. **Manually read every flagged match.** Automated counts overstate
   both failure and success.
5. **Variance is a metric.** Five different interpretations = wording
   isn't binding. Tighten the form before adding words.

**Testing methodology:** See [testing-skills-with-subagents.md](testing-skills-with-subagents.md)
for the complete methodology: how to write pressure scenarios, pressure
types (time, sunk cost, authority, exhaustion), plugging holes
systematically, meta-testing techniques.

## Match the Form to the Failure

Before writing guidance, classify the baseline failure. The form that
bulletproofs one failure type measurably backfires on another.

| Baseline failure | Right form | Wrong form |
|---|---|---|
| Skips/violates a rule under pressure | Prohibition + rationalization table + red flags | Soft guidance ("prefer...", "consider...") |
| Complies, but output has the wrong shape | Positive recipe: state what the output IS | Prohibition list ("don't X") |
| Omits a required element | Structural: REQUIRED field or slot in template | Prose reminders near the template |
| Behavior should depend on a condition | Conditional keyed to an observable predicate | Unconditional rule + exemption clauses |

**Why prohibitions backfire on shaping problems:** under a competing
incentive, agents negotiate with "don't X." In wording tests, the
prohibition arm produced more unwanted content than the recipe arm —
and trended worse than the no-guidance control.

**Rules for whichever form you pick:**
- **No nuance clauses.** "Don't X unless it matters" reopens the
  negotiation. Express real exceptions as conditionals on observable
  predicates.
- **Exemption clauses don't scope.** "This limit doesn't apply to code
  blocks" still suppresses code blocks. Restructure so the rule can't
  reach exempt content.

## Bulletproofing Against Rationalization

Skills that enforce discipline need to resist rationalization. Agents
are smart and will find loopholes when under pressure.

**Scope:** this toolkit is for discipline failures — an agent that knows
the rule and skips it under pressure. For wrong-shaped output or omitted
elements, use the forms in Match the Form to the Failure instead.

### Close Every Loophole Explicitly

Don't just state the rule — forbid specific workarounds:

```markdown
Write code before test? Delete it. Start over.

**No exceptions:**
- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Don't look at it
- Delete means delete
```

### Address "Spirit vs Letter" Arguments

Add foundational principle early:

```markdown
**Violating the letter of the rules is violating the spirit of the rules.**
```

### Build Rationalization Table

Capture rationalizations from baseline testing. Every excuse agents
make goes in the table:

```markdown
| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
```

### Create Red Flags List

Make it easy for agents to self-check when rationalizing:

```markdown
## Red Flags — STOP and Start Over

- Code before test
- "I already manually tested it"
- "This is different because..."

**All of these mean: Delete code. Start over with TDD.**
```

**Psychology foundation:** See [persuasion-principles.md](persuasion-principles.md)
for the research foundation (authority, commitment, scarcity, social
proof, unity principles).

## Validation Infrastructure

After writing a skill, run soredium's validators for mechanical
validation:

```bash
python3 scripts/validate_all.py --tier commit
```

This checks frontmatter, CSO descriptions, flowchart format, naming
conventions, cross-references, and structure. Soredium's validators
check structure; writing-skills' testing methodology checks behaviour.

## Skill Creation Checklist (TDD Adapted)

**Create a todo for EACH item.**

**RED Phase — Write Failing Test:**
- [ ] Create pressure scenarios (3+ combined pressures for discipline
      skills)
- [ ] Run scenarios WITHOUT skill — document baseline behavior verbatim
- [ ] Identify patterns in rationalizations/failures

**GREEN Phase — Write Minimal Skill:**
- [ ] Skill addresses specific baseline failures identified in RED
- [ ] Guidance form matches the failure type (see Match the Form)
- [ ] For behavior-shaping guidance: wording micro-tested (5+ reps)
- [ ] Run scenarios WITH skill — verify agents now comply

**REFACTOR Phase — Close Loopholes:**
- [ ] Identify NEW rationalizations from testing
- [ ] Add explicit counters (if discipline skill)
- [ ] Build rationalization table from all test iterations
- [ ] Create red flags list
- [ ] Re-test until bulletproof

**Quality Checks:**
- [ ] Run `python3 scripts/validate_all.py --tier commit`
- [ ] Flowcharts use Mermaid `flowchart TD` (not dot digraph)
- [ ] No `hortora:` prefixes in skill references

**Deployment:**
- [ ] Commit skill to git
- [ ] Run `sync-local` to propagate to `~/.claude/skills/`

## Common Rationalizations for Skipping Testing

| Excuse | Reality |
|--------|---------|
| "Skill is obviously clear" | Clear to you ≠ clear to other agents. Test it. |
| "It's just a reference" | References can have gaps. Test retrieval. |
| "Testing is overkill" | Untested skills have issues. Always. |
| "I'll test if problems emerge" | Problems = agents can't use skill. Test BEFORE. |
| "Too tedious to test" | Testing is less tedious than debugging bad skill. |
| "No time to test" | Deploying untested skill wastes more time later. |

## STOP: Before Moving to Next Skill

**After writing ANY skill, STOP and complete the deployment process.**

Do NOT create multiple skills in batch without testing each. Deploying
untested skills = deploying untested code.

## Skill Chaining

**Invoked by:**
- `using-superpowers` — when a user needs to create or edit a skill

**Complements:**
- `test-driven-development` — this skill IS TDD applied to
  documentation. Same Iron Law, same cycle, same principles.
- `verification-before-completion` — after writing and testing, verify
  validators pass before claiming done.
