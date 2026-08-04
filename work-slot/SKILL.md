---
name: work-slot
description: >
  Use when creating parallel clone-based slots for multi-repo family work —
  user says "create a slot", "spin up a slot for issue #N", "parallel
  work on engine and iot", or invokes /work-slot. Also use "work-slot next"
  to advance, "work-slot list" to see status, "work-slot remove" to archive,
  "work-slot add-repo" to add a repo, and "work-slot remove-repo" to drop one.
  NOT for single-repo worktree isolation (use using-git-worktrees for that).
slash-command: true
---

# work-slot

Create and manage numbered clone-based slots for parallel development
across a multi-repo family. Each slot contains standalone `git clone
--shared` repos (not git worktrees), isolated `.m2`, re-pointed symlinks,
and a `.plan` file for the issue queue.

> **Legacy:** existing slots under `worktrees/` continue to work. New slots are created under `slots/`.

## Slot Lifecycle

| State | Marker | Meaning |
|-------|--------|---------|
| `active` | slot dir exists, no markers | Work in progress |
| `archived` | in `slots/attic/<N>/` | Clones moved to attic, metadata kept |

---

## `work-slot` (create)

Accepts 1..n issue numbers OR free text — same input modes as `work-start`.
Epics are auto-detected from GitHub (recursive, unlimited nesting). A `.plan`
file is always created, even for single issues.

### Step 1 — Gather input

Ask the user for:
- **Issues or description:** issue numbers (e.g., `#42 #50`) or free text
  (e.g., "improve the scoring engine")
- **Repos:** which repos in the family to include (e.g., "engine", "engine and iot")
- **Context:** what needs doing and any background

The user may provide all of this in one sentence or you may need to ask.

### Step 2 — Find family root

Walk up from CWD looking for a directory that is not itself a git repo
and contains child directories with `wksp` symlinks. Or accept an
explicit path from the user.

If the family root cannot be determined, ask:
> "Which directory is the family root? (e.g., ~/claude/casehub)"

### Step 3 — Build queue and derive branch name

**Issue mode:** For each issue number, call `plan_manager.detect_epic()`
to check if it's an epic (has `## Scope` with `- [ ] #N` entries).
Epics are recursively expanded. Build the queue tree via
`plan_manager.build_queue()`.

If any epic has 5+ children → batch planning (LLM-driven grouping:
domain affinity, shared API surface, scale fit, dependency ordering).
User approves or adjusts the batch plan.

**Free text mode:** Empty queue. Issues created during brainstorming
are added to `.plan` as created.

Branch name: `issue-<N>-<slug>` from the primary issue (or text slug).
Show to user, allow override.

### Step 4 — Create the slot

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py create-slot <family-root> \
  repos=<csv> branch=<branch-name> issue=<N> issue-repo=<owner/repo> \
  covers=<csv> context=<text>
```

Read output: `SLOT_NUMBER`, `SLOT_DIR`, `BRANCH`. If `ERROR=`, report
and stop.

### Step 5 — Write `.plan`

Write the `.plan` file at the slot root (alongside `.slot`):

```bash
python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude/skills/work-slot')
from plan_manager import build_plan_content, rewrite_plan
# ... build and write .plan from the approved queue
"
```

### Step 6 — Activate issues on project board

If the project has `GitHub project:` configured in CLAUDE.md (read via
ctx.py `GITHUB_PROJECT`), activate issues on the project board:

```bash
python3 ~/.claude/skills/issue-workflow/issue_setup.py activate-issues \
  <issue-repo> issues=<covers> project=<github-project-number>
```

Non-fatal — warn and continue on failure.

### Step 7 — Write batch plan to GitHub epic (if applicable)

If batch planning ran in Step 3, update the epic's `## Scope` section
on GitHub with the batch-grouped checklist.

**Safeguards:**
- Show a diff preview before writing. User confirms explicitly.
- Preserve all content outside the Scope section.

### Step 8 — Offer iTerm2 tab

> "Open an iTerm2 tab in the slot? (y/n)"

If yes:
```bash
osascript -e 'tell application "iTerm2"
    tell current window
        create tab with default profile
        tell current session
            write text "cd <slot-dir>/<primary-repo>"
        end tell
    end tell
end tell'
```

Warn and continue if iTerm2 is unavailable.

### Step 9 — Report

```
Slot <N> created: <branch-name>
  Repos: engine, iot
  Queue: <issue-count> issues (<batch-count> batches)
  Workspace: work (shared) / work-iot (external)
  .m2: slots/<N>/.m2
  .plan: slots/<N>/.plan
  .slot: slots/<N>/.slot
  iTerm2: tab opened / skipped

Open a CLI in <slot-dir>/<primary-repo> and run `work`.
work-start will detect the existing scaffold and run the resume path.
```

---

## `work-slot list`

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py list-slots <family-root>
```

Format output as a table:

| Slot | Branch | Repos | State |
|------|--------|-------|-------|
| 1 | issue-42-spi | engine | active |
| 2 | issue-55-ledger | engine, iot | active |

---

## `work-slot next`

Delegates to the unified `work next` command (see work/SKILL.md Step 5).
The `.plan` file is the single source of truth — same behaviour in branch
and slot mode.

**Precondition:** `.plan` must exist at the slot root.

---

## `work-slot status`

Show queue progress for the current or specified slot.

### Usage

`work-slot status` (from inside a slot) or
`work-slot status <family-root> slot=<N>` (from main repo).

### Step 1 — Get status

```bash
python3 ~/.claude/skills/work-slot/plan_manager.py detect <slot-dir>/.plan
```

### Step 2 — Format output

```
Queue — issue-50-weighted-profiles (Slot 38)

  Batch 1 — Vocabulary and docs (S+S+S+S) ✅
    #108 ✓  #109 ✓  #110 ✓  #114 ✓

  Batch 2 — Weighted profiles API (M+M) ← current
    #111 — Add weight parameter ← active
    #112 — Dominant-auxiliary scoring

  Batch 3 — Signal store extension (S)
    #115 — Qualifier SPI widening

  Progress: 4/10 issues (40%), 1/5 batches complete
  Safe exit: yes (Batch 1 complete)
```

### Step 3 — Divergence detection (optional)

Cross-check `.plan` against the GitHub epic body. Report if:
- Issues added to the epic on GitHub after batching
- Issues closed on GitHub but not checked in `.plan`

```
⚠️ Divergence detected:
  - #118 added to epic on GitHub — not in batch plan
  Action: add to .plan via plan_manager.append_to_queue().
```

---

## `work-slot add-repo <repo-name>`

Add a repository to an existing slot. Run from inside a slot.

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py add-repo <slot-dir> repo=<repo-name>
```

Read output: `CLONED=yes`, `REPO_PATH=<path>`. If `ERROR=`, report and stop.

The script clones the repo into the slot, sets up the isolated `.m2`,
re-points `wksp`/`proj` symlinks, creates the feature branch, and
updates `.slot` to include the new repo.

---

## `work-slot remove-repo <repo-name>`

Remove a repository from an existing slot. Run from inside a slot.
Cannot remove the primary repo.

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py remove-repo <slot-dir> repo=<repo-name>
```

Read output: `REMOVED=yes`. If `ERROR=`, report and stop.

---

## `work-slot remove <N>`

> "Archive slot <N>? Slot clones will be moved to
> `slots/attic/<N>/` with .slot and markers preserved. (y/n)"

Wait for confirmation. Then:

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py remove-slot <family-root> slot=<N>
```

**Default behaviour is archive to attic, not delete.** The slot directory
moves to `slots/attic/<N>/` preserving .slot, `.plan`, and any other
metadata for auditing and branch hygiene.

**Never pass `--force-delete`** unless the user explicitly says "permanently
delete" or "destroy". Archived slots cost nothing and enable branch hygiene
scans, blog recovery, and stamp verification.

---

## How slots work

- **Self-contained.** Everything under `slots/<N>/` — repo clones,
  workspace clone, isolated `.m2`, `.slot` context file, `.plan` queue.
- **Isolated .m2.** Every slot gets its own Maven local repo via
  `.mvn/maven.config`. No cross-contamination with the originals.
- **Symlinks re-pointed.** `wksp`/`proj` symlinks point to the slot's
  workspace, not the originals. ctx.py follows them transparently.
- **Scaffold pre-created.** `.meta` and `JOURNAL.md` exist in the slot.
  work-start detects state 2 (scaffold exists) and runs the resume path.

### What happens in the slot

1. Human opens a CLI session in `slots/<N>/<primary-repo>`
2. Runs work-start — detects existing scaffold, runs resume path
3. Does the work (implementation, tests, etc.)
4. Runs work-end — detects slot mode, runs the full close sequence
   (review, promote, squash, push, merge to original, stamp, archive)

### What it doesn't do

- Does not run work-start — the human runs `work` in the new session (scaffold.py writes `state: scaffolded`, auto-resolved on first `work` invocation)
- Does not coordinate between slots — the human sequences merges
- **Does not delete slots** — all cleanup paths archive to
  `slots/attic/<N>/`. Deletion requires explicit `--force-delete`
  from the user. An archived slot costs nothing; a deleted slot loses
  branch hygiene data, blog entries, and audit trail permanently.

---

## Skill Chaining

**Invoked by:** Human directly (`/work-slot`, "create a slot for...",
"spin up a slot", "parallel work on...")

**Invokes:** Nothing — creates the environment; the human starts work.

**Complements:**
- `work-start` — runs inside the slot after creation (resume path).
  For slots with a `.plan`, work-start displays queue context on resume.
- `work-end` — runs the full close sequence inside the slot (review,
  promote, squash, push, merge to original, stamp, archive). One command,
  no separate merge step.
- `handover` — HANDOFF.md for session handoffs. For slots with a `.plan`,
  handover auto-includes a Queue Progress section.
- `using-git-worktrees` — different git primitive (`git worktree add`
  vs `git clone --shared`), different use case (single-repo ephemeral
  isolation for subagent dispatch)
- `issue-workflow` — activate-issues called during slot creation
- `plan_manager.py` — queue parsing, issue advancement, and progress
  queries for `.plan` files
