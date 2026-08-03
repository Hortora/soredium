# Tiered Design Review

**Issue:** Hortora/soredium#98
**Date:** 2026-07-31
**Status:** Draft

## Problem

Design review has a flat model: you either run a full adversarial review (4-10 rounds, ~$15-25, ~15 min) or skip review entirely. This wastes time on mechanical specs and under-reviews complex ones that didn't look complex at first glance.

The current phase selector (pre-review / spec-review / code-review / final-review) conflates *what* is being checked with *how deeply*. "Pre-review" names a lifecycle point. "Adversarial" names a method. They aren't parallel.

## Design

### Two Orthogonal Dimensions

**Types** — the aspect being examined. Each maps to a reviewer brief that focuses the reviewer's attention on specific concerns.

| Type | What it checks | Lifecycle point | Maps to `--type` |
|------|---------------|-----------------|------------------|
| Coherence | Completeness, consistency, obvious gaps | After spec/plan | `coherence` |
| Structure | Decomposition, boundaries, dependencies | After spec | `structure` |
| Robustness | Failure modes, edge cases, error paths | After spec | `robustness` |
| Conformance | Implementation vs spec alignment | After implementation | `conformance` |
| Readiness | Ship-worthiness, production concerns | Before ship | `readiness` |

**Degrees** — how deeply and aggressively the review runs. Controls round count, model choice, and whether ultrathink is enabled.

| Degree | Rounds | Min rounds | Ultrathink | Budget/session | Model | `--degree` |
|--------|--------|------------|------------|----------------|-------|------------|
| Light | 1 | 1 | No | $1.50 | sonnet | `light` |
| Standard | 3 | 2 | No | $5.00 | opus | `standard` |
| Adversarial | 6 | 4 | No | $5.00 | opus | `adversarial` |
| Deep | 10 | 6 | Yes | $8.00 | opus | `deep` |

### Review Prompt Flow

After a spec or plan is produced (from brainstorming or writing-plans), the agent runs a three-part prompt: recommendation text, then two AskUserQuestion selectors.

**Part 1 — Full recommendation (text, before any Q&A):**

The agent reads the spec, identifies complexity signals, and presents the complete recommendation with reasoning as a text block. The user sees the full picture before making any selection.

```
Recommendation: Coherence / Light
This spec introduces new module boundaries between the scanner and
lifecycle manager, but the interaction model is straightforward
request-response with no concurrency. A coherence check catches
completeness gaps. If the coherence check finds structural concerns,
it will recommend escalation.
```

Or for Skip:
```
Recommendation: Skip
Mechanical config change — no new abstractions, no boundary changes,
straightforward wiring. If unsure, Coherence/Light costs ~1 min and
will flag if deeper review is needed.
```

The recommendation must be specific to this spec — not generic. Name the actual signals found.

**Part 2 — Type selection (AskUserQuestion):**

Uses the `AskUserQuestion` tool. The recommended option is listed first with "(Recommended)" suffix. Option descriptions are brief — the full reasoning was already presented in Part 1.

```python
AskUserQuestion(questions=[{
    "question": "Review this spec?",
    "header": "Review type",
    "options": [
        {"label": "Skip (Recommended)", "description": "No review needed"},
        {"label": "Coherence", "description": "Completeness, consistency, gaps"},
        {"label": "Structure", "description": "Decomposition, boundaries, dependencies"},
        {"label": "Robustness", "description": "Failure modes, edge cases, error paths"},
    ],
    "multiSelect": false,
}])
```

**Part 3 — Degree selection (AskUserQuestion, if not Skip):**

```python
AskUserQuestion(questions=[{
    "question": "Review degree?",
    "header": "Depth",
    "options": [
        {"label": "Light (Recommended)", "description": "~1 min — quick pass, flags if deeper needed"},
        {"label": "Standard", "description": "~5 min — thorough examination"},
        {"label": "Adversarial", "description": "~12 min — actively tries to break the design"},
        {"label": "Deep", "description": "~25 min — exhaustive, ultrathink enabled"},
    ],
    "multiSelect": false,
}])
```

**Part 4 — Run the review** at selected type x degree.

**Part 5 — Escalation report:**

Every review at Light or Standard degree includes an explicit escalation assessment as the final output. The reviewer is briefed to assess whether the spec warrants deeper scrutiny.

No escalation:
```
Escalation assessment: No escalation recommended.
```

Escalation recommended:
```
Escalation recommendation: Structure / Adversarial
Reason: The spec introduces a new event boundary between scanner and lifecycle
manager with concurrency implications that a light coherence check cannot
fully validate.
```

The agent presents this to the user and asks (via AskUserQuestion) whether to proceed with the escalated review or skip.

### Recommendation Engine

The agent analyzes the spec for complexity signals to determine the recommended type and degree.

**Signals and what they point toward:**

| Signal | Type | Degree |
|--------|------|--------|
| Config-only, rename, mechanical wiring | Skip | — |
| Clear requirements, known domain, no new abstractions | Coherence | Light |
| New module introduced, API surface changes | Structure | Light or Standard |
| Dependency ordering changes, cross-module boundaries | Structure | Standard |
| Auth, security, PII handling | Robustness | Adversarial |
| Concurrency, distributed state, data migration | Robustness | Adversarial |
| Novel architecture, first-of-kind in codebase | Structure + Robustness | Deep |
| High-stakes (payment, compliance, data loss risk) | Robustness | Deep |

The recommendation is a heuristic, not a gate. The user always chooses. The value is in the *reasoning* — explaining what the agent sees in the spec so the user can calibrate.

### CLI Changes to review.py

**New flag: `--type`**

```
--type {coherence,structure,robustness,conformance,readiness}
```

Replaces `--mode` for the new model. Old `--mode` values still accepted for backward compatibility:

| Old `--mode` | Maps to `--type` |
|-------------|------------------|
| `pre-review` | `coherence` (degree: light) |
| `spec-review` | `structure` (degree: adversarial) |
| `code-review` | `conformance` |
| `final-review` | `readiness` |

**Expanded `--depth` to `--degree`**

```
--degree {light,standard,adversarial,deep}
```

Available for all types (removes the final-review-only restriction). `--depth` accepted as alias for backward compat.

**Degree presets:**

```python
DEGREE_PRESETS = {
    "light":       {"max_rounds": 1,  "min_rounds": 1, "budget_per_session": 1.5, "model": "sonnet", "ultrathink": False},
    "standard":    {"max_rounds": 3,  "min_rounds": 2, "budget_per_session": 5.0, "model": "opus",   "ultrathink": False},
    "adversarial": {"max_rounds": 6,  "min_rounds": 4, "budget_per_session": 5.0, "model": "opus",   "ultrathink": False},
    "deep":        {"max_rounds": 10, "min_rounds": 6, "budget_per_session": 8.0, "model": "opus",   "ultrathink": True},
}
```

**Default degree per type (when `--degree` not specified):**

| Type | Default degree |
|------|---------------|
| coherence | light |
| structure | standard |
| robustness | adversarial |
| conformance | standard |
| readiness | standard |

### Reviewer Brief Changes (prompts.py)

Each type gets a focused reviewer brief. The reviewer's attention is directed to the aspect that matters for that type.

**Coherence brief:** "Check for completeness, internal consistency, missing requirements, ambiguous language. Do not deep-dive architecture or failure modes."

**Structure brief:** "Evaluate decomposition: are boundaries clean? Are dependencies well-ordered? Could this be simpler? Are responsibilities clearly assigned? Look for coupling, circular dependencies, unclear ownership."

**Robustness brief:** "Try to break this design. Construct failure scenarios: what happens when X fails? What about concurrent access? What are the edge cases? Where could data be lost or corrupted?"

**Conformance brief:** "Compare implementation against spec section by section. Flag deviations, missing features, and spec requirements that are implemented differently than specified."

**Readiness brief:** "Evaluate production-readiness: error handling, logging, monitoring, rollback, deployment concerns, backward compatibility, performance under load."

### Escalation Assessment

For Light and Standard degrees, the reviewer brief includes an additional instruction:

"After your review, assess whether this spec warrants a deeper review. Consider: did you encounter complexity you couldn't fully evaluate at this depth? Are there interaction effects between components that need adversarial pressure? If so, recommend a specific type and degree for the follow-up, with a one-sentence reason."

The escalation output is a structured section at the end of the reviewer's response:

```
## Escalation Assessment

ESCALATE: yes|no
RECOMMENDED_TYPE: <type>
RECOMMENDED_DEGREE: <degree>
REASON: <one sentence>
```

### Integration Points

**brainstorming/SKILL.md** — New step between "User Review Gate" and "Implementation":

```
### Step 7b — Review depth prompt

After the user approves the spec, prompt for review depth before
transitioning to writing-plans. Follow the two-step Q&A flow defined
in design-review/review-tiers.md.

If the user selects Skip, proceed directly to writing-plans.
If a review is selected, run it and handle escalation before proceeding.
```

**writing-plans/SKILL.md** — New step after plan is written:

```
### Step N — Review depth prompt

After the plan is written and approved, prompt for review depth.
Plans are typically lighter than specs — default recommendation is
Coherence / Light or Skip.
```

**design-review/SKILL.md** — Step 0.5 replaced:

The flat phase checklist is replaced with the type x degree Q&A flow. When invoked directly (`/design-review`), the agent still analyzes the spec and recommends, but the user can override to any type x degree.

### Backward Compatibility

- `--mode pre-review|spec-review|code-review|final-review` still accepted, mapped to new types
- `--depth light|standard|deep` still accepted as alias for `--degree`
- Existing review workspaces (`.mode` file) still readable
- No changes to workspace layout, tracker format, or response format

## Not in Scope

- Automatic type selection (always prompts, always lets user choose)
- Multiple types in one run (run sequentially if needed)
- Changes to the reviewer/implementor adversarial loop mechanics
- Changes to issue tracking, evidence verification, or convergence detection
