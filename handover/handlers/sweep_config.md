# Handler: wrap_sweep_config

Present all items ON by default:

```
Session wrap — create before writing the handover?

[x] 1  forage sweep      check for gotchas, techniques, undocumented
[x] 2  protocol sweep    check for project rules worth formalising
[x] 3  update-claude-md  sync any new workflow conventions
[x] 4  write-content     capture this session's work as a diary entry

Type numbers to toggle, or "go" to proceed:
```

Pass selections back: `sweep_selected=forage,protocol,update_claude_md,write_content`

Do not recommend skipping. The user decides.

Session-bound items (forage, protocol, write-content, garden feedback)
depend on conversation context. They cannot be deferred — "defer to
next session" means "lose forever."
