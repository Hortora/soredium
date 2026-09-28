# Handler: deferred_check

All planned issues complete but deferred items exist. Present them for triage.

1. Read deferred items from `.plan`
2. Present each with scale, complexity, and deferral reason:
   ```
   All planned issues complete. N deferred items:
     0. <title> (S / Low) — <reason>
     1. <title> (M / High) — blocked by #55
   Select items to add to queue (e.g. "0,2"), or "none" to close.
   ```
3. Assess feasibility based on reason and current context
4. If user selects items, call with:
   ```
   step_done=deferred_check promoted_indices=0,2
   ```
5. If "none", route to work-end:
   ```
   step_done=deferred_check promoted_indices=
   ```
