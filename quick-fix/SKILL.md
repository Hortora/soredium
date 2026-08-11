---
name: quick-fix
description: >
  Use when landing a small change directly on main without a feature branch —
  user says "quick-fix", "land this on main", "commit to main", or invokes
  /quick-fix. Not for feature work (use work start for that).
---

# quick-fix

Land changes on main via an ephemeral branch. Same speed as `git commit && git push`
but keeps main tracking the blessed repo at all times.

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

Read the output KEY=value lines:

| Key | Values | Meaning |
|-----|--------|---------|
| `MODE` | `normal`, `rescue` | Whether there were unpushed commits on main |
| `COMMITTED` | `yes`, `skipped` | Whether a new commit was created (skipped in rescue with no dirty tree) |
| `REBASED` | `yes`, `skipped`, `conflict` | Whether the branch was rebased onto upstream |
| `LANDED` | `yes` | Merge --ff-only succeeded |
| `PUSHED` | `yes`, `failed`, `skipped` | Push to blessed remote |
| `MIRRORED` | `yes`, `failed`, `na` | Push to fork mirror (na if no fork) |
| `CLEANED` | `yes` | Ephemeral branch deleted |

---

## Rescue mode

If main has commits ahead of the blessed remote (someone committed directly),
quick-fix auto-detects this and rescues:

1. Moves the unpushed commits to an ephemeral branch
2. Resets main to match the blessed remote
3. Rebases the ephemeral branch onto the updated main
4. Lands via --ff-only

No code is lost — commits are preserved on the ephemeral branch before any reset.

---

## Advisory pre-commit hook

An optional pre-commit hook warns when committing directly to main. Install it per-project:

```bash
git config core.hooksPath .githooks/
```

The hook is advisory — it warns but does not block. The rescue flow handles
direct-to-main commits safely if the warning is ignored.

---

## Skill Chaining

**Invoked by:**
- User saying "quick-fix", "land this on main", "/quick-fix"
- `fix-ci` — uses quick-fix to land CI fixes instead of committing directly

**Invokes:** Nothing — standalone landing flow.

**Complements:**
- `work` — quick-fix is for trivial changes; work is for feature branches
- `git-commit` — quick-fix replaces direct `git commit` on main

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Using quick-fix for multi-commit work | Squashes everything into one commit on main | Use work start for feature branches |
| Running quick-fix from a feature branch | Script errors — only works from main | Checkout main first, or use work end |
| Ignoring rebase conflicts | Commits stuck on ephemeral branch | Resolve conflicts manually, then retry |
