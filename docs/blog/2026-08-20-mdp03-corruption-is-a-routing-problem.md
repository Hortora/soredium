---
layout: post
title: "Corruption is a routing problem"
date: 2026-08-20
entry_type: note
subtype: diary
projects: [soredium]
tags: [lifecycle, state-machine, corruption, design]
---

The lifecycle state machine has been solid since it landed — explicit states, a transition table, three-phase commit protocol. But one category of failure was handled badly: what happens when the state is *incoherent with the environment*?

The `.plan` says `state: active` but the branch doesn't exist. Or all the covered issues are already closed on GitHub. Or the state field has a value that isn't in `VALID_STATES` — which crashes `ctx.py` outright, because `work_state.py` calls `read_state()` without catching `CorruptedState`.

The existing handling was a grab bag. `read_state()` defaulted missing state fields to `active` (legacy migration — fine). Invalid values raised an exception (crashes the session — not fine). And `work_health.py` had advisory warnings for some scenarios that were easy to miss.

I wanted structured recovery: detect the inconsistency, present it with actions, let the user confirm. No auto-fixing — when your state is incoherent, auto-fixing based on those same incoherent assumptions is how you get cascading corruption.

The key design insight was that corruption is a routing concern, not a transition concern. When the state doesn't match reality, you shouldn't enter the normal work lifecycle menu at all — you should enter a triage flow. That places corruption detection in the routing path (`ctx.py`), not inside `transition()`.

A new `corruption.py` module owns this. Eight scenarios, each a pure function: takes state and environment, returns an optional `Finding` with scenario ID, severity, and an ordered list of recovery actions. `diagnose()` orchestrates all eight with short-circuiting — if the state value itself is invalid (S2), skip the checks that depend on having a valid state (S3, S4, S6).

The module boundary matters. `lifecycle.py` stays a pure state machine — transitions, validation, read/write. `corruption.py` asks "is this state coherent with the environment?" and imports from lifecycle without lifecycle knowing corruption exists. `work_health.py` keeps its advisory checks — the three that overlap with corruption scenarios will eventually delegate detection to `corruption.py` so the logic isn't duplicated.

`ctx.py` calls `diagnose()` after state detection and emits `CORRUPTION_COUNT` plus indexed `CORRUPTION_N` / `CORRUPTION_N_SEVERITY` / `CORRUPTION_N_DETAIL` / `CORRUPTION_N_ACTIONS` lines. The `work` router checks `CORRUPTION_COUNT > 0` before normal routing and enters the triage flow when findings exist.

The `base_branch` threading through `work_health.py` landed as part of this branch — three functions that compared against literal `"main"` now accept a parameter. Small fix, but it had been sitting in the #261 review notes as a residual.

The corruption module opens up a useful pattern: any time a state machine interacts with an external environment (git branches, GitHub issues, filesystem markers), you need a coherence layer that sits between the state reader and the routing logic. The state machine itself shouldn't know about the environment — it validates transitions. The coherence layer asks whether the preconditions for those transitions actually hold.
