# Review Tiers Reference

Two orthogonal dimensions: **type** (what aspect to examine) and **degree** (how deeply).

## Types

| Type | Focus | Lifecycle point |
|------|-------|-----------------|
| Coherence | Completeness, consistency, gaps | After spec/plan |
| Structure | Decomposition, boundaries, dependencies | After spec |
| Robustness | Failure modes, edge cases, error paths | After spec |
| Conformance | Implementation vs spec alignment | After implementation |
| Readiness | Ship-worthiness, production concerns | Before ship |

## Degrees

| Degree | Rounds | Ultrathink | Time |
|--------|--------|------------|------|
| Light | 1 | No | ~1 min |
| Standard | 2-3 | No | ~5 min |
| Adversarial | 4-6 | No | ~12 min |
| Deep | 8-10 | Yes | ~25 min |

## Default Degree Per Type

| Type | Default |
|------|---------|
| Coherence | Light |
| Structure | Standard |
| Robustness | Adversarial |
| Conformance | Standard |
| Readiness | Standard |

## Recommendation Signals

| Signal | Type | Degree |
|--------|------|--------|
| Config-only, rename, mechanical wiring | Skip | — |
| Clear requirements, known domain | Coherence | Light |
| New module, API surface changes | Structure | Light or Standard |
| Dependency ordering, cross-module boundaries | Structure | Standard |
| Auth, security, PII handling | Robustness | Adversarial |
| Concurrency, distributed state, data migration | Robustness | Adversarial |
| Novel architecture, first-of-kind | Structure + Robustness | Deep |
| High-stakes (payment, compliance, data loss) | Robustness | Deep |

## Prompt Flow

### 1. Full recommendation (text)

Before any Q&A, present the complete recommendation with reasoning specific to this spec:

```
Recommendation: Coherence / Light
This spec introduces new module boundaries between the scanner and
lifecycle manager, but the interaction model is straightforward.
A coherence check catches completeness gaps.
```

### 2. Type selection (AskUserQuestion)

Recommended option listed first with "(Recommended)" suffix. Skip is always an option.

### 3. Degree selection (AskUserQuestion, if not Skip)

Recommended option listed first with "(Recommended)" suffix.

### 4. Escalation report

Light and standard reviews report whether they recommend escalation:

```
## Escalation Assessment

ESCALATE: yes|no
RECOMMENDED_TYPE: <type>
RECOMMENDED_DEGREE: <degree>
REASON: <one sentence>
```

If escalation recommended, prompt user via AskUserQuestion: proceed with escalated review or skip.
