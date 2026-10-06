# Handler: queue_decision

The `.plan` has remaining queue items. Present the options to the user:

```
.plan has {REMAINING} remaining items. Next: {NEXT_TITLE}

  1) work sync (Recommended if continuing same work)
     Land code to main, keep this branch open for more work.

  2) fork next
     Create branch for the next item, carry .plan + HANDOFF,
     then close this branch.

  3) work end
     Close this branch. Remaining queue items will be discarded.
```

Based on user choice, call the orchestrator with:

- **sync**: `step_done=queue_decision produced=sync`
  The orchestrator will return `ACTION=redirect_sync`. Re-invoke with `mode=sync`.

- **fork next**: `step_done=queue_decision produced=fork_next`
  The orchestrator will run `fork_next_branch` to create the new branch,
  then continue the close ceremony. After close, it switches to the new branch.

- **end**: `step_done=queue_decision produced=end`
  The orchestrator continues the close normally. Queue items are lost.
