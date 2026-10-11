# Handler: resolve_issue

The pipeline needs an issue number to create a branch.

1. Read `OWNER_REPO` from the ACTION output
2. **Cross-repo detection (slots only):** If the user provided an issue
   reference like `<repo>#<N>` where `<repo>` is a short name (no slash):
   a. Check if `IN_SLOT=yes` and `SLOT_PATH` is set
   b. Read the slot's repo list via `parse_slot(SLOT_PATH)`
   c. If `<repo>` matches a repo name in the slot:
      - Call `write_active_repo(SLOT_PATH, <repo>)` to switch active project
      - Return `step_done=resolve_issue issue_n=<N> SWITCH_REPO=<repo>`
      - The work/SKILL.md orchestrator will re-invoke ctx.py with the
        updated topology before continuing the pipeline
   d. If no match, treat as a normal issue reference
3. Invoke `issue-workflow` Phase 2 (Task Intake) with the work description
4. When Phase 2 returns the resolved issue, call the orchestrator again with:
   ```
   step_done=resolve_issue issue_n=<N> issue_title=<title>
   ```

If the user explicitly skips issue creation, call with:
```
skip_step=resolve_issue
```
