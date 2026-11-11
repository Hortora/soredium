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
9. **Squash noise** — invoke `git-squash` to compact WIP/fixup noise.
   This is the ONLY path to squashing — close.py FF-merges unless
   git-squash writes a `.squash-plan`. The skill classifies commits
   intelligently: KEEP meaningful ones, only squash noise. Always offer
   this step; skip only if the branch has clean, well-structured commits.

Present these as a checklist. User picks which to run.

## Step 3 — Close ceremony

```bash
python3 ~/.claude/skills/work-end/close.py $WORKSPACE
```

This runs the atomic ceremony: resolve targets, preflight, land (rebase +
FF-merge), stamp branches, advance queue. Either succeeds fully or
fails cleanly — repos are never left on mixed branches.

**Landing strategy:** after rebasing the branch onto base, close.py
FF-merges by default — preserving every individual commit on main.
Squash-merge only runs when a `.squash-plan` exists (user ran
`/git-squash` pre-close to compact noise). This ensures the reasoning
chain in individual commits is never silently destroyed.

Read the output:
- `ACTION=complete` — ceremony succeeded. Read `LANDED_*` and `NEXT_ITEM`.
- `ACTION=error` — ceremony failed. Read `ERROR=` lines, diagnose, and
  report to user.

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
`git-squash` (noise compaction — writes `.squash-plan` for close.py)

**Uses:** `work-end/close.py` — atomic close ceremony
