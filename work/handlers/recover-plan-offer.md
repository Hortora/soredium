# Handler: recover_plan_offer

An orphaned `.plan` was found on a previously closed branch. Present the options:

```
Found .plan with {ORPHANED_REMAINING} remaining items on closed branch {ORPHANED_BRANCH}.
Next item: {ORPHANED_NEXT}

  1) Carry forward (Recommended)
     Copy .plan and HANDOFF.md to this branch and continue the queue.

  2) Start fresh
     Ignore the orphaned plan. Scaffold a new .plan for this issue only.
```

Based on user choice:

- **Carry forward**: Read `.orphaned-plan` marker, write `.plan` and `HANDOFF.md`
  to the workspace, commit them, then delete the marker.
  ```python
  import json
  marker = Path(workspace) / ".orphaned-plan"
  data = json.loads(marker.read_text())
  (Path(workspace) / ".plan").write_text(data["plan_content"])
  if data.get("handoff_content"):
      (Path(workspace) / "HANDOFF.md").write_text(data["handoff_content"])
  marker.unlink()
  git add .plan HANDOFF.md && git commit -m "chore: carry forward .plan from {ORPHANED_BRANCH}"
  ```

- **Start fresh**: Delete the marker and continue. The scaffold step will create
  a new `.plan`.
  ```python
  (Path(workspace) / ".orphaned-plan").unlink()
  ```

Then call the orchestrator with:
```
step_done=recover_plan_offer
```
