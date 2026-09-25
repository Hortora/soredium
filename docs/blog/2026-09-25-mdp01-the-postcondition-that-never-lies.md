---
layout: post
title: "The Postcondition That Never Lies"
date: 2026-09-25
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [idempotency, pipeline, crash-safety, work-end]
---

# The Postcondition That Never Lies

The work-end pipeline has around 40 steps across six phases. When a step fails mid-execution — network drops during a push, filesystem permission error on an archive move, GitHub API timeout — the steps before it have already mutated state. Re-running the pipeline used to mean guessing which steps completed and which didn't. Sometimes the guess was wrong.

The root cause was optimistic reporting. A step would print `ARCHIVED=42` before `shutil.move()` had returned. It would write `.landed` with empty SHAs because the marker was created before the verification loop confirmed the SHAs were on the remote. The progress file would say "pushed" before the fetch-and-verify check ran. Each of these is a small honesty gap, but when a crash lands between the claim and the reality, recovery becomes archaeological — cross-referencing four different state sources to work out what actually happened.

The fix is a pattern older than most frameworks: check-execute-verify. Before executing a step, check whether its postcondition is already met — skip if so. After executing, verify the postcondition holds — fail explicitly if not. The engine enforces this mechanically for every mechanical step. No step can bypass the pattern because the engine owns the loop.

The interesting design choice was where to put the enforcement. Each step script could have added its own pre/post checks — more flexible, but it would need getting right independently in 40 places. That's the approach that created the original problem. Instead, we added a `postcondition_fn` field to `StepDef` and taught the engine's `run_loop` to call it at both gates. One code change, universal enforcement. A new step that forgets to add a postcondition gets caught by a test that asserts every mechanical step has one.

The postcondition functions themselves are pure checks. `push_postcondition` runs `git merge-base --is-ancestor sha origin/main` — it asks git whether the SHA is actually on the remote, not whether the push script said it succeeded. `promote_postcondition` checks whether `.artifacts-promoted` exists on disk, not whether `close_artifacts.py` returned exit code 0. Ground truth, not reported truth.

There was a second design question: whether to make the progress journal the single authoritative state source, deriving everything else from it. The issue proposed this, and it's architecturally clean — eliminate disagreement by eliminating independent sources. But the postcondition checks already solve the disagreement problem at the root. Once markers are only written after verification, they don't disagree with the journal because they're honest. Making the journal authoritative would have meant rewriting every consumer of `.landed`, `.phase-a-complete`, and `.artifacts-promoted` — the auditor, the reconciler, the archive scripts — for a problem that honest reporting already fixes.

The convergence property falls out naturally. A pipeline run where every step finds its postcondition already met is a no-op — it skips everything and returns `ACTION=complete`. A pipeline run after a mid-step crash skips the completed steps and picks up where it left off. No recovery code. No `--force` flags. Just: run it again.

What this opens up is less about the pipeline and more about the operational posture. The auditor that was cross-referencing `.slot`, the DB, disk markers, and git branches to diagnose inconsistencies can now trust that if the pipeline says "done," it checked. The manual workaround cascade — where fixing one failure created three downstream inconsistencies — can't happen when each step verifies its own output. "Run it again" replaces twenty distinct recovery procedures.
