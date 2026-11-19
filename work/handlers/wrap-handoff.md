# Handler: handoff

Bring `HANDOFF.md` up to date with the `handover` skill.

1. What was finished this session, and what state the active item is in.
2. What is next in the queue.
3. Anything the next session must know that is not in an issue.
4. Commit it in the workspace.
5. Report: `step_done=handoff outcome=completed produced=1`

Do not run any other `work.py` command from inside this step. When the sequence
completes it prints `THEN=`: that is what to run afterwards.
