---
name: work-end
description: >
  Use when the current branch is complete and ready to close — user says
  "work end", "close this branch", or "wrap up this issue". Must be invoked
  from a branch with active work or from main with a .queue. On main, skips
  branch-specific steps (merge, stamp, rebase, squash). Replaces "epic close".
---

# work-end

Three phases: pre-close (advisory, skills), ceremony (close.py), post-close (issues, report).

<HARD-GATE>
**Do NOT defer.** Session-bound items are lost if the session ends.
</HARD-GATE>

## Step 1 — Context

```bash
python3 ~/.claude/skills/project/ctx.py
```

**Structural integrity gate:** If `CORRUPTION_COUNT` > 0, stop and report.
Do not proceed with work-end while structural corruption exists.

Use: `WORKSPACE`, `PROJECT`, `CURRENT_BRANCH`, `ISSUE_N`, `COVERS`,
`OWNER_REPO`, `BASE_BRANCH`, `QUEUE_STATUS`, `HAS_QUEUE`, `QUEUE_PATH`,
`ON_MAIN`, `IN_SLOT`, `SLOT_PATH`.

## Step 2 — Pre-close checklist (advisory)

These steps run BEFORE the ceremony. They are advisory — the ceremony
does not depend on them. Skip any that don't apply.

1. **Code review** — invoke `code-review` if not yet done this session
2. **Branch audit** — invoke `branch-audit` for holistic review
3. **Forage SWEEP** — invoke `forage` SWEEP for knowledge capture
4. **Protocol SWEEP** — invoke `protocol` SWEEP for convention capture
5. **Update CLAUDE.md** — invoke `update-claude-md` if build/test/naming changed
6. **Doc sync** — invoke `implementation-doc-sync` if docs need updating
7. **ADR** — invoke `adr` if architectural decisions were made
8. **Write content** — invoke `write-content` (diary) for the session
9. **Squash review** — invoke `git-squash` on every project repo whose
   branch has more than one commit. This is the ONLY path to squashing:
   close.py never squashes. The skill keeps informational commits and
   compacts only noise, then records the reviewed branch tip. The
   ceremony refuses to land a multi-commit branch without that record,
   so this step is required, not optional, for such branches. Never
   create a `.squash-plan` file — nothing reads it.

Present these as a checklist. User picks which to run.

## Step 3 — Close ceremony

```bash
python3 ~/.claude/skills/work-end/close.py $WORKSPACE
```

This runs the atomic ceremony: resolve targets, preflight, land (rebase +
FF-merge), stamp branches, advance queue. Either succeeds fully or
fails cleanly — repos are never left on mixed branches.

**Landing strategy:** close.py rebases the branch onto base and
fast-forwards. Every commit on the branch reaches main individually.
close.py has no squash path of any kind.

**Squash review gate:** before touching anything, close.py checks each
project repo's branch against the tip git-squash recorded
(`refs/squash-reviewed/<branch>`). A single-commit branch needs no
review. Otherwise the recorded tip must equal the branch tip.

Read the output:
- `ACTION=complete` — ceremony succeeded. Read `LANDED_*` and `NEXT_ITEM`.
  `LANDED_<repo>` is that project repo's base-branch tip after landing.
  Workspace repos are reported separately as `WORKSPACE_LANDED_<repo>`,
  because a workspace can share its directory name with the project.
- `ACTION=squash_review_needed` — nothing was changed. Each
  `SQUASH_REVIEW=<repo>:<branch>: <reason>` line names a branch that has
  not been reviewed at its current tip (never reviewed, commits added
  since, or rebased since). Invoke `git-squash` for each one, then run
  the ceremony again. Do not work around this by landing manually.
- `ACTION=error` — ceremony failed. Read `ERROR=` lines, diagnose, and
  report to user.
  If an error says a rebase, merge or other operation is in progress, or
  that HEAD is detached, stop and tell the user. Do not run
  `git rebase --abort` or `git merge --abort` yourself: commits made while
  the operation was stopped belong to no branch and are discarded by an
  abort. Find and save them first (`git reflog`).

**If `.close-state` exists** before running, a previous ceremony was
interrupted. The ceremony is idempotent — re-run it. It picks up from
committed state.

## Step 4 — Post-close actions

After `ACTION=complete`:

1. **Artifact sweep** — promote workspace artifacts to project:
   ```bash
   python3 ~/.claude/skills/work-end/artifact_sweep.py $WORKSPACE $PROJECT covers=$COVERS
   ```
   This compares workspace `blog/`, `specs/`, `docs/adr/`, `plans/`,
   `snapshots/` against project destinations and copies anything missing.
   Covers all categories, not just blog. Reports `GAPS=N` and `PROMOTED=N`.

1b. **Canonical workspace sweep** — also check the canonical workspace
   (not just the slot clone) for unpromoted blogs/specs/images:
   ```bash
   python3 ~/.claude/skills/work-end/artifact_promote.py sweep-gaps $PROJECT $CANONICAL_WORKSPACE covers=$COVERS
   ```
   `$CANONICAL_WORKSPACE` is the original workspace repo (e.g.
   `~/claude/public/casehub/quarkmind`), resolved via the project's
   `wksp` symlink target's `local` remote. If `$WORKSPACE` IS the
   canonical workspace (non-slot work), skip this step.
   Reports `PROMOTION_GAPS=N` and `SWEPT=N`. Auto-fixes all gaps.

2. **Close GitHub issues:**
   ```bash
   gh issue close $ISSUE_N --repo $OWNER_REPO --comment "Landed as <SHA>"
   ```

3. **Archive slot** (if `IN_SLOT=yes`):
   ```bash
   python3 ~/.claude/skills/work-slot/slot_manager.py archive-slot $FAMILY_ROOT slot=$SLOT_NUM
   ```

3. **Queue advancement:**
   If `NEXT_ITEM` is present, report it: "Next issue: `NEXT_ITEM`".
   If no next item, the queue is drained.

4. **Report:** Print the ceremony result. Include landed SHAs and
   any rescued commits.

---

## Skill Chaining

**Invoked by:** `work`, `executing-plans`, `subagent-driven-development`

**Invokes (pre-close):** `code-review`, `branch-audit`, `forage`, `protocol`,
`update-claude-md`, `implementation-doc-sync`, `adr`, `write-content`,
`git-squash` (semantic squash; records the reviewed tip that close.py checks)

**Uses:** `work-end/close.py` — atomic close ceremony
