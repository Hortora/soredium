# Work Command Taxonomy — Design Spec

**Issue:** #202
**Date:** 2026-08-10
**Status:** Draft
**Scope:** work lifecycle commands, `/brief` orientation, HANDOFF.md integration
**Related Specs:** `2026-08-06-unified-work-state-design.md` (#188) — that spec's
"stop caching, start deriving" principle is complementary: `continue` loads
HANDOFF.md for its narrative value (reasoning, failed attempts), not for state.
Issue progress, branch status, and queue position derive from their authoritative
sources (`.plan`, GitHub, git).

---

## Problem Statement

Three issues with the current work lifecycle commands:

1. **"resume" is semantically overloaded** — used for both pause-stack restoration
   (`work-resume` skill, lifecycle event `work_resume`) AND reading HANDOFF.md to
   continue on an existing branch (Step 4 option in `work/SKILL.md`). Two different
   operations, one word.

2. **"start" appears when work is already started** — after `work start` in one
   session, `/clear`, then `/work`, Step 4 shows "start — begin working (first
   session on this branch)" because `HAS_HANDOFF=no`. The label is wrong — the
   branch exists, scaffold exists, work has been done. The underlying behavior
   is correct (runs the resume path), but the label misleads.

3. **No "continue" concept** — the distinction between "resume" (has HANDOFF.md)
   and "start" (no HANDOFF.md) in Step 4 is an implementation detail the user
   shouldn't see. Both mean "keep working on this branch."

Additionally, HANDOFF.md's role has been largely mechanised. Context that used to
require explicit handover narrative is now captured by `.meta`, `.plan`, specs,
JOURNAL.md, and `work_health.py`. The remaining unique value of HANDOFF.md is
the 2-3 line "Last Session" narrative (what was tried, what reasoning drove
decisions) — and `continue` can auto-load this.

---

## Decisions

### D1: Command taxonomy

**Choice:** Three distinct verbs with non-overlapping semantics

| Verb | Meaning | Lifecycle? |
|------|---------|-----------|
| `continue` | Keep working on the current branch | Yes — auto-loads all context |
| `resume` | Restore a paused branch from the pause stack | Yes — pause-stack only |
| `brief` | Orientation summary — what's the state of things? | No — purely informational |

**Alternatives:**
- Single `resume` for both pause-stack and branch continuation — ambiguous, current problem
- `continue` + `resume` only, no `brief` — loses the orientation use case

**Rationale:** Each verb maps to exactly one operation. No overloading. The user
never has to wonder which "resume" they're invoking.

**Exploration:** deep-analysis
**Status:** captured

### D2: `continue` subsumes HANDOFF.md reading

**Choice:** `continue` reads HANDOFF.md when present and presents a brief
summary (what was done, what reasoning drove decisions) before proceeding —
along with `.meta`, `.plan`, specs, and `work_health.py` output. No separate
"resume handover" step.

`resume handover` still works as an explicit manual invocation if the user wants
to interrogate the handover document directly. But the automatic context
restoration is intrinsic to `continue`.

**Alternatives:**
- Keep `resume handover` as a distinct lifecycle action — adds a step the user
  doesn't need, since `continue` already loads everything
- Remove HANDOFF.md entirely — loses the narrative context ("what was tried and
  failed") that git log can't capture

**Rationale:** HANDOFF.md's unique value (narrative context) is thin — 2-3 lines.
It doesn't warrant a separate command. Auto-loading it during `continue` gives
the LLM the context without user ceremony.

**Depends on:** D1 (continue exists as a distinct verb)
**Exploration:** deep-analysis
**Status:** captured

### D3: `continue` done-detection with auto-suggest

**Choice:** When `continue` detects the current issue is complete, it
auto-suggests the next action:
- If queue has remaining items: "Current issue complete. `next` (N remaining) or `end`?"
- If queue is empty: "Current issue complete. `end` to close the branch?"

**Mechanical definition:** "current issue is complete" = the active `.plan`
leaf is marked `[x]` after `work_health.py --scope entry` runs `plan_state`
validation. `continue` runs health sync explicitly (behavioral spec step 2
in both `HAS_HANDOFF` paths) before done-detection. `plan_state`
batch-validates all `.plan` issues against GitHub and marks closed issues
via `plan_manager.mark_completed()`. No additional API call is needed after
health sync — done-detection reads `.plan` directly.

**Implementation owner:** Done-detection lives in `work/SKILL.md`'s
`continue` action, not in `work_router.py`. The router resolves routing
state; the skill implements UX behavior. After health sync,
`PLAN_ACTIVE_ISSUE` is empty when the current issue has been marked
complete (`mark_completed()` removes the `← active` marker). The skill
checks:
- `PLAN_ACTIVE_ISSUE` empty + `PLAN_POSITION` has remaining → suggest `next`
- `PLAN_ACTIVE_ISSUE` empty + all completed → suggest `end`
- `PLAN_ACTIVE_ISSUE` set → in progress, no auto-suggest

**When `HAS_PLAN=no`:** Done-detection is not available — no plan outputs
are present. `continue` proceeds directly to context loading without
auto-suggest. This covers single-issue branches, branches started
before the plan system, and legacy epic branches. No degradation — these
branches work exactly as today's resume path does.

**Alternatives:**
- Report only — "Current issue is complete." Then wait for user to type the
  next command. More control, extra round-trip.

**Rationale:** Saves a round-trip for the common case. The user can always ignore
the suggestion and do something else. Done-detection is scoped to `.plan`
branches because they're the only ones with a well-defined "current issue"
concept.

**Depends on:** D1 (continue exists)
**Exploration:** quick
**Status:** captured

### D4: Wrong-context command behavior

**Choice:** Forgiving for `start`, strict for `resume`, error for `continue` on main

| Command | Wrong context | Behavior |
|---------|--------------|----------|
| `work start` | On feature branch | **Redirect** → `continue` + note: "Already on `<branch>` — continuing." |
| `work resume` | On feature branch (not paused) | **Error** → "Not paused — use `continue` to keep working, or `work pause` first." |
| `work continue` | On main, no stack | **Error** → "No active branch — use `work` to start new work." |
| `work continue` | On main, with stack | **Error** → "No active branch — use `work` to start new work or `work resume` to return to a paused branch." |
| `work continue` | workspace_dirty | **Error** → "Workspace is on a stale branch — run `work` to clean up." |
| `work resume` | On main, no stack | **Error** → "Nothing to resume — pause stack is empty. Use `work` to start new work." (**Intentional behavioral change:** currently this falls through the router to `ROUTE=start` and redirects to work-start. The new behavior is semantically stricter — "resume" with nothing to resume is an error, not a silent redirect.) |

**Alternatives:**
- All strict (error on every wrong-context) — punishes `start` users unnecessarily
- All forgiving (redirect everything) — undermines the semantic distinction for `resume`

**Rationale:** `start` redirect is forgiving because the intent is clear. `resume`
is strict because the semantic distinction is the whole point. `continue` on main
has no reasonable interpretation.

**Exploration:** quick
**Status:** captured

### D5: `/brief` as standalone skill with structured data layer

**Choice:** `brief.py` script outputs structured data (branch, issue, plan state,
recent commits, HANDOFF summary, stack depth, notes, health checks). `/brief`
skill is a thin CLI wrapper that formats this output for the terminal.

The real delivery mechanism will be the Trellis frame — showing this information
ambiently. `brief.py` is the reusable data contract; `/brief` is the interim CLI
interface.

```
brief.py (structured data output)
  ├── /brief skill (CLI formatting — lightweight wrapper)
  └── Trellis frame (future — reads same structured output)
```

`brief.py` composes output from existing scripts: `ctx.py` + `work_router.py`
+ `work_health.py` + HANDOFF.md parsing. It imports `ctx.resolve()`,
`work_router.detect_state()`, and `work_health.run_checks()` as Python
functions — direct calls, not subprocess shelling. `ctx.py` requires
refactoring to support import (see Implementation Scope). It derives no
new state from the first three — it calls each sequentially, collects
their output, and emits a unified structured result. The only new logic is branch
enumeration for the "main, no work" state (see D6) and HANDOFF.md summary
extraction.

**What `brief.py` adds beyond calling scripts directly:** a single structured
data contract consumable by both the CLI skill and the future Trellis frame.
Without it, every consumer replicates the composition logic.

**Dependency diamond concern:** The scripts are called sequentially within
a single invocation. No concurrent writer exists during `brief` execution —
`.meta`, `.plan`, and git state do not change between calls. Inconsistent
views are not possible in practice.

**Output format:** KEY=VALUE lines for scalars, consistent with `ctx.py` and
`work_router.py`. List data uses established section conventions:

```
# Scalar fields (always emitted)
STATE=feature_branch|main_with_stack|main_idle
BRANCH=<name>                    # empty if on main
ISSUE=<number>                   # empty if none
STACK_DEPTH=<N>

# Plan fields (only when HAS_PLAN=yes)
HAS_PLAN=yes|no
PLAN_POSITION=<completed>/<total>
PLAN_ACTIVE_ISSUE=<N>
PLAN_BATCH=<batch name>

# Context fields
HAS_HANDOFF=yes|no
HANDOFF_SUMMARY=<first 2-3 lines of Last Session section>
RECENT_COMMITS=<N>               # count; commit lines follow

# Commit lines (one per line, most recent first, max 6)
COMMIT=<sha7> <subject>

# Health check lines (from work_health.py, same format)
CHECK=<name> STATUS=ok|warn|changed [DETAIL=<text>]

# Completed branches (only when STATE=main_idle, max 5)
CLOSED_BRANCH=<name> ISSUE=<N> CLOSED=<relative date>
```

**CSO description for `brief/SKILL.md`:**
```
Use when the user says "/brief", "brief me", "what's the state",
"where are we", or "orient me" — provides an orientation summary of the
current work state, branch, issue, plan progress, and health checks.
Not for writing content (use write-content for that).
```

**Alternatives:**
- Full skill with rich formatting — over-invests in CLI UX that Trellis replaces
- No skill at all, just the script — need a CLI interface before Trellis lands

**Rationale:** Thin CLI wrapper avoids wasted effort. Structured data layer serves
both CLI (now) and Trellis (soon). The script pattern matches `ctx.py` and
`work_router.py`.

**Exploration:** quick
**Status:** captured

### D6: `brief` works from any state

**Choice:** `brief` adapts to context:

| State | What brief shows |
|-------|-----------------|
| Feature branch with `.meta` | Branch, issue, plan queue, recent commits, HANDOFF summary (if present), specs loaded, health checks |
| Main with pause stack | Stack depth, paused branch summaries, open issue summary |
| Main, no stack, no work | Recent completed branches, open issue summary |

**"Recent completed branches" enumeration:** This requires new logic beyond
composing existing scripts. `is_closed()` in `lifecycle.py` checks a specific
branch but doesn't enumerate. `brief.py` implements:

1. List branches sorted by recency: `git for-each-ref --sort=-committerdate --format='%(refname:short)' 'refs/heads/issue-*'`
2. Take top 10 candidates (bounds the cost regardless of total branch count)
3. For each, call `is_closed(project, branch, workspace)` — sub-second per branch
4. Filter for `CLOSED` or `MERGED_UNSTAMPED`, take most recent 5
5. Output as `CLOSED_BRANCH=<name> ISSUE=<N> CLOSED=<relative date>` lines

Pre-sorting by committer date and capping at 10 candidates keeps the cost
bounded (~30 git commands) even on workspaces with 50+ branches.

**Alternatives:**
- Feature branch only — misses the "picking up cold on main" use case

**Rationale:** Orientation is useful in every state. The data is all available
from existing scripts, except the branch enumeration which is new but
straightforward.

**Boundary with `work`:** `brief` on main is purely informational — it
displays open issues and recent activity but does not offer to start work
on them. Starting work is `work`'s job (Step 2a, `enrichment.py what-next`).
`brief` shows state; `work` acts on it.

**Exploration:** quick
**Status:** captured

---

## HANDOFF.md Coverage Audit

Verified no gaps in mechanical coverage:

| HANDOFF.md section | Mechanical replacement | Gap? |
|---|---|---|
| Last Session (narrative) | Git log + JOURNAL.md + blog | **Partial** — git log gives facts but not reasoning or failed attempts. HANDOFF.md still captures this; `continue` auto-loads it |
| Immediate Next Step | `.plan` active issue | None |
| Cross-Module blockers | GitHub issues with labels | None |
| References (paths) | `find` on workspace dirs | None |
| Queue progress | `.plan` + `format_resume_display()` | None — already moved |
| What's Left / What's Next | `.plan` + GitHub issues | None — already moved |
| State validation | `work_health.py --scope entry` | None — already moved |

**Session wrap checklist** (forage sweep, protocol sweep, write-content, etc.)
stays with the `wrap` command. These are session-bound operations at wrap time,
not resume time. No change needed.

**HANDOFF.md is still written** at session end via the handover skill. The change
is only that reading it on resume is automatic (part of `continue`) rather than
a separate command.

---

## Implementation Scope

### Changes to existing files

| File | Change |
|------|--------|
| `work/SKILL.md` | Routing table: add `continue`, separate from `resume`. Step 4: replace "resume"/"start" with "continue". Add done-detection auto-suggest. Add wrong-context redirects (D4). Update CSO description to: `Use when the user says "work", "work end", "work pause", "work resume", "work continue", or "work next" — detects current branch state and routes to the correct work lifecycle skill automatically.` |
| `work-resume/SKILL.md` | CSO description updated to: `Use when returning to a paused branch from the pause stack — user says "work-resume", "resume", or "go back to that branch". Pause-stack restoration only, not general branch continuation (use "work continue" for that).` |
| `handover/SKILL.md` | Update resume section (Step R1-R3): note that `continue` subsumes automatic HANDOFF.md reading. `resume handover` remains as explicit manual invocation. |
| `work_router.py` | Fix `_handoff_references_branch()` substring match: use `re.search(rf'#{issue_num}\b', result.stdout)` for word-boundary matching (prevents #42 matching #421). No new outputs — D3 done-detection uses existing `PLAN_ACTIVE_ISSUE` + `PLAN_POSITION` after `work_health.py` sync. |
| `project/ctx.py` | Refactor into importable library: wrap top-level code in `resolve() -> dict[str, str]` function, guard output with `if __name__ == '__main__'`. Enables `brief.py` to import context resolution directly instead of shelling out. |
| `lifecycle.py` | Update `INVALID_MESSAGES[('active', 'work')]` to mention `continue`: "Already on an active branch. Use `work continue`, `work end`, `work pause`, or `work next`." No state machine changes. |

### New files

| File | Purpose |
|------|---------|
| `brief/SKILL.md` | Thin CLI skill — calls `brief.py`, formats output |
| `brief/brief.py` | Structured data aggregator — composes `ctx.py` + `work_router.py` + `work_health.py` + HANDOFF.md |
| `brief/commands/brief.md` | Slash command registration |

### Not changed

| File | Why |
|------|-----|
| `work-pause/SKILL.md` | No changes — pause semantics are unchanged |
| `work-end/SKILL.md` | No changes — end semantics are unchanged |
| `work-start/SKILL.md` | No changes — start semantics are unchanged (it's the internal skill; the user-facing `start` redirect is handled in `work/SKILL.md`) |

---

## Updated `/work` Menu (Step 4 — on feature branch)

```
1. continue — keep working (loads context automatically)
2. resume — you have N paused branch(es) — restore one from stack     ← only if STACK_DEPTH > 0
N. next — mark current issue done, advance to next in queue       ← only if HAS_PLAN=yes
N+1. end — close this branch, merge, push, return to main
N+2. pause — commit WIP, push to stack, switch to main
N+3. wrap — end session but keep branch open (write handover)
```

The "resume"/"start" distinction is gone. `continue` is always option 1
regardless of HANDOFF.md existence.

**`continue` behavioral specification:**

When `HAS_HANDOFF=yes` (subsequent session):
1. Read `$HANDOFF_PATH` — summarise last session's narrative
2. Run `work_health.py --scope entry` — syncs `.plan` with GitHub, validates workspace state
3. If `HAS_PLAN=yes`: read `.plan` for queue progress and active issue
4. If `IN_SLOT=yes` and `HAS_PLAN=no`: read `.slot` for issue context
5. Load design specs (work-start Step 3c) — scan for specs, read them all
6. Done-detection auto-suggest (D3) — if active issue is complete, suggest next/end
7. Proceed to work

When `HAS_HANDOFF=no` (first session, or HANDOFF.md missing):
1. Run work-start Steps 0, 2, 3, 3b, 3c, 11:
   - **Step 0:** path resolution (already done by router)
   - **Step 2:** platform coherence — read platform doc, five coherence questions
   - **Step 3:** relevant protocols — scan and read applicable rules
   - **Step 3b:** Garden search — spawn `garden-retriever` for domain context
   - **Step 3c:** design spec loading (mandatory)
   - **Step 11:** IntelliJ MCPs — hard stop if unavailable
2. Run `work_health.py --scope entry` — syncs `.plan` with GitHub, validates workspace state
3. If `HAS_PLAN=yes` or `IN_SLOT=yes`: read plan/slot context
4. Done-detection auto-suggest (D3)
5. Proceed to work

The asymmetry is intentional: subsequent sessions skip environment pre-checks
(platform coherence, protocols, IntelliJ) because the environment was verified
in the first session and the branch scaffold already exists. First sessions
(no HANDOFF.md) run the full pre-check suite including the IntelliJ hard gate.
`continue` preserves this existing behavior under a unified label.

---

## Updated Routing Table (Step 1)

| Invocation | Route to |
|------------|---------|
| `work end` | → **work-end** immediately |
| `work pause` | → **work-pause** immediately |
| `work next` | → advance to next issue in `.plan` queue (Step 5) |
| `work resume` / `resume` | → **work-resume** (pause-stack only; error if on active branch) |
| `work continue` / `continue` | → run router → Step 4 `continue` action directly |
| `work` / `work start` | → run router (Step 1b) |
| `resume handover` | → handover skill directly (manual invocation) |

**Wrong-context error handling (D4):** The routing table in `work/SKILL.md`
owns all wrong-context errors. Before forwarding to a sub-skill:

- `work resume` + `ON_MAIN=no` → error (not forwarded to work-resume)
- `work resume` + `ON_MAIN=yes` + `STACK_DEPTH=0` → error (not forwarded)
- `work continue` + `ON_MAIN=yes` → error (no branch to continue on)
- `work continue` + `workspace_dirty` → error ("Workspace is on a stale branch — run `work` to clean up.")
- `work start` + `resume_branch` → redirect to `continue` with note

The errors are emitted by the router/skill layer, not by the sub-skills.
`work-resume/SKILL.md` can assume it is invoked correctly (on main, with
stack entries present).

When router returns `resume_branch` and invocation was `work start`:
redirect to `continue` with note "Already on `<branch>` — continuing."

---

## Implementation Phases

D1-D4 (taxonomy, continue, wrong-context) and D5-D6 (brief) can be
implemented independently — they touch different files with no shared code.

| Phase | Decisions | Files touched | Depends on |
|-------|-----------|--------------|-----------|
| 1 — Taxonomy | D1, D2, D3, D4 | `work/SKILL.md`, `work-resume/SKILL.md`, `handover/SKILL.md`, `work_router.py` | Nothing |
| 2 — Brief | D5, D6 | `brief/SKILL.md`, `brief/brief.py`, `brief/commands/brief.md` | Nothing (thematically linked to D1's verb table, no code dependency) |

Phase 1 is the core fix — resolving the semantic overload. Phase 2 is a
new feature that happens to be defined alongside its verb. Either can
proceed, stall, or be reverted without affecting the other.
