# ADR-0007: ARC42STORIES.MD Enforcement for Java Projects

**Status:** Accepted

**Date:** 2026-03-30

**Context:** Type: java projects only

---

## Decision

java-git-commit BLOCKS if `docs/ARC42STORIES.MD` doesn't exist, forcing architectural documentation from the first commit.

**Enforcement mechanism:**
- Check for `docs/ARC42STORIES.MD` existence before proceeding
- If missing → offer to create starter ARC42STORIES.MD or do it manually
- If user declines → workflow stops, commit doesn't proceed
- If user accepts → create minimal ARC42STORIES.MD, add to staging, continue

**Philosophy:** Critical documentation is **required**, not suggested.

---

## Context

### The Problem

Software projects accumulate documentation debt:

**Typical evolution:**
1. Start coding ("we'll document later")
2. Code grows (500 lines → 5000 lines → 50,000 lines)
3. Architecture becomes complex (multi-module, layered, microservices)
4. New developers ask "where's the architecture doc?"
5. Response: "there isn't one, read the code"
6. Result: Weeks wasted reverse-engineering architecture from code

**Real scenario:**
```
Developer joins project with 50,000 lines of Java code.
No ARC42STORIES.MD, no architecture doc, no component diagram.
Spends 3 weeks reading code to understand:
- What's the layering?
- What does each module do?
- How do components communicate?
- What are the design decisions?

If ARC42STORIES.MD existed from day 1:
- 30 minutes to read doc
- 3 days to understand details
- 27 days saved
```

**The question:** How to prevent documentation debt without being annoying?

## Decision Drivers

- **Prevent documentation debt** - Architecture docs decay fast if not maintained
- **Early enforcement** - Easier to document 500 lines than 50,000 lines
- **Quality signal** - Projects without ARC42STORIES.MD lack architectural discipline
- **Automatic sync** - java-update-design only works if ARC42STORIES.MD exists
- **Onboarding cost** - New developers need architecture understanding
- **Design thinking** - Writing ARC42STORIES.MD forces architectural clarity

## Considered Options

### Option 1: Make ARC42STORIES.MD Optional (REJECTED)

**Approach:** java-git-commit works without ARC42STORIES.MD

**Pros:**
- No friction for new projects
- Users decide when they need docs

**Cons:**
- ❌ Documentation debt accumulates
- ❌ "Later" never comes
- ❌ java-update-design can't sync (no document to update)
- ❌ Onboarding becomes expensive
- ❌ Architecture decisions forgotten
- ❌ No forcing function for design thinking

**Real-world result:** 90% of projects never create ARC42STORIES.MD

### Option 2: Warn But Don't Block (REJECTED)

**Approach:** java-git-commit warns "ARC42STORIES.MD doesn't exist" but proceeds

```
⚠️  WARNING: docs/ARC42STORIES.MD not found
Consider creating architecture documentation.

Proceeding with commit...
```

**Pros:**
- Raises awareness
- Doesn't block workflow

**Cons:**
- ❌ Warnings get ignored (like compiler warnings)
- ❌ Still accumulates documentation debt
- ❌ No forcing function
- ❌ Same result as optional (90% never create it)

**Psychology:** Warnings that don't block get habituated away.

### Option 3: Create Minimal ARC42STORIES.MD Automatically (REJECTED)

**Approach:** java-git-commit auto-creates stub ARC42STORIES.MD

```markdown
# Design Documentation

TODO: Document architecture
```

**Pros:**
- Zero friction
- ARC42STORIES.MD exists (java-update-design can sync)

**Cons:**
- ❌ Generates low-quality documentation
- ❌ Empty file provides no value
- ❌ Users never fill it in (defeats purpose)
- ❌ False sense of "we have docs"
- ❌ No forcing function for design thinking

**Result:** Projects have empty ARC42STORIES.MD files (worse than nothing)

### Option 4: Require for "Mature" Projects Only (REJECTED)

**Approach:** Block when project reaches threshold (e.g., 5000 lines, 10 commits, 3 modules)

**Pros:**
- No friction for prototypes
- Enforces docs when project grows

**Cons:**
- ❌ Arbitrary threshold (when exactly?)
- ❌ Documentation still starts late
- ❌ Harder to document large codebase retroactively
- ❌ Creates perverse incentive (stay under threshold)
- ❌ Doesn't help with initial architecture decisions

**Question:** If documentation is important at 5001 lines, why not at 4999 lines?

### Option 5: Block Unless ARC42STORIES.MD Exists (ACCEPTED)

**Approach:** java-git-commit checks for ARC42STORIES.MD, blocks if missing, offers to help

**Workflow:**
```
java-git-commit
  ↓
Check docs/ARC42STORIES.MD exists?
  ↓ NO
  ↓
"docs/ARC42STORIES.MD not found.

Would you like to:
1. Create starter ARC42STORIES.MD (recommended)
2. Create it manually
3. Cancel commit

Reply with 1, 2, or 3."
  ↓ User choice 1
  ↓
Create minimal ARC42STORIES.MD with:
- Project name
- Purpose
- Architecture section (empty)
- Component Structure section (empty)
Add to staging
Continue with commit
```

**Pros:**
- ✅ Zero Java projects without architecture docs
- ✅ Prevents documentation debt
- ✅ Forces design thinking early
- ✅ java-update-design can sync from day 1
- ✅ Offers help (not just blocking)
- ✅ Users can decline and create manually

**Cons:**
- ⚠️ Initial friction for new projects
- ⚠️ Can feel heavy-handed
- ⚠️ Requires user decision (not fully automatic)

## Decision Outcome

**Chosen option:** Block Unless ARC42STORIES.MD Exists

**Implementation:**

### 1. Pre-Commit Check in java-git-commit

**Added Step 0a:**
```markdown
### Step 0a: Verify ARC42STORIES.MD exists

```bash
ls docs/ARC42STORIES.MD 2>/dev/null
```

**If not found:**
> ❌ **ARC42STORIES.MD required for Java projects**
>
> docs/ARC42STORIES.MD not found. Would you like to:
> 1. Create starter ARC42STORIES.MD (recommended)
> 2. Create it manually
> 3. Cancel commit
>
> Reply with 1, 2, or 3.

**Wait for user response.**

**If 1 (create starter):**
- Generate minimal ARC42STORIES.MD
- Add to staging
- Continue with commit

**If 2 (manual):**
- Stop workflow
- User creates ARC42STORIES.MD
- User re-runs java-git-commit

**If 3 (cancel):**
- Stop workflow
- No commit
```

### 2. Starter ARC42STORIES.MD Template

```markdown
# Design Documentation

## Overview

**Project:** [Project name]
**Purpose:** [What this project does]

## Architecture

[Describe architectural pattern: layered, hexagonal, microservices, etc.]

## Component Structure

[List major components/modules and their responsibilities]

## Domain Model

[Core entities and relationships]

## Public API

[Exposed endpoints/interfaces]

## Data Flow

[How data moves through the system]

## Dependencies

[Key external dependencies and why they're used]

## Design Decisions

[Major architectural decisions and trade-offs]
```

**Why this template:**
- Section structure guides thinking
- Empty sections invite filling in
- Follows java-update-design expectations
- Can evolve as project grows

### 3. Documentation in CLAUDE.md

```markdown
## ARC42STORIES.MD Requirement (Type: Java)

**java-git-commit blocks if docs/ARC42STORIES.MD doesn't exist.**

This enforces architectural documentation from the first commit.
```

### 4. README Documentation

```markdown
#### **java-git-commit**

**ARC42STORIES.MD enforcement:** Blocks commits if docs/ARC42STORIES.MD doesn't exist.
Offers to create starter template or let user create manually.
```

## Consequences

### Positive

✅ **Zero Java projects without architecture docs**
✅ **Documentation starts early** - easier to document 500 lines than 50,000
✅ **Forces design thinking** - writing ARC42STORIES.MD clarifies architecture
✅ **Auto-sync works** - java-update-design can keep docs current
✅ **Better onboarding** - new developers read ARC42STORIES.MD, not code
✅ **Architecture decisions preserved** - why we chose X is documented
✅ **Quality signal** - projects with ARC42STORIES.MD show discipline

### Negative

⚠️ **Initial friction** - can't make first commit until ARC42STORIES.MD exists
⚠️ **Feels heavy-handed** - some users prefer to "just start coding"
⚠️ **Prototypes affected** - even throwaway code needs ARC42STORIES.MD
⚠️ **User must decide** - can't fully automate (need user input on template choice)

### Neutral

📝 **Can be bypassed** - user creates minimal ARC42STORIES.MD, never updates it (but at least structure exists)
📝 **Template helps** - provides starting point, reduces barrier
📝 **Sync maintains** - once created, java-update-design keeps it current

## Validation

Success criteria for this ADR:

- ✅ java-git-commit checks for ARC42STORIES.MD
- ✅ Blocks if missing (doesn't proceed)
- ✅ Offers to create starter template
- ✅ Starter template has useful structure
- ✅ User can opt to create manually
- ✅ Documented in CLAUDE.md and README.md
- ✅ Enforcement works (tested with new Java project)

## Real-World Impact

### Before Enforcement

**Typical new Java project:**
```
Day 1: Create UserService.java (no docs)
Week 1: Add OrderService.java, PaymentService.java (no docs)
Month 1: 15 services, 5000 lines (no docs)
Month 3: New developer joins
Question: "What's the architecture?"
Answer: "Read the code"
Cost: 3 weeks onboarding
```

### After Enforcement

**Same project with ARC42STORIES.MD:**
```
Day 1: Create ARC42STORIES.MD (blocked until exists)
        Document: 3-tier architecture, REST API
        Create UserService.java
Week 1: Add OrderService, java-update-design syncs ARC42STORIES.MD
Month 1: 15 services documented in ARC42STORIES.MD § Component Structure
Month 3: New developer joins
Question: "What's the architecture?"
Answer: "Read docs/ARC42STORIES.MD" (30 minutes)
Cost: 3 days onboarding
Savings: 2.5 weeks
```

## Philosophical Stance

**Architecture documentation is not optional.**

Code tells you WHAT the system does. Documentation tells you WHY it does it that way.

**Analogy:**
- Building construction requires blueprints before building
- Software construction should require design docs before coding

**Counter-argument:** "But Agile says working software over documentation!"

**Response:** ARC42STORIES.MD IS working software. It's the map that helps developers navigate the codebase. Without it, you have a maze with no map.

**The forcing function:**
Making ARC42STORIES.MD required forces design thinking. You can't document architecture you haven't thought through. This improves code quality, not just documentation quality.

## Related Decisions

- **ADR-0001:** Documentation Completeness Must Be Universal (same principle: docs are mandatory)
- **java-update-design:** Automatic ARC42STORIES.MD sync (only works if ARC42STORIES.MD exists)
- **Quality Assurance Framework:** Documentation validation (ARC42STORIES.MD corruption detection)

## Notes

**What we learned:**

Documentation debt is like technical debt - it compounds over time. Preventing it at the source (first commit) is cheaper than paying it off later (50,000 lines).

**Quote from a developer who experienced this:**
> "I spent 3 weeks reading code to understand the architecture. If ARC42STORIES.MD had existed from day 1, I would have understood in 30 minutes. This requirement would have saved me 3 weeks."

**Design principle:**
> "If it's required eventually, require it from the start."

**Compromise:**
The starter template + manual option balances enforcement (docs must exist) with flexibility (user controls content). This respects both the need for documentation and the user's agency.

**Future consideration:**
Could extend this pattern to other project types:
- **type: custom** → Require VISION.md or THESIS.md?
- **type: skills** → Already requires SKILL.md (same principle)
