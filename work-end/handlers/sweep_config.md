# Handler: sweep_config

**Always present the checklist.** If you believe an item already ran
this session, mark it with evidence (what artifact exists) but still
show it. The user decides whether to re-run or skip.

```
Pre-close sweep — create before closing?

[✓] 1  Knowledge capture   (ran earlier — 2 forage entries captured)
[x] 2  ADR                 record architectural decisions
[x] 3  Doc sync            (update-claude-md then implementation-doc-sync)
[✓] 4  write-content       (diary entry written: 2026-08-27-...)

Items marked ✓ already completed. Toggle to re-run.
Type numbers to toggle, "all" to toggle all, or "go" to proceed:
```

<NEVER-SKIP-WITHOUT-PRESENTING>
You MUST present the checklist to the user. Always. Even if you believe
every item already ran. The user decides — not you.

Do not recommend skipping. Do not unilaterally deselect items. If an
item ran, show the evidence and let the user confirm.

Session-bound items (1, 4) cannot be deferred to another session.
</NEVER-SKIP-WITHOUT-PRESENTING>

Report selected items back to orchestrator via sweep_selected= argument:
```
python3 work-end/work_end_orchestrator.py ... sweep_selected=forage,protocol,update_claude_md,impl_doc_sync,adr,write_content
```

**Journal validation:** If JOURNAL_DRIFT or UNANCHORED_ENTRIES in
orchestrator output, present decisions interactively before proceeding.
