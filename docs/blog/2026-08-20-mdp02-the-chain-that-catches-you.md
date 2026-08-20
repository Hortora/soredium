---
title: "The chain that catches you"
date: 2026-08-20
author: mdp
entry_type: note
subtype: diary
series: issue-261-unified-work-queue
projects: [soredium]
tags: [lifecycle, state-machine, routing, design]
---

# The chain that catches you

The work lifecycle had a split personality. On a branch, `.plan` tracked
your queue and `work next` advanced through it. On main, an ad-hoc
enrichment pipeline guessed what you might want to do next. Two
mechanisms, two codepaths, two sets of failure modes — and a gap between
them where work fell through.

The gap shows up as two specific failures. You call `work next` and skip
an issue that isn't actually finished. Or you call `work continue` and
there's nothing to continue because the queue drained while you weren't
looking. Both cases end with the same result: work that should have been
done isn't, and nobody told you.

## Bidirectional chaining

The fix is a chain of four commands — `continue`, `next`, `end`, `find` —
where each one knows when to cascade forward and when to guard backward.

```
continue ←→ next ←→ end ←→ find
    →  "nothing to do, cascade forward"
    ←  "not ready, go back"
```

If you call `continue` and the active issue is already closed, it chains
forward to `next`. If you call `next` and the issue is still open, it
guards backward: "Issue #42 is still open. Continue working." If the
queue empties, `next` chains to `end`. After `end` finishes its ceremony,
it chains to `find` — which runs the discovery pipeline and populates
the queue with new work.

The backward direction is the interesting part. Call `find` when there's
unfinished work? It pushes you back to `next`. Call `end` when the queue
has items? Back to `next`. No matter which command you type, you land at
the right place. You can't accidentally skip work, and you can't get
stuck at a dead end.

## Python decides, LLM follows

I wanted the chaining logic out of the skill instructions entirely. When
routing decisions live in markdown that Claude interprets, they're
non-deterministic — the LLM might reason its way to the wrong branch,
especially under context pressure. A `work_chain.py` module now evaluates
the current state and returns a directive: `proceed`, `chain_to_next`,
`guard_continue`, and so on. The skill reads the directive and follows it.
No judgment calls.

This is the pattern I want more of: mechanical decisions in Python,
creative decisions in the LLM. The state machine shouldn't depend on
whether Claude is having a good context day.

## The naming problem

The new state for "queue empty, ceremony done, plan still exists" was
originally called `ended`. The design review caught a collision: the
worklog layer already maps `idle → ended` to mean "branch permanently
closed." A new lifecycle state also called `ended` with different
semantics — "main queue paused between find cycles" — creates ambiguity
that worklog consumers can't resolve.

`drained` is better. The queue is empty. It's waiting to be refilled.
The plan persists. `drained → transitioning → active` reuses the existing
context-loading path when `work find` populates new items — no new
activation machinery needed.

## What this opens up

The `.plan` on main is the real unlock. Today, starting a session on main
means running enrichment scripts and manually picking an issue. With a
main `.plan`, the queue persists across sessions. `work find` populates
it, `work next` advances through it, `work end` closes the ceremony
and sets state to `drained`. The same commands, the same queue, whether
you're on a feature branch or main.

The corruption recovery work (#262) builds on top of this. When the
state machine reaches an inconsistent state — a mid-ceremony crash, a
stale `.plan` from a previous branch — Python detects the inconsistency
and proposes a resolution directive. Same pattern: Python decides, LLM
presents. That's next.
