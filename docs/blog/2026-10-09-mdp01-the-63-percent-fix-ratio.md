---
layout: post
title: "The 63% Fix Ratio"
date: 2026-10-09
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [pipeline-architecture, refactoring, work-end, verification]
series: issue-423-pipeline-structural-audit
---

Soredium's work-end pipeline had become the most-edited file in the repo — 92 changes to `work_end_orchestrator.py` alone. Fixes outnumbered features nearly two to one. Each fix was correct: add a conditional for the edge case that crashed, move a step that ran in the wrong order, handle the repo configuration nobody anticipated. But the ratio kept climbing.

I wanted to understand why. Not the individual bugs — those were obvious once found — but what structural property made them inevitable.

We ran a systematic audit: git history for fix patterns, code architecture for design flaws, recent diffs for the specific shape of each failure. Claude ran four parallel investigations into the orchestrator engine, both verification systems, the landing flow, and the last 30 fix commits. The findings converged on the same answer from every angle.

**Seven things were wrong at the architecture level.**

The deepest: every step in the pipeline independently probes git to determine repo state. Does this repo have a feature branch? How many commits ahead? Is it dirty? Each probe has its own edge-case handling. When a new edge case surfaces — zero commits ahead, no feature branch, workspace-only repo — it gets fixed in whichever probe crashed, not in all of them. Issues #421 and #422 were discovered a day apart: same check function, same conditional block, different edge case. The fix for one didn't prevent the other because the architecture doesn't classify repos — it discovers them, piecemeal, at runtime.

The second worst: two entirely independent verification systems. `verify_slot_close.py` was built at issue #184. The `verification/` library was extracted later at #339. They check eight of the same things with different logic, different return types, and different repo discovery. They can disagree on which repos are in a slot. When they do, the LLM is stuck — it can't tell which answer is authoritative.

Sixteen copies of the `git()` helper function, with three different return types and two different parameter orders. Thirteen skip predicates, each independently shelling out to git. All progress state stored as strings, parsed inline — the same `int(produced)` bug crashed three times in the same function.

The core insight is something I'm calling "classify early, act late." When a pipeline operates on heterogeneous entities — repos in different states, with different types, requiring different handling — the natural impulse is to probe each entity's state when you need it. It feels simpler: each step asks its own question. The cost is hidden. It surfaces as a fix ratio that creeps upward, one narrow conditional at a time, for months.

The alternative: compute a complete classification at pipeline entry. Every repo gets a type (`PROJECT`, `WORKSPACE`, `CLONE`) and a disposition (`HAS_WORK`, `EMPTY_BRANCH`, `NO_BRANCH`, `ALREADY_LANDED`). Make it immutable. Pass it to every step. Steps that only apply to `HAS_WORK` repos filter by disposition. No probing, no missed edge cases, no "one more conditional."

We broke the restructuring into seven phases, dependency-ordered: extract a single `git()` function (#424), unify four slot parsers (#425), build `RepoState` at pipeline entry (#426), replace skip predicates with mode declarations (#427), add explicit step dependencies (#428), merge the two verification systems (#429), type all progress state (#430). Phase 1 is done — 16 helpers consolidated, net minus 53 lines, one protocol to prevent regression.

The question I'm sitting with: Phase 3 (`RepoState`) is where the architecture actually changes. Phases 1 and 2 are cleanup — necessary but mechanical. Phase 3 is the one that makes the "classify early" principle concrete. It's also the one where getting the taxonomy wrong means re-doing everything downstream. The `RepoDisposition` enum needs to be exhaustive without being over-specified. Four values feel right — but "feels right" is exactly the kind of reasoning that produced the original mess.

Separately, #431 arrived mid-session — the work lifecycle is single-project-focused even when running inside a multi-repo slot. ctx.py always resolves to the CWD's git root, ignoring which repo is active. That's orthogonal to the pipeline fragility, but it benefits from the same foundation: once repos are classified as first-class objects, slot-aware routing has something to route to.

## 2026-10-10 — The architecture actually lands

The Phase 3 question answered itself. Four `RepoDisposition` values turned out to be exactly right — `HAS_WORK`, `EMPTY_BRANCH`, `NO_BRANCH`, `ALREADY_LANDED` — because they map one-to-one to what steps need to decide. Nobody has asked for a fifth. Which is either lucky or evidence that the taxonomy was correctly derived from the pipeline's actual decision points rather than guessed from the domain model.

Phase 4 replaced thirteen skip predicates with five declared modes on each step. The shift from "each step decides whether to run" to "the engine decides which steps exist" is subtle but significant. Before: add a new mode and you're touching every affected step's skip predicate, hoping you don't miss one. After: declare the mode, and steps that don't include it are filtered out before the loop starts. The `_skip_cycle_mode` predicate was particularly expensive — it hit the GitHub API to check issue state, and it ran per step per invocation. Now that's a single `determine_pipeline_mode()` call at entry.

Phase 5 added explicit dependencies to step definitions. The immediate trigger was issue #420 — `close_issues` ran before `verify` because nothing in the step list structurally prevented it. Position was the only ordering mechanism, and position is invisible to anyone editing the list. Now `close_issues` declares `requires=("verify",)` and the engine checks before executing.

Three things surprised me during implementation.

First: per-repo progress keys. When steps fan out across repos, progress is tracked as `rebase:engine`, `rebase:soredium` — compound keys. A naive dependency check looking for `ctx.done("rebase")` finds nothing, because the base name is never written. The fix is a scan for all matching prefix keys, but the failure mode is completely silent: the dependency appears unmet, the engine returns an error, and you're debugging a "step failed" message that has nothing to do with the step itself.

Second: the progress dict is a snapshot. The engine reads it once at loop start and never refreshes it. Mechanical steps A and B can both execute within the same loop call. After A completes and writes to the progress file, B's dependency check still sees the stale snapshot. This was never a problem before because mechanical steps didn't have dependencies on each other — they just ran in list order. The fix is simple (update the dict alongside the file) but the bug is invisible until you add structural dependencies.

Third: mode-filtered dependencies. If `land` requires `rebase`, but `rebase` only runs in non-MAIN modes, then running in MAIN mode makes `land` fail — `rebase` was correctly excluded but the dependency check doesn't know that. The fix is to build a set of active step names from the filtered list and only enforce requires against steps that are actually present. Vacuous truth: if the step isn't in this pipeline configuration, its dependents have nothing to wait for.

Five of seven phases done. The remaining two — unifying the verification systems (#429) and typing progress state (#430) — are independent of each other and both build on the foundation already in place. Phase 6 is flagged as highest risk because the two verification systems overlap on eight checks with subtly different logic. The question is which logic to keep — and the answer will probably be "neither, write the correct version from the ground truth."
