---
name: work
description: >
  Use when the user says "work", "work done", "work end", "work pause",
  "work resume", "work start", "work continue", "work next", "work sync",
  or "work find" — detects current
  branch state and routes to the correct work lifecycle skill automatically.
  "work" or "work continue" carries on with the current item. "work start"
  or "work next" moves on to the next item (gates on active work).
  "work done" marks the current item done without starting the next.
  "work end" closes the branch. "work pause" saves state. "work resume"
  restores a paused branch from the stack. "work sync" lands completed
  work without closing the branch. "work find" discovers and populates the
  queue with new work.
---

# work

Unified entry point for the work lifecycle. Routes to Python-driven
pipelines for mechanical operations. The LLM handles judgment steps;
`project/work.py` handles routing and mechanical execution.

---

## Never switch branches yourself

Never create, check out or switch a branch with git. The pipeline manages
branches in every repo — project, workspace and slot clones — atomically.
If the repos look out of step, run `work.py continue` and relay what it
says. It detects the alignment state and either repairs it or returns a
decision for you to present.

---

## Command table

| Invocation | Run |
|------------|-----|
| `work` | `python3 ~/.claude/skills/project/work.py continue` |
| `work continue` | `python3 ~/.claude/skills/project/work.py continue` |
| `work start` (no issue) | `python3 ~/.claude/skills/project/work.py start` |
| `work next` | `python3 ~/.claude/skills/project/work.py next` |
| `work done` | `python3 ~/.claude/skills/project/work.py done` |
| `work start #N` | `python3 ~/.claude/skills/project/work.py start issue_n=N` |
| `work pause` | `python3 ~/.claude/skills/project/work.py pause` |
| `work resume` | `python3 ~/.claude/skills/project/work.py resume` |
| `work find` | `python3 ~/.claude/skills/project/work.py find` |
| `work wrap` | `python3 ~/.claude/skills/project/work.py wrap` |
| `work end` | `python3 ~/.claude/skills/project/work.py end` |
| `work sync` | → **work-end** (close.py) |

Run from the workspace directory. No other arguments: the script resolves
its own context via `ctx.py` internally. Do not run `ctx.py` first.

**Two intents.** `work` and `work continue` mean "carry on" — keep
working on the current item. `work start` (no issue) and `work next`
mean "move on" — begin the next item. When an item is active, "move on"
gates: the user must release it first (done, deferred, move down, or
cancel).

**Multiple issue scheduling.** When the user provides multiple issue
numbers (`work start #42 #43 #44`): run `plan_manager.py append` to add
them all to the queue. If there is no active work, run `work.py start`
— it picks up the first open item. If work is already in progress, the
new issues are queued after the current work; continue as normal and
they will be reached in order via `work next` after each item is released.

**Before a named start.** `work start #N` on a working branch whose
active queue item is not #N: do not run it yet. Offer: pause current
work and start #N (Recommended — preserves current state cleanly), or
continue current work. If #N is the active item, run `work.py continue`
instead.

---

## Reading the output

The script prints KEY=VALUE lines in two phases.

### Alignment output

Printed first, and only when the project and workspace disagree
about which branch is checked out:

| Line | Meaning |
|------|---------|
| `ALIGNMENT_REPAIRED=<state>` | The repos were out of step and have been brought together. Tell the user in one line, with `ALIGNMENT_ACTIONS=`, then carry on |
| `ALIGNMENT_ACTIONS=<what was done>` | Each change made, separated by `; ` |
| `ALIGNMENT=<state>` | The repos are out of step and no repair is safe. An `ACTION=decision` follows with `DECISION=alignment_<reason>` |

### Route output

Printed before the pipeline runs:

| Line | Meaning |
|------|---------|
| `ROUTE_REASON=<reason>` | Why this route was chosen (always present) |
| `ISSUE=<ref>` | The issue the route concerns |
| `ACTIVATED=<ref>` | An open item was activated in the queue |
| `COMMAND=<pipeline>` | The pipeline that will run (`start`, `continue`, `done`, `resume`) |
| `OFFER=wrap_or_continue` | Finished items are waiting — present the wrap-vs-continue decision below, with a recommendation, before doing anything else. Do not skip it and do not offer work-end per issue |
| `DONE_ITEMS=<ref@branch,...>` | Items finished on their branch, awaiting the close ceremony |

### Pipeline output

After routing, the pipeline runs and prints one of these terminal lines:

**`ACTION=<judgment step>`** with `HANDLER=<path>` — Read the handler
file and do what it says, then resume the pipeline:

```
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=<step> outcome=completed
```

Use the `COMMAND=` value printed in the route output, not the word the
user typed. To skip: `outcome=skipped`. If blocked:
`outcome=blocked block_reason="..."`.

**`ACTION=complete`** — The pipeline finished. Report the `SUMMARY=` line.

**`ACTION=stop`** with `NEXT=` — Nothing to run. Tell the user what
`NEXT=` says and run nothing else.

**`ACTION=decision`** with `DECISION=`, `DETAIL=`, `OPTIONS=` — Present
the options with a recommendation and wait. Never run git to resolve
it yourself.

**`DECISION=current_item_not_released`** — The user typed `start` or
`next` while an item is active. Read `handlers/move-on-gate.md` for the
four options (done, deferred, move_down, continue_current). After the
user chooses, call back with:

```
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=move_on_gate outcome=completed choice=<option>
```

If the working tree has uncommitted changes, the pipeline returns
`ACTION=stop` instead — the user must commit or stash first.

**`ACTION=error`** — Report `ERROR=` and `DETAIL=`. If `RETRY=` is
present, re-run the same command.

**`ACTION=user_input`** — A judgment step failed repeatedly. Report
`STEP=`, `REASON=` and `ATTEMPTS=` to the user and ask what to do.

### ACTION → handler table

| ACTION | Handler |
|--------|---------|
| `resolve_issue` | Read `handlers/resolve-issue.md` |
| `branch_name` | Read `handlers/branch-name.md` |
| `platform_coherence` | Read `handlers/platform-coherence.md` |
| `check_protocols` | Read `handlers/check-protocols.md` |
| `brainstorm_offer` | Read `handlers/brainstorm-offer.md` |
| `load_context` | Read `handlers/load-context.md` |
| `stack_pick` | Read `handlers/stack-pick.md` |
| `present_candidates` | Read `handlers/present-candidates.md` |
| `deferred_check` | Read `handlers/deferred-check.md` |
| `resolve_conflict` | Read `handlers/resolve-conflict.md` |
| `recover_plan_offer` | Read `handlers/recover-plan-offer.md` |
| `clone_guard` | Read `handlers/clone-guard.md` |

The output includes `HANDLER=<path>` when a handler file exists. Read
from `HANDLER=` first; fall back to this table for steps without one.

**Cross-repo re-invocation:** When a handler produces `SWITCH_REPO=<name>`,
the active project has changed. Make the follow-up call from that
project's workspace directory, with no context arguments: the script
resolves the new project and workspace itself. Do not carry paths over
from the earlier call.

---

## Wrap and end

`work wrap` and `work end` are the end-of-session sequence. Run the command
and do each step it hands you, in the order it hands them; never run the steps
from memory or out of order.

| | `work wrap` | `work end` |
|---|---|---|
| Review, diary entry, loose ends filed and queued | yes | yes |
| Is the active item finished? Mark it done if so | yes | yes |
| Land what is marked done; publish | no | yes |
| Handoff | yes | yes |

- **`work wrap`** changes nothing outside the working branches: nothing is
  landed or published. Use it at the end of any session.
- **`work end`** also lands every item marked done and publishes.
  Typing it is the user's go-ahead to publish exactly what the ceremony
  covered: its own project (or the repos of its slot or clone)
  and their landed blog entries. Never publish or post anything the
  sequence did not, and never look for other repos that are ahead.
- It can be run part-way through the queue. An unfinished active item is never
  landed; it stays active on its branch.

The `item_finished` step needs an answer, not just completion:

```
python3 ~/.claude/skills/project/work.py <wrap|end> step_done=item_finished outcome=completed finished=yes
python3 ~/.claude/skills/project/work.py <wrap|end> step_done=item_finished outcome=completed finished=no
```

If a step fails the sequence stops with `ACTION=error` and `STEP=`. Fix what
it names (`ERROR=squash_review_needed` means invoke `git-squash`), then run the same
command again: it resumes at that step. Do not carry on by hand.

When it completes it prints one `STEP_<NAME>=` line per step. Relay them. If
there is an `ATTENTION=` line, tell the user what could not be done and why.
Then run the command on the `THEN=` line: after a finished item it scaffolds
the next one, and you stop there without beginning the work.

---

## Finishing an item

When the active issue's work is complete, run:

```bash
python3 ~/.claude/skills/project/work.py done
```

It marks the item done on its branch and prints `OFFER=wrap_or_continue`.

**Done is not closed.** `done` on a feature branch marks the active item
*done on its branch* and activates the next one. Nothing is landed and
the GitHub issue stays open. Never close an issue, tick a checkbox or run
work-end to move to the next issue: `work end`, once, lands and closes
every done item in queue order. `DONE_ITEMS` lists what is waiting.

**After done, "Continue" means** `work.py continue` on the next item.
Where its branch starts is decided by the queue, not by you:
`create-branches` stacks it on the branch just finished, in every repo,
unless the item is marked `(from main)`. Relay `STACKED=`, `STACKED_ON=`,
`START_REASON=` and `CUT_FROM=` from the output; never pick a start
point or run `git checkout -b` yourself.

---

## Fallback: merge conflict in .queue

If routing returns unexpected results (wrong issue, missing items), check
whether the `.queue` file contains merge conflict markers (`<<<<<<`). If
it does, stop and show the user both sides of the conflict. The queue is
the only record of what is finished and what is waiting: never delete or
hand-edit it. Once the user has said which side is right, restore that
version with git and re-run the pipeline.

---

## Wrap-vs-continue decision

The pipeline prints `NEXT_ITEM=`, `NEXT_TITLE=`, `NEXT_SCALE=`,
`NEXT_COMPLEXITY=`, and `DONE_WAITING=` alongside `OFFER=wrap_or_continue`.
Use these to make the recommendation — do not search for or request
the data separately.

Present four things, then recommend:

1. **Context usage** — approximate percentage of the context window used.
   Do NOT trust `<total_tokens>` — compression resets it, so it always
   reads ~15M. Instead estimate from session work: each issue/task
   consumes roughly 10-20% of the window. A session that has completed
   3+ issues is likely past 50%. If you can't recall specifics from
   early in the session without re-reading, compression has happened.
2. **Next task** — from the pipeline output: `NEXT_ITEM`, `NEXT_SCALE`,
   `NEXT_COMPLEXITY`. If scale is "unknown", estimate from the title.
3. **Relevance to current context** — does the next task build on what
   this session worked on, or is it a topic change?
4. **Recommendation with reasoning** — one of:

| Situation | Recommend |
|-----------|-----------|
| Enough room, no done items waiting | **Continue** |
| Enough room, done items piling up (DONE_WAITING >= 2) | **End then continue** — land what's done, keep working |
| Not enough room, done items waiting | **End and stop** |
| Not enough room, nothing done waiting | **Wrap and stop** |

Examples:
- "Continue — context is ~30% used, next task is S/Low and builds
  directly on the work we just did"
- "End then continue — 3 items waiting to land, context is ~40% used,
  next task is S and same domain"
- "End and stop — context is ~70% used, next task is M/High in a
  different area, 2 items waiting"
- "Wrap — context is ~60% used, next task is a topic change, fresh
  session will reason better"

Compressed context is not always bad — when the session moved in one
direction, compressed understanding is still better than a cold start
that has to re-read everything. Wrap when the next task is a topic
change where compressed context adds noise, not signal.

After the user decides, record the recommendation and choice:

```bash
python3 project/worktrace.py record context-budget repo=$WORKSPACE branch=$BRANCH \
    recommendation=continue next_issue=$NEXT_ITEM next_scale=$NEXT_SCALE chosen=continue
```

**Keeping scale/complexity in sync.** When you change a scale or
complexity label on a GitHub issue, also update the queue item:

```bash
python3 work-slot/plan_manager.py set-scale <queue_path> ref=<ref> scale=<S> complexity=<Med>
```

---

## Mid-task context monitoring

While working on an item, watch for signs that the context is running
long relative to what remains on the task. If the item has consumed a
large share of the context window and there is still substantial work
ahead, suggest `work wrap` before context is exhausted — not after.

Signals: you can no longer recall details from the start of the session
without re-reading; the task is growing beyond its original scale
estimate; you are on your third or fourth sub-problem within the same
item.

This is a judgment call, not a hard threshold. A short item that is
almost done should finish. A large item with hours of work ahead should
wrap early enough for the handoff to capture context while it is fresh.

---

## Close / Sync

`work end` runs `project/work.py end` (see Wrap and end above); the atomic
ceremony in `work-end/close.py` is one of its steps. `work sync` still
invokes the `work-end` skill directly.

---

## Skill Chaining

**Routes to:**
- `work-start` — for `start` and initial `work` commands
- `work-pause` — for `pause` command
- `work-resume` — for `resume` command
- `work-end` (close.py) — for `end` and `sync` commands
- `handover` — when user picks "wrap" from contextual options

**Complements:** `quick-fix` — lands small changes on the base branch without a feature branch

**Uses:**
- `project/work.py` — Python-driven pipeline for start/continue/done/pause/resume/find
- `project/work_route.py` — decides from the queue what `continue` runs
- `project/alignment.py`, `project/alignment_repair.py` — check, and where safe repair, that project and workspace are on the same branch

**This skill routes and dispatches.** Mechanical execution lives in
`work.py`. Judgment step details live in `handlers/*.md`. Close ceremony
lives in `close.py`.
