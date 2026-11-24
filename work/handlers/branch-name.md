# Handler: branch_name

The pipeline needs a branch name to create branches.

1. Read `ISSUE_N` and `ISSUE_TITLE` from the ACTION output
2. Derive: `issue-NNN-<slug>` (title lowercased, special chars stripped, max 30 chars after prefix)
3. Show to user, allow override
4. Guards: reject `main`, `HEAD`, or the base branch name. Existing branches from a previous attempt are resumed automatically if they have a base record. An existing branch with no base record fails with a structured error — suggest deleting it or choosing a different name
5. Call the orchestrator again with:
   ```
   step_done=branch_name branch=<confirmed-name>
   ```
