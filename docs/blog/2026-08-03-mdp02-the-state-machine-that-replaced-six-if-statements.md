---
layout: post
title: "The State Machine That Replaced Six If-Statements"
date: 2026-08-03
entry_type: note
subtype: diary
projects: [soredium]
---

The soredium work lifecycle has eleven entry points — `work`, `work start`, `work end`, `work pause`, `work resume`, `work epic`, `work next`, `work-slot create`, `work-slot epic`, `work-slot next`, and the session hook. Each one needs to know what state the system is in before it can do anything useful. Until today, each one figured that out independently.

The detection logic in work-start had six states, derived from five filesystem signals: does `.meta` exist? What branch are we on? Does `.pause-stack` have entries? Does a handoff file exist? Is there an `.epic` file? Combine those signals correctly and you get the right behaviour. Get one combination wrong and context setup is silently skipped — no error, no warning, just missing garden search results or unloaded specs.

Six of eleven entry points had gaps. `work epic #N` created the branch and scaffold, then told the user "Run work-start to begin" — a manual second step that added friction without value. `work next` advanced to the next epic issue but never refreshed context for the new issue's domain. The session hook ran project setup checks but never detected that you were sitting on a feature branch with work in progress. Each gap was a silent failure: the system appeared to work, but context setup — garden search, spec loading, protocol checks — was skipped.

I'd been thinking about this as a wiring problem. Claude framed it differently: if every entry point is re-deriving state from scattered signals, the problem isn't the individual entry points — it's the inference model. Replace inference with explicit state.

The fix is a single Python module — `lifecycle.py` — with a data-driven transition table. Eleven states, eighteen transitions, one dict:

```python
TRANSITION_TABLE = {
    ('idle', 'work'):              ('scaffolded', ['create_branch', 'write_meta'], []),
    ('scaffolded', 'auto_setup'):  ('active',     ['garden_search', 'load_specs', ...], []),
    ('active', 'work_pause'):      ('paused',     ['wip_commit'], ['switch_to_main', 'push_stack']),
    # ... 15 more rows
}
```

Every entry point is now a single line: fire an event, get back the effects to execute. No entry point decides what subset of work-start to run. The table decides. An entry point that fires the wrong event gets `InvalidTransition` with a human-readable message. An entry point that doesn't exist in the table doesn't exist in the system.

Two design choices emerged from the adversarial review that I hadn't anticipated. First, the closing sequence needed its own sub-states — `closing:review`, `closing:verified`, `closing:promoted`, `closing:pushed`, `closing:merged`, `closing:stamped` — each gated by a specific script completing successfully. The pre-push hook reads the state and blocks pushes that skip gates. This generalises the single `.artifacts-promoted` stamp file into enforcement of every closing step.

Second, some transitions switch branches. `work_pause` writes state to `.meta` on the feature branch, then switches to main — after which `.meta` is inaccessible. The review caught this: a two-phase protocol (validate, then write) doesn't work when the write target disappears. The solution is three phases: `transition()` validates without writing, the caller executes pre-commit effects, `commit_transition()` writes state atomically, then post-commit effects handle the branch switch. State is always written before it becomes inaccessible.

The testability difference is stark. The old inference logic required mocking five filesystem signals in combination — each new entry point multiplied the test matrix. The state machine is a pure function: given state X and event Y, assert state Z and effects list. One parametrised test covers every valid transition. Another covers every invalid one. The entire module — transitions, read/write, migration, hygiene checks — has 127 tests that run in one second.

What this enables is more interesting than what it replaces. The state machine gives the worklog (#158) exactly the event stream it needs — every `transition()` call is a natural emission point. The pre-push hook generalises #170's single promotion gate to every closing step. And the hygiene invariants — untracked files, branch alignment, clean working tree — run mechanically at every transition instead of being checked ad-hoc by whichever skill remembers to.

The inference logic worked fine with three entry points. It stopped working at eleven. The state machine will work at fifty.
