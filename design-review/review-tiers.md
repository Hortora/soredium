# Unified Review Framework Reference

Reviews are lifecycle-driven. The **lifecycle point** determines which
dimensions run and their emphasis. The **degree** (user's only choice)
determines how deep each dimension goes. A **cross-cutting pass** runs
automatically when 2+ dimensions complete.

## Lifecycle Points

| Lifecycle | When | Dimensions | Emphasis |
|-----------|------|------------|----------|
| Post-spec | After spec written and approved | Coherence, Structure, Robustness + cross-cutting | Coherence heavy, Structure heavy, Robustness medium |
| Post-brainstorming | After approach selected, before spec | Decision | Approach fitness, prior art, platform conformance |
| Post-implementation | After code written, before merge | Implemented by: `branch-audit` (conformance, coherence, structure, robustness) | Inline single-pass; see branch-audit/SKILL.md |
| Pre-ship | Before release | *(future — robustness, readiness)* | — |

## Dimensions

| Dimension | Focus |
|-----------|-------|
| Coherence | Completeness, consistency, gaps, ambiguity |
| Structure | Decomposition, boundaries, dependencies, coupling, ownership |
| Robustness | Failure modes, concurrency, edge cases, data integrity, error propagation |
| Cross-cutting | Contradictions, intersection failures, coverage gaps between dimensions |
| Conformance | Implementation vs spec alignment *(post-implementation only)* |
| Decision | Rationale soundness, unconsidered alternatives, platform coherence, implicit decisions *(post-brainstorming only)* |
| Readiness | Ship-worthiness, observability, rollback *(pre-ship only)* |

## Degrees

| Degree | Rounds | Ultrathink | Approx time | When to use |
|--------|--------|------------|-------------|-------------|
| Light | 1 | No | ~2 min | Clear requirements, known domain, small scope |
| Standard | 2-3 | No | ~5 min | New module, API surface changes |
| Adversarial | 4-6 | No | ~12 min | Auth, security, concurrency, distributed state |
| Deep | 8-10 | Yes | ~25 min | Novel architecture, first-of-kind, high-stakes |

Light degree is reviewer-only (no implementor round). All other degrees
run the full reviewer→implementor loop.

## Recommendation Signals

The recommendation engine analyzes the spec and suggests a degree (or Skip):

| Signal | Recommendation |
|--------|---------------|
| Config-only, rename, mechanical wiring | Skip |
| Clear requirements, known domain, small scope | Light |
| New module, API surface changes | Standard |
| Cross-module boundaries, dependency ordering | Standard |
| Auth, security, PII, concurrency, distributed state | Adversarial |
| Novel architecture, first-of-kind, high-stakes | Deep |

## Prompt Flow

### 1. Recommendation (text)

Present the recommendation with reasoning specific to the spec:

```
Recommendation: Standard
New API surface across two modules, but the interaction model
follows established platform patterns.
```

### 2. Degree selection (AskUserQuestion)

Single question — no type selection. Recommended option listed first.
Skip is always available.

### 3. Launch dimensions

For post-spec: launch coherence, structure, and robustness as parallel
review.py instances. Each gets the same spec, source dirs, and degree.

### 4. Cross-cutting (automatic)

When all dimension reviews complete, launch a cross-cutting review with
`--type crosscutting --arch-files <tracker1> <tracker2> <tracker3>`.
The cross-cutting reviewer reads the dimension trackers and finds
problems between them.

If only 1 dimension completed (failure in the others), skip cross-cutting.

### 5. Escalation report

Light and standard reviews include escalation assessment. If escalation
is recommended, prompt the user to proceed with the deeper review.

## Output

All review outputs go to `~/reviews/{project}/{title}-{dimension}-{timestamp}/`.

Each workspace contains: tracker.md, context.md, progress.log, responses/,
decisions/, handovers/, agents/{reviewer,implementor}/.
