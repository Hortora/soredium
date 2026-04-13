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

## Gotcha Template

Bug, silent failure, or workaround:

```markdown
---
id: GE-YYYYMMDD-xxxxxx
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

### Why it's not obvious
Why would someone not know this exists? Is it in the source but not the docs?
Only mentioned in a GitHub issue? Only in an old commit message?

### Caveats
Any limitations, version constraints, or risks from relying on undocumented behaviour.

*Score: N/15 · Included because: [why this belongs] · Reservation: [none / brief reason]*
```

---

## Revise Template

Enrichment for an existing entry — solution, alternative, variant, update, or status change:

```markdown
---
id: GE-YYYYMMDD-xxxxxx
type: revise
revision_kind: solution | alternative | variant | update | resolved | deprecated
target_id: GE-YYYY
target_path: <domain>/GE-YYYY.md
domain: <same as target>
submitted: YYYY-MM-DD
---

## What this adds
[1–2 sentences on what new knowledge this brings to the existing entry]

## Content
[The actual solution, alternative, update, or note — complete and runnable where code is involved]

## Why it belongs with the existing entry
[How it relates — is it a complete fix, an alternative approach, additional context?]

## Trade-offs / caveats
[Any limitations, constraints, or conditions under which this applies or doesn't]

*Score: N/15 · Included because: [why this belongs] · Reservation: [none / brief reason]*
```

**Revision kind guide:**

| Kind | When to use |
|------|------------|
| `solution` | Gotcha had no fix / workaround only — now there's a real fix |
| `alternative` | Entry has one solution — found a different approach with different trade-offs |
| `variant` | Same pattern but different context, constraint, or technology |
| `update` | Additional context, edge cases, or discovery that enriches the entry |
| `resolved` | The library/tool fixed the bug — entry stays but notes the version |
| `deprecated` | Feature removed or approach obsolete — entry stays with a warning |

**Garden Score for REVISE:** score the revision itself, not the original entry.

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
