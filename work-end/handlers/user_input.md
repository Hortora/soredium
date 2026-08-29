# Handler: user_input (parameterised by CONTEXT=)

## CONTEXT=arc42_scan

If ARC42STORIES.MD exists, scan for stale statuses and offer fixes.

## CONTEXT=session_rename

Suggest a descriptive session name if auto-generated.

## CONTEXT=garden_feedback

Skeptical review of garden entries retrieved this session. The script is
the source of truth for what was retrieved — not conversation context.

1. Run the feedback table script:
   ```bash
   python3 scripts/garden_feedback_table.py <PROJECT_PATH> hours=4
   ```

2. If `NO_ENTRIES=true`: skip silently — no garden entries were retrieved.

3. Present the table with inverted default — all entries default to RELEVANT:
   ```
   Garden feedback — N entries retrieved this session

     1.   GE-20260824-c09677  "Stateless re-entrant script pattern"     → RELEVANT
     2.   GE-20260821-ebba3b  "work-end can stamp without merging"      → RELEVANT
     3. ⚠️ GE-20260809-96d41c  "gitignore trailing-slash skips symlinks" → RELEVANT
          verified_on: git 2.43 — project uses git 2.47

   Be skeptical — which should NOT go back as RELEVANT?
   Downgrade any? (e.g. "3 OUTDATED 4 NOT_RELEVANT", or "go" to send all as RELEVANT)
   ```

   **Your job is to be skeptical about unflagged entries.** Mechanically
   flagged entries (version mismatch, stale) are already surfaced. You add
   judgment: were the unflagged entries genuinely used this session?

4. After user responds, group by outcome and call gardenFeedback:
   ```
   gardenFeedback(geIds: "GE-...|GE-...", outcome: "RELEVANT",
       issueRepo: "<OWNER_REPO>", issueNumber: <ISSUE_N>)
   gardenFeedback(geIds: "GE-...", outcome: "OUTDATED",
       stack: "<from PROJECT_STACK>",
       issueRepo: "<OWNER_REPO>", issueNumber: <ISSUE_N>)
   ```

5. MCP unavailable → warn once, continue (never block)

## CONTEXT=notes

Surface most recent date section from $WORKSPACE/.notes/NOTES.md.
Offer to append. If user provides notes, append under today's date
and commit to orphan notes branch.

## CONTEXT=step_failed

Judgment step failed after 3 retries. Present STEP, ATTEMPTS, REASON.
Options: skip / retry / abort.

<SKIP-ISOLATION>
**Skipping is scoped to the failed step ONLY.** Each step is independent.
The orchestrator validates `skip_step=` against the last yielded step.

**When you may pass skip_step:**
- The orchestrator returned `CONTEXT=step_failed` for that specific STEP
- The user explicitly asked to skip that specific step

**When you may NOT pass skip_step:**
- A different step failed and you want to "skip the rest of the sweep"
- You think the step is unnecessary based on session context
- You want to save time or tokens
</SKIP-ISOLATION>

## CONTEXT=rebase_conflict

Rebase failed with conflicts. This is NOT retryable — the same conflicts
will recur on every attempt. Present the situation and let the user decide.

**Available context fields:** `CONFLICT_COUNT`, `CONFLICT_FILES`, `ERROR_DETAIL`,
`STEP` (rebase or rebase:{repo} in slot mode), `REPO` (slot mode only).

**Present to the user:**

```
Rebase onto {base_branch} failed — {CONFLICT_COUNT} conflicted file(s):
  {CONFLICT_FILES}

Options:
  1. Resolve manually — you fix conflicts, then I continue with conflict_resolved=yes
  2. Skip rebase — accept non-linear history (merge to main without rebasing)
  3. Abort — stop work-end and return to active state
```

**After user chooses:**

| Choice | Action |
|--------|--------|
| Resolve manually | User resolves outside the orchestrator. When done, re-invoke with `conflict_resolved=yes` (add `conflict_repo={repo}` in slot mode). |
| Skip rebase | Re-invoke with `conflict_resolved=yes` — the branch lands without rebasing. Merge to main will use `--no-ff` instead of `--ff-only`. |
| Abort | Re-invoke with `abort=yes`. |

## CONTEXT=per_repo_failures

Slot mode: a per-repo step was attempted across all repos. Some succeeded
(already marked done), some failed. The user sees the full picture.

**Available context fields:** `STEP` (step name, e.g. "rebase"),
`FAILED_REPOS` (comma-separated list of repos that failed),
`ERROR_{repo}` and `DETAIL_{repo}` for each failed repo,
`CONFLICTS_{repo}` (for rebase conflicts).

**Present to the user:**

```
{STEP} results across repos:
  engine:  FAILED — {ERROR_engine}: {DETAIL_engine} ({CONFLICTS_engine} conflicts)
  blocks:  FAILED — {ERROR_blocks}: {DETAIL_blocks}
  qhorus:  OK (done)

Options per repo:
  1. Resolve manually — fix conflicts, then pass conflict_resolved=yes conflict_repo={repo}
  2. Skip — pass force_done={STEP}:{repo} to skip that repo's step
  3. Abort — pass abort=yes to stop work-end entirely
```

Repos that succeeded are already marked done. Only failed repos need action.
