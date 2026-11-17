---
name: quick-fix
description: >
  Use when landing a small change directly on main without a feature branch —
  user says "quick-fix", "land this on main", "commit to main", or invokes
  /quick-fix. Not for feature work (use work start for that).
---

# quick-fix

Commit a small change on the base branch and land it on disk. Nothing is
pushed: publishing is a separate step the script offers.

---

## When to use

- Small fixes that don't warrant a feature branch
- CI fixes (fix-ci uses this)
- Config tweaks, typo fixes, one-line changes

**Not for:** feature work, multi-commit changes, anything that needs review.
Use `work start` for those.

---

## Usage

```bash
python3 ~/.claude/skills/quick-fix/quick_fix.py <project> message="<commit message>"
```

The project must be on its base branch. Its uncommitted changes become one
commit on that branch. In a slot clone the commit is then landed in the
canonical repo. The script never stashes, resets, switches a checkout or uses
the network.

Read the output KEY=value lines:

| Key | Values | Meaning |
|-----|--------|---------|
| `COMMITTED` | `yes`, `skipped` | Whether a new commit was created (skipped when a slot clone only had commits waiting to land) |
| `LANDED` | `yes` | The change is on the canonical repo's base branch, on disk |
| `SHA` | commit | The canonical base branch tip |
| `UNPUBLISHED` | number | Commits canonical's base branch holds that its remote lacks |
| `OFFER` | `publish` | Present when `UNPUBLISHED` is above zero |

When `OFFER=publish` appears, ask the user once whether to publish. On yes:

```bash
python3 ~/.claude/skills/project/canonical_sync.py publish <project>
```

Never `git push` yourself.

Errors: `NOT_ON_MAIN`, `NOTHING_TO_DO`, `BUSY` (a rebase or merge is in
progress: tell the user, do not abort it), `COMMIT_FAILED` (a hook rejected the
commit; the changes are still in the working tree, unstaged),
`REBASE_CONFLICT` (a slot's fix conflicts with what canonical already has;
nothing was landed).

---

## Commits already on the base branch

Commits on the base branch that the remote does not have yet are landed work
waiting to be published. quick-fix leaves them exactly as they are and commits
on top. It does not move them to a branch or reset the base branch.

---

## Skill Chaining

**Invoked by:**
- User saying "quick-fix", "land this on main", "/quick-fix"
- `fix-ci` — uses quick-fix to land CI fixes, then publishes when the user agrees

**Invokes:** Nothing. Lands through `project/canonical_sync.py`; publishing is `canonical_sync.py publish`.

**Complements:**
- `work` — quick-fix is for trivial changes; work is for feature branches
- `git-commit` — quick-fix replaces direct `git commit` on main

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Using quick-fix for multi-commit work | Everything uncommitted becomes one commit on the base branch | Use work start for feature branches |
| Running quick-fix from a feature branch | Script errors — only works from main | Checkout main first, or use work end |
| Pushing after quick-fix with `git push` | Only the canonical repo publishes, through one command | `canonical_sync.py publish <project>`, when the user says so |
| Treating unpublished commits on the base branch as a mistake | They are landed work awaiting publish | Leave them; publish when the user says so |
