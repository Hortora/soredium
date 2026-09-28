# Handler: branch_name

The pipeline needs a branch name to create branches.

1. Read `ISSUE_N` and `ISSUE_TITLE` from the ACTION output
2. Derive: `issue-NNN-<slug>` (title lowercased, special chars stripped, max 30 chars after prefix)
3. Show to user, allow override
4. Guards: reject `main`, `HEAD`, or any existing branch name
5. Call the orchestrator again with:
   ```
   step_done=branch_name branch=<confirmed-name>
   ```
