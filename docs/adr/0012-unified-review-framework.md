# ADR-0012: Unified Review Framework — Lifecycle-Driven Dimensions with Degree-Only User Choice

**Status:** Proposed
**Date:** 2026-08-01
**Replaces:** Current separate design-review and code-review skill models

## Context

The current review system has two independent skills with different mental models:

- **design-review** — type×degree matrix (coherence/structure/robustness × light/standard/adversarial/deep), user picks both
- **code-review** — language-specific checklists (java.md, typescript.md, python.md), no degree control

Problems observed:

1. **Users always want all dimensions.** When offered type selection, the rational choice for any non-trivial spec is "all three." Asking which dimensions to review is like asking which parts of code to test — the answer is always all of them.

2. **Missing cross-cutting pass.** Three independent typed reviews find problems within their dimension but miss intersection failures — e.g., a boundary decomposition (structure) that creates a failure mode (robustness). No synthesis step existed.

3. **Post-brainstorming gap.** After brainstorming produces an approach, there's no review that asks "is this the right approach?" before committing to a full spec. The emphasis here is fundamentally different from post-spec review.

4. **No conformance check.** Post-implementation review doesn't systematically check whether code matches the spec that was written.

5. **Type selection is the wrong abstraction.** The review dimensions are orthogonal and universal — what changes between lifecycle points is the emphasis, not which dimensions apply.

## Decision

Replace the type×degree selection model with a **lifecycle-driven framework** where:

- The **lifecycle point** determines which dimensions run and their relative emphasis
- The **degree** (user's only choice) determines how deep each dimension goes
- A **cross-cutting pass** runs automatically when 2+ dimensions are active
- Language-specific checklists feed into the framework as domain knowledge, not a separate system

### Lifecycle Points

#### Post-brainstorming (approach validation)

Runs after brainstorming produces candidate approaches, before committing to a spec.

| Dimension | Emphasis | Focus |
|-----------|----------|-------|
| Approach fitness | Heavy | Is this the best way to solve the problem? Are there better patterns? |
| Prior art | Heavy | What does the industry show? Published best practices? Known anti-patterns? |
| Platform conformance | Heavy | Does this fit existing platform patterns, conventions, and cohesiveness? |
| Alternatives | Medium | Did we miss a fundamentally different approach? |
| Cross-cutting | Auto | Contradictions between dimensions |

This is not about reviewing a document — it's about stress-testing a direction before investing in a full design.

#### Post-spec (design review)

Runs after the spec is written and user-approved, before implementation planning.

| Dimension | Emphasis | Focus |
|-----------|----------|-------|
| Coherence | Heavy | Is the design complete? Gaps? Consistency? |
| Structure | Heavy | Module boundaries? Dependency composition? API surface? |
| Robustness | Medium | Failure modes on paper? Edge cases in the design? |
| Cross-cutting | Auto | Intersection failures across dimensions |

#### Post-implementation (code review)

Runs after implementation, before merge.

| Dimension | Emphasis | Focus |
|-----------|----------|-------|
| Conformance | Heavy | Does the code match the spec? Drift? Missing pieces? |
| Robustness | Heavy | Error handling, concurrency, security, null paths |
| Structure | Medium | Class decomposition, coupling, API surface |
| Coherence | Light | Missing cases, naming consistency |
| Cross-cutting | Auto | Boundary between modules creates failure mode neither owns |

#### Pre-ship (readiness review)

Runs before release, after implementation is reviewed.

| Dimension | Emphasis | Focus |
|-----------|----------|-------|
| Robustness | Heavy | Production failure scenarios, data loss paths |
| Readiness | Heavy | Observability, rollback plan, runbook, monitoring |
| Conformance | Light | Drift since last review? |
| Cross-cutting | Auto | Gaps between what's monitored and what can fail |

### Degree Scale

The user's only choice. Controls depth uniformly across all active dimensions.

| Degree | Rounds | Ultrathink | Approx time |
|--------|--------|------------|-------------|
| Light | 1 | No | ~2 min |
| Standard | 2-3 | No | ~5 min |
| Adversarial | 4-6 | No | ~12 min |
| Deep | 8-10 | Yes | ~25 min |

### Cross-Cutting Pass

Automatic when 2+ dimensions ran. Reads the findings from all dimensions and looks for:

- **Contradictions** — Structure says split this module, Robustness says keep it together
- **Intersection failures** — A boundary (structure) that creates a failure mode (robustness) that neither reviewer connected
- **Coverage gaps** — All reviewers assumed someone else would check X
- **Conformance drift** — Spec says X, structure review assumed Y

The cross-cutting pass does not re-review the artifact — it reviews the reviews against each other, with the artifact as reference.

### Recommendation Engine

Before prompting, the engine analyzes the artifact and recommends a degree (or Skip). The recommendation signals shift by lifecycle point:

| Signal | Recommendation |
|--------|---------------|
| Config-only, rename, mechanical wiring | Skip |
| Clear requirements, known domain, small scope | Light |
| New module, API surface changes | Standard |
| Cross-module boundaries, dependency ordering | Standard |
| Auth, security, PII, concurrency, distributed state | Adversarial |
| Novel architecture, first-of-kind, high-stakes | Deep |

The recommendation is presented with reasoning before the prompt, so the user understands why Skip or a specific degree was suggested.

### User Experience

The prompt becomes a single question with the recommendation pre-filled:

```
Recommendation: Standard
New API surface across two modules, but the interaction model
follows established platform patterns.

Review depth?

  1. Skip               — no review needed
  2. Light              — single pass, ~2 min
  3. Standard (Recommended) — 2-3 rounds, ~5 min
  4. Adversarial        — 4-6 rounds, ~12 min
  5. Deep               — 8-10 rounds + ultrathink, ~25 min
```

The lifecycle point is inferred from context (post-brainstorming, post-spec, post-implementation, pre-ship). No dimension selection needed.

## Consequences

### Positive

- Simpler user experience — one question instead of two
- No risk of missing a dimension — all relevant dimensions always run
- Cross-cutting analysis catches intersection failures that independent reviews miss
- Post-brainstorming review fills the "is this the right approach?" gap
- Conformance checking connects specs to implementation systematically
- Language-specific checklists become domain knowledge feeding into universal dimensions, not a parallel system

### Negative

- Light reviews do more work than before (all dimensions instead of one) — mitigated by light being single-round
- Post-brainstorming review adds a step to the brainstorming→spec flow — mitigated by it being optional (Skip remains)
- Unifying design-review and code-review is a significant refactor of two established skills

### Review Output Location

All review outputs go to `~/reviews/`, a global directory outside any repo (same model as the current `~/adr/`). Organized by project with timestamped review folders.

```
~/reviews/
  casehub-blocks/
    affordance-renderer-20260728-110956/
    engine-integration-20260701-055226/
  casehub-engine/
    ...
  soredium/
    ...
```

This replaces the current `~/adr/` directory. The name `adr` was overloaded — adversarial design review outputs collided with Architecture Decision Records (`docs/adr/`). `~/reviews/` is unambiguous and captures all review types (post-brainstorming, post-spec, post-implementation, pre-ship) at all degrees (light through deep).

### Implementation Notes

- design-review and code-review skills merge into a single review framework
- The review-tiers.md reference doc becomes the unified dimension/degree/lifecycle specification
- Language-specific content files (java.md, typescript.md, python.md) remain but feed into the framework's dimensions
- The brainstorming skill's Review Depth Prompt adapts to the new single-question model
- Recommendation signals (from current review-tiers.md) inform the default degree, not the type selection
- Existing adversarial design review outputs in `~/adr/` migrate to `~/reviews/`
