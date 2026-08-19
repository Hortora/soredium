---
name: branch-audit
description: >
  Use when reviewing a full branch diff at lifecycle gates (work-end,
  handover) — holistic review across conformance, coherence, structure,
  and robustness dimensions. NOT for per-commit review (use code-review).
  NOT for spec review (use design-review).
---

# Branch Audit

Holistic branch-level review across four dimensions. Runs inline — single
pass per dimension, no external sessions, no adversarial rounds.

<HARD-GATE>
**Branch audit is mandatory at work-end.** It runs at Step 2.2, after
code-review (Step 2.1) and before the forcing function (Step 2.4).
No branch closes without a branch audit.
</HARD-GATE>

## Dimensions

Each dimension includes (but is not limited to) the listed sub-concerns.
Review the full branch diff (`git diff main...HEAD`) against these
dimensions.

### Conformance — did we build what we said we'd build?

The reference document varies by context:
- **With spec:** implementation vs spec requirements
- **With issue only:** implementation vs issue description and acceptance
  criteria
- **With neither:** implementation vs commit messages and conversation
  context (lightest form — confirms code does what was described;
  fewer, lower-severity findings expected)

Includes: issue conformance, completeness, missing requirements, gaps in
edge case coverage, untested scenarios, acceptance criteria not met.

### Coherence — does the branch hold together as a whole?

Includes: internal consistency, uniform patterns across changes, naming
consistency, architectural fit with the rest of the codebase, dead code
or debug artifacts, leftover TODOs that should have been resolved,
commented-out blocks.

### Structure — are the boundaries right?

Includes: decomposition, module boundaries, dependency cleanliness,
separation of concerns, file organisation, whether new code lives in
the right place.

### Robustness — what could go wrong?

Includes: failure modes, error paths, surface-level security (auth,
input validation, data exposure), regression risk (downstream callers
affected), boundary conditions, silent failures.

When Robustness identifies security concerns (auth, PII, payment, user
input code), offer to escalate to `security-audit` for the full OWASP
pass. At work-end, branch-audit owns this escalation — code-review
suppresses its own offer to avoid duplication.

## Execution Model

1. Resolve the reference document (spec, issue, or commit messages)
2. Get the full branch diff: `git diff main...HEAD`
3. Review against each dimension in order: Conformance, Coherence,
   Structure, Robustness
4. For each finding: assign severity (CRITICAL / WARNING / NOTE) and
   classify by dimension
5. After each dimension completes, append findings to
   `$WORKSPACE/.audit/findings.jsonl` via `append_finding` from
   `project/findings.py`
6. Present all findings grouped by dimension

### Finding format

```json
{
  "category": "audit",
  "dimension": "conformance|coherence|structure|robustness",
  "severity": "critical|warning|note",
  "check": "<finding-type>",
  "location": "<file:line or spec:section>",
  "detail": "<description>",
  "source": "branch-audit",
  "branch": "<current-branch>",
  "status": "open",
  "timestamp": "<ISO-8601>"
}
```

### Severity model

| Level | Meaning | Resolution |
|-------|---------|------------|
| **CRITICAL** | Wrong behavior, data loss, security vulnerability | Fix or File — cannot be dismissed |
| **WARNING** | Confusion, inconsistency, maintenance burden | Fix, File, or Dismiss |
| **NOTE** | Minor improvement, style preference | Fix, File, or Dismiss |

## Relationship to Other Review Skills

| Skill | Scope | When |
|-------|-------|------|
| `code-review` | Per-line checklist (safety, types, async) | Per-commit and work-end Step 2.1 |
| `branch-audit` | Holistic branch-level (4 dimensions) | Work-end Step 2.2 |
| `design-review` | Adversarial spec review (multi-round) | After spec written |
| `security-audit` | Full OWASP checklist | On escalation from Robustness |

Branch-audit fills the post-implementation lifecycle point in
`design-review/review-tiers.md` with a simpler execution model.

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Skipping Conformance when no spec exists | Issue description and commit messages are still reference documents | Run Conformance in lightest mode |
| Duplicating code-review findings | Branch-audit is holistic, not per-line | If code-review already caught it, skip |
| Offering security-audit escalation when code-review already did | Double escalation confuses the user | At work-end, branch-audit owns the escalation |
| Not persisting findings | Findings die with the session | Append to findings.jsonl after each dimension |

## Skill Chaining

**Invoked by:**
- `work-end` — Step 2.2, mandatory gate

**Invokes:**
- `security-audit` — offered when Robustness identifies security concerns

**Complements:**
- `code-review` — different scope (per-line vs holistic); both run at work-end
- `design-review` — different lifecycle point (post-spec vs post-implementation);
  shares four-dimension vocabulary
- `loose-ends-sweep` — runs after branch-audit at Step 2.3; different
  concern (session state vs code quality)
