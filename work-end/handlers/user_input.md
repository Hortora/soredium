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
</SKIP-ISOLATION>

## CONTEXT=rebase_conflict

Rebase conflict needs manual resolution. User resolves, then pass
`conflict_resolved=yes` to the orchestrator.
