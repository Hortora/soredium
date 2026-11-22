# Handler: recover_plan_offer

An orphaned `.queue` was found on a previously closed branch. Present the options:

```
Found .queue with {ORPHANED_REMAINING} remaining items on closed branch {ORPHANED_BRANCH}.
Next item: {ORPHANED_NEXT}

  1) Carry forward (Recommended)
     Copy .queue and HANDOFF.md to this branch and continue the queue.

  2) Start fresh
     Ignore the orphaned queue. Scaffold a new .queue for this issue only.
```

Based on user choice:

- **Carry forward**: Read `.orphaned-plan` marker, write `.queue` and `HANDOFF.md`
  to the queue directory (resolved via `queue_io.queue_dir(workspace)`), commit
  them, then delete the marker.
  ```python
  import json
  from project.queue_io import queue_dir
  marker = Path(workspace) / ".orphaned-plan"
  data = json.loads(marker.read_text())
  qdir = queue_dir(workspace)
  (qdir / ".queue").write_text(data["plan_content"])
  if data.get("handoff_content"):
      (Path(workspace) / "HANDOFF.md").write_text(data["handoff_content"])
  marker.unlink()
  git add .queue HANDOFF.md && git commit -m "chore: carry forward .queue from {ORPHANED_BRANCH}"
  ```

- **Start fresh**: Delete the marker and continue. The scaffold step will create
  a new `.queue`.
  ```python
  (Path(workspace) / ".orphaned-plan").unlink()
  ```

Then call the orchestrator with:
```
step_done=recover_plan_offer
```
