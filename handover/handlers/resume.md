# Handler: Resume Handover

When the user says "resume handover", locate and read HANDOFF.md.

## Step R1 — Find HANDOFF.md

```bash
python3 ~/.claude/skills/project/ctx.py
```

Use `WORKSPACE` from output. HANDOFF.md is at `<WORKSPACE>/HANDOFF.md`.
Do not scan CLAUDE.md for workspace path — use ctx.py.

## Step R2 — Check freshness, then read

```bash
git -C "$WORKSPACE" log -1 --format="%ar" -- HANDOFF.md
```

If older than a week, flag: "HANDOFF.md is N days old — verify key assumptions."

Read the file, then run entry-scope validation:
```bash
python3 ~/.claude/skills/project/work_health.py --scope entry --project "$PROJECT" --workspace "$WORKSPACE"
```

Check for an open branch via `.plan` and `is_closed()`:

```python
from lifecycle import is_closed, ClosureState
state = is_closed(PROJECT, branch, workspace=WORKSPACE)
```

- `OPEN` or `MERGED_UNSTAMPED` → branch still open:
  > "Branch `<name>` is still open for #`<issue>`. Run `/work` to continue."
- `CLOSED` or `DELETED` → previous session closed cleanly. Proceed normally.
- No `.plan` → no active branch. Proceed normally.

## Step R3 — Display .plan queue

If `$WORKSPACE/.plan` exists, display via `format_resume_display()` from
`work_health.py`.

Present resume output:

**## Last Session** — 2-3 lines: what was done, what was tried.

**## Immediate Next Step** — single specific action right now.

**## Cross-Module** — only active blockers with tracked issues. Each must
reference an issue. Omit if none. Not static dependencies.

- **Blocking** — we owe something another repo needs
- **Enabled** — we delivered our part, downstream work unblocked
- **Blocked by** — work here can't proceed until another repo ships

**## Queue** — if `.plan` exists, display via `format_resume_display()`.

**## work_health findings** — if any warnings or changes, summarise.

No What's Left, What's Next, or cleaned-up sections. Work tracking is
in `.plan` and GitHub issues.
