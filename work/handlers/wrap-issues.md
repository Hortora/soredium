# Handler: file_issues

File what this session leaves undone, and queue it.

1. One issue for every deferred item, loose end, review finding and suggestion
   that was not fixed. One concern per issue, with enough detail that a new
   session could start from it cold.
2. Issue references are always the full form, `owner/repo#N`.
3. Add each issue to the queue, in the order it should be worked:
   ```
   python3 ~/.claude/skills/work-slot/plan_manager.py append <queue> issues=<owner/repo#N>:<title>,...
   ```
   Commit the queue change in the workspace.
4. Report: `step_done=file_issues outcome=completed produced=<issues filed>`
