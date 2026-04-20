# Garden Entry Formats

Reference for all entry file formats used by forage CAPTURE and SWEEP.

---

## File Naming

```
${HORTORA_GARDEN:-~/.hortora/garden}/<domain>/GE-YYYYMMDD-xxxxxx.md
```

REVISE entries include "revise" in the filename:
```
${HORTORA_GARDEN:-~/.hortora/garden}/<domain>/GE-YYYYMMDD-xxxxxx-revise-<target-slug>.md
```

**Version policy for the Stack field:**
- **Third-party libraries:** Always include version or range — `Quarkus 3.9.x`, `tmux 3.2+`, `GraalVM 25`. The gotcha may be fixed in a later version; future readers need to know if it applies to them.
- **"all versions"** — only use when the behaviour is fundamental: `Java (all versions with lambda)`, `JEXL3 (all versions)`.
- **Own pre-1.0 projects** — omit version entirely; revisit when 1.0 ships.

---

## Optional Frontmatter Fields

These fields can be added to any entry type. The validator accepts but does not require them.

| Field | Type | Purpose |
|-------|------|---------|
| `verified_on` | string | Version(s) this was verified on. Used by forage SEARCH to produce a concrete staleness annotation rather than a generic age warning. Example: `"quarkus: 3.34.2"` or `"tmux: 3.4"`. Only meaningful for library/tool-specific entries — omit for technique/cross-cutting entries. |
| `last_reviewed` | YYYY-MM-DD | Date of last manual staleness review. Resets the staleness clock — forage SWEEP and harvest REVIEW use `max(submitted, last_reviewed)` as the reference date when computing entry age. Set by forage SWEEP (Confirm) and harvest REVIEW (Confirm). |
| `author` | string | Your initials or handle — appears on the contributor scoreboard. Set automatically by forage at CAPTURE time from `~/.claude/settings.json` `initials`. Example: `"mdp"` |
| `constraints` | string or list | What conditions must hold for this fix to apply. Freetext: `"requires Java 17+, not applicable to reactive pipelines"`. Structured: `[{applies_when: "java.version >= 17", note: "uses sealed classes"}]`. Each format earns the same +1 bonus. |
| `invalidation_triggers` | string or list | What changes would make this entry wrong. Freetext: `"revisit if Spring Boot 4.0 changes auto-configuration"`. Structured: `[{library: "spring-boot", version: ">= 4.0", reason: "model may change"}]`. Earns +1 bonus. |

**Bonus scoring:** `validate_pr.py` awards +1 per WHY field present (up to +3 effective bonus). The base score gate (≥8) applies to the self-reported score only — bonus points don't bypass it. Effective score = base + bonus and is used by the contributor scoreboard.

**Adding to an entry frontmatter:**

```yaml
staleness_threshold: 730
verified_on: "quarkus: 3.34.2"   # optional — omit if not applicable
last_reviewed: 2026-04-14         # optional — set by staleness review
author: "mdp"                     # optional — set by forage at CAPTURE time
constraints: "requires Java 17+"  # optional — adds +1 bonus
invalidation_triggers: "revisit if library major-version ships"  # optional — adds +1 bonus
submitted: 2026-04-14
```

**Why this fix section** (optional body section, scores ≥12 only):

For entries scoring 12 or above, forage CAPTURE will prompt for an optional rationale. If provided, it is added as a body section after **Why this is non-obvious**:

```markdown
### Why this fix
[Why this approach over the obvious alternative — written by submitter at capture time]
```

---

## Gotcha Template

Bug, silent failure, or workaround:

```markdown
---
id: GE-YYYYMMDD-xxxxxx
garden: discovery
title: "Short imperative title — the weird thing, not the fix"
type: gotcha
domain: tools
stack: "Technology, Library, Version"
tags: [tag1, tag2]
score: N
verified: true
staleness_threshold: 730
submitted: YYYY-MM-DD
---

## Short imperative title — the weird thing, not the fix

**ID:** GE-YYYYMMDD-xxxxxx
**Stack:** Technology, Library, Version — e.g. `Quarkus 3.9.x`, `tmux 3.2+`, `GraalVM 25`
**Symptom:** What you observe — especially the misleading part. Quote exact
error messages. "No error" is important context.
**Context:** When/where this applies. What setup triggers it.

### What was tried (didn't work)
*(mandatory heading — do not inline or omit)*
- tried X — result
- tried Y — result

### Root cause
Why it happens. The underlying mechanism — WHY, not just WHAT.

### Fix *(or "None known — workaround: [X]" if unsolved)*
Code block or config. Be complete. Include what NOT to do alongside what works.
If no fix exists yet, describe the best available workaround — the entry is still worth capturing.
A REVISE submission can add a solution later.

### Alternatives considered *(optional — adds +1 bonus; omit if no meaningful alternatives)*
- Alternative A — reason it was rejected or why it didn't work
- Alternative B — reason it was rejected or why it didn't work

### Why this is non-obvious
The insight. What makes this a gotcha? Why would a skilled developer be misled?

*Score: N/15 · Included because: [why this belongs] · Reservation: [none / brief reason]*
```

---

## Technique Template

Specific how-to, strategic approach, design philosophy, or pattern — all non-obvious positive knowledge:

```markdown
---
id: GE-YYYYMMDD-xxxxxx
garden: discovery
title: "Short active title — what you can do"
type: technique
domain: tools
stack: "Technology, Library, Version"
tags: [tag1, tag2]
score: N
verified: true
staleness_threshold: 730
submitted: YYYY-MM-DD
---

## Short active title — what you can do

**ID:** GE-YYYYMMDD-xxxxxx
**Stack:** Technology, Library, Version
**Labels:** `#label1` `#label2`
**What it achieves:** One sentence — the outcome this technique produces.
**Context:** When/where this applies. What problem it solves.

### The technique
Code block or concrete description. Complete and runnable.

### Alternatives considered *(optional — adds +1 bonus; omit if no meaningful alternatives)*
- Alternative A — reason most developers reach for this instead and why it's less good

### Why this is non-obvious
What would most developers do instead? Why wouldn't they reach for this?
What's the insight that makes it work?

### When to use it
Conditions where this applies. Any limitations or caveats.

*Score: N/15 · Included because: [why this belongs] · Reservation: [none / brief reason]*
```

**Choosing tags:** Pick tags that describe the *cross-cutting character* — `#strategy` for broad design philosophy, `#testing` for test patterns, `#ci-cd` for pipeline concerns, `#performance`, `#debugging`, or technology tags like `#tmux`, `#llm-testing`. Check the Tag Index in GARDEN.md first; reuse existing tags before inventing new ones.

---

## Undocumented Template

Behaviour, feature, or option not in official docs:

```markdown
---
id: GE-YYYYMMDD-xxxxxx
garden: discovery
title: "Short title — describes what exists, not that it's undocumented"
type: undocumented
domain: tools
stack: "Technology, Library, Version"
tags: [tag1, tag2]
score: N
verified: true
staleness_threshold: 730
submitted: YYYY-MM-DD
---

## Short title — describes what exists, not that it's undocumented

**ID:** GE-YYYYMMDD-xxxxxx
**Stack:** Technology, Library, Version — version matters here as undocumented behaviour may appear/disappear across releases
**What it is:** One sentence — the feature, behaviour, or option that exists.
**How discovered:** Source code reading / trial and error / someone told me / commit history

### Description
Full description of what this does. Treat it as documentation that doesn't
exist yet. Be precise about conditions, defaults, edge cases.

### How to use it / where it appears
Code block or concrete example. Show it working.

### Alternatives considered *(optional — adds +1 bonus; omit if no meaningful alternatives)*
- Alternative A — the documented approach that doesn't work / is harder

### Why it's not obvious
Why would someone not know this exists? Is it in the source but not the docs?
Only mentioned in a GitHub issue? Only in an old commit message?

### Caveats
Any limitations, version constraints, or risks from relying on undocumented behaviour.

*Score: N/15 · Included because: [why this belongs] · Reservation: [none / brief reason]*
```

---

## Revise Template

**Submission ID:** GE-YYYYMMDD-xxxxxx (the new revision's own ID)
**Target entry:** GE-XXXX — [title of entry being revised]

REVISE modifies the target entry file directly. No separate file is created.

**Revision kind guide:**

| Kind | When to use | How to apply |
|------|------------|-------------|
| `solution` | Gotcha had no fix — now there's a real fix | If Fix says "None known": replace with solution. If Fix already has one: restructure into Solution 1 / Solution 2 (see below). |
| `alternative` | Entry has one solution — found a different approach | Add `### Alternative — [brief name]` after existing Fix section with pros/cons. |
| `variant` | Same pattern in a different context | Add `## Variant — [context]` section within the file. |
| `update` | Additional context, edge cases, or discovery | Append to the relevant section (Root cause, Context, Caveats, etc.). |
| `resolved` | Library/tool fixed the bug in a newer version | Add `**Resolved in: vX.Y** — [brief note]` after the **Stack** line. Keep entry intact. |
| `deprecated` | Feature removed or approach obsolete | Add `**Deprecated:** [reason and date]` near the top. Keep entry for historical reference. |

**Multiple Solutions structure** — only when 2 or more solutions exist:

```markdown
### Solution 1 — [brief descriptive name]
**Approach:** [one sentence]
**Pros:** [what makes it good]
**Cons/trade-offs:** [limitations, constraints]
[code block]

### Solution 2 — [brief descriptive name]
**Approach:** [one sentence]
**Pros:** [what makes it good]
**Cons/trade-offs:** [limitations, constraints]
[code block]
```

Single solutions never get pros/cons structure. Only restructure when a second solution is being added.

**Score line:** Append a score line for the revision itself (not the original entry score):
```
*Revision score: N/15 · Adds: [what's new] · Reservation: [none / brief reason]*
```

**Critical:** For `resolved` entries — never delete the original content. Users on older versions still need it. Add the resolved note and keep everything else.

---

## Scoring Dimensions

Rate each dimension 1–3:

| Dimension | 1 | 2 | 3 |
|-----------|---|---|---|
| **Non-obviousness** | Somewhat surprising; findable with effort | Would mislead most experienced devs | Would stump even experts; deeply counterintuitive |
| **Discoverability** | Buried in docs but findable | Source code / GitHub issues only | Trial and error; effectively invisible |
| **Breadth** | Narrow edge case or rare setup | Common pattern; many users will hit this | Affects almost anyone using this technology |
| **Pain / Impact** | Annoying but quickly diagnosed | Significant time loss; misleading symptoms | Silent failure, production risk, or data loss |
| **Longevity** | May be fixed or changed soon | Stable API; unlikely to change near-term | Fundamental behaviour; essentially permanent |

---

## patterns-garden Entry Template

```yaml
---
id: GE-YYYYMMDD-xxxxxx
garden: patterns
title: "Pattern name"
type: architectural | migration | integration | testing
domain: jvm | python | tools | web | data | infrastructure | security | cloud
stack: "Technology, Version"
tags: [tag1, tag2]
score: N
verified: true
staleness_threshold: 3650
submitted: YYYY-MM-DD
---
```

**Body sections:**

```markdown
## Pattern

[One paragraph: what problem this solves and why it works]

## Structure

[Description of the structural elements]

## Suitability

[When to use. When not to use.]

## Variants

### Variant: [name]
[Description and tradeoffs]
```

**Editorial bar:** Would a practitioner facing this class of problem reach for something more complex or less elegant without this pattern?

---

## examples-garden Entry Template

```yaml
---
id: GE-YYYYMMDD-xxxxxx
garden: examples
title: "Intent — e.g. 'Multi-datasource Quarkus with named injection'"
type: code
domain: jvm | python | tools | web | data | infrastructure | security | cloud
stack: "Technology, Version"
tags: [tag1, tag2]
score: N
verified: true
staleness_threshold: 1095
submitted: YYYY-MM-DD
---
```

**Body sections:**

```markdown
## Example

[One sentence of intent]

```java
// Minimal working example — copy-paste ready
```

## Notes

[Optional: what to watch out for, what this doesn't cover]
```

**Editorial bar:** Minimal, working, demonstrating a real use case — not a toy?

---

## evolution-garden Entry Template

```yaml
---
id: GE-YYYYMMDD-xxxxxx
garden: evolution
title: "Library X.Y — what changed and what breaks"
type: breaking | deprecation | capability
domain: jvm | python | tools | web | data | infrastructure | security | cloud
stack: "Library, Version range"
tags: [tag1, tag2]
score: N
verified: true
staleness_threshold: 1095
changed_in: "X.Y.Z"
breaking: true
migration_effort: low | medium | high
submitted: YYYY-MM-DD
---
```

**Body sections:**

```markdown
## What Changed

[What the library did before and what it does now]

## Impact

[What breaks. What needs to change in consumer code.]

## Migration

[Step-by-step if migration_effort is medium or high]
```

**Editorial bar:** Does this describe a breaking change, deprecation, or capability shift that would change code correctness for someone on that version?

---

## risk-garden Entry Template

```yaml
---
id: GE-YYYYMMDD-xxxxxx
garden: risk
title: "Failure mode name"
type: failure-mode | antipattern | incident
domain: jvm | python | tools | web | data | infrastructure | security | cloud
stack: "Technology, Version"
tags: [tag1, tag2]
score: N
verified: true
staleness_threshold: 1825
severity: low | medium | high | critical
failure_pattern: "brief pattern name"
observed_at_scale: true | false
submitted: YYYY-MM-DD
---
```

**Body sections:**

```markdown
## Failure Mode

[What goes wrong and how it manifests]

## Root Cause

[Mechanism — not just what breaks, but why]

## Mitigation

[How to prevent or recover]

## Detection

[How to know this is happening]
```

**Editorial bar:** Has this failure mode caused production harm at meaningful scale, and is the mechanism universal enough to recur in other systems?

---

## decisions-garden Entry Template

```yaml
---
id: GE-YYYYMMDD-xxxxxx
garden: decisions
title: "Technology/approach X chosen over Y for Z"
type: architecture | technology | process
domain: jvm | python | tools | web | data | infrastructure | security | cloud
stack: "Technology, Version"
tags: [tag1, tag2]
score: N
verified: true
staleness_threshold: 3650
submitted: YYYY-MM-DD
---
```

**Body sections:**

```markdown
## Decision

[What was chosen and a one-sentence summary of why]

## Context

[What problem was being solved. What constraints applied.]

## Alternatives Considered

- **[Alternative A]:** [Why rejected]
- **[Alternative B]:** [Why rejected]

## Reasoning

[The argument for the chosen approach over the alternatives]

## Consequences

[What this decision makes easier. What it makes harder.]
```

**Editorial bar:** Does this capture the reasoning clearly enough that someone facing the same choice could apply it — including what was rejected and why?
