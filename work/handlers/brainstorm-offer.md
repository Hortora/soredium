# Handler: brainstorm_offer

Branch is set up, context is loaded. Offer brainstorming.

> "Start a brainstorm? (y/n)"

If yes: invoke `brainstorming` skill. Specs write to `$WORKSPACE/specs/<branch-name>/`.

If no: call the orchestrator with:
```
step_done=brainstorm_offer
```

This is the final step in the start pipeline. After it completes, the orchestrator returns `ACTION=complete`.
