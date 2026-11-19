---
title: "Three-Valued Truth"
date: 2026-10-13
author: Mark Proctor
entry_type: note
subtype: diary
series: issue-450-outcome-based-verification
tags: [verification, pipeline, architecture, postconditions]
---

# Three-Valued Truth

The work-end pipeline had a lying problem.

Not malicious — structural. Every postcondition returned `bool`. True or
false. But the real world has a third answer: *I don't know yet*. A push
that hasn't propagated to the remote. A SHA that hasn't been fetched. An
API that's rate-limited. None of these are failures. They're the absence
of evidence — and the pipeline was collapsing them into one of two bins
depending on which code path happened to run first.

This is what caused #436. `content_landed_postcondition` received an
empty `landed_shas` dict and returned `True` — the logic was "no SHAs
to check, therefore nothing failed, therefore pass." Eight issues in the
tracker trace back to this pattern: missing evidence treated as success.
The fix for #436 was narrow — flip that specific empty check to `False`.
But the structural problem remained: a bool can't distinguish "verified
and passed" from "couldn't verify."

## The Fix: PASS / FAIL / UNKNOWN

`VerifyResult` is an enum with three values. Every verification function
returns a `Verification` dataclass: the check name, the result, an
evidence dict explaining *what was checked and what was found*, and the
repo name for per-repo fan-out.

The evidence dict is the part that matters most. A FAIL from
`verify_content_landed` doesn't just say "failed" — it says which files
have diffs, which SHA was checked, which method was used. An UNKNOWN
says *why* it's unknown: "no landed SHA available," "main tip unchanged
since classification," "remote unreachable." When the engine escalates
an UNKNOWN to the LLM after retries, it hands over structured context,
not a bare "postcondition not met."

## Two Layers Become One

The codebase had two overlapping verification systems.
`step_postconditions.py` returned bools for the orchestrator engine's
check-execute-verify pattern. `close_checks.py` returned `list[Finding]`
for the close-time verification report. Both checked the same things —
content landed, branch stamped, push complete — but with different
logic. Fixes to one didn't propagate to the other.

Now there's one: `verification/outcomes.py`. The orchestrator engine
uses `outcome_fn` on `StepDef` — a lambda that binds context fields
and calls the pure verify function. `close_verify.py` calls the same
functions and converts via `verification_to_findings()`. One check, one
truth, two consumers with different presentation needs.

The design review caught something I'd missed: `verify_fn` on `StepDef`
already had eight active consumers for judgment response validation.
The initial plan to repurpose it would have silently broken the squash
step, the forcing function, and all four branch audit dimensions.
`outcome_fn` is a new field — `verify_fn` stays untouched.

## Idempotent vs. Not

The `land` step is the interesting case. Its old postcondition was
`lambda ctx: push_postcondition(ctx) and content_landed_postcondition(ctx)`.
When either returned False, the engine retried the entire step —
re-executing the land operation. But landing isn't idempotent. A second
push after a successful one is harmless; a second merge attempt after a
successful merge creates conflicts.

The engine now has an `idempotent` flag on `StepDef`. When a
non-idempotent step returns UNKNOWN, the engine yields for
re-verification without re-executing. On the next loop iteration, the
outcome function runs again — if evidence has propagated (the push
reached the remote, the SHA became fetchable), it returns PASS and the
step completes without re-execution.

## What's Left

Stamp files (`.artifacts-promoted`, `.landed`, `.phase-a-complete`)
still exist. The verify functions read them as secondary evidence during
migration — git state is the primary check, stamps are the fallback for
UNKNOWN resolution. Once confidence is established that the git-state
checks cover every scenario the stamps did, the stamps go away. That's
a future session's work.

Phase 4 (#451) formalises the LLM interface — `JudgmentRequest` and
`JudgmentResponse` with JSON schemas. It builds directly on
`Verification` as the outcome type. The typed interface and the
three-valued verification are orthogonal implementations of the same
parent architecture: make implicit contracts explicit, make evidence
primary, make unknown states visible instead of silent.
