# Handler: upstream_pr

Offered when the project has a fork topology (upstream remote exists).
After the branch is landed and verified, offer to create a PR from
the fork to upstream.

## When FORK_AHEAD > 0

The fork has work not on upstream. Present:

```
Fork has N commits not on upstream. Create PR? (y/n/later)
  y — create PR now
  n — skip (work stays on fork only)
  later — skip now, remind next session
```

**If y:** Create the PR:
```bash
gh pr create --repo <upstream-repo> --head <fork-owner>:main --base main \
  --title "Sync fork: <brief summary of landed work>" \
  --body "Accumulated fork work from <N> commits across <issues>."
```

Extract the upstream repo from UPSTREAM_URL (e.g., `github.com/org/repo.git` → `org/repo`).
Extract the fork owner from `gh api user --jq '.login'` or from origin URL.

Mark done with `step_done=upstream_pr produced=1`.

**If later:** Write a marker for the next session:
```bash
echo "pending_upstream_pr=true" >> $WORKSPACE/.plan-state
```
Mark done with `step_done=upstream_pr produced=0`.

**If n:** Mark done with `step_done=upstream_pr produced=0`.

## When FORK_AHEAD == 0

Fork is in sync with upstream. Mark done silently:
`step_done=upstream_pr produced=0`

## When UPSTREAM_AHEAD > 0

Also surface: "Upstream has M commits not on fork." This is informational —
sync-main handles incorporating upstream changes.
