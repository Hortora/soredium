---
layout: post
title: "The Stamp That Lied"
date: 2026-09-06
entry_type: note
subtype: diary
projects: [hortora/soredium]
tags: [work-end, stamps, verification, git]
---

# The Stamp That Lied

Every branch closure in soredium writes a stamp commit: `chore: branch closed — landed as abc123 on main`. The SHA tells you which commit on main carries the branch's content. Auditable. Deterministic. Except it wasn't.

The stamp was written with the correct SHA at merge time. Then squash rewrote main's history, and the SHA stopped existing. The verification step caught it every time — `project_landing_sha: fail` — but the failure was always hand-waved as "a known consequence of squashing after stamping." Recording information that's immediately wrong is worse than not recording it, because it looks like it's being tracked.

The root cause was an idempotency guard in `_stamp_repo` that trusted any existing stamp unconditionally. If the branch tip started with "chore: branch closed," the function returned True without checking whether the SHA was still on main. A partial run that stamped before squash would leave the stale stamp in place — and every subsequent run would skip it.

Two fixes, both required. First: capture the landed SHA fresh from `rev-parse main` at stamp time, rather than relying on a SHA passed through from the merge step. The merge SHA can go stale if anything between merge and stamp rewrites main — squash, push-retry rebase, concurrent push. Fresh capture eliminates the source of staleness.

Second: when an existing stamp is found, validate the SHA with `merge-base --is-ancestor` before skipping. If the SHA isn't on main, the function now amends the stamp commit with the correct SHA instead of creating a second stamp on the branch.

The amend raised a design question: what about the old SHA? We added a structured `stamp-history:` block in the commit body. Each entry records timestamp, SHA, and reason for the change. The subject line stays machine-parseable — existing tools that match `chore: branch closed — landed as` keep working. The body carries the audit trail.

```
chore: branch closed — landed as def456 on main  Refs #42

stamp-history:
- 2026-09-01T00:00:00Z sha=abc123 reason=initial
- 2026-09-06T14:32:00Z sha=def456 reason=stale_sha_not_on_base prev=abc123
```

The verification side reads this too. `check_landing_sha` now reports lineage when history is present — "re-stamped 1x, lineage: abc123 → def456" — so the verify output explains what happened instead of just failing.

Old stamps without a history block still pass verification. When one does get re-stamped, the code synthesises a history entry from the existing SHA — the old stamp's data isn't lost, just retroactively structured.

The integration test captures the exact scenario: stamp with SHA-A, squash main to create SHA-B, call `_stamp_repo` again. It detects the stale SHA, amends to SHA-B, and the history shows both. The verify passes. This was the test that would have caught the original bug if it had existed from the start.
