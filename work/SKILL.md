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
pipelines for mechanical operations. The LLM handles routing decisions
and judgment steps; `project/work.py` handles mechanical execution.

---

## Step 1 — Parse and route

**Step 1a — Command table**

| Invocation | Route |
|------------|-------|
| `work end` | → **work-end** (work_end_orchestrator.py) |
| `work sync` | → **work sync** (work_end_orchestrator.py mode=sync) |
| `work pause` | → pipeline: `pause` |
| `work resume` / `resume` | → pipeline: `resume` |
| `work continue` / `continue` | → pipeline: `continue` |
| `work next` | → pipeline: `next` |
| `work find` | → pipeline: `find` |
| `work` / `work start` | → router (Step 1b) → pipeline: `start` |
| `resume handover` | → handover skill directly |

For `continue`, `next`, `find`: read `CHAIN_DIRECTIVE` from ctx.py
first (Step 1c).

**Step 1b — Run ctx.py**

```bash
python3 ~/.claude/skills/project/ctx.py
```

Read all KEY=VALUE lines. These determine the route AND provide
context for work.py args.

**Step 1b-pre — Corruption triage (before normal routing)**

If `CORRUPTION_COUNT` > 0, enter triage flow:

- If `AUTO_RECOVERABLE=yes`: execute each `CORRUPTION_N_AUTO_ACTION`
  without prompting, re-run ctx.py to verify.
- If `AUTO_RECOVERABLE=no`: present findings with actions, wait for
  user to pick. Execute actions, re-run ctx.py.

| Action | Command |
|--------|---------|
| `accept_default` | No-op |
| `write_active` | `lifecycle.py commit-transition ... new_state=active` |
| `switch_to_plan_branch` | Checkout both repos to plan branch |
| `update_plan_branch` | `plan_manager.py set-state ... key=branch value=<branch>` |
| `remove_plan` | `rm <PLAN_PATH>` and commit |
| `continue_close` | Route to work-end |
| `rollback_to_active` | `lifecycle.py commit-transition ... new_state=active event=abort_close` |
| `sync_plan_with_github` | `work_health.py --scope entry` |
| `fetch_and_checkout` | `git fetch origin <branch> && git checkout <branch>` |
| `ignore` | No-op |

**Step 1c — Bidirectional chaining**

| DIRECTIVE | Action |
|-----------|--------|
| `proceed` | Continue with the invoked command |
| `chain_to_next` | Redirect to `next` pipeline |
| `chain_to_end` | Redirect to work-end |
| `chain_to_find` | Redirect to `find` pipeline |
| `guard_continue` | "Issue still open. Continue working." → `continue` pipeline |
| `guard_next` | "Queue has items. Continue or advance?" → present choice |
| `no_work_found` | "No work found." → stay |

**Step 1d — Wrong-context errors**

| Invocation | Condition | Action |
|------------|-----------|--------|
| `work resume` | on feature branch | Error: "Use `continue`, not `resume`." |
| `work resume` | main + empty stack | Error: "Nothing to resume." |
| `work start` | `ROUTE=resume_branch` | Redirect → `continue` |

## Step 2 — Route based on ctx.py output

| `ROUTE` | Action |
|---------|--------|
| `start` | What-next recommendation (if no issue specified), then → `start` pipeline |
| `resume_stack` | → `resume` pipeline (stack_pick handler shows picker) |
| `resume_branch` | → contextual options menu |
| `workspace_dirty` | Warn, offer reset, then → `start` pipeline |
| `drained` | "Queue drained. Run `work find` or `work start #N`." |

**What-next recommendation (start without issue):**

1. `python3 scripts/enrichment.py refresh --repo $OWNER_REPO`
2. `python3 scripts/enrichment.py what-next --repo $OWNER_REPO --mode general --limit 5`
3. Present candidates. User picks → `start` pipeline with issue number.

**Contextual options (on feature branch):**

Present: continue / switch / next / sync / end / pause / wrap.
User picks → route to the matching pipeline or skill.

**Mid-session issue completion (D4):** When an issue completes during
a session, check queue state before suggesting next action.
Recommend `next` or `wrap` with reasoning. Never suggest work-end
when queue has remaining issues.

**Wrap-vs-continue guidance:**

Do NOT use `<total_tokens>` to judge session freshness — compression
resets the count, so it always reads ~15M regardless of how long the
session has been running. A compressed context loses fidelity: earlier
decisions, file contents, and reasoning are summarised, not preserved.

Use **session work completed** as the signal instead:

| Signal | Favours continue | Favours wrap |
|--------|-----------------|--------------|
| 0–1 issues completed this session | yes | — |
| 2 issues completed | yes if next is related | wrap if topic change |
| 3+ issues completed | — | yes |
| Next issue is XS/S and same domain | yes | — |
| Next issue is M+ or different domain | — | yes |
| Session has hit compression (you can't recall early details) | — | yes |
| Current work built context the next issue needs | yes | — |

**Compression is not always bad.** When the session has moved in one
direction — same domain, same codebase, decisions building on each
other — compressed context still carries accumulated understanding
that a cold start would have to rebuild from scratch. A fresh session
re-reads files but loses the reasoning chain. Favour continuing when
the next task builds directly on what this session explored, even if
compression has happened. Favour wrapping when the next task is a
topic change where the compressed context adds noise, not signal.

Always recommend one option with reasoning. Never present bare choices.

---

## Orchestrator Loop

For commands: `start`, `continue`, `pause`, `resume`, `next`, `find`.

Once routing determines the command, call `project/work.py` in a loop:

```bash
python3 project/work.py <command> \
    workspace=$WORKSPACE project=$PROJECT \
    branch=$BRANCH base_branch=$BASE_BRANCH \
    on_main=$ON_MAIN in_slot=$IN_SLOT \
    covers=$COVERS issue_repo=$ISSUE_REPO \
    meta_state=$META_STATE owner_repo=$OWNER_REPO \
    issue_n=$ISSUE_N issue_title=$ISSUE_TITLE \
    has_handoff=$HAS_HANDOFF handoff_path=$HANDOFF_PATH \
    has_platform_doc=$HAS_PLATFORM_DOC \
    has_protocols_dir=$HAS_PROTOCOLS_DIR \
    flyway_next_v=$FLYWAY_NEXT_V \
    design_repo_key=$DESIGN_REPO_KEY \
    [plan_path=$PLAN_PATH] [slot_path=$SLOT_PATH]
```

Read `ACTION=` from output. Dispatch:

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
| `complete` | Done. Report summary. |
| `error` | Read ERROR= and STEP=. Diagnose and retry. |
| `user_input` | A judgment step failed repeatedly. Ask the user. |

After handling a judgment step, call work.py again with the same args
plus `step_done=<step_name>` and any values the handler produced.
Repeat until `ACTION=complete`.

---

## Close / Sync (work-end orchestrator)

`work end` and `work sync` use `work_end_orchestrator.py` directly:

```bash
python3 work-end/work_end_orchestrator.py \
    workspace=$WORKSPACE project=$PROJECT branch=$BRANCH \
    base_branch=$BASE meta_state=$META_STATE \
    [mode=sync] [covers=...] [issue_repo=...] [plan_path=...]
```

These commands are NOT routed through `project/work.py`. They use the
existing work-end close pipeline with its own step list and handlers.

---

## Skill Chaining

**Routes to:**
- `work-end` (work_end_orchestrator.py) — for `end` and `sync` commands
- `handover` — when user picks "wrap" from contextual options

**Uses:**
- `project/work.py` — Python-driven pipeline for start/continue/pause/resume/next/find
- `work_chain.py` — bidirectional chaining engine for routing directives

**This skill routes and dispatches.** Mechanical execution lives in
`work.py`. Judgment step details live in `handlers/*.md`. Close ceremony
lives in `work_end_orchestrator.py`.
