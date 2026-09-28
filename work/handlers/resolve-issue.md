# Handler: resolve_issue

The pipeline needs an issue number to create a branch.

1. Read `OWNER_REPO` from the ACTION output
2. Invoke `issue-workflow` Phase 2 (Task Intake) with the work description
3. When Phase 2 returns the resolved issue, call the orchestrator again with:
   ```
   step_done=resolve_issue issue_n=<N> issue_title=<title>
   ```

If the user explicitly skips issue creation, call with:
```
skip_step=resolve_issue
```
