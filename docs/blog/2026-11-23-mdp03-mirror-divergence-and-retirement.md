---
layout: post
title: "When the Fork Lies and the Dead Code Stays"
date: 2026-11-23
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [canonical-sync, mirror, retirement, lifecycle]
---

# When the Fork Lies and the Dead Code Stays

A session that fixed a silent failure in the publish pipeline and deleted a thousand lines of code that nobody was calling.

## The mirror that never catches up

`canonical_sync.py` has a function called `mirror()` that pushes canonical's base branch to the fork remote after every publish. When the push fails, it appends a warning: "it catches up on the next publish." Except it doesn't. It never catches up.

The root cause is a CI action — API docs regeneration — that runs independently on both the org repo (casehubio) and the fork (mdproctor). Same action, same trigger, same content, but different SHAs because they commit independently. The histories diverge. Every subsequent mirror push is non-fast-forward, every publish logs the same lie, and the gap grows silently. Engine was 27 commits behind.

The fix had two halves. First, `mirror()` now fetches the fork's main branch before pushing. If the fork has commits canonical doesn't — which should never happen in the model where canonical is the single sync point — it returns `"diverged"` instead of `"failed"` and the warning names the specific commits instead of promising a recovery that can't happen. Second, the CI workflow on all three casehub repos gained `if: github.repository_owner == 'casehubio'` to stop the action from committing on forks in the first place.

What I found interesting is the architectural invariant at play. The canonical repo is the sync point. Both origin and fork only receive from canonical. When this model holds, every push is fast-forward by definition. The CI action broke the model by creating commits outside the canonical flow. Force-pushing to fix it felt wrong — not because it wouldn't work (it would, the fork has no unique work), but because force-push as normal operation masks the real failure. The right fix restores the invariant.

## Deleting what nobody calls

`work_chain.py` and `lifecycle.py` were the original lifecycle engines. The transition table, the state machine, the chaining directives. 1,003 lines between them. By the time I looked, neither had a production caller.

`work_chain.py` exported exactly one live function: `done_fields()`, six lines that read done-not-closed items from the queue. Its `evaluate()` function — the whole chaining engine — was exercised only by tests. Twenty-seven tests across three files, all testing a module no skill invokes.

`lifecycle.py` was similar. The state machine with its `closing:*` states, the transition table, `commit_transition`, `read_state`, `write_state` — all dead. Three live symbols survived: `VALID_STATES` (a frozen set used for `.plan` field validation), and `is_closed()` with `ClosureState` (a git-based branch closure check used by `work_health.py`).

The retirement was mechanical: inline the live symbols where they're consumed, delete the modules and their tests, update the docs. Net result: -1,651 lines, 37 tests removed (5 surviving tests updated to import from the new locations).

The review caught something I missed. My grep for importers searched `project/` and `tests/` but not `brief/`, `scripts/`, or `handover/`. Four files outside those directories still imported from `lifecycle` — they would have crashed at runtime. A wider search at the start would have caught it. The lesson is obvious enough that I shouldn't need to write it down, and yet here I am writing it down.
