---
name: work
description: >
  Use when the user says "work", "work end", "work pause", "work resume",
  "work continue", "work next", "work sync", or "work find" — detects current
  branch state and routes to the correct work lifecycle skill automatically.
  "work" alone starts new work or shows the pause stack. "work end" closes the
  branch. "work pause" saves state. "work continue" keeps working on the current
  branch. "work resume" restores a paused branch from the stack. "work next"
  advances to the next issue in the .plan queue. "work sync" lands completed
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
| `work start` (no issue) | `python3 ~/.claude/skills/project/work.py continue` |
| `work continue` | `python3 ~/.claude/skills/project/work.py continue` |
| `work next` | `python3 ~/.claude/skills/project/work.py continue` |
| `work start #N` | `python3 ~/.claude/skills/project/work.py start issue_n=N` |
| `work pause` | `python3 ~/.claude/skills/project/work.py pause` |
| `work resume` | `python3 ~/.claude/skills/project/work.py resume` |
| `work find` | `python3 ~/.claude/skills/project/work.py find` |
| `work end` | → **work-end** (close.py) |
| `work sync` | → **work-end** (close.py) |

Run from the workspace directory. No other arguments: the script resolves
its own context via `ctx.py` internally. Do not run `ctx.py` or
`work_chain.py` first.

**Multiple issue scheduling.** When the user provides multiple issue
numbers (`work start #42 #43 #44`): run `plan_manager.py append` to add
them all to the queue. If there is no active work, run `work.py continue`
— it picks up the first open item. If work is already in progress, the
new issues are queued after the current work; continue as normal and
they will be reached in order via `done` → `work.py continue`.

**Before a named start.** `work start #N` on a working branch whose
active queue item is not #N: do not run it yet. Offer: pause current
work and start #N (Recommended — preserves current state cleanly), or
continue current work. If #N is the active item, run `work.py continue`
instead.

---

## Reading the output

The script prints KEY=VALUE lines in two phases.

### Alignment output

Printed first, and only when the project and workspace repos disagree
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
`NEXT=` says and run nothing else. With `STOP_REASON=canonical_repo_of_clone_family`, tell the user to open the session at the path in `NEXT=` (or run the create command it gives) and do not start work in the current repo.

**`ACTION=decision`** with `DECISION=`, `DETAIL=`, `OPTIONS=` — Present
the options with a recommendation and wait. Never run git to resolve
it yourself.

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

The output includes `HANDLER=<path>` when a handler file exists. Read
from `HANDLER=` first; fall back to this table for steps without one.

**Cross-repo re-invocation:** When a handler produces `SWITCH_REPO=<name>`,
the active project has changed. Make the follow-up call from that
project's workspace directory, with no context arguments: the script
resolves the new project and workspace itself. Do not carry paths over
from the earlier call.

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

Present four things, then recommend:

1. **Context usage** — approximate percentage of the context window used.
   Do NOT trust `<total_tokens>` — compression resets it, so it always
   reads ~15M. Instead estimate from session work: each issue/task
   consumes roughly 10-20% of the window. A session that has completed
   3+ issues is likely past 50%. If you can't recall specifics from
   early in the session without re-reading, compression has happened.
2. **Next task scale and complexity** — XS/S/M/L/XL and Low/Med/High
3. **Relevance to current context** — does the next task build on what
   this session worked on, or is it a topic change?
4. **Recommendation with reasoning** — one of:
   - "Continue — context is ~30% used, next task is S/Low and builds
     directly on the orchestrator work we just did"
   - "Continue — context is full but next task is XS and same domain,
     compressed context still carries the understanding we built"
   - "Wrap — context is ~60% used and next task is a different repo
     with different domain, fresh session will reason better"
   - "Wrap — we've completed 4 issues, context is heavily compressed,
     next task is M/High in a different area"

Compressed context is not always bad — when the session moved in one
direction, compressed understanding is still better than a cold start
that has to re-read everything. Wrap when the next task is a topic
change where compressed context adds noise, not signal.

---

## Close / Sync

`work end` and `work sync` invoke the `work-end` skill, which runs
`close.py` — the atomic close ceremony. These commands are NOT routed
through `project/work.py`.

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
