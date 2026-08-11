# soredium — Development Workflow Guide

soredium manages the full development loop: branch creation, design specs,
adversarial review, implementation, knowledge capture, semantic squash, and
branch closure. Each step preserves context for future sessions — specs so
designs aren't re-derived, journals so decisions aren't forgotten, semantic
commits so intent survives squash, forage entries so hard-won knowledge
reaches the next developer who hits the same problem. It also includes a fork of superpowers that replaces bash-based file
editing with IntelliJ MCP operations — rename, move, find references,
safe delete, change signature. Without this, Claude defaults to grep
and sed for refactoring, which breaks on large codebases and silently
misses references. The IntelliJ-first approach means semantic
operations use the IDE's index, not regex.

The workflow is opinionated about one thing: nothing learned during a
session should be lost when the session ends.

Everything goes through `/work`. Start, close, pause, resume, advance — one
command, subcommands for each verb.

| Command | What it does |
|---------|-------------|
| `/work` | Start new work or continue an existing branch |
| `work continue` | Keep working on the current branch — loads context automatically |
| `work end` | Close the branch — full sequence, one command |
| `work pause` | Save state, switch to main |
| `work resume` | Return to a paused branch from the pause stack |
| `work next` | Advance to the next issue in the queue |
| `work slot` | Create a multi-repo slot (see Slots below) |
| `quick-fix` | Land a small change on main via ephemeral branch |

---

## The Workspace

Every project has a companion **workspace** directory. The project repo
holds your code. The workspace holds everything else — design specs,
blog entries, architecture decision records, plans, and session state
files (`.meta`, `JOURNAL.md`, `.plan`).

Why separate? Your project repo is shared with your team. The workspace
is yours — methodology artifacts, work-in-progress design docs, and
session state that don't belong in the project history. At branch close,
anything worth keeping gets copied to the right place in the project
repo automatically.

Both repos track the same branch name. When you create
`issue-42-fix-login`, it exists in both the project and the workspace.
When you close the branch, both return to main.

You work from the project directory. The workspace is managed for you —
`wksp/` in the project is a symlink to the workspace, and `proj/` in
the workspace points back. You rarely need to touch the workspace
directly.

---

## Starting Work

```
/work
```

Or with issues:
```
work start #42 #50 #32
```

Or with a description:
```
work start "improve the scoring engine"
```

What you see:
1. A branch is created (`issue-42-<slug>`) in both repos
2. If any issue has child issues (an epic), they're detected
   automatically and expanded. No separate epic command needed.
3. A `.plan` file is built — this is your issue queue (more below)
4. Platform checks run — protocols, garden search, IDE verification
5. You're offered a brainstorm to explore the problem before coding

On resume (branch already exists), `work continue` loads context
automatically — HANDOFF.md from the last session, design specs from
brainstorming, health sync against GitHub — and picks up where the
previous session left off. See "Between Sessions" below.

### Specs and brainstorming

When you accept the brainstorm offer, design specs are written to the
workspace under `specs/<branch-name>/`. These are the authoritative
design decisions for the branch. On every resume, they're loaded
automatically so Claude doesn't propose alternatives to settled designs.

At branch close, specs are copied to `docs/specs/` in the project repo
so they survive as permanent records.

### Design review

After a spec is written, invoke `/design-review` to stress-test it
before implementation begins. The review is adversarial — independent
Claude sessions argue against the design to find weaknesses.

**Dimensions** — what gets reviewed:

| Dimension | Focus |
|-----------|-------|
| Coherence | Completeness, consistency, gaps, ambiguity |
| Structure | Decomposition, boundaries, dependencies, coupling |
| Robustness | Failure modes, concurrency, edge cases, error paths |
| Cross-cutting | Contradictions and coverage gaps between dimensions |

All dimensions run automatically. You don't pick them.

**Degrees** — how deep the review goes (your only choice):

| Degree | Rounds | Time | When to use |
|--------|--------|------|-------------|
| Light | 1 | ~2 min | Clear requirements, known domain, small scope |
| Standard | 2–3 | ~5 min | New module, API surface changes |
| Adversarial | 4–6 | ~12 min | Auth, security, concurrency, distributed state |
| Deep | 8–10 | ~25 min | Novel architecture, first-of-kind, high-stakes |

A recommendation is presented based on complexity signals in the spec —
config-only changes suggest Skip, cross-module boundaries suggest
Standard, security-sensitive work suggests Adversarial. You can accept
or override.

Each round, a reviewer session finds issues, then an implementor session
responds. Issues that survive multiple rounds are real. Issues that get
refuted are dropped. What remains is a prioritised list of genuine
design weaknesses — fix them before writing code.

---

## During Work

### Design decisions

As you implement, significant design decisions are captured in a
**journal** (`JOURNAL.md` in the workspace). Each entry is tagged with
a section anchor (e.g. `§10 Cross-cutting`) that maps to a section in
the project's design document (`ARC42STORIES.MD`). At branch close,
journal entries are merged into the design doc — the branch's decisions
become part of the project's permanent design record.

You don't manage the journal directly. When Claude records a design
decision, it writes a journal entry. When the branch closes, those
entries are merged with a three-way diff that preserves changes made
on main since the branch was created.

### The queue (`.plan`)

Every branch gets a `.plan` file. It's a markdown checklist:

```markdown
## Queue
- [x] #42 — Fix login validation
- [ ] #50 — Weighted profiles (epic)
  - [x] #108 — Add weight field
  - [ ] #109 — Update scoring ← active
  - [ ] #110 — Migration script
- [ ] #32 — Update API docs
```

Epics expand their children inline. Nested epics are supported.

### Batching

Epics with 5+ children get batch planning. Children are grouped into
batches by domain affinity, shared API surface, scale fit, and
dependency ordering. You approve the batch plan before work begins.

```markdown
- [ ] #50 — Weighted profiles (epic)
  ### Batch 1 — Data model ← current
  - [ ] #108 — Add weight field ← active
  - [ ] #109 — Migration script
  ### Batch 2 — Scoring logic
  - [ ] #110 — Update scoring algorithm
  - [ ] #111 — Recalculate existing scores
```

Batch boundaries are **wrap points**. When you complete the last
issue in a batch, `work next` tells you:

> "Batch 1 complete. Wrap point — run `wrap` to clear context, or
> continue to Batch 2."

The idea: an LLM's context fills up as it works through issues.
Forage sweeps, protocol captures, and diary entries depend on
conversation context — the longer the session runs, the more gets
missed. A batch boundary is where you wrap: run the sweeps, write
the handover, end the session. The next session starts fresh with
a clean context window, loads the handover, and picks up Batch 2.

Batches are sized so a single session can complete one without
context degradation. The grouping criteria (domain affinity, shared
API surface, scale fit, dependency ordering) aren't about independent
releases — they're about keeping related work together so the LLM
has coherent context while working, then clearing it before moving
to a different domain.

You can also `work end` at a batch boundary if the branch has enough
to merge. The remaining issues stay in the queue — start work again
with the same epic number and auto-detection picks up where you
left off.

### Advancing

```
work next
```

Checks off the current issue, moves the active marker, and ticks
the checkbox on the GitHub epic.

---

## Between Sessions

A session is one Claude Code conversation. When you start a new session
on an existing branch, you need orientation — what happened last time,
where you are in the queue, what's left.

### `work continue`

`work continue` is the verb for picking up where you left off. It loads:

- **HANDOFF.md** — the previous session's narrative (see below)
- **`.plan` position** — which issue is active, how many are done, what
  batch you're in
- **Design specs** — loaded from both workspace and project so settled
  decisions aren't re-proposed
- **Health sync** — validates `.plan` state against GitHub, marks any
  issues that were closed externally

If the active issue was completed (by another session or externally),
`continue` detects this and suggests `work next` or `work end`.

### `/brief`

`/brief` gives orientation without starting work:

```
Branch: issue-190-enriched-backlog
Issue:  #192 (active)
Queue:  2/4 complete
Recent: 3 commits (schema migration, enrichment API, trajectory capture)
Health: plan_state=ok, github_sync=ok
```

Works from any state — on a feature branch, on main with paused
branches, or on main with no work. Adapts output to context. On main
with no active work, it shows recently closed branches and open issues
instead.

### HANDOFF.md — the session bridge

HANDOFF.md is the only record of *why* decisions were made. Git log
tells you what changed. Specs tell you what was designed. HANDOFF.md
tells you what was tried and rejected, what reasoning drove a choice,
and what the next session should do first.

It spans the `.plan` queue — a branch might have 8 issues across 3
sessions. Each session's handover carries forward the narrative thread:
what was learned in session 1 that affects session 2's approach to a
different issue. Without it, each session re-derives context from code
and commits, missing the reasoning that didn't make it into either.

Written automatically at `wrap` and `work end`. Read automatically
by `work continue` at the start of the next session.

### Notes — the persistent notebook

`.notes/NOTES.md` is a worktree-global file — any branch can write to
it, and it persists across branches because it lives in a separate git
worktree that tracks main. Use it for things that aren't tied to the
current issue but need to survive session boundaries:

- Reminders ("check auth token expiry after the migration")
- Cross-branch context ("engine reindex needed after next schema change")
- Observations that don't have a home yet

Notes are surfaced after `work end` — a final reminder before you
decide what to do next. They can also be read on demand at any point.

Unlike HANDOFF.md (which is per-session and overwritten each time),
notes accumulate. They're organized by date section and persist until
you remove them.

### `continue` vs `resume`

Two verbs, non-overlapping:

| Verb | Meaning |
|------|---------|
| `work continue` | Keep working on the current branch |
| `work resume` | Restore a paused branch from the pause stack |

`continue` is for picking up where you left off on the branch you're
already on. `resume` is specifically for the pause stack — you paused
a branch, switched to something else, and now you want to go back.

---

## Wrapping a Session (Branch Stays Open)

```
wrap
```

When the branch isn't done but the session is ending. This runs a
knowledge capture sweep and writes handover notes:

- **Forage sweep** — captures gotchas, techniques, or undocumented
  behaviours discovered this session into the knowledge garden
- **Protocol sweep** — formalises any project rules established or
  reinforced this session
- **Diary entry** — captures what happened this session as a blog entry

These depend on conversation context and can't be deferred to the next
session. If you skip them, that knowledge is lost.

After the sweep, `HANDOFF.md` is written with what happened, what's
left, and what to do next. The next session reads this on resume.

---

## Closing Work

```
work end
```

One command regardless of context — branch or slot. Here's what you
experience:

### 1. Knowledge capture

The same sweep as `wrap`, plus three more items that work from file
state (and can be deferred if needed):

- **ADR** — record any architectural decisions worth a formal record
- **CLAUDE.md sync** — capture new workflow conventions
- **Doc sync** — sync documentation with code changes

All six default to ON. Toggle numbers to skip what doesn't apply,
or type "go" to proceed with all checked.

### 2. Code review

Mandatory. The diff is classified (structural vs body-only) and an
appropriate review is recommended. Critical or important findings
must be fixed before proceeding.

### 3. Close plan

You see exactly what will happen:

```
work end close plan — issue-42-fix-login

  Artifact routing
  ├── specs/issue-42/   → project docs/specs/
  ├── blog/entry.md     → workspace main
  └── adr/0005.md       → project docs/adr/
  Journal merge      → ARC42STORIES.MD (3 sections)
  Issues             → close #42, #43
  Squash             → 12 commits → 3 groups
  Push               → fork, then prompt for blessed repo

Approve all, or step by step? (all / step)
```

Specs, blog entries, ADRs, and plans are moved from the workspace
branch to their permanent homes — specs and ADRs go to the project
repo, blog entries stay in the workspace on main. This happens
automatically; the close plan shows you what will move where.

### 4. Semantic squash and push

Commits are analysed and grouped into a squash plan that preserves
meaningful history. The goal is **not** to reduce everything to one
commit — that destroys context that future sessions need.

LLMs don't remember why they made decisions. The commit history is
one of the few durable records of intent — *why* a change was made,
not just *what* changed. And LLMs read git history easily, so
well-structured commits are a direct input to future reasoning.

The squash groups commits by semantic concern: a feature commit stays
separate from a bugfix, a refactor stays separate from a test addition.
CI fixup commits (`fix typo`, `oops`, `try again`) get folded into the
commit they were fixing. The result is clean history where each commit
has a clear purpose — not a single squash blob and not raw noise.

You approve the plan before it executes. Then the branch is pushed to
your fork and you're prompted to push to the blessed repo or open a PR.

### 5. Stamp and handover

The branch is stamped as closed (an empty commit marking it as
archived), both repos return to main, and HANDOFF.md is written.

---

## Pausing and Switching

```
work pause
```

Commits everything as a `WIP:` commit, pushes to a pause stack on
workspace main, and switches both repos to main. The WIP commit is
visible in history — on resume it's reset so work continues cleanly.

The stack supports multiple paused branches:

```
work resume
```

Shows a picker if multiple branches are paused, restores the selected
branch, and rebases onto current main (picks up work that landed while
you were away).

---

## Slots — Multi-Repo Parallel Work

Slots are for when you need to work across multiple repos at once —
for example, changing an SPI in the engine repo and its consumer in
the IoT repo on the same branch.

### What a slot is

A slot is a set of repo clones under `slots/<N>/`, completely isolated
from your original repos. Each slot contains:

- **Repo clones** — `git clone --shared` of each repo you include.
  Shared means they reuse the original's object store (disk-efficient)
  but have independent refs (branch-safe).
- **A workspace clone** — the primary repo's workspace is cloned too.
  Specs, journals, and session state live here, same as normal work.
- **An isolated `.m2`** — each slot gets its own Maven local repository
  at `slots/<N>/.m2/`. Every repo clone has a `.mvn/maven.config`
  pointing to it.

### Why clones instead of worktrees?

Git worktrees share refs with the original repo. Branch operations in
a worktree affect the original's ref namespace, and you can't have two
worktrees on the same branch. Clones are fully independent — multiple
slots can exist for the same repo without interference.

### `.m2` shadowing

The isolated `.m2` means:

- Builds in the slot never pollute your machine's `~/.m2/`
- Builds on your machine never see slot artifacts
- Two slots building different versions of the same artifact don't
  collide
- The `.m2` is shared across all repos *within* the slot, so repo A's
  artifacts are visible to repo B in the same slot — which is exactly
  what you need for cross-repo work

### Creating a slot

```
work slot #42
```

Or with multiple issues and specific repos:
```
work slot #42 #50 repos=engine,iot
```

Epics are auto-detected, same as `work start`. The slot gets a `.plan`
queue, a `.slot` context file, and scaffolded metadata.

### The workspace in a slot

The slot clones the workspace alongside the repo clones. The `wksp/`
and `proj/` symlinks are re-pointed to the slot's copies. This means:

- Specs written during brainstorming go to the **slot workspace**, not
  your original workspace
- The journal lives in the slot workspace
- On close, artifacts are copied from the slot workspace to the
  original workspace (on main) and then to the project repo

You don't manage this — it's transparent. `/work` in the slot detects
the scaffold and runs the resume path as usual.

### Working in a slot

1. Open a terminal in `slots/<N>/<primary-repo>`
2. Run `/work` — detects the existing scaffold, loads specs
3. Work normally — implement, test, commit
4. Run `work end` when done

### Closing a slot

`work end` in a slot runs the full sequence: review, copy artifacts to
their permanent homes, squash, push, merge into the original repos,
stamp branches, and archive the slot to `slots/attic/<N>/`. One command,
no separate merge step.

### Managing repos and slots

```
work slot add-repo <name>       # add a repo to the current slot
work slot remove-repo <name>    # drop a repo (can't remove primary)
work slot list                  # table of all slots and state
work slot status                # queue progress for current slot
work slot remove <N>            # archive a slot
```

---

## The Worklog and What-Next

Every lifecycle event is recorded in a SQLite database (`worklog.db`
in the workspace). Start, end, pause, resume, issue transitions, slot
creation, slot archive — all logged with timestamps, branch names,
issue numbers, and metadata.

### What it feeds

The worklog isn't something you interact with directly. It's the data
layer behind two things you do interact with:

**`/brief`** — orientation at any point. Branch, issue, queue position,
health status. All derived from the worklog and `.plan` state, no
GitHub API calls needed.

**`what-next` recommendations** — when you say `work` on main with no
issue number, the system queries the enriched backlog:

```
Recommended next:
  1. #42 — Fix caching bug (score: 12, quick-win, ready, compounding)
  2. #55 — Refactor auth (score: 8, load-bearing, ready, stable)

Pick a number, type an issue #, or describe what you want to work on.
```

### Enrichment

Each issue can carry local metadata that GitHub doesn't track:

| Field | Values | Purpose |
|-------|--------|---------|
| Strategic role | quick-win, load-bearing, parallelizable, dependency-unlocker | Sequencing |
| Readiness | ready, needs-design, needs-spike, needs-decision | Can we start now? |
| Decay | stable, compounding, perishable | Does waiting make it worse? |
| Blast radius | isolated, local, cross-cutting, foundational | Safe to parallelize? |
| Trajectory | free-text | "What this implies for next steps" |

Enrichment is updated at `work end` — after closing an issue, you
capture trajectory notes ("schema landed — #192 and #193 are now
ready") and update sibling issues' readiness. This is optional but
compounds over time — the more issues are enriched, the better
`what-next` recommendations become.

---

## The Typical Shape

Most work follows this pattern:

1. **`work`** on main — picks an issue (what-next recommends, or you specify)
2. **Brainstorm** → spec → design review (if non-trivial)
3. **Implement** → test → commit (`Refs #N`)
4. **`work next`** — advance to the next issue
5. **Implement** → commit → **`work next`** → implement → commit → ...
6. At a batch boundary: **`wrap`** → end session
7. New session: **`work continue`** → reads HANDOFF.md → picks up at new batch
8. Continue iterating through **`work next`**
9. Queue empty → **`work end`** → sweep → review → squash → push → done

The branch stays open across sessions. Each session wraps cleanly.
The queue tracks progress. The DB records history. The garden captures
knowledge. Nothing learned during a session is lost when the session
ends.

For small fixes that don't need a feature branch — typos, config
tweaks, CI fixes — use **`quick-fix "message"`** instead. It creates
an ephemeral branch, commits, rebases onto upstream, and lands on main
in one step.

---

## Command Reference

### Every session

| You say | What happens |
|---------|-------------|
| `/work` | Start new work or continue an existing branch |
| `work continue` | Keep working on the current branch — loads context |
| `/brief` | Orientation summary — branch, issue, queue, health |
| `wrap` | End session, keep branch open — runs sweep, writes HANDOFF.md |

### Closing

| You say | What happens |
|---------|-------------|
| `work end` | Full close — sweep, review, promote, squash, push, stamp |
| `work next` | Advance to next issue in the queue |

### Branching

| You say | What happens |
|---------|-------------|
| `work pause` | WIP commit, push to stack, switch to main |
| `work resume` | Pick from pause stack, restore branch |

### Slots

| You say | What happens |
|---------|-------------|
| `work slot #N` | Create a slot for issue(s) |
| `work slot list` | Show all slots |
| `work slot status` | Queue progress for current slot |
| `work slot add-repo <name>` | Add a repo to the current slot |
| `work slot remove-repo <name>` | Remove a repo from the current slot |
| `work slot remove <N>` | Archive a slot |

### Mid-session (standalone)

These run automatically during `wrap` and `work end`. Invoke standalone
only when you want to capture something mid-session.

| You say | What happens |
|---------|-------------|
| `/forage` | Capture a gotcha or technique to the knowledge garden |
| `/protocol` | Capture or search project conventions |
| `/design-review` | Adversarial review of a design spec |
| `/code-review` | Review staged changes |
| `/brainstorming` | Explore a problem before implementing |
| `quick-fix "msg"` | Land a small change on main via ephemeral branch |
