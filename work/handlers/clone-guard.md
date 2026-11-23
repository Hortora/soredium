# Handler: clone_guard

The user ran a work command in a canonical repo of a clone-enabled
family. Present the decision based on the OPTIONS line.

## OPTIONS=open_clone,stop

A clone already exists. Present:

1. **Open clone (Recommended)** — the clone is at CLONE= with its
   workspace at WORKSPACE=. Tell the user to open a new session there.
2. **Stop** — do nothing.

After the user chooses:

```
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=clone_guard outcome=completed choice=open_clone
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=clone_guard outcome=completed choice=stop
```

## OPTIONS=create_and_open,stop

No clone exists yet. Present:

1. **Create and open (Recommended)** — creates a permanent clone for
   this repo. The CREATE_CMD= line has the exact command. After
   creation, tell the user to open a new session at the clone workspace.
2. **Stop** — do nothing.

After the user chooses:

```
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=clone_guard outcome=completed choice=create_and_open
python3 ~/.claude/skills/project/work.py <COMMAND> step_done=clone_guard outcome=completed choice=stop
```

Use the COMMAND= value from the route output (the original command the
user typed: start, continue, next, or done).
