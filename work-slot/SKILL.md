---
name: work-slot
description: >
  Use when creating parallel worktree slots for multi-repo family work —
  user says "create a slot", "spin up a worktree for issue #N", "parallel
  work on engine and iot", or invokes /work-slot. Also use "work-slot
  epic" to iterate through an epic's child issues, "work-slot next" to
  advance, "work-slot list" to see status, "work-slot remove" to archive,
  and "work-slot merge" to land ready slots.
  NOT for single-repo worktree isolation (use using-git-worktrees for that).
slash-command: true
---

# work-slot

Create and manage numbered worktree slots for parallel development across
a multi-repo family. Each slot is a self-contained work environment with
isolated `.m2`, re-pointed symlinks, and a context file for the session
that works there.

## Slot Lifecycle

| State | Marker | Meaning |
|-------|--------|---------|
| `active` | slot dir exists, no markers | Work in progress |
| `ready to land` | `.phase-a-complete` | Phase A done, awaiting merge |
| `landed` | `.landed` | Merged to main, awaiting archive |
| `archived` | in `worktrees/attic/<N>/` | Worktrees removed, metadata kept |

---

## `work-slot create`

### Step 1 — Gather input

Ask the user for:
- **Repos:** which repos in the family to include (e.g., "engine", "engine and iot")
- **Issue:** the issue number and repo (e.g., `#42` on `casehubio/engine`)
- **Context:** what needs doing and any background (constraints, relevant files, design decisions)

The user may provide all of this in one sentence or you may need to ask.

### Step 2 — Find family root

Walk up from CWD looking for a directory that is not itself a git repo
and contains child directories with `wksp` symlinks. Or accept an
explicit path from the user.

```bash
# The family root is NOT a git repo but contains git repos with wksp symlinks
```

If the family root cannot be determined, ask:
> "Which directory is the family root? (e.g., ~/claude/casehub)"

### Step 3 — Derive branch name

`issue-<N>-<slug>` from the primary issue, same convention as work-start
Step 5. Show to the user, allow override.

### Step 4 — Create the slot

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py create-slot <family-root> \
  repos=<csv> branch=<branch-name> issue=<N> issue-repo=<owner/repo> \
  covers=<csv> context=<text>
```

Read output: `SLOT_NUMBER`, `SLOT_DIR`, `BRANCH`. If `ERROR=`, report
and stop.

### Step 5 — Activate issues on project board

If the project has `GitHub project:` configured in CLAUDE.md (read via
ctx.py `GITHUB_PROJECT`), activate issues on the project board:

```bash
python3 ~/.claude/skills/issue-workflow/issue_setup.py activate-issues \
  <issue-repo> issues=<covers> project=<github-project-number>
```

Non-fatal — warn and continue on failure.

### Step 6 — Offer iTerm2 tab

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

### Step 7 — Report

```
Slot <N> created: <branch-name>
  Repos: engine, iot
  Workspace: work (shared) / work-iot (external)
  .m2: worktrees/<N>/.m2
  Slot context: worktrees/<N>/.slot
  iTerm2: tab opened / skipped

Open a CLI in <slot-dir>/<primary-repo> and run work-start.
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
| 2 | issue-55-ledger | engine, iot | ready to land |

---

## `work-slot epic <owner/repo>#<N>`

Create an epic slot — a single slot that iterates through an epic's
child issues using batch planning. One slot, one branch, multiple
sessions.

### Step 0 — Guard: check for existing epic slot

Scan active slots via `list_slots()` and check each .slot for
`Type: epic` with the same epic issue number. If found, refuse:

> "Slot N already tracks epic #M (branch: `<branch>`).
> Run `work-slot merge` to land it first, or `work-slot status`
> to see its progress."

### Step 1 — Gather input

Ask the user for:
- **Epic:** the epic issue number and repo (e.g., `#50` on `casehubio/engine`)
- **Repos:** which repos in the family to include
- **Context:** background on the epic (constraints, goals)

### Step 2 — Fetch child issues

```bash
gh issue view <N> --repo <owner/repo> --json body,title
gh issue list --repo <owner/repo> --state open --limit 100
```

Parse the epic's Scope checklist (`- [ ] #N` entries) to find child
issues. For each child, fetch title, labels, and body.

### Step 3 — Estimate scale and complexity

For each child issue, read its labels. If `scale:` or `complexity:`
labels are missing, estimate from title + body using the Scale and
Complexity Triage table (from issue-workflow). Propose labels, apply
on user approval.

### Step 4 — Batch planning

Analyze children for batch grouping:
- Same domain/subsystem → group together
- Shared API surface (changes that should land together) → group
- Scale fit (combine small issues, keep large ones solo or paired)
- Dependency mentions ("depends on #N") → later batch

Present a batch plan table:

```
┌────────┬──────────────┬─────────┬──────────────────────────────┐
│ Batch  │    Issues    │  Scale  │         Why together         │
├────────┼──────────────┼─────────┼──────────────────────────────┤
│ 1      │ #108, #109   │ S+S     │ Vocabulary — no API change   │
│ 2      │ #111, #112   │ M+M     │ Weighted profiles — the API  │
│ 3      │ #116         │ M       │ Depends on #111              │
└────────┴──────────────┴─────────┴──────────────────────────────┘
```

User approves or adjusts the batch plan. The batch plan is a one-shot
LLM decision — re-running may produce different grouping. The approved
plan is authoritative.

### Step 5 — Write batch plan to GitHub epic

Update the epic's `## Scope` section on GitHub with batch-grouped
checklist.

**Safeguards:**
- Locate `## Scope` by heading match (case-insensitive). If not found,
  warn and skip — .slot still has the plan.
- Show a diff preview before writing. User confirms explicitly.
- Preserve all content outside the Scope section.

### Step 6 — Derive branch name

`issue-<N>-<slug>` from the epic issue, same convention as work-start
Step 5. Show to user, allow override.

### Step 7 — Create the slot

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py create-slot <family-root> \
  repos=<csv> branch=<branch-name> issue=<N> issue-repo=<owner/repo> \
  covers= context=<text>
```

Then overwrite .slot with the epic format:

```bash
python3 -c "
import sys; sys.path.insert(0, '$HOME/.claude/skills/work-slot')
from epic_manager import write_epic_slot_md
from pathlib import Path
import json
# ... write_epic_slot_md with the approved batches
"
```

Or call `write_epic_slot_md()` directly from the skill context.

### Step 8 — Report

```
Epic slot <N> created: <branch-name>
  Epic: <owner/repo>#<issue>
  Batches: <count> (issues: <total>)
  Repos: <list>
  Starting: Batch 1 — <name> (#<first-issue>)

Open a CLI in <slot-dir>/<primary-repo> and run work-start.
```

---

## `work-slot next`

Advance to the next issue in the epic. Run from inside an epic slot.

**Precondition:** .slot must contain `Type: epic`.

### Step 1 — Run advance

```bash
python3 ~/.claude/skills/work-slot/epic_manager.py advance <slot-dir>/.slot
```

Parse the JSON output. The script atomically:
1. Checks off the current issue in .slot
2. Appends it to `COVERS` in `.meta`
3. Moves the `← active` marker to the next issue
4. Updates Session State

### Step 2 — Announce result

Based on the output flags:

- If `batch_complete` and not `epic_complete`:
  > "Batch N complete. Safe exit point — you can run work-end now
  > to merge everything done so far, or continue to Batch N+1."
  >
  > "Next: #<issue> — <title> (Batch N+1)"

- If `epic_complete`:
  > "All batches complete. Epic #N is done. Run work-end to close."

- Otherwise:
  > "Next: #<issue> — <title>"

Set the active issue for commit linkage (`Refs #<next_issue>`).

### Step 3 — GitHub checkbox (non-fatal)

Check the issue's checkbox on the GitHub epic body:

```bash
# Fetch current body, update checkbox, push back
gh issue view <epic-number> --repo <epic-repo> --json body
# Replace "- [ ] #<completed>" with "- [x] #<completed>"
gh issue edit <epic-number> --repo <epic-repo> --body-file /tmp/updated-body.md
```

This is progress signaling, not issue closure. Issues remain open
until `work-end` closes them via COVERS.

If GitHub update fails (auth, network), warn and continue.

---

## `work-slot status`

Show epic progress for the current or specified slot.

### Usage

`work-slot status` (from inside a slot) or
`work-slot status <family-root> slot=<N>` (from main repo).

### Step 1 — Get status

```bash
python3 ~/.claude/skills/work-slot/epic_manager.py status <slot-dir>/.slot
```

### Step 2 — Format output

```
Epic #50 — Weighted Profiles
Branch: issue-50-weighted-profiles (Slot 38)

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

Cross-check .slot against the GitHub epic body. Report if:
- Issues added to the epic on GitHub after batching
- Issues closed on GitHub but not checked in .slot

```
⚠️ Divergence detected:
  - #118 added to epic on GitHub — not in batch plan
  Action: re-run `work-slot epic #N` after this slot completes.
```

---

## `work-slot remove <N>`

> "Archive slot <N>? Git worktrees will be removed but .slot and
> markers are preserved in `worktrees/attic/<N>/`. (y/n)"

Wait for confirmation. Then:

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py remove-slot <family-root> slot=<N>
```

**Default behaviour is archive to attic, not delete.** The slot directory
moves to `worktrees/attic/<N>/` preserving .slot, `.phase-a-complete`,
`.landed`, and any other metadata for auditing and branch hygiene.

**Never pass `--force-delete`** unless the user explicitly says "permanently
delete" or "destroy". Archived slots cost nothing and enable branch hygiene
scans, blog recovery, and stamp verification.

---

## `work-slot merge`

Merge ready-to-land slots from the main repo. Runs the full Phase B
sequence: rebase, push, close issues, promote artifacts, stamp, archive.

### Step 1 — Find family root

Walk up from CWD looking for a directory that is not itself a git repo
and contains child directories with `wksp` symlinks. For each candidate,
verify its child repos have `.git` directories (not files) — worktree
checkouts have `.git` files and must be skipped.

If the walk-up fails, ask:
> "Which directory is the family root? (e.g., ~/claude/casehub)"

### Step 2 — Scan and present

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py scan-ready <family-root>
```

Parse the JSON output. For each slot, fetch the issue title:
```bash
gh issue view <issue-number> --repo <issue-repo> --json title --jq '.title'
```

Present the rich listing:
```
Slots ready to merge:

  [1] issue-42-spi
      Repos: engine (3 commits, +142/-38)
      Issue: casehubio/engine#42 — "Add expression SPI"
      Context: Implement SPI for pluggable expression evaluation
      Phase A completed: 2026-07-18 14:32

Merge which slot? (number, or "all")
```

If no slots are ready: "No slots ready to merge." Stop.

### Step 3 — Pre-check

For every original repo across all selected slots, verify:
1. Main checked out
2. Clean working tree (`git -C <repo> status --short` is empty)
3. No unpushed commits (`git -C <repo> log origin/main..main --oneline`
   is empty)
4. Fetch origin — warn if remote is ahead (non-blocking)

If any check fails, stop and report which repo failed and why.

### Step 4 — Merge each slot

For each selected slot, in order:

**4a. Rebase and push:**
```bash
python3 ~/.claude/skills/work-slot/slot_manager.py merge-slot <family-root> slot=<N>
```

Read output. If `ERROR=conflict`: stop, report which repo conflicted.
If `ERROR=retry_exhausted`: stop, provide manual instructions.
If `STAGE=push STATUS=pass`: continue to 4b.

**4b. Post-merge actions** (skill handles these):
- Close issues:
  ```bash
  python3 ~/.claude/skills/work-end/artifact_promote.py close-issues <issue-repo> covers=<covers>
  ```
- Promote artifacts from slot workspace to original workspace:
  ```bash
  python3 ~/.claude/skills/work-end/artifact_promote.py to-workspace-main <original-workspace> branch=<branch> artifacts=<paths>
  ```
- Publish blog:
  ```bash
  python3 ~/.claude/skills/work-end/blog_dest.py <original-workspace>/blog <branch>
  ```

**4c. Stamp branches** — handled programmatically by `merge_slot()`.
`merge_slot()` writes stamp commits on all repo and workspace worktrees
after confirming all pushes succeeded. Do NOT write stamps manually.

**4d. Mark closed:**
```bash
python3 ~/.claude/skills/work-end/branch_cleanup.py create-epic-closed \
  <slot>/<primary-workspace> branch=<branch> date=$(date +%Y-%m-%d) \
  issues=<covers> single-repo=no
```

**4e. Archive:**
```bash
python3 ~/.claude/skills/work-slot/slot_manager.py archive-slot <family-root> slot=<N>
```

If archive fails: report error but do NOT roll back — code is on main.
Report manual cleanup commands.

### Step 5 — Report (mechanical)

Render the close-out report from collected step results:

```bash
python3 ~/.claude/skills/work-end/close_report.py render /tmp/work-end-report.json
```

Record results into the report after each sub-step in Step 4 (rebase, merge,
push, stamp, worktree-remove, archive) using `close_report.py record`. The
script produces a deterministic, structured summary identical to work-end.

If "all" was selected, repeat Step 4 for next slot. If any slot fails at
4a, stop — report which slot failed and that prior slots landed.

---

## How slots work

- **Self-contained.** Everything under `worktrees/<N>/` — repo worktrees,
  workspace worktree, isolated `.m2`, .slot context file.
- **Isolated .m2.** Every slot gets its own Maven local repo via
  `.mvn/maven.config`. No cross-contamination with the originals.
- **Symlinks re-pointed.** `wksp`/`proj` symlinks point to the slot's
  workspace, not the originals. ctx.py follows them transparently.
- **Scaffold pre-created.** `.meta` and `JOURNAL.md` exist in the slot.
  work-start detects state 2 (scaffold exists) and runs the resume path.

### What happens in the slot

1. Human opens a CLI session in `worktrees/<N>/<primary-repo>`
2. Runs work-start — detects existing scaffold, runs resume path
3. Does the work (implementation, tests, etc.)
4. Runs work-end — detects slot mode, runs Phase A (review, verify,
   squash, push branch), stops before merge. Desktop notification.
5. Human returns later, says "merge" — work-end Phase B runs (rebase,
   push main, close issues, promote artifacts, cleanup slot)

### What it doesn't do

- Does not run work-start — the human does that in the new session
- Does not merge to main — work-end Phase B handles that
- Does not coordinate between slots — the human sequences merges
- **Does not delete slots** — all cleanup paths archive to
  `worktrees/attic/<N>/`. Deletion requires explicit `--force-delete`
  from the user. An archived slot costs nothing; a deleted slot loses
  branch hygiene data, blog entries, and audit trail permanently.

---

## Skill Chaining

**Invoked by:** Human directly (`/work-slot`, "create a slot for...",
"spin up a worktree", "parallel work on...", "drive through the epic",
"work-slot epic #N")

**Invokes:** Nothing — creates the environment; the human starts work.

**Complements:**
- `work-start` — runs inside the slot after creation (resume path).
  For epic slots, work-start detects `Type: epic` in .slot and
  displays batch context on resume.
- `work-end` — Phase A writes `.phase-a-complete`; work-slot merge reads
  it and runs Phase B externally. After Phase A in a slot, work-end
  offers to stamp/close/archive. Phase B from inside the slot still works.
- `handover` — HANDOFF.md for session handoffs. For epic slots,
  handover auto-includes an Epic Progress section from .slot.
- `using-git-worktrees` — same git primitive, different use case
  (single-repo ephemeral isolation for subagent dispatch)
- `issue-workflow` — activate-issues called during slot creation
- `artifact_promote.py` / `blog_dest.py` / `branch_cleanup.py` — shared
  scripts used by both work-end Phase B and work-slot merge
- `epic_manager.py` — batch plan parsing, issue advancement, and
  progress queries for epic slots
