# Handler: wrap_sweep_config

**Always present the checklist.** If you believe an item already ran
this session, mark it with evidence (what artifact exists) but still
show it. The user decides whether to re-run or skip.

```
Session wrap — create before writing the handover?

[✓] 1  forage sweep      (ran during work-end — 2 entries)
[x] 2  protocol sweep    check for project rules worth formalising
[x] 3  update-claude-md  sync any new workflow conventions
[✓] 4  write-content     (diary entry written: 2026-08-27-...)

Items marked ✓ already completed. Toggle to re-run.
Type numbers to toggle, or "go" to proceed:
```

Pass selections back: `sweep_selected=forage,protocol,update_claude_md,write_content`

You MUST present the checklist to the user. Always. Even if you believe
every item already ran. The user decides — not you.

Session-bound items (forage, protocol, write-content, garden feedback)
depend on conversation context. They cannot be deferred — "defer to
next session" means "lose forever."
