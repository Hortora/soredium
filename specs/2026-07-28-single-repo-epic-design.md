# Single-Repo Epic Support

**Issue:** Hortora/soredium#100
**Also closes:** #103 (start vs resume)
**Date:** 2026-07-28
**Status:** Approved

## Problem

Epic-driven iteration currently requires the full slot infrastructure —
multi-repo family root, git worktrees, SLOT.md, symlink re-pointing,
Maven isolation. Single-repo projects that want to iterate through an
epic's child issues sequentially have no equivalent.

## Design Decisions

- **Single branch** for the whole epic (no branch-per-child-issue)
- **`.epic` dotfile** in `workspace/design/` for state tracking (consistent
  with `.meta`, `.slot`, `.phase-a-complete`)
- **Optional batching** — flat list for small epics, batch planning for 5+
  children (LLM-driven grouping, same approach as `work-slot epic` Step 4)
- **Entry via `work epic #N`** — new verb in the `work` router
- **Iteration via `work next`** — new verb in the `work` router, context-aware
  (detects slot vs single-repo)

## .epic File Format

Lives at `workspace/design/.epic`, committed to the workspace repo.

```
# Epic #100 — single-repo-epic-support

## Issue
Hortora/soredium#100
Covers:
Type: epic
Safe exit: after any completed batch

## What to do
Single-repo epic support — sequential child issue iteration.
Current: Batch 1 — Infrastructure

## Batch Plan

### Batch 1 — Infrastructure ← current
- [ ] #102 — Rename SLOT.MD to .slot ← active
- [ ] #103 — Router start vs resume fix

### Batch 2 — Integration
- [ ] #104 — work next for single-repo
- [ ] #105 — work-start epic overlay

## Session State
Current batch: 1
Current issue: #102 — Rename SLOT.md to .slot
Last wrap: epic created
```

Differences from `.slot`:
- No `## Repos` section
- No `## Created` with slot number
- Heading: `# Epic #N — slug` instead of `# Slot N — branch`

Shared with `.slot`:
- `Safe exit: after any completed batch` (same machine-readable line)
- `Type: epic` in `## Issue` section
- `← current` / `← active` markers (Unicode left arrow, not ASCII `<-`)

## Entry Point: `work epic #N`

New verb in `work/SKILL.md` Step 1 routing table.

1. Fetch epic issue from GitHub, parse child issues from `## Scope`
   checklist (`- [ ] #N` entries). For each child, check issue state
   via `gh issue view` — skip children that are already CLOSED (handles
   re-running `work epic` on a partially-complete epic after mid-epic
   work-end). Only open children enter the batch plan.
2. Fetch title/labels/body for each child
3. If 5+ children → batch planning (LLM-driven grouping using the same
   criteria as `work-slot epic` Step 4: domain affinity, shared API
   surface, scale fit, dependency ordering). Otherwise flat ordered list
   as a single batch.
4. Sync main before branch creation — equivalent to work-start Step 4d.
   Fetch from origin/upstream, rebase local main, push to fork if
   applicable. This prevents the epic branch starting behind main.
5. Create or reset branch (target name: `issue-N-<slug>`):
   - If branch does not exist → `git checkout -b issue-N-<slug>`
   - If branch exists with closure stamp (`chore: branch closed` as
     latest commit subject) → mid-epic resume. Reset the branch to
     current HEAD: `git checkout -B issue-N-<slug>`. The old branch
     content is already on main (the stamp guarantees this).
   - If branch exists without closure stamp → error: "Epic branch
     `issue-N-<slug>` already exists and is active. Use `work` to
     resume."
6. Scaffold `.meta` and `JOURNAL.md` via existing `scaffold.py`
7. Write `workspace/design/.epic` with batch plan
8. Activate issues on project board — equivalent to work-start Step 4c.
   If `GITHUB_PROJECT` configured, activate all child issues (non-fatal).
9. Report and instruct to run work-start

## Iteration: `work next`

New verb in `work/SKILL.md`. Detects context automatically:

- `/worktrees/` in project path → slot context, reads `.slot`
- `workspace/design/.epic` exists → single-repo context, reads `.epic`

Steps:

1. Call `epic_manager.py advance <epic-path> <meta-path>`. The script
   atomically checks off the current issue, appends it to COVERS in
   `.meta`, moves `← active` to the next issue, and updates Session State.
2. Check off the completed issue's checkbox on the GitHub epic body
   (progress signaling, not issue closure — issues remain open until
   `work-end` closes them via COVERS, consistent with `work-slot next`).
3. If `batch_complete` and not `epic_complete` → log "Batch N complete.
   Safe exit point — run work-end to merge, or continue."
4. If `epic_complete` → add the epic issue number itself to `Covers:` in
   `.meta`, then report "All children done. Run work-end to close."
5. Report new active issue, set `Refs #<next-issue>` for commit linkage.

## Router Fix (#103): Start vs Resume

**Bug:** `work/SKILL.md` Step 4 always shows "resume" as option 1 on a
feature branch, even when `HAS_HANDOFF=no`.

**Fix:** Change Step 4 option 1 to be conditional:

```
If HAS_HANDOFF=yes:
  1. resume — read the last handover and continue
If HAS_HANDOFF=no:
  1. start — invoke work-start (first session on this branch)
```

Add epic-specific option when `IS_EPIC=yes`:

```
  N. next — mark current child issue done, advance to next
```

## work_router.py Changes

Detect `.epic` alongside existing `.slot` detection:

```python
epic_candidate = workspace / "design" / ".epic"
if epic_candidate.exists():
    content = epic_candidate.read_text()
    if "Type: epic" in content:
        is_epic = True
        # parse batch/active issue (same logic as .slot)
        result["EPIC_PATH"] = str(epic_candidate)
```

New output key: `EPIC_PATH` (for single-repo). Existing `SLOT_PATH`
remains for slot context. `IS_EPIC`, `EPIC_BATCH`, `EPIC_ACTIVE_ISSUE`
work identically for both.

## ctx.py Changes

Detect `.epic` in single-repo mode and expose epic context for downstream
skills (work-end, handover, work-pause, work-resume):

```python
epic_path = Path(workspace) / "design" / ".epic"
is_epic = False
if epic_path.exists():
    epic_content = epic_path.read_text()
    if "Type: epic" in epic_content:
        is_epic = True
```

New output keys:
- `EPIC_PATH` — full path to `.epic` file (empty if not present)
- `IS_EPIC` — `yes` / `no`

These parallel `work_router.py`'s output but are sourced from ctx.py so
that skills that don't call work_router (e.g. work-end Step 0, handover)
can detect epic state directly.

## epic_manager.py Generalisation

All public and internal functions accept explicit file paths instead of
deriving from `slot_dir`:

```python
# Before
def parse_batch_plan(slot_dir: Path) -> dict:
    slot_md = slot_dir / ".slot"

# After
def parse_batch_plan(epic_path: Path) -> dict:
    # epic_path is full path to .slot or .epic
```

`advance()` already accepts `meta_path`; change first parameter and
propagate `epic_number` / `epic_repo` from `parse_batch_plan()` into
the return dict (needed by `work next` step 4 to add the epic issue
to COVERS on completion):

```python
# Before
def advance(slot_dir: Path, meta_path: Path | None = None) -> dict:
    # returns: completed, next_issue, next_issue_title,
    #          batch_complete, epic_complete, safe_exit

# After
def advance(epic_path: Path, meta_path: Path | None = None) -> dict:
    # returns: all of the above PLUS epic_number, epic_repo
    # (propagated from parse_batch_plan() — always present,
    #  not just when epic_complete)
```

Internal functions follow the same pattern:

```python
# Before
def _rewrite_slot_md(slot_dir: Path, ...) -> None:
    slot_md = slot_dir / ".slot"

# After — renamed to match generalisation
def _rewrite_epic_file(epic_path: Path, ...) -> None:
    content = epic_path.read_text()

# Before
def status(slot_dir: Path) -> dict:
    plan = parse_batch_plan(slot_dir)

# After
def status(epic_path: Path) -> dict:
    plan = parse_batch_plan(epic_path)
```

CLI dispatch changes:

```python
# Before
slot_dir = Path(sys.argv[2])
result = parse_batch_plan(slot_dir)

# After — accepts file path directly
epic_path = Path(sys.argv[2])
result = parse_batch_plan(epic_path)
```

Callers:
- Slot: `advance(slot_dir / ".slot", slot_dir / repo / "design" / ".meta")`
- Single-repo: `advance(wksp / "design" / ".epic", wksp / "design" / ".meta")`

Write functions:

```python
# Before
def write_epic_slot_md(slot_dir, slot_number, repos, branch, issue, ...)

# After — explicit output path, no slot assumptions
def write_epic_file(epic_path: Path, heading: str, repos: list[str] | None,
                    issue: str, issue_repo: str, batches: list[dict],
                    context: str) -> None:

# New convenience — single-repo (no Repos section, no slot number)
def write_epic(workspace: Path, issue: str, slug: str,
               issue_repo: str, batches: list[dict],
               context: str) -> None:
    epic_path = workspace / "design" / ".epic"
    heading = f"# Epic #{issue} — {slug}"
    write_epic_file(epic_path, heading, repos=None, ...)
```

## work-start Epic Overlay

Generalise the overlay trigger to detect both slot and single-repo epics:

```
If /worktrees/ in $PROJECT:
    epic_file = $PROJECT/../.slot
Elif workspace/design/.epic exists:
    epic_file = workspace/design/.epic
Else:
    skip overlay
```

Guard: `epic_file` must exist and contain `Type: epic` in `## Issue`.

Both `.slot` and `.epic` share the same `## Batch Plan` and
`## Session State` format, so the overlay display code is identical:
batch progress, active issue, commit linkage (`Refs #<active-issue>`).
The only difference is the file heading (`# Slot N — branch` vs
`# Epic #N — slug`), which the overlay does not display.

## work-end Epic Closure

When `.epic` exists:
- All batches complete → epic issue already in COVERS (added by `work next`
  step 4 on final advance), close it alongside children
- Mid-epic exit → only close completed children, epic stays open.
  To resume remaining children: run `work epic #N` again. Step 1
  detects already-closed children and plans only the open remainder.
  This makes `work epic` idempotent on partially-complete epics.

Cleanup (single-repo only, in 8j-cleanup):
- `branch_cleanup.py cleanup-scaffold` already removes `.meta` and
  `JOURNAL.md` from main after rebase. Extend it to also remove `.epic`.
- `.epic` survives on the epic branch (branches are kept, not deleted)
  for audit — analogous to `.slot` surviving in the attic in slot mode.
- `EPIC-CLOSED.md` is committed to the epic branch (Step 9), not main.

## Change Set

| File | Change |
|------|--------|
| `work/SKILL.md` | Add `work epic`, `work next` verbs; fix Step 4 (#103) |
| `work/work_router.py` | Detect `.epic`, output `EPIC_PATH` |
| `work-slot/epic_manager.py` | Generalise to accept paths; rename write function; rename internal functions |
| `work-start/SKILL.md` | Generalise epic overlay trigger with dual-path detection |
| `work-end/SKILL.md` | Epic-aware closure; `.epic` in 8j-cleanup scaffold list |
| `work-end/branch_cleanup.py` | Add `.epic` to cleanup-scaffold removal list |
| `work-slot/SKILL.md` | Update `work-slot next` to pass explicit paths |
| `project/ctx.py` | Detect `workspace/design/.epic`, output `EPIC_PATH` and `IS_EPIC` |
| `handover/SKILL.md` | Detect `.epic` alongside `.slot` for Epic Progress section |
| `tests/test_epic_manager.py` | Update for path params; add `.epic` tests |
| `tests/test_work_router.py` | Add `.epic` detection tests |
| `tests/test_ctx.py` | Add `.epic` detection tests for `EPIC_PATH` and `IS_EPIC` output keys |

## Not In Scope

- Batch planning UX changes (same LLM-driven criteria as work-slot epic)
- Historical specs (left unchanged)
- `work-slot` creation flow (unchanged — still creates `.slot`)
