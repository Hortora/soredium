# Work Scope — Design Spec

**Date:** 2026-11-26
**Issue:** Hortora/soredium#573
**Supersedes:** The #573 description (workspace co-location design) and
`2026-04-09-workspace-model-design.md` (workspace-as-methodology-surface).
Informed by ADR-0018 (kill promotion, ephemeral workspace).
**Status:** Draft

## Problem

The workspace model has failed in three ways:

1. **Promotion loses artifacts.** Blogs, specs, and ADRs are written to a
   workspace repo and copied to the project repo by a promotion step. That step
   fails silently, is missed during ceremony, or creates conflicts. Result:
   108-file promotion gap (#558), 69 specs rescued manually, zero `promote`
   actions in production worktrace for weeks at a time.

2. **Workspace repos add complexity for no durable value.** Each workspace is a
   git repo with branches, remotes, landing, and settling. The close ceremony
   must land workspace branches alongside project branches, handle workspace
   conflicts, detect unpromoted artifacts, and settle permanent clone workspaces
   back to the base branch. This is ~40% of work-end's code and the source of
   most ceremony failures.

3. **The workspace is scoped to a project, but work is scoped to a sequence of
   issues.** A slot with three project clones gets three workspace clones, each
   with its own queue inherited from canonical. Queues diverge. Handoffs
   fragment. Pipeline state scatters. The `.queue-root` marker was a patch;
   the real fix is scoping work state to the work, not to a project.

## Design Principles

1. **If it matters, it lives in the project repo.** Blogs, specs, ADRs, and code
   are project artifacts. They are written directly to the project repo's
   `docs/blog/`, `docs/specs/`, `docs/adr/` on the working branch, travel with
   the branch, and land on main when the branch lands. No intermediate copy.

2. **Work state belongs to the work, not to a project.** The queue, handoff,
   plans, and pipeline state are facets of a single abstraction: a *work scope*.
   That scope applies equally to canonical repos, permanent clones, slots, and
   agent sessions.

3. **If it's in the work scope, it's disposable.** Plans are reproducible from
   the issue and codebase. Handoffs are session-scoped. Pipeline state is
   transient. None of these need landing, promotion, or ceremony — they are
   overwritten, not merged.

4. **Same shape everywhere.** The work scope has the same structure whether the
   execution context is a canonical repo, a clone, a slot, or an agent. Tools
   don't branch on context type to find work state.

## Work Scope Model

### What is a work scope?

A work scope is the state of an ongoing sequence of 1..N issues being worked in
consecutive sessions within an execution context. It contains:

| Artifact | Purpose | Lifecycle |
|----------|---------|-----------|
| `queue` | Issue sequence and status | Persists across sessions; committed |
| `handoff.md` | Session continuity | Overwritten each session; never landed |
| `plans/` | Implementation plans | Transient; discarded when work ends |
| `progress` | Pipeline step state | Transient; reset each ceremony |
| `wrap-log.jsonl` | Ceremony event log | Appended; discarded when work ends |

### Where does work state live?

The answer depends on whether the execution context is single-repo or multi-repo.

#### Single-repo contexts (canonical, permanent clone)

Work state lives on the **`.notes` orphan branch**, checked out as a git worktree
at a well-known path.

```
<canonical-or-clone-root>/
  <repo>/                    # project repo (working tree)
  <repo>/.notes/             # .notes worktree (work state)
    queue                    # issue sequence
    handoff.md               # session continuity
    plans/                   # implementation plans
    progress                 # pipeline state
    wrap-log.jsonl           # ceremony log
```

**Why `.notes` and not a plain directory?** Version history. The queue needs to
be committed (the ceremony modifies it atomically). The handoff benefits from
`git log` for debugging. Plans persist across sessions within a work sequence.
An orphan branch gives all of this without polluting the project's branch
namespace or requiring a separate remote.

**Branching per work sequence.** Each work sequence (a contiguous run of issues)
gets its own branch on `.notes`: `work/<first-issue>`. When work ends, the
branch is deleted. When new work starts, a new branch is created. The
pause/resume stack references these branches.

**Concurrency.** A single-repo context is worked by one session at a time
(clone guard ensures this for clone-enabled families; canonical repos are
single-session by convention). The `.notes` worktree is therefore
uncontended. If a second session attempts to attach the worktree, git
rejects it — this is a natural lock.

#### Multi-repo contexts (slots, agents)

Work state lives in a **`.work/` directory** at the context root. This is a
plain directory, not a git repo.

```
<slot-or-agent-root>/
  .slot                      # metadata
  .work/                     # work state
    queue                    # issue sequence
    handoff.md               # session continuity
    plans/                   # implementation plans
    progress                 # pipeline state
    wrap-log.jsonl           # ceremony log
  <repo-1>/                  # project clone
  <repo-2>/                  # project clone
```

**Why not `.notes` here?** A slot/agent root is not a single git repo — it's a
directory containing multiple repo clones. There is no repo to attach an orphan
branch to. A plain `.work/` directory is simpler and sufficient: slots are
already one-session-at-a-time, and the lifecycle files don't need independent
version history (the slot root has no git history to pollute).

**What about the existing `.queue-root` marker?** It becomes unnecessary. Work
state is always in `.work/` at the root (for multi-repo) or on `.notes` (for
single-repo). There is no ambiguity about where the queue lives.

### Resolution logic

A single function (`work_scope.resolve(path)`) returns the work scope location:

```
1. If path is inside a slot/agent root (has .slot ancestor):
   → <root>/.work/
2. If path is inside a permanent clone (has .permanent ancestor):
   → <clone-root>/<repo>/.notes/ worktree
3. If path is a canonical repo:
   → <repo>/.notes/ worktree
4. Otherwise: error — not in a managed execution context
```

This replaces `queue_io.queue_dir()`, `ctx.py` workspace resolution, and the
`.queue-root` / `.workspace` marker system.

## Artifact Routing

### Direct-write model

All durable artifacts are written directly to the project repo on the working
branch:

| Artifact | Written to | Previously |
|----------|-----------|------------|
| Blog entries | `<project>/docs/blog/` | `<workspace>/blog/` → promote |
| Specs | `<project>/docs/specs/` | `<workspace>/specs/` → promote |
| ADRs | `<project>/docs/adr/` | `<workspace>/adr/` → promote |
| Code | `<project>/src/...` | Same (unchanged) |

`resolve_artifact_dir.py` is modified to return project-side paths instead of
workspace paths. `write-content`, `brainstorming`, and `adr` skills call it
and write directly. Images commit alongside their document.

### Cross-repo queue items

If a queue item touches multiple repos (e.g. an issue affecting both casehub
and engine), it must decompose into linked per-repo issues before work starts:

1. `work start #N` reads the issue body and identifies affected repos.
2. If multiple repos: creates child issues (`gh issue create`) linked to the
   parent, one per repo. The parent becomes the coordinating issue.
3. Each child issue is queued. The blog entry for the work lives in the
   primary repo (the one the parent issue was filed against).
4. Blog frontmatter lists all related repos via a `projects:` field.

This decomposition is mechanical and can be automated. Cross-repo issues that
don't decompose are a source of ambiguity (which repo gets the blog? which
branch holds the spec?). Decomposition eliminates that.

### Queue format

Queues switch to long-form issue references everywhere:

```
- [ ] Hortora/soredium#573 — work scope redesign
- [ ] Hortora/engine#42 — dedup pipeline fix ← done on issue-42-dedup-fix
- [x] Hortora/soredium#605 — silent landing failure
```

This is unambiguous in multi-repo contexts and consistent with the protocol
(`issue-references-are-always-qualified`). Bare `#N` references are no longer
valid in queue files.

## What Gets Deleted

### Code

| File/module | Reason |
|-------------|--------|
| `artifact_promote.py` (all subcommands) | No promotion step |
| `_copromote_images` in close | Images commit at write time |
| Promotion gate in close (`unpromoted_artifacts`, `promotion_backlog`) | No promotion |
| Workspace landing step in close | No workspace branches to land |
| `settle_permanent_clone` workspace settling | No workspace to settle |
| `_strip_inherited_lifecycle` in slot creation | No workspace clones |
| Workspace alignment checks in `alignment.py` | No workspace branches |
| `workspace-init` skill (or radically simplified) | No workspace repos |
| `proj/` and `wksp/` symlink creation and resolution | No workspace to link |
| `.workspace` marker system | Replaced by `.work/` |
| `.queue-root` marker system | Replaced by `.work/` or `.notes` |

### Infrastructure

| Item | Disposition |
|------|-------------|
| `~/claude/public/` workspace repos | Frozen, then archived (see Migration) |
| `wsp-*` workspace clones in slots/clones | Not created in new contexts |
| Workspace branch per issue | Not created; work state is on `.notes` |
| Workspace remotes (`local` → canonical workspace) | Not created |

## What Stays the Same

| Component | Why unchanged |
|-----------|---------------|
| Publishing (`canonical_sync.py publish`, `publish-blog`) | Reads from project `docs/blog/`; routing via `blog-routing.yaml` |
| Landing (`canonical_sync.land`) | Lands project branches; no workspace branches to handle |
| Stamping | Same mechanism, fewer branches (no workspace stamp) |
| GitHub issue close | Same |
| Pause/resume stack | Adapts to reference `.notes` branches |
| Clone guard | Same decision logic |
| Slot creation (for project clones) | Creates project clones; skips workspace clones |

## Migration

### Principle: don't migrate, let old work finish

Migrating active work from the old model to the new model mid-sequence risks
data loss and introduces a combinatorial testing burden. Instead:

1. **Existing slots** finish their queues under the old model, then archive.
   The ceremony detects which model it's in by the presence of `.work/` (new)
   vs `wsp-*` directories (old).

2. **Existing permanent clones** (soredium) are the first migration target
   because they persist across work sequences. When the current queue drains,
   remove the workspace clone, create the `.notes` branch, and start the next
   work sequence under the new model.

3. **Canonical workspace repos** (`~/claude/public/`) are frozen: no new writes.
   Blog entries already in the workspace but not yet in the project repo are
   copied to the project repo in a one-time migration script. After 30 days
   with no writes, archive.

4. **Agents** are heterogeneous (some have `.slot`, some don't, some have
   workspace clones, some don't). Convert agent-by-agent as each is touched.

### Detection

```python
def model_version(root: Path) -> str:
    if (root / ".work").is_dir():
        return "v2"  # new model
    if any(d.name.startswith("wsp-") for d in root.iterdir() if d.is_dir()):
        return "v1"  # old model with workspace clones
    if (root / "workspace").is_dir():
        return "v1b"  # #573 co-located workspace (never deployed)
    return "unknown"
```

The ceremony, `work.py`, and `ctx.py` all call this. v1 paths are preserved
exactly as they are today — no behaviour change for old-model contexts.

### One-time migration script

```bash
python3 scripts/migrate_to_work_scope.py <context-root>          # audit
python3 scripts/migrate_to_work_scope.py <context-root> --plan    # show actions
python3 scripts/migrate_to_work_scope.py <context-root> --apply   # execute
```

For a permanent clone, this:
1. Copies any unpromoted workspace artifacts to the project repo
2. Removes the workspace clone directory
3. Creates the `.notes` orphan branch with initial queue state
4. Attaches the `.notes` worktree

For a slot root, this:
1. Copies any unpromoted workspace artifacts to each project clone
2. Removes workspace clone directories
3. Creates `.work/` with queue state migrated from the old location

## Risks and Mitigations

### Plans lost on session crash

Plans live in `.work/` or on `.notes`, not in conversation context alone. They
persist across sessions within a work sequence. A session crash loses unsaved
plan changes — same risk as today, mitigated by the commit-after-every-response
discipline.

### `.notes` worktree conflicts

If a session crashes without detaching the `.notes` worktree, a subsequent
session can't attach it. `git worktree prune` resolves this — `work_scope.resolve`
runs it automatically before attempting attachment.

### Blog placement ambiguity for cross-repo work

Decomposition into per-repo issues resolves this: each repo's blog is in that
repo's `docs/blog/`. The coordinating issue's blog (the cross-cutting narrative)
lives in the primary repo. `projects:` frontmatter cross-references the others.

### Old-model and new-model contexts coexist

During the migration period, some contexts use v1 and some use v2. The detection
function ensures tools dispatch to the correct path. The risk is a tool that
doesn't check — mitigated by making `work_scope.resolve` the single entry point
for all work-state access, so there is one place to get wrong rather than many.

### Canonical repos without clone-enabled may have concurrent sessions

If `clone_enabled=False`, two sessions could work in the same canonical repo.
Both would try to use the `.notes` worktree. Git's worktree lock prevents this
from corrupting state, but the second session gets an error.

**Mitigation:** `work_scope.resolve` checks the worktree lock. If locked, it
returns a `DECISION=work_scope_locked` for the LLM to present: "Another session
is using this repo. Open a clone instead, or wait."

## Implementation Phases

### Phase 1: Infrastructure (can land independently)

- [ ] `work_scope.py` — resolution logic, `.notes` worktree management, v1/v2
      detection
- [ ] `resolve_artifact_dir.py` — return project-side paths instead of workspace
- [ ] Tests for both: resolution in all context types, artifact path routing

### Phase 2: Direct-write artifacts

- [ ] `write-content` writes to project `docs/blog/`, `docs/specs/`
- [ ] `brainstorming` writes specs to project `docs/specs/`
- [ ] `adr` writes to project `docs/adr/`
- [ ] Images commit alongside documents (no `_copromote_images`)
- [ ] Update `blog-routing.yaml` scanning to look in project repos

### Phase 3: Close ceremony simplification

- [ ] Remove workspace landing step
- [ ] Remove promotion gate and backlog sweep
- [ ] Remove workspace settling
- [ ] Remove `artifact_promote.py`
- [ ] Close ceremony uses `work_scope.resolve` for pipeline state files

### Phase 4: Slot/clone creation

- [ ] Slot creation: `.work/` instead of workspace clones
- [ ] Clone creation: `.notes` branch instead of workspace clone
- [ ] Remove `_strip_inherited_lifecycle`
- [ ] Remove workspace alignment checks

### Phase 5: Existing context migration

- [ ] `migrate_to_work_scope.py` script
- [ ] Migrate soredium permanent clone (first target)
- [ ] Freeze canonical workspaces
- [ ] Convert agents as touched

### Phase 6: Cleanup

- [ ] Remove `workspace-init` skill (or reduce to `.notes` setup)
- [ ] Remove `proj/` and `wksp/` symlink code
- [ ] Remove `.workspace` and `.queue-root` marker handling
- [ ] Update lifecycle-maintainer-guide.md
- [ ] Archive `~/claude/public/` after 30-day freeze

## Prerequisites

- [ ] Hortora/soredium#605 — silent landing failure detection (landed)
- [ ] Hortora/soredium#615 — slot overwrite guard (landed)
- [ ] Hortora/soredium#610 — untrack pipeline state files (reduces ceremony
      friction, but not a hard gate — the new model eliminates the workspace
      where most of these files lived)

## Done When

- A new slot creates `.work/`, not workspace clones
- A new permanent clone creates `.notes`, not a workspace clone
- `write-content` writes directly to project `docs/blog/`
- The close ceremony has no promotion gate and no workspace landing step
- Existing v1 contexts still work unchanged
- The lifecycle-maintainer-guide matches the code
- `~/claude/public/` has had no writes for 30 days
