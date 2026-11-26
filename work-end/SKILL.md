---
name: work-end
description: >
  Use when the current branch is complete and ready to close — user says
  "work end", "close this branch", or "wrap up this issue". Must be invoked
  from a branch with active work or from main with a .queue. On main, skips
  branch-specific steps (merge, stamp, rebase, squash). Replaces "epic close".
---

# work-end

> **`work end` is run through `python3 ~/.claude/skills/project/work.py end`** (see the
> `work` skill, "Wrap and end"). That sequence does the review, diary entry and issue
> filing as steps, then runs this ceremony, then publishes within the
> ceremony's scope. This skill documents the ceremony itself and `work sync`. Where the
> advisory pre-close checklist below overlaps the sequence's steps, the sequence wins.


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
`ON_MAIN`, `IN_SLOT`, `SLOT_PATH`, `DONE_PENDING`, `DONE_ITEMS`.

**Batch close:** `DONE_PENDING` > 0 means earlier issues in this session were
marked done but not closed (`work next`). `DONE_ITEMS` lists them as
`<issue>@<branch>`, in queue order. This one work-end closes all of them and
the active issue together. The batch is every branch in `DONE_ITEMS` plus
`CURRENT_BRANCH`.

## Step 2 — Pre-close checklist (advisory)

These steps run BEFORE the ceremony. They are advisory — the ceremony
does not depend on them. Skip any that don't apply.

**For a batch, run each step once, over the whole batch** — not once per
issue. Code review and branch audit read the diff of every batch branch;
the sweeps, CLAUDE.md, doc sync and ADR steps cover the whole session; one
diary entry covers every issue closed. The exception is squash review,
which is per branch.

1. **Code review** — invoke `code-review` if not yet done this session
2. **Branch audit** — invoke `branch-audit` for holistic review
3. **Forage SWEEP** — invoke `forage` SWEEP for knowledge capture
4. **Protocol SWEEP** — invoke `protocol` SWEEP for convention capture
5. **Update CLAUDE.md** — invoke `update-claude-md` if build/test/naming changed
6. **Doc sync** — invoke `implementation-doc-sync` if docs need updating
7. **ADR** — invoke `adr` if architectural decisions were made
8. **Write content** — invoke `write-content` (diary) for the session
9. **Doc freshness** — invoke `doc-freshness` to check for stale structural anchors
10. **Squash review** — invoke `git-squash` on every project repo whose
   branch has more than one commit, for every branch in the batch. One
   unreviewed branch holds back the whole batch. This is the ONLY path to squashing:
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

This runs the ceremony: resolve targets, preflight, land (rebase +
FF-merge), stamp branches, advance queue. Repos are never left on mixed
branches.

**Batch:** the ceremony lands every done item's branch in queue order, then
the active item's branch. Everything is checked before anything lands: a
branch needing squash review, or a done item whose branch no longer exists,
stops the batch with nothing changed. An item is checked `[x]` only after
its own landing and stamp succeed. If a later branch fails (a rebase
conflict, say), the earlier items are landed and closed, the failed one and
those after it stay done-but-not-closed, and the progress is committed.
Fix the failed branch and run the ceremony again; it continues from there.

**Landing strategy:** close.py rebases the branch onto base and
fast-forwards. Every commit on the branch reaches main individually.
close.py has no squash path of any kind.

**Squash review gate:** before touching anything, close.py checks each
project repo's branch against the tip git-squash recorded
(`refs/squash-reviewed/<branch>`). A single-commit branch needs no
review. Otherwise the recorded tip must equal the branch tip.

Read the output:
- `ACTION=complete` — ceremony succeeded. Read `LANDED_*`, `CLOSED_ITEM`
  and `NEXT_ITEM`. Each `CLOSED_ITEM=<issue> branch=<branch>` line is one
  queue item this ceremony landed and closed, in landing order.
  `LANDED_<repo>` is that project repo's base-branch tip after landing.
  **Landed means on disk.** Every branch is now on its canonical repo's
  base branch (the repo under `~/claude/<family>/`); from a slot, the work
  has reached canonical. Landing uses no network and pushes nothing. Each
  `UNPUBLISHED=<canonical repo> commits=<N>` line names a canonical repo
  whose base branch holds commits its remote lacks. `WARN=` lines are
  shown to the user as they are.
  In a slot the ceremony also carries everything else the slot holds:
  `CARRIED=<repo>:<branch> commits=<N>` is work outside the queue's branch
  that it landed in canonical.
  `NOT_LANDED=<repo>:<branch> reason=<why>` is work it could not land;
  the slot is then not marked ready for archive. Report every
  `NOT_LANDED` line to the user and fix the cause (uncommitted changes or
  a conflict in that repo), then run the ceremony again.
**Order and stacked branches.** The ceremony works out the landing order
itself, from what each branch was cut from; the queue's order only breaks
ties. A branch stacked on another lands after it and contributes only its
own commits. You do not choose or change the order. If it reports that a
branch was stacked on one that "has not landed and is not part of this
close", that a branch "no longer sits on the commit it was recorded as cut
from", or that "the repos disagree about the order", nothing was landed:
show the `ERROR=` line to the user and stop. Do not rebase or reorder
branches to get past it.

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

1. **Close GitHub issues** — one per `CLOSED_ITEM` line, and no others:
   ```bash
   gh issue close $ISSUE_N --repo $OWNER_REPO --comment "Landed as <SHA>"
   ```
   If the ceremony failed part-way, it raised an error rather than printing
   `CLOSED_ITEM` lines. Read the queue: items now checked `[x]` have landed
   and their issues should be closed; items still marked `← done on` have
   not, and their issues stay open.

3. **Slot status** (if `IN_SLOT=yes`): never archive from here and never offer to.
   A slot cannot be archived by a session running inside it.
   - `SLOT_READY_FOR_ARCHIVE=<slot>` in the ceremony output: report "Slot N has
     landed and is marked ready for archive."
   - No such line and a `NEXT_ITEM`: the slot still has work queued; say nothing
     about archiving.
   - No such line and no `NEXT_ITEM`: report that the slot was not marked landed
     and show the ceremony output. Do not work around it with `--force`.

4. **Queue advancement:**
   If `NEXT_ITEM` is present, report it: "Next issue: `NEXT_ITEM`".
   If no next item, the queue is drained.

5. **Report:** Print the ceremony result. Include landed SHAs and any
   `WARN=` lines.

6. **Offer to publish** (only when the output has `OFFER=publish`):
   publishing is a separate step from landing and is never done without
   the user saying so. List each `UNPUBLISHED` repo with its commit count
   and ask once whether to publish them. On yes, for each repo:

   ```bash
   python3 ~/.claude/skills/project/canonical_sync.py publish <canonical repo>
   ```

   Publishing fetches the main remote, puts canonical's unpublished commits
   on top of it if it moved, pushes them to the fork as the branch
   `publish/<base>`, pushes to the main remote (never forced), and lets the
   fork's base branch follow. Read the output:
   - `PUBLISHED=<remote>` and `PUSHED=<N>`: done. `REBASED=<N>` above zero
     means the remote had moved and N unpublished commits were replayed on
     top of it; say so. `STAGED=failed` or `MIRRORED=failed`, each with a
     `WARN=` line, mean the main remote has the work and only the fork is
     behind.
   - `ERROR=rebase_conflict`: the unpublished commits conflict with what the
     remote gained. Nothing was changed. Tell the user which files; do not
     force, reset or rebase the base branch yourself.
   - `ERROR=rebase_refused`: the base branch's checkout in the canonical
     repo has uncommitted changes. Nothing was changed. Tell the user.
   - `ERROR=fetch_failed` or `ERROR=publish_failed`: the remote could not
     be reached. The commits stay landed on disk; publish again later.

   On no, say the commits stay on disk and can be published later with the
   same command.
   `canonical_sync.py status <repo>` prints `UNPUBLISHED=<N>` at any time.
   Never push with `git push` from a slot or a feature branch.

---

## Skill Chaining

**Invoked by:** `work`, `executing-plans`, `subagent-driven-development`

**Invokes (pre-close):** `code-review`, `branch-audit`, `forage`, `protocol`,
`update-claude-md`, `implementation-doc-sync`, `adr`, `write-content`,
`doc-freshness`, `git-squash` (semantic squash; records the reviewed tip that close.py checks)

**Complements:** `work-slot` — slot sessions close through this skill's ceremony

**Uses:** `work-end/close.py` — atomic close ceremony
