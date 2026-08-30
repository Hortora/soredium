# Duplicate Commit Detection and Reconciliation

## Problem

When `sync-main` rebases already-pushed commits, the rebased commits get new
SHAs. If the fork later merges upstream (which has the old SHAs), both copies
end up on main — every affected commit appears twice with identical content but
different SHAs. 29 duplicate pairs were found across 13 casehub repos.

#301 prevents NEW duplicates by merging instead of rebasing when pushed commits
exist. This design adds a safety net: detect existing duplicates before merge,
reconcile automatically, and audit repos for historical damage.

## Components

### 1. Detection — `_find_duplicate_commits()`

New function in `branch_create.py`.

**Input:** repo path, two ref ranges (local-only commits, remote-only commits)

**Algorithm:**
1. Collect commit subjects from both sides via `git log --format='%H %s'`
2. Group by subject — commits with different subjects cannot be duplicates
3. For subject matches, compute `git patch-id` for each commit on both sides
4. Return pairs where patch-ids match — same content, different SHAs

**Why two-stage:** Message matching is O(n) string comparison. Patch-id requires
reading the full diff. The message pre-filter eliminates most commits cheaply;
patch-id confirms the matches are real content duplicates, not just similar
messages.

**Output:** List of `(local_sha, remote_sha, subject)` tuples.

### 2. Pre-merge gate — in `_sync_repo()`

Runs BEFORE the existing merge (line 174) or rebase (line 185).

**Flow:**

```
fetch blessed → fetch origin →
  compute local_only = blessed/main..main
  compute remote_only = main..blessed/main
  duplicates = _find_duplicate_commits(repo, local_only, remote_only)

  if duplicates:
    print DUPLICATE_COMMITS=N with details
    → reconcile: rebase onto blessed, auto-skip duplicate commits
    → if rebase fails on non-duplicate conflict: abort, warn, return skipped
    → print RECONCILED=N
    → push to origin
  else:
    → existing merge/rebase logic (unchanged)
```

**Reconciliation detail:**

The rebase will encounter conflicts on duplicate commits (same patch applied
twice). For each conflict:
1. Check if the conflicting commit's patch-id matches any commit already on
   blessed/main
2. If yes: `git rebase --skip` — the work is already there
3. If no: this is a real conflict, not a duplicate — `git rebase --abort`,
   return `skipped` with warning

Since `git rebase` doesn't expose per-commit hooks, the implementation uses
`GIT_SEQUENCE_EDITOR` to drop duplicate commits from the rebase todo list
before the rebase begins. This is cleaner than skip-on-conflict:

```python
# Build set of patch-ids already on blessed
blessed_patches = {patch_id for patch_id in _get_patch_ids(repo, f"main..{blessed}/{base}")}

# Get patch-ids of local-only commits
local_commits = _get_commits_with_patch_ids(repo, f"{blessed}/{base}..{base}")

# Commits to drop: local commits whose patch-id is in blessed
drop_shas = {sha for sha, pid in local_commits if pid in blessed_patches}

# Rebase with those commits dropped
_rebase_dropping(repo, blessed, base, drop_shas)
```

**Output (KEY=VALUE lines):**
- `DUPLICATE_COMMITS=N` — count of duplicates detected
- `DUPLICATE_DETAIL=<sha1>:<sha2>:<subject>` — one per pair (truncated)
- `RECONCILED=N` — count of commits dropped during rebase
- `STRATEGY=reconcile` — signals this was a reconciliation, not a normal sync

### 3. Audit script — `scripts/audit_duplicate_commits.py`

Standalone script for periodic or on-demand scanning.

**Usage:**
```bash
python3 scripts/audit_duplicate_commits.py <repo_path>
python3 scripts/audit_duplicate_commits.py <family_root> --all-repos
```

**Algorithm:**
1. Walk `git log main --format='%H %s'` (main branch only)
2. Group commits by subject
3. For groups with 2+ commits, compute patch-ids
4. Report pairs where patch-ids match but SHAs differ

**Output (KEY=VALUE lines):**
```
REPO=engine
PAIRS=6
PAIR=abc1234:def5678:feat(#1000): JudgmentNodeExecutor
PAIR=...
TOTAL_PAIRS=29
STATUS=dirty|clean
```

**Exit codes:** 0 = clean (no duplicates), 1 = duplicates found

**`--all-repos` mode:** Scan all git repos under the given directory. Report
per-repo and total. Useful for family-wide audits.

### 4. Project-health integration

Add `duplicate_commits` as a health check category. Invoke
`audit_duplicate_commits.py` on the project repo. Report:
- `clean` — no duplicates
- `N duplicate pairs` — historical damage, stable (not growing)
- `N duplicate pairs (NEW since last check)` — regression, active problem

The check is advisory (warning, not blocker) since existing duplicates are
harmless content-wise.

## Testing

- `_find_duplicate_commits()`: unit tests with synthetic git repos containing
  known duplicate commits (same content, different SHAs via cherry-pick or
  rebase)
- Pre-merge gate: integration test — create a repo with duplicates on both
  sides of a merge, verify the gate fires and reconciliation drops the right
  commits
- Audit script: integration test — create a repo with known duplicates,
  verify the script finds them and reports correct counts
- Negative cases: commits with same message but different content should NOT
  be flagged (patch-id mismatch)

## Scope boundaries

- This does NOT fix existing duplicate pairs in repos — they are harmless
  (0-line content diff) and the audit tracks the count
- This does NOT change the #301 merge-instead-of-rebase behavior — that
  prevents the root cause. This is the safety net for when it didn't
- This does NOT run in CI — it runs inside `sync_main` (before work-start)
  and as an on-demand audit

## References

- Issue #312 body — root cause chain and evidence
- `branch_create.py:149-156` — `_has_shared_fork_commits()` (#301 fix)
- `branch_create.py:159-199` — `_sync_repo()` merge/rebase logic
- `git-patch-id(1)` — content-based commit identity
