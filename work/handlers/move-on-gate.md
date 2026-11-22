# Handler: move-on-gate (current_item_not_released)

The user typed `start` or `next` while an item is active. Present the
four ways to release it and recommend one:

1. **Done** (Recommended when the work is complete) — mark it done on
   its branch; `work end` lands it later. The next branch stacks on it.
2. **Deferred** — not doing it now; it moves to the deferred section
   and leaves the open queue entirely.
3. **Move down** — stays in the queue but loses its active slot; placed
   at the end. The next open item becomes active.
4. **Continue** — the "move on" was typed by mistake; carry on with the
   current item.

Present via `AskUserQuestion` with the recommendation that fits best:
- Work looks complete on the branch → recommend Done
- Not sure / user seems to want to skip → recommend Move down
- User explicitly said "not doing this" → recommend Deferred

After the user chooses, call the orchestrator:

```
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=move_on_gate outcome=completed choice=done
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=move_on_gate outcome=completed choice=deferred reason="<reason>"
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=move_on_gate outcome=completed choice=move_down position=end
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=move_on_gate outcome=completed choice=continue
```

Use the `COMMAND=` value from the route output (either `start` or `next`).
